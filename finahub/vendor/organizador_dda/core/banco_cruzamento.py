"""
banco_cruzamento.py
Motor de cruzamento DDA × banco com pré-filtro por Hash Map.

CORREÇÕES v2 (identificadas em auditoria):
  1. Sanitização absoluta de strings antes de qualquer comparação —
     elimina crash fatal quando fornecedor é NaN/float.
  2. Pré-filtro por Hash Map (data, valor_arredondado) → O(1) lookup
     antes de chamar rapidfuzz. Elimina complexidade O(N×M) e reduz
     chamadas ao fuzzy em ~95% dos casos reais.
  3. Fallback robusto para SequenceMatcher quando rapidfuzz não instalado.

CORREÇÕES v3 (bug "notas somem"):
  4. Match UM-PARA-UM: cada pagamento do banco só pode dar baixa em UMA
     nota do DDA. Antes, um único pagamento (ex.: 1 pagamento à White
     Martins) casava com TODAS as notas do mesmo CNPJ e todas saíam de
     "pendente" indevidamente. Agora, ao casar, o pagamento é consumido.
  5. Escopo por EMPRESA: uma nota da Alfametal só casa com pagamento da
     conta Alfametal (idem Betaviaria). Evita que uma nota some porque
     casou com o pagamento da outra empresa ao mesmo fornecedor.

CORREÇÕES v4 (bug "divergentes somem"):
  6. Match exige CNPJ + DATA + VALOR juntos. Antes, um match por CNPJ com
     valor DIFERENTE virava "divergente" — e o relatório nunca exportava as
     divergentes, então a nota sumia por completo. Agora, valor diferente
     significa que o pagamento NÃO confere: a nota simplesmente continua
     PENDENTE. A categoria "divergente" foi eliminada (df_divergente fica
     vazio, mantido só por compatibilidade de API).
"""
from __future__ import annotations

import logging
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .banco_parser import PagamentoBanco, _normalizar
from .utils import cnpj_digitos

logger = logging.getLogger(__name__)

# Threshold de similaridade mínima para considerar mesmo fornecedor
_SIMILARIDADE_MINIMA = 70.0

# Janela de tolerância de data (em dias) para match por CNPJ.
# O vencimento do DDA é ajustado para dia útil; a data do banco pode
# divergir em 1-2 dias úteis do vencimento original. Como o CNPJ é
# determinístico, a janela não cria falsos positivos de identidade.
_TOLERANCIA_DIAS_CNPJ = 3


def _str_seguro(valor) -> str:
    """
    Converte qualquer valor para string segura.
    NaN, None e float viram string vazia — nunca crasham o rapidfuzz.
    """
    if valor is None:
        return ""
    try:
        import math
        if isinstance(valor, float) and math.isnan(valor):
            return ""
    except Exception:
        pass
    s = str(valor).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _similaridade(a: str, b: str) -> float:
    """Similaridade fuzzy entre dois nomes normalizados."""
    # Entradas já sanitizadas — proteção extra
    a = _str_seguro(a)
    b = _str_seguro(b)
    if not a or not b:
        return 0.0
    try:
        from rapidfuzz import fuzz
        return float(fuzz.token_set_ratio(a, b))
    except ImportError:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a, b).ratio() * 100


def _chave_hash(data, valor: float) -> Tuple:
    """
    Chave do HashMap de pré-filtro: (data, valor arredondado em centavos).
    Arredondar em centavos garante tolerância a erros de float.
    """
    return (data, round(valor, 2))


def _grupo_empresa(texto) -> str:
    """
    Reduz o nome de empresa (do DDA ou da conta do banco) a um grupo
    canônico: 'ALFAMETAL' ou 'BETAVIARIA'. Retorna '' quando não é
    possível determinar — nesse caso o match NÃO é bloqueado por empresa
    (fallback seguro para não gerar falsos pendentes).
    """
    s = _str_seguro(texto).upper()
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    # Corrige grafias erradas comuns do nome Betaviaria
    for errado in ("RANSNOVAG", "TRASNOVAG", "TRANS NOVAG"):
        s = s.replace(errado, "BETAVIARIA")
    if "BETAVIARIA" in s or "TRANSPORTE" in s:
        return "BETAVIARIA"
    if "ALFAMETAL" in s:
        return "ALFAMETAL"
    return ""


def _empresas_compativeis(g_dda: str, g_pg: str) -> bool:
    """
    Empresas compatíveis se forem o mesmo grupo, ou se alguma for
    indeterminada (fallback: não bloqueia por empresa).
    """
    return (not g_dda) or (not g_pg) or (g_dda == g_pg)


