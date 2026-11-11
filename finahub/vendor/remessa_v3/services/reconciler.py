"""
Motor de conciliação Sistema → Banco (3 passadas).

Estratégia:
  Passada 1: Match perfeito       → CONCILIADO (verde)
  Passada 2: Match por data ±5 dias úteis (valor exato)
  Passada 3: Match por nome (≥75%, com filtro de sanidade no valor)
             → DIVERGÊNCIA (amarelo) nas passadas 2 e 3
  Restante: INCONSISTÊNCIA (vermelho)
"""

from dataclasses import dataclass, field
from enum import Enum

from core.utils import (
    date_to_weekday, date_sort_key,
    business_days_between, name_similarity,
)
from .parsers import Record


# ─── Configurações ──────────────────────────────────────────────
TOLERANCIA_DIAS_UTEIS = 5
SIMILARIDADE_NOME_MIN = 0.75   # 75%
TOLERANCIA_VALOR_MAX_PCT = 0.50  # filtro de sanidade


# ─── Estruturas ──────────────────────────────────────────────────
class TipoMotivo(str, Enum):
    DATA_DIFERE      = "Data difere"
    VALOR_DIFERE     = "Valor difere"
    NOME_SIMILAR     = "Nome similar"
    NAO_ENCONTRADO   = "Não encontrado no banco"


@dataclass
class Divergencia:
    """Registro do sistema com possível par no banco (sugestão)."""
    record: Record          # registro do sistema
    sugestao: Record        # registro candidato no banco
    motivo: TipoMotivo
    diff_valor: float       # diferença de valor (banco − sistema)
    diff_dias_uteis: int    # diferença em dias úteis
    similaridade: float     # 0.0 a 1.0


@dataclass
class Inconsistencia:
    """Registro sem nenhum par no banco."""
    record: Record
    motivo: str = TipoMotivo.NAO_ENCONTRADO.value


@dataclass
class DayStatus:
    data: str
    dia_semana: str
    ok: bool                          # totalmente verde
    has_divergencias: bool = False
    has_inconsistencias: bool = False
    qtd_total: int = 0
    qtd_conciliados: int = 0
    qtd_divergencias: int = 0
    qtd_inconsistencias: int = 0
    valor_total: float = 0.0
    valor_atencao: float = 0.0

    @property
    def status_cor(self) -> str:
        """Retorna 'ok', 'warn' ou 'err' para exibição."""
        if self.has_inconsistencias:
            return "err"
        if self.has_divergencias:
            return "warn"
        return "ok"


@dataclass
class ResultadoConciliacao:
    conciliados: list[Record]                = field(default_factory=list)
    divergencias: list[Divergencia]          = field(default_factory=list)
    inconsistencias: list[Inconsistencia]    = field(default_factory=list)
    nao_conciliados_banco: list[Record]      = field(default_factory=list)
    status_por_dia: dict[str, DayStatus]     = field(default_factory=dict)
    remessas_ausentes: list[str]             = field(default_factory=list)  # ex: ["21601", "21602"]
    total_sistema: float       = 0.0
    total_banco: float         = 0.0
    total_conciliado: float    = 0.0
    total_divergente: float    = 0.0
    total_inconsistente: float = 0.0

    @property
    def qtd_conciliados(self)     -> int: return len(self.conciliados)
    @property
    def qtd_divergencias(self)    -> int: return len(self.divergencias)
    @property
    def qtd_inconsistencias(self) -> int: return len(self.inconsistencias)
    @property
    def qtd_dias(self)            -> int: return len(self.status_por_dia)
    @property
    def qtd_remessas(self) -> int:
        return len(self.conciliados) + len(self.divergencias) + len(self.inconsistencias)
    @property
    def tudo_ok(self) -> bool:
        return self.qtd_divergencias == 0 and self.qtd_inconsistencias == 0
    @property
    def qtd_atencao(self) -> int:
        return self.qtd_divergencias + self.qtd_inconsistencias

    def pct(self, n: int) -> int:
        """Percentual de n sobre qtd_remessas (0-100)."""
        total = self.qtd_remessas
        if total == 0:
            return 0
        return round(100 * n / total)


