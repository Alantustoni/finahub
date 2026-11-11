"""
dda_compras.py — Extras do Organizador DDA (pedidos de 29/10/2026).

1. Abreviação "de cartório" do fornecedor (tira LTDA/EIRELI/S.A., troca
   INDUSTRIA→IND…), sem cortar o nome — o que identifica fica.
2. "JÁ VEIO": procura cada nota do DDA na planilha de notas recebidas de
   Compras (NOTAS - COMPRAS.xlsx, alimentada pela automação do e-mail), na
   ordem combinada com o usuário:
       1º nome + vencimento + NF
       2º vencimento + NF
       3º nome + vencimento               (menos seguro → "conferir")
   Cada nota de Compras só "paga" UM boleto (evita marcar 4 boletos da
   Gamma Gasotec do mesmo dia por causa de 1 nota só).
   O vencimento de Compras vem como a data original (pode cair em sábado/
   domingo); antes de comparar ele é ajustado para dia útil, igual o DDA.
3. CNPJs "não cobrar" (pela raiz): também saem como "JÁ VEIO".
4. Monta a lista do relatório com pendentes + programadas (programadas
   marcadas para ficarem amarelas no Excel).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

import pandas as pd

# internas (começam com "_" → não viram coluna no Excel). O texto de
# _COMPRAS é escrito DENTRO da coluna ERROS da Planilha1 (pedido do usuário),
# sem contar como erro na aba ERROS.
COL_COMPRAS = "_COMPRAS"
COL_PROGRAMADA = "_PROGRAMADA"
COL_BANCO_DATA = "_BANCO_DATA"
JA_VEIO = "JÁ VEIO"

_SIM_NOME_COM_NF = 70     # nome parecido quando a NF e o vencimento batem
_SIM_NOME_SEM_NF = 85     # nome tem que ser bem parecido quando não há NF


# ====================================================================== #
# Texto                                                                   #
# ====================================================================== #
def _sem_acento(s) -> str:
    s = "" if s is None else str(s)
    if s.lower() in ("nan", "none"):
        return ""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").upper()


# sufixos societários — saem do nome
_SOCIETARIOS = {"LTDA", "LTD", "EIRELI", "ME", "EPP", "SA", "S/A", "S.A", "S.A.",
                "MEI", "SS", "SLU", "LIMITADA"}
# palavras longas → forma curta reconhecível
_TROCAS = {
    "INDUSTRIA": "IND", "INDUSTRIAS": "IND", "INDUSTRIAL": "IND",
    "INDUSTRIAIS": "IND", "COMERCIO": "COM", "COMERCIAL": "COM",
    "DISTRIBUIDORA": "DISTRIB", "DISTRIBUICAO": "DISTRIB",
    "TRANSPORTES": "TRANSP", "TRANSPORTE": "TRANSP",
    "TRANSPORTADORA": "TRANSP", "SERVICOS": "SERV", "SERVICO": "SERV",
    "ADMINISTRACAO": "ADM", "ADMINISTRADORA": "ADM",
    "PARTICIPACOES": "PART", "EQUIPAMENTOS": "EQUIP",
    "IMPORTACAO": "IMP", "EXPORTACAO": "EXP", "REPRESENTACOES": "REPRES",
    "CONSTRUCOES": "CONSTR", "ENGENHARIA": "ENG", "TECNOLOGIA": "TEC",
    "SOLUCOES": "SOLUC", "MANUTENCAO": "MANUT", "LOGISTICA": "LOG",
    "COMPANHIA": "CIA", "BRASILEIRA": "BRAS", "NACIONAL": "NAC",
}
_LIGACOES = {"DE", "DA", "DO", "DOS", "DAS", "E", "EM", "&"}


def abreviar_fornecedor(nome) -> str:
    """'ORBITA SISTEMAS INDUSTRIA E COMERCIO DE PECAS LTDA' →
    'ORBITA SISTEMAS IND COM PECAS'. Nunca devolve vazio se havia nome."""
    original = _sem_acento(nome).strip()
    if not original:
        return ""
    # S/A, S.A., S A (no fim) → SA, que é tirado logo abaixo
    txt = re.sub(r"\bS\s*/\s*A\b|\bS[\s.]+A\.?\s*$", " SA ", original)
    txt = re.sub(r"[,;]", " ", txt)
    txt = re.sub(r"\s+-\s+", " ", txt)
    palavras = [p.strip(".") for p in txt.split()]
    out: List[str] = []
    for i, p in enumerate(palavras):
        if not p:
            continue
        if p in _SOCIETARIOS:
            continue
        # "E"/"DE"… só saem no meio; a 1ª palavra fica (ex.: "E-CRED")
        if p in _LIGACOES and out:
            continue
        out.append(_TROCAS.get(p, p))
    # tirou demais (nome que era só sigla societária)? devolve o original
    return " ".join(out) if out else original


def _nome_busca(nome) -> str:
    """Nome para comparar: sem acento, pontuação, sufixos e ligações."""
    txt = re.sub(r"[^A-Z0-9 ]", " ", _sem_acento(nome))
    palavras = [p for p in txt.split()
                if p not in _SOCIETARIOS and p not in _LIGACOES
                and p not in ("S", "A", "COM", "IND", "CIA")]
    return " ".join(_TROCAS.get(p, p) for p in palavras)


def _similar(a: str, b: str) -> int:
    if not a or not b:
        return 0
    try:
        from rapidfuzz import fuzz
        return int(fuzz.token_set_ratio(a, b))
    except Exception:                                   # noqa: BLE001
        from difflib import SequenceMatcher
        return int(100 * SequenceMatcher(None, a, b).ratio())


# ====================================================================== #
# Datas                                                                   #
# ====================================================================== #
def _para_data(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.date()
    s = str(v).strip()
    if not s or s.lower() in ("nan", "nat", "none"):
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        n = int(float(s))
        return date(1899, 12, 30) + timedelta(days=n) if 20000 < n < 80000 else None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


class DiaUtil:
    """Ajuste para o próximo dia útil — mesma regra do motor do DDA."""

    def __init__(self, feriados_fixos: Iterable[str] = ()) -> None:
        self._fixos = list(feriados_fixos or [])
        self._cache: Dict[int, Set[date]] = {}

    def _feriados(self, ano: int) -> Set[date]:
        if ano not in self._cache:
            s: Set[date] = set()
            for d in self._fixos:
                try:
                    dia, mes = str(d).split("/")[:2]
                    s.add(date(ano, int(mes), int(dia)))
                except (ValueError, IndexError):
                    pass
            try:
                from ..vendor.organizador_dda.core.processor import feriados_moveis
                s |= {f.date() if hasattr(f, "date") else f for f in feriados_moveis(ano)}
            except Exception:                           # noqa: BLE001
                pass
            self._cache[ano] = s
        return self._cache[ano]

    def ajustar(self, d: Optional[date]) -> Optional[date]:
        if d is None:
            return None
        for _ in range(30):
            if d.weekday() < 5 and d not in self._feriados(d.year):
                return d
            d += timedelta(days=1)
        return d


# ====================================================================== #
# Notas fiscais                                                           #
# ====================================================================== #
_RE_NF_TRACO = re.compile(r"^\s*0*(\d+)\s*-\s*\d+\s*$")


def limpar_nf(nf):
    """
    Regra pedida em 29/10/2026 (padrão Gamma Gasotec): NF no formato
    'número-número' fica só com a parte ANTES do traço, sem zeros à esquerda.
      '00001957-610001' → '1957'
    Qualquer outro formato volta igual.
    """
    s = "" if nf is None else str(nf)
    m = _RE_NF_TRACO.match(s)
    return m.group(1) if m else nf

def nfs_do_dda(nf) -> Set[str]:
    """
    Formas possíveis da NF a partir do 'Nº doc.' do boleto:
      '0417529701'      → 417529701, 4175297 (sem parcela 01), 417529 (sem 001)
      '00009033-669001' → 9033, 669001, 669 …
      '000011/A'        → 11
    """
    s = str(nf or "").strip()
    if not s or s.lower() in ("nan", "none", "0"):
        return set()
    out: Set[str] = set()
    for parte in re.findall(r"\d+", s):
        base = parte.lstrip("0")
        if not base:
            continue
        out.add(base)
        if len(base) > 4:
            out.add(base[:-2].lstrip("0"))
        if len(base) > 5:
            out.add(base[:-3].lstrip("0"))
    return {n for n in out if len(n) >= 2}


def nfs_de_compras(nf) -> Set[str]:
    """'630/625/624' → {630, 625, 624}; '0001234' → {1234}."""
    out = set()
    for parte in re.split(r"[/;,\s\-]+", str(nf or "")):
        dig = re.sub(r"\D", "", parte).lstrip("0")
        if dig:
            out.add(dig)
    return out


# ====================================================================== #
# Planilha de Compras                                                     #
# ====================================================================== #
@dataclass
class NotaCompras:
    linha: int
    nfs: Set[str]
    empresa: str          # ALFAMETAL / BETAVIARIA / ""
    fornecedor: str       # já no formato de busca
    venc: Optional[date]  # ajustado para dia útil
    usada: bool = False
    recebido: Optional[datetime] = None   # data/hora do e-mail de Compras

    def rotulo(self, como: str) -> str:
        quando = f" – E-MAIL {self.recebido:%d/%m/%Y %H:%M}" if self.recebido else ""
        return f"{JA_VEIO}{quando} ({como})"


def _para_data_hora(v) -> Optional[datetime]:
    """Serial do Excel com fração (46324.7056) ou texto dd/mm/aaaa hh:mm."""
    s = str(v or "").strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        f = float(s)
        if 20000 < f < 80000:
            return datetime(1899, 12, 30) + timedelta(days=f, seconds=30)  # arredonda
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            pass
    return None


def ler_compras(path: Path, dia_util: DiaUtil) -> List[NotaCompras]:
    """
    Lê as abas 'Notas recebidas' (automação) e 'Recuperadas' (notas que a
    automação perdeu, recuperadas dos e-mails em 30/10/2026).
    """
    from .pensoes import ler_xlsx      # leitor do XML (abre mesmo com o Excel aberto)
    abas = ler_xlsx(Path(path))
    if not abas:
        raise ValueError("a planilha de Compras está vazia.")
    nomes = [k for k in abas if any(t in _sem_acento(k) for t in ("RECEBID", "RECUPERAD"))]
    if not nomes:
        nomes = [next(iter(abas))]
    notas: List[NotaCompras] = []
    for nome in nomes:
        notas.extend(_ler_aba_compras(abas[nome], dia_util, obrigatoria=(nome == nomes[0])))
    return notas


def _ler_aba_compras(linhas, dia_util: DiaUtil, obrigatoria: bool = True) -> List[NotaCompras]:
    hi = None
    for i, r in enumerate(linhas[:40]):
        textos = {_sem_acento(v).strip() for v in r.values()}
        if "NF" in textos and "FORNECEDOR" in textos:
            hi = i
            break
    if hi is None:
        if not obrigatoria:          # aba extra fora do padrão: ignora
            return []
        raise ValueError("não achei o cabeçalho (NF / Fornecedor) na planilha de Compras.")
    cab = {_sem_acento(v).strip(): c for c, v in linhas[hi].items()}
    c_nf, c_forn = cab.get("NF"), cab.get("FORNECEDOR")
    c_emp, c_venc = cab.get("EMPRESA"), cab.get("VENCIMENTO")
    c_rec = cab.get("RECEBIDO EM")
    notas: List[NotaCompras] = []
    for n, r in enumerate(linhas[hi + 1:], start=hi + 2):
        nfs = nfs_de_compras(r.get(c_nf))
        forn = _nome_busca(r.get(c_forn))
        if not nfs and not forn:
            continue
        notas.append(NotaCompras(
            linha=n, nfs=nfs,
            empresa=_sem_acento(r.get(c_emp)).strip() if c_emp is not None else "",
            fornecedor=forn,
            venc=dia_util.ajustar(_para_data(r.get(c_venc))) if c_venc is not None else None,
            recebido=_para_data_hora(r.get(c_rec)) if c_rec is not None else None))
    return notas


# ====================================================================== #
# Cruzamento DDA × Compras                                                #
# ====================================================================== #
def _grupo(empresa) -> str:
    e = _sem_acento(empresa)
    return "BETAVIARIA" if "BETAVIARIA" in e else ("ALFAMETAL" if "ALFAMETAL" in e else "")


def _raizes(cnpjs: Iterable[str]) -> Set[str]:
    out = set()
    for c in cnpjs or []:
        d = re.sub(r"\D", "", str(c))
        if len(d) >= 8:
            out.add(d[:8])
    return out


@dataclass
class ResumoCompras:
    por_nf_nome: int = 0
    por_nf_venc: int = 0
    por_nome_venc: int = 0
    por_cnpj: int = 0
    lidas: int = 0
    erro: str = ""

    @property
    def total(self) -> int:
        return self.por_nf_nome + self.por_nf_venc + self.por_nome_venc + self.por_cnpj


def marcar_ja_veio(df: pd.DataFrame, notas: Sequence[NotaCompras],
                   cnpjs_nao_cobrar: Iterable[str] = ()) -> ResumoCompras:
    """
    Preenche df[COMPRAS] (in place) com "JÁ VEIO (…)" ou "".
    Pendentes são procuradas antes das programadas, para não "gastar" uma
    nota de Compras com algo que já está no banco.
    """
    res = ResumoCompras(lidas=len(notas))
    df[COL_COMPRAS] = ""
    if df.empty:
        return res
    raizes = _raizes(cnpjs_nao_cobrar)
    ordem = list(df.index)
    if COL_PROGRAMADA in df.columns:
        ordem.sort(key=lambda i: bool(df.at[i, COL_PROGRAMADA]))

    # índice NF → notas (acelera os passos 1 e 2)
    por_nf: Dict[str, List[NotaCompras]] = {}
    for nt in notas:
        for nf in nt.nfs:
            por_nf.setdefault(nf, []).append(nt)

    def compativel(nt: NotaCompras, grupo: str) -> bool:
        return not nt.empresa or not grupo or nt.empresa == grupo

    pendentes_passo3 = []
    for i in ordem:
        row = df.loc[i]
        cnpj = re.sub(r"\D", "", str(row.get("CNPJ", "")))
        if raizes and len(cnpj) >= 8 and cnpj[:8] in raizes:
            df.at[i, COL_COMPRAS] = f"{JA_VEIO} (CNPJ NA LISTA)"
            res.por_cnpj += 1
            continue
        venc = _para_data(row.get("VENC"))
        grupo = _grupo(row.get("EMPRESA"))
        nome = _nome_busca(row.get("FORNECEDOR"))
        cands = [nt for nf in nfs_do_dda(row.get("PRV NF"))
                 for nt in por_nf.get(nf, []) if not nt.usada and compativel(nt, grupo)]
        achou = None
        # 1º nome + vencimento + NF
        for nt in cands:
            if venc and nt.venc == venc and _similar(nome, nt.fornecedor) >= _SIM_NOME_COM_NF:
                achou, rotulo = nt, "NF + NOME + VENC"
                res.por_nf_nome += 1
                break
        # 2º vencimento + NF
        if achou is None:
            for nt in cands:
                if venc and nt.venc == venc:
                    achou, rotulo = nt, "NF + VENC"
                    res.por_nf_venc += 1
                    break
        if achou is not None:
            achou.usada = True
            df.at[i, COL_COMPRAS] = achou.rotulo(rotulo)
        else:
            pendentes_passo3.append((i, venc, grupo, nome))

    # 3º nome + vencimento — só depois que as NFs já consumiram as suas notas
    for i, venc, grupo, nome in pendentes_passo3:
        if not venc or not nome:
            continue
        melhor, nota_melhor = 0, None
        for nt in notas:
            if nt.usada or nt.venc != venc or not compativel(nt, grupo):
                continue
            s = _similar(nome, nt.fornecedor)
            if s >= _SIM_NOME_SEM_NF and s > melhor:
                melhor, nota_melhor = s, nt
        if nota_melhor is not None:
            nota_melhor.usada = True
            df.at[i, COL_COMPRAS] = nota_melhor.rotulo("NOME + VENC - CONFERIR")
            res.por_nome_venc += 1
    return res


_RE_EMAIL = re.compile(r"E-MAIL\s+(\d{2})/(\d{2})/\d{4}\s+(\d{2}:\d{2})")


def situacao(programada, compras, banco_data="") -> tuple:
    """
    Situação da nota para a tela do DDA → (tag, texto).
    tag: "prog" (programada no banco), "ok" (já veio) ou "cob" (cobrar).
    Programada vence: ela já está paga no banco, como no Excel (amarela).
    """
    def _vazio(v) -> bool:
        return v is None or (isinstance(v, float) and v != v) or \
            str(v).strip().lower() in ("", "nan", "nat", "none")

    if bool(programada) and not _vazio(programada):
        d = _para_data(banco_data) if not _vazio(banco_data) else None
        return "prog", "● Programada" + (f" · banco {d:%d/%m}" if d else "")
    txt = "" if _vazio(compras) else str(compras)
    if txt:
        if "CNPJ" in txt:
            det = "CNPJ na lista"
        else:
            m = _RE_EMAIL.search(txt)
            det = f"e-mail {m.group(1)}/{m.group(2)} {m.group(3)}" if m else "Compras"
        if "CONFERIR" in txt:
            det += " (conferir)"
        return "ok", f"✓ Já veio · {det}"
    return "cob", "! Cobrar"


# ====================================================================== #
# Lista do relatório                                                      #
# ====================================================================== #
def montar_df_relatorio(df_base: pd.DataFrame, rc=None,
                        abreviar: bool = True) -> pd.DataFrame:
    """
    Sem cruzamento: a lista do DDA. Com cruzamento: pendentes + programadas
    (estas marcadas em COL_PROGRAMADA para ficarem amarelas).
    Mantém só as colunas do relatório (as BANCO_* ficam na aba ERROS).
    """
    colunas = [c for c in ("FILIAL", "EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF",
                           "TIPO", "VENC", "VALOR", "ERROS") if c in df_base.columns]
    if rc is None:
        df = df_base[colunas].copy()
        df[COL_PROGRAMADA] = False
    else:
        pend = rc.df_pendente.reindex(columns=colunas).copy()
        pend[COL_PROGRAMADA] = False
        prog = rc.df_programado.reindex(columns=colunas).copy()
        prog[COL_PROGRAMADA] = True
        # data do pagamento no banco (só p/ a tela; "_" não vai p/ o Excel)
        if "BANCO_DATA" in rc.df_programado.columns:
            prog[COL_BANCO_DATA] = rc.df_programado["BANCO_DATA"].values
        pend[COL_BANCO_DATA] = ""
        partes = [p for p in (pend, prog) if not p.empty]
        df = (pd.concat(partes, ignore_index=True) if partes
              else df_base[colunas].assign(**{COL_PROGRAMADA: False}))
    if "ERROS" in df.columns:
        df["ERROS"] = df["ERROS"].fillna("")
    if abreviar and "FORNECEDOR" in df.columns:
        df["FORNECEDOR"] = df["FORNECEDOR"].map(abreviar_fornecedor)
    return df.reset_index(drop=True)