@dataclass
class ResultadoCruzamento:
    df_pendente:      pd.DataFrame
    df_programado:    pd.DataFrame
    df_divergente:    pd.DataFrame
    total_dda:        int   = 0
    total_programado: int   = 0
    total_divergente: int   = 0
    total_pendente:   int   = 0
    valor_programado: float = 0.0
    valor_pendente:   float = 0.0
    # Pagamentos do banco que NÃO casaram com nenhuma nota do DDA.
    # Sinal valioso: pode ser uma nota que faltou no DDA. (item 5)
    pagamentos_nao_casados: List[PagamentoBanco] = field(default_factory=list)


def cruzar(
    df_dda: pd.DataFrame,
    pagamentos_banco: List[PagamentoBanco],
    callback_progresso=None,   # callable(pct: float, msg: str) opcional
) -> ResultadoCruzamento:
    """
    Cruza o DataFrame do DDA com a lista de pagamentos do banco.

    Algoritmo de dois estágios:
      Estágio 1 — HashMap: busca O(1) por (data, valor) exato
      Estágio 2 — Fuzzy:   só ativado para candidatos do estágio 1

    Isso reduz chamadas ao rapidfuzz de O(N×M) para O(N×k),
    onde k é o número médio de pagamentos com mesmo valor no mesmo dia
    (tipicamente 1 a 3 na prática).
    """
    if df_dda.empty or not pagamentos_banco:
        return ResultadoCruzamento(
            df_pendente=df_dda.copy(),
            df_programado=pd.DataFrame(),
            df_divergente=pd.DataFrame(),
            total_dda=len(df_dda),
            total_pendente=len(df_dda),
            # Sem DDA para casar → todos os pagamentos ficam "sem nota".
            pagamentos_nao_casados=[
                pg for pg in pagamentos_banco
                if pg.data is not None and pg.valor is not None
            ],
        )

    # ── Estágio 0: Sanitizar e indexar banco em HashMap ──────────────── #
    # Índice 0: cnpj_favorecido → lista  [busca DETERMINÍSTICA, com
    #           tolerância de data — DDA ajustado por feriado e banco
    #           frequentemente divergem em 1 dia útil]
    # Índice 1: (data, valor) → lista de PagamentoBanco  [busca exata]
    # Índice 2: data → lista de PagamentoBanco           [busca por data]
    idx_cnpj:  Dict[str, List[PagamentoBanco]] = defaultdict(list)
    idx_exato: Dict[Tuple, List[PagamentoBanco]] = defaultdict(list)
    idx_data:  Dict[object, List[PagamentoBanco]] = defaultdict(list)

    for pg in pagamentos_banco:
        # Sanitizar nome do banco na ingestão
        pg.favorecido_norm = _normalizar(_str_seguro(pg.favorecido))
        # Grupo da conta (Alfametal/Betaviaria) para escopo de match
        pg.grupo = _grupo_empresa(pg.empresa_banco)
        if pg.data is not None and pg.valor is not None:
            idx_exato[_chave_hash(pg.data, pg.valor)].append(pg)
            idx_data[pg.data].append(pg)
            cnpj_pg = cnpj_digitos(pg.cnpj_favorecido)
            if len(cnpj_pg) == 14:
                idx_cnpj[cnpj_pg].append(pg)

    linhas_programadas: list = []
    linhas_divergentes: list = []
    linhas_pendentes:   list = []

    # Baixa um-para-um: cada pagamento (por identidade) só casa com UMA
    # nota. Sem isso, 1 pagamento à Gamma Gasotec casava com todas as
    # notas do mesmo CNPJ e todas sumiam de "pendente".
    usados: set = set()

    total = len(df_dda)
    logger.info("Iniciando cruzamento: %d linhas DDA × %d registros banco",
                total, len(pagamentos_banco))

    for i, (_, row) in enumerate(df_dda.iterrows()):

        # Progresso granular para a ProgressBar determinada
        if callback_progresso and i % 10 == 0:
            pct = i / total
            callback_progresso(pct, f"Cruzando linha {i+1} de {total}...")

        # Sanitizar campos da linha DDA
        venc = row.get("VENC")
        if pd.isna(venc) or venc is None:
            linhas_pendentes.append(row)
            continue

        try:
            data_dda = pd.Timestamp(venc).date()
        except Exception:
            linhas_pendentes.append(row)
            continue

        valor_raw = row.get("VALOR")
        try:
            valor_dda = float(valor_raw)
            if pd.isna(valor_dda):
                raise ValueError
        except (TypeError, ValueError):
            linhas_pendentes.append(row)
            continue

        # Sanitizar nome do fornecedor DDA — NaN vira ""
        forn_dda_norm = _normalizar(_str_seguro(row.get("FORNECEDOR", "")))

        # Grupo da empresa da nota (Alfametal/Betaviaria) para escopo
        grupo_dda = _grupo_empresa(row.get("EMPRESA", ""))

        melhor_match:      Optional[PagamentoBanco] = None
        melhor_sim:        float = 0.0
        melhor_valor_igual: bool = False
        match_tipo:        str = "NOME"

        # ── Estágio 1: CNPJ (determinístico) ─────────────────────────── #
        # CNPJ existe nos dois lados; é sinal forte. Fuzzy de nome vira
        # fallback, não método primário. Tolerância de ±3 dias na data
        # cobre o desalinhamento DDA ajustado (feriado/fds) × banco.
        # Critério: menor distância de data; empate → menor dif. de valor.
        cnpj_dda = cnpj_digitos(row.get("CNPJ", ""))
        if len(cnpj_dda) == 14:
            melhor_dist = None
            for pg in idx_cnpj.get(cnpj_dda, []):
                if id(pg) in usados:
                    continue
                if not _empresas_compativeis(grupo_dda, pg.grupo):
                    continue
                # Exige VALOR igual (alem de CNPJ e data). So remove da
                # pendencia quando o pagamento confere de verdade. Se o valor
                # difere, e outra nota do fornecedor -> nota continua pendente.
                if abs(pg.valor - valor_dda) >= 0.01:
                    continue
                dist_dias = abs((pg.data - data_dda).days)
                if dist_dias > _TOLERANCIA_DIAS_CNPJ:
                    continue
                if melhor_dist is None or dist_dias < melhor_dist:
                    melhor_dist  = dist_dias
                    melhor_match = pg
            if melhor_match is not None:
                melhor_valor_igual = True
                # Match por CNPJ+data+valor — similaridade marca 100.
                melhor_sim = 100.0
                match_tipo = "CNPJ"

        # ── Estágio 2: HashMap (data + valor exato) ─────────────────── #
        if melhor_match is None:
            candidatos = idx_exato.get(_chave_hash(data_dda, valor_dda), [])

            for pg in candidatos:
                if id(pg) in usados:
                    continue
                if not _empresas_compativeis(grupo_dda, pg.grupo):
                    continue
                if not pg.favorecido_norm:
                    continue
                sim = _similaridade(forn_dda_norm, pg.favorecido_norm)
                if sim >= _SIMILARIDADE_MINIMA and sim > melhor_sim:
                    melhor_sim         = sim
                    melhor_match       = pg
                    melhor_valor_igual = (abs(pg.valor - valor_dda) < 0.01)

        # Estagio "so por data" REMOVIDO: antes ele casava por nome+data com
        # valor diferente e gerava "divergentes" — que nao eram exportadas e
        # sumiam do relatorio. Agora, valor diferente => nota fica PENDENTE.

        # ── Classificação final ──────────────────────────────────────── #
        # So existem dois destinos: PROGRAMADO (CNPJ/nome + data + valor
        # conferem) ou PENDENTE. Nada de "divergente" que suma do relatorio.
        if melhor_match is None:
            linhas_pendentes.append(row)
        else:
            row_extra = row.copy()
            row_extra["BANCO_FAVORECIDO"] = melhor_match.favorecido
            row_extra["BANCO_DATA"]       = str(melhor_match.data)
            row_extra["BANCO_VALOR"]      = melhor_match.valor
            row_extra["BANCO_EMPRESA"]    = melhor_match.empresa_banco
            row_extra["SIMILARIDADE"]     = round(melhor_sim, 1)
            row_extra["MATCH_TIPO"]       = match_tipo
            linhas_programadas.append(row_extra)
            # Baixa: consome o pagamento para nenhuma outra nota o reutilizar.
            usados.add(id(melhor_match))

    if callback_progresso:
        callback_progresso(1.0, "Cruzamento concluído.")

    def _to_df(linhas: list) -> pd.DataFrame:
        return pd.DataFrame(linhas).reset_index(drop=True) if linhas else pd.DataFrame()

    df_pendente   = _to_df(linhas_pendentes)
    df_programado = _to_df(linhas_programadas)
    df_divergente = _to_df(linhas_divergentes)

    # Pagamentos do banco que sobraram (nenhuma nota casou com eles). (item 5)
    pagamentos_nao_casados = [
        pg for pg in pagamentos_banco
        if id(pg) not in usados and pg.data is not None and pg.valor is not None
    ]

    logger.info(
        "Cruzamento: %d programados | %d pendentes | %d pagamentos do banco sem nota",
        len(df_programado), len(df_pendente), len(pagamentos_nao_casados),
    )

    return ResultadoCruzamento(
        df_pendente=df_pendente,
        df_programado=df_programado,
        df_divergente=df_divergente,
        total_dda=len(df_dda),
        total_programado=len(df_programado),
        total_divergente=len(df_divergente),
        total_pendente=len(df_pendente),
        valor_programado=float(df_programado["VALOR"].dropna().sum()) if not df_programado.empty else 0.0,
        valor_pendente=float(df_pendente["VALOR"].dropna().sum())     if not df_pendente.empty   else 0.0,
        pagamentos_nao_casados=pagamentos_nao_casados,
    )