# ═════════════════════════════════════════════════════════════════
# MOTOR
# ═════════════════════════════════════════════════════════════════
def reconciliar(sistema: list[Record], banco: list[Record]) -> ResultadoConciliacao:
    """
    Roda 3 passadas em sequência sobre o sistema.
    Cada registro do banco só pode ser usado UMA vez.
    """
    resultado = ResultadoConciliacao()
    resultado.total_sistema = round(sum(r.valor for r in sistema), 2)
    resultado.total_banco   = round(sum(r.valor for r in banco), 2)

    banco_usado: set[int] = set()
    sistema_ord = sorted(sistema, key=lambda r: (date_sort_key(r.data), r.valor))

    # ─── PASSADA 1: Match perfeito (data + valor) ─────────────
    pendentes: list[Record] = []
    banco_por_chave: dict[tuple[str, float], list[int]] = {}
    for i, r in enumerate(banco):
        banco_por_chave.setdefault((r.data, r.valor), []).append(i)

    for rec in sistema_ord:
        candidatos = [i for i in banco_por_chave.get((rec.data, rec.valor), [])
                      if i not in banco_usado]
        if candidatos:
            banco_usado.add(candidatos[0])
            resultado.conciliados.append(rec)
            resultado.total_conciliado += rec.valor
        else:
            pendentes.append(rec)

    # ─── PASSADA 2: Data ±5 dias úteis, valor exato ────────────
    ainda_pendentes: list[Record] = []
    for rec in pendentes:
        idx = _achar_match_data_aproximada(rec, banco, banco_usado)
        if idx is not None:
            banco_usado.add(idx)
            cand = banco[idx]
            resultado.divergencias.append(Divergencia(
                record=rec,
                sugestao=cand,
                motivo=TipoMotivo.DATA_DIFERE,
                diff_valor=round(cand.valor - rec.valor, 2),
                diff_dias_uteis=business_days_between(rec.data, cand.data),
                similaridade=name_similarity(rec.fornecedor, cand.fornecedor),
            ))
            resultado.total_divergente += rec.valor
        else:
            ainda_pendentes.append(rec)

    # ─── PASSADA 3: Nome similar (≥75%, com sanidade) ──────────
    realmente_pendentes: list[Record] = []
    for rec in ainda_pendentes:
        idx, similaridade = _achar_match_por_nome(rec, banco, banco_usado)
        if idx is not None:
            banco_usado.add(idx)
            cand = banco[idx]
            diff_valor = round(cand.valor - rec.valor, 2)
            mesmo_dia = rec.data == cand.data

            if mesmo_dia and abs(diff_valor) > 0.005:
                motivo = TipoMotivo.VALOR_DIFERE
            else:
                motivo = TipoMotivo.NOME_SIMILAR

            resultado.divergencias.append(Divergencia(
                record=rec,
                sugestao=cand,
                motivo=motivo,
                diff_valor=diff_valor,
                diff_dias_uteis=business_days_between(rec.data, cand.data),
                similaridade=similaridade,
            ))
            resultado.total_divergente += rec.valor
        else:
            realmente_pendentes.append(rec)

    # ─── PASSADA 4: Inconsistências (resto) ────────────────────
    for rec in realmente_pendentes:
        resultado.inconsistencias.append(Inconsistencia(record=rec))
        resultado.total_inconsistente += rec.valor

    resultado.nao_conciliados_banco = [
        r for i, r in enumerate(banco) if i not in banco_usado
    ]

    resultado.status_por_dia = _construir_status_por_dia(
        sistema_ord, resultado.conciliados,
        resultado.divergencias, resultado.inconsistencias,
    )

    resultado.total_conciliado    = round(resultado.total_conciliado, 2)
    resultado.total_divergente    = round(resultado.total_divergente, 2)
    resultado.total_inconsistente = round(resultado.total_inconsistente, 2)

    # ─── Detecta remessas inteiras ausentes no banco ────────────
    resultado.remessas_ausentes = _detectar_remessas_ausentes(
        sistema_ord, resultado.inconsistencias,
    )

    return resultado


def _achar_match_data_aproximada(
    rec: Record, banco: list[Record], usados: set[int],
) -> int | None:
    """Procura match com valor exato e data dentro de ±5 dias úteis."""
    candidatos: list[tuple[int, int]] = []

    for i, b in enumerate(banco):
        if i in usados or b.valor != rec.valor:
            continue
        diff_dias = business_days_between(rec.data, b.data)
        if diff_dias <= TOLERANCIA_DIAS_UTEIS:
            candidatos.append((i, diff_dias))

    if not candidatos:
        return None
    candidatos.sort(key=lambda x: x[1])
    return candidatos[0][0]


def _achar_match_por_nome(
    rec: Record, banco: list[Record], usados: set[int],
) -> tuple[int | None, float]:
    """
    Match por nome ≥75% com filtro de sanidade (valor não pode diferir > 50%).
    Score combinado pondera valor (50%), dias (30%), nome (20%).
    """
    candidatos: list[tuple[int, float, float]] = []

    for i, b in enumerate(banco):
        if i in usados:
            continue

        sim = name_similarity(rec.fornecedor, b.fornecedor)
        if sim < SIMILARIDADE_NOME_MIN:
            continue

        # Filtro de sanidade no valor
        menor = min(rec.valor, b.valor)
        diff_abs = abs(rec.valor - b.valor)
        if menor > 0 and (diff_abs / menor) > TOLERANCIA_VALOR_MAX_PCT:
            continue

        diff_dias = business_days_between(rec.data, b.data)
        norm_diff_valor = diff_abs / max(rec.valor, 1.0)
        norm_diff_dias  = min(diff_dias / 10.0, 1.0)
        score = (
            0.50 * (1 - norm_diff_valor) +
            0.30 * (1 - norm_diff_dias) +
            0.20 * sim
        )
        candidatos.append((i, score, sim))

    if not candidatos:
        return None, 0.0
    candidatos.sort(key=lambda x: x[1], reverse=True)
    best_idx, _, best_sim = candidatos[0]
    return best_idx, best_sim


def _construir_status_por_dia(
    sistema: list[Record],
    conciliados: list[Record],
    divergencias: list[Divergencia],
    inconsistencias: list[Inconsistencia],
) -> dict[str, DayStatus]:
    """Agrupa por data e calcula estatísticas."""
    by_date: dict[str, DayStatus] = {}

    for rec in sistema:
        if rec.data not in by_date:
            by_date[rec.data] = DayStatus(
                data=rec.data, dia_semana=date_to_weekday(rec.data), ok=True,
            )
        st = by_date[rec.data]
        st.qtd_total += 1
        st.valor_total += rec.valor

    for rec in conciliados:
        st = by_date.get(rec.data)
        if st:
            st.qtd_conciliados += 1

    for div in divergencias:
        st = by_date.get(div.record.data)
        if st:
            st.has_divergencias = True
            st.ok = False
            st.qtd_divergencias += 1
            st.valor_atencao += div.record.valor

    for inc in inconsistencias:
        st = by_date.get(inc.record.data)
        if st:
            st.has_inconsistencias = True
            st.ok = False
            st.qtd_inconsistencias += 1
            st.valor_atencao += inc.record.valor

    for st in by_date.values():
        st.valor_total = round(st.valor_total, 2)
        st.valor_atencao = round(st.valor_atencao, 2)

    return dict(sorted(by_date.items(), key=lambda kv: date_sort_key(kv[0])))


# ─── Detecção de remessas inteiras ausentes ──────────────────────
def _detectar_remessas_ausentes(
    sistema: list[Record],
    inconsistencias: list[Inconsistencia],
) -> list[str]:
    """
    Detecta remessas que provavelmente não foram enviadas ao banco.

    Lógica:
      1. Calcula o valor total de cada remessa no sistema
      2. Soma os valores das inconsistências agrupadas por remessa
      3. Se a soma das inconsistências de uma remessa == total da remessa
         no sistema → remessa inteira ausente

    Retorna lista de números de remessa ausentes, ordenada.
    """
    # Ignora registros sem número de remessa
    if not inconsistencias:
        return []

    # Total de cada remessa no sistema (todos os registros, incluindo conciliados)
    total_por_remessa: dict[str, float] = {}
    for rec in sistema:
        rem = rec.remessa.strip()
        if not rem or rem == "—":
            continue
        total_por_remessa[rem] = round(
            total_por_remessa.get(rem, 0.0) + rec.valor, 2
        )

    # Soma das inconsistências por remessa
    incons_por_remessa: dict[str, float] = {}
    for inc in inconsistencias:
        rem = inc.record.remessa.strip()
        if not rem or rem == "—":
            continue
        incons_por_remessa[rem] = round(
            incons_por_remessa.get(rem, 0.0) + inc.record.valor, 2
        )

    # Compara: se valor das inconsistências == valor total da remessa → ausente
    ausentes = []
    for rem, valor_incons in incons_por_remessa.items():
        valor_total = total_por_remessa.get(rem, 0.0)
        if valor_total > 0 and abs(valor_incons - valor_total) < 0.02:
            ausentes.append(rem)

    return sorted(ausentes)

