"""
pensoes.py — Pagamento de pensões (último dia útil do mês).

Fluxo:
  1. Lê o Excel que o DP manda (relatório FPRF004: matrícula, nome,
     competência, pagamento, valor).
  2. Busca cada matrícula no CADASTRO (aba da planilha
     "PENSÃO - ALFAMETAL.xlsx") → código e nome da pensionista no sistema.
  3. Matrícula que também existe com sufixo "-A", "-B"… no cadastro paga
     MAIS DE UMA pensão. O DP manda um valor só; quanto vai para cada uma
     só se sabe pela folha física — o usuário digita o valor das pensões
     extras e a principal fica com o restante.
  4. Monta o CSV de importação (mesmo leiaute do "ALFAMETAL - IMPORTAÇÃO"):
     separador ";", cabeçalho, CRLF, Windows-1252, valor "1.234,56".

Título: "MM-AAAA-SAL" da competência. O sistema rejeita mesmo fornecedor +
mesmo título, então a 2ª linha para o MESMO fornecedor usa "MM.AAAA-SAL".

O Excel do DP vem com estilos corrompidos (o openpyxl quebra ao abrir), por
isso a leitura é feita direto no XML do .xlsx.
"""
from __future__ import annotations

import re
import sys
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

_NS_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# maiúsculo, igual ao arquivo de pensão que o usuário importa (coluna D)
DIAS_SEMANA = ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"]

CABECALHO_CSV = ("REGT;EMPRESA;VENCIMENTO;;COD;FORNECEDOR;TITULO;VALOR;"
                 "OBSERVAÇÃO;TIPO;G.CONTAS;TRANSAÇÃO;CONTA FINANCEIRA;"
                 "CENTRO DE CUSTO;CONTA CONTABIL")

# campos fixos da linha de pensão (podem ser trocados pelo config "pensoes")
PADRAO = {
    "regt": "0",
    "empresa": "1",
    "observacao": "0",
    "tipo": "SAL",
    "g_contas": "19",
    "transacao": "90540",
    "sufixo_titulo": "SAL",
}


# ====================================================================== #
# Leitura do .xlsx direto do XML                                          #
# ====================================================================== #
def _ler_bytes(path: Path) -> bytes:
    """Lê o arquivo mesmo se estiver aberto no Excel (Windows)."""
    try:
        return Path(path).read_bytes()
    except PermissionError:
        if not sys.platform.startswith("win"):
            raise
    # Excel segura o arquivo; abre com compartilhamento total (só leitura)
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    GENERIC_READ, SHARE_ALL, OPEN_EXISTING = 0x80000000, 0x7, 3
    h = k32.CreateFileW(str(path), GENERIC_READ, SHARE_ALL, None,
                        OPEN_EXISTING, 0, None)
    if h in (None, wintypes.HANDLE(-1).value):
        raise PermissionError(
            f"não consegui abrir {Path(path).name} — feche no Excel e tente de novo.")
    try:
        import msvcrt
        fd = msvcrt.open_osfhandle(h, 0)
    except Exception:
        k32.CloseHandle(h)
        raise
    with open(fd, "rb") as f:
        return f.read()


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def ler_xlsx(path: Path) -> Dict[str, List[Dict[int, str]]]:
    """{nome_aba: [ {indice_coluna: texto}, ... ]} — uma entrada por linha."""
    z = zipfile.ZipFile(BytesIO(_ler_bytes(path)))
    nomes = z.namelist()
    ss: List[str] = []
    if "xl/sharedStrings.xml" in nomes:
        raiz = ET.fromstring(z.read("xl/sharedStrings.xml"))
        ss = ["".join(t.text or "" for t in si.iter(_NS_M + "t"))
              for si in raiz.findall(_NS_M + "si")]
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    alvo = {r.get("Id"): r.get("Target") for r in rels.iter(_NS_PR + "Relationship")}
    if not alvo:   # alguns geradores não usam namespace nos rels
        alvo = {r.get("Id"): r.get("Target") for r in rels}
    abas: Dict[str, List[Dict[int, str]]] = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(_NS_M + "sheet"):
        t = (alvo.get(sh.get(_NS_R + "id")) or "").lstrip("/")
        if not t.startswith("xl/"):
            t = "xl/" + t
        if t not in nomes:
            continue
        dados = ET.fromstring(z.read(t)).find(_NS_M + "sheetData")
        linhas: List[Dict[int, str]] = []
        for r in (dados if dados is not None else []):
            v: Dict[int, str] = {}
            for c in r:
                tp = c.get("t")
                if tp == "inlineStr":
                    val = "".join(e.text or "" for e in c.iter(_NS_M + "t"))
                else:
                    x = c.find(_NS_M + "v")
                    if x is None or x.text is None:
                        continue
                    val = ss[int(x.text)] if tp == "s" else x.text
                v[_col(c.get("r"))] = val
            linhas.append(v)
        abas[sh.get("name")] = linhas
    return abas


# ====================================================================== #
# Utilitários                                                             #
# ====================================================================== #
def _sem_acento(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", s)
                   if unicodedata.category(ch) != "Mn").upper().strip()


def _matricula(v: Any) -> str:
    s = str(v or "").strip().upper()
    s = re.sub(r"\.0+$", "", s)           # 104812.0 → 104812
    return re.sub(r"\s+", "", s)


def _centavos(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(round(float(v) * 100))
    from ..core.utils import parse_valor_br
    f = parse_valor_br(v)
    return None if f is None else int(round(f * 100))


def valor_br(centavos: int) -> str:
    """123456 → '1.234,56'"""
    txt = f"{centavos / 100:,.2f}"
    return txt.replace(",", "X").replace(".", ",").replace("X", ".")


def _data_excel(v: Any) -> Optional[date]:
    """Aceita serial do Excel (46296) ou texto dd/mm/aaaa."""
    s = str(v or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return date(1899, 12, 30) + timedelta(days=int(float(s)))
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            pass
    return None


def _limpar_campo(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace(";", ",")).strip()


# ====================================================================== #
# Entradas                                                                #
# ====================================================================== #
@dataclass
class LinhaDP:
    matricula: str
    nome: str
    competencia: Optional[date]
    pagamento: Optional[date]
    referencia: str
    centavos: int


@dataclass
class DadosDP:
    linhas: List[LinhaDP] = field(default_factory=list)
    qtd_rodape: Optional[int] = None
    total_rodape: Optional[int] = None       # centavos
    avisos: List[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(l.centavos for l in self.linhas)


def ler_dp(path: Path) -> DadosDP:
    """Lê o relatório de pensão do DP (1ª aba)."""
    abas = ler_xlsx(path)
    if not abas:
        raise ValueError("o Excel do DP não tem nenhuma aba legível.")
    linhas = next(iter(abas.values()))
    r = DadosDP()
    for n, row in enumerate(linhas, start=1):
        a = _matricula(row.get(0))
        if re.fullmatch(r"\d{4,8}", a) and row.get(7):
            c = _centavos(row.get(10))
            if c is None:
                r.avisos.append(f"Linha {n}: valor ilegível para a matrícula {a}.")
                continue
            r.linhas.append(LinhaDP(
                matricula=a,
                nome=_limpar_campo(row.get(1, "")),
                competencia=_data_excel(row.get(6)),
                pagamento=_data_excel(row.get(7)),
                referencia=str(row.get(9, "") or "").strip(),
                centavos=c))
            continue
        juntos = " ".join(str(x) for x in row.values())
        if "TOTAL DE COLABORADORES" in _sem_acento(juntos):
            try:
                r.qtd_rodape = int(float(row.get(5)))
            except (TypeError, ValueError):
                pass
            r.total_rodape = _centavos(row.get(10))
    if not r.linhas:
        raise ValueError("não encontrei nenhuma linha de pensão no Excel do DP "
                         "(esperava matrícula na coluna A e pagamento na H).")
    return r


def ler_cadastro(path: Path) -> Dict[str, Tuple[str, str]]:
    """Aba CADASTRO: matrícula (com ou sem -A) → (cód. fornecedor, pensionista)."""
    abas = ler_xlsx(path)
    aba = next((v for k, v in abas.items() if _sem_acento(k) == "CADASTRO"), None)
    if aba is None:
        raise ValueError(f"a planilha {Path(path).name} não tem a aba CADASTRO.")
    cad: Dict[str, Tuple[str, str]] = {}
    for row in aba[1:]:
        m = _matricula(row.get(0))
        cod = _matricula(row.get(2))
        nome = _limpar_campo(row.get(3, ""))
        if m and cod and nome:
            cad[m] = (cod, nome)
    if not cad:
        raise ValueError("a aba CADASTRO está vazia.")
    return cad


# ====================================================================== #
# Montagem                                                                #
# ====================================================================== #
@dataclass
class PensaoExtra:
    chave: str              # ex. "100002-A" — usado para o valor digitado
    cod: str
    pensionista: str


@dataclass
class CasoDivisao:
    linha: LinhaDP
    principal_cod: str
    principal_nome: str
    extras: List[PensaoExtra]


@dataclass
class LinhaCSV:
    matricula: str
    colaborador: str
    vencimento: date
    cod: str
    fornecedor: str
    titulo: str
    centavos: int

    def como_csv(self, cfg: Dict[str, str]) -> str:
        campos = [
            cfg["regt"], cfg["empresa"], self.vencimento.strftime("%d/%m/%Y"),
            DIAS_SEMANA[self.vencimento.weekday()], self.cod, self.fornecedor,
            self.titulo, valor_br(self.centavos), cfg["observacao"],
            cfg["tipo"], cfg["g_contas"], cfg["transacao"], "", "", "",
        ]
        return ";".join(campos)


@dataclass
class Preparacao:
    """Resultado da 1ª etapa: DP + cadastro cruzados, antes das divisões."""
    dp: DadosDP
    cadastro: Dict[str, Tuple[str, str]]
    casos: List[CasoDivisao] = field(default_factory=list)
    sem_cadastro: List[LinhaDP] = field(default_factory=list)
    competencia: Optional[date] = None
    vencimento: Optional[date] = None
    avisos: List[str] = field(default_factory=list)


def _extras_de(matricula: str, cad: Dict[str, Tuple[str, str]]) -> List[PensaoExtra]:
    out = []
    for letra in "ABCDEFGH":
        chave = f"{matricula}-{letra}"
        if chave in cad:
            cod, nome = cad[chave]
            out.append(PensaoExtra(chave, cod, nome))
    return out


def preparar(dp: DadosDP, cadastro: Dict[str, Tuple[str, str]]) -> Preparacao:
    p = Preparacao(dp=dp, cadastro=cadastro, avisos=list(dp.avisos))
    comps = {l.competencia for l in dp.linhas if l.competencia}
    pags = {l.pagamento for l in dp.linhas if l.pagamento}
    p.competencia = min(comps) if comps else None
    p.vencimento = min(pags) if pags else None
    if len(comps) > 1:
        p.avisos.append("O DP tem mais de uma competência no mesmo arquivo — "
                        "usei a mais antiga para o título.")
    if len(pags) > 1:
        p.avisos.append("O DP tem datas de pagamento diferentes — cada linha "
                        "usa a sua.")
    if p.competencia is None and p.vencimento is not None:
        p.competencia = p.vencimento
    if p.competencia is None:
        p.avisos.append("Não encontrei a competência nem a data de pagamento.")

    if dp.qtd_rodape is not None and dp.qtd_rodape != len(dp.linhas):
        p.avisos.append(f"O rodapé do DP diz {dp.qtd_rodape} colaboradores, "
                        f"mas li {len(dp.linhas)} linhas.")
    if dp.total_rodape is not None and dp.total_rodape != dp.total:
        p.avisos.append(f"O rodapé do DP soma R$ {valor_br(dp.total_rodape)}, "
                        f"mas as linhas somam R$ {valor_br(dp.total)}.")

    for l in dp.linhas:
        if l.matricula not in cadastro:
            p.sem_cadastro.append(l)
            continue
        extras = _extras_de(l.matricula, cadastro)
        if extras:
            cod, nome = cadastro[l.matricula]
            p.casos.append(CasoDivisao(l, cod, nome, extras))
    return p


def titulo_base(competencia: date, sufixo: str = "SAL") -> str:
    return f"{competencia:%m}-{competencia:%Y}-{sufixo}"


def titulo_repetido(competencia: date, sufixo: str = "SAL") -> str:
    return f"{competencia:%m}.{competencia:%Y}-{sufixo}"


@dataclass
class ResultadoPensoes:
    linhas: List[LinhaCSV] = field(default_factory=list)
    erros: List[str] = field(default_factory=list)       # bloqueiam o CSV
    avisos: List[str] = field(default_factory=list)
    total_dp: int = 0
    titulo: str = ""
    cfg: Dict[str, str] = field(default_factory=lambda: dict(PADRAO))

    @property
    def total(self) -> int:
        return sum(l.centavos for l in self.linhas)

    @property
    def ok(self) -> bool:
        return bool(self.linhas) and not self.erros and self.total == self.total_dp


def montar(prep: Preparacao, valores_extra: Dict[str, Optional[int]],
           cfg: Optional[Dict[str, Any]] = None) -> ResultadoPensoes:
    """
    valores_extra: chave "100002-A" → centavos digitados (None = não preenchido).
    0 = essa pensão não é paga neste mês (não gera linha).
    """
    c = dict(PADRAO)
    for k, v in (cfg or {}).items():
        if k in PADRAO and v not in (None, ""):
            c[k] = str(v)
    r = ResultadoPensoes(total_dp=prep.dp.total, cfg=c, avisos=list(prep.avisos))

    for l in prep.sem_cadastro:
        r.erros.append(f"Matrícula {l.matricula} ({l.nome}) não está no CADASTRO.")
    if prep.competencia is None:
        r.erros.append("Sem competência/pagamento — não dá para montar o título.")
        return r

    sufixo = c["sufixo_titulo"]
    r.titulo = titulo_base(prep.competencia, sufixo)
    casos = {cs.linha.matricula: cs for cs in prep.casos}

    brutas: List[Tuple[LinhaDP, str, str, int]] = []   # (linha, cod, nome, centavos)
    for l in prep.dp.linhas:
        if l.matricula not in prep.cadastro:
            continue
        cod, nome = prep.cadastro[l.matricula]
        caso = casos.get(l.matricula)
        if not caso:
            brutas.append((l, cod, nome, l.centavos))
            continue
        soma, faltando = 0, False
        partes: List[Tuple[str, str, int]] = []
        for ex in caso.extras:
            v = valores_extra.get(ex.chave)
            if v is None:
                faltando = True
                continue
            if v < 0:
                r.erros.append(f"{l.nome}: valor negativo para {ex.pensionista}.")
                faltando = True
                continue
            soma += v
            partes.append((ex.cod, ex.pensionista, v))
        if faltando:
            r.erros.append(f"{l.nome}: falta digitar o valor de "
                           + ", ".join(e.pensionista for e in caso.extras) + ".")
            continue
        resto = l.centavos - soma
        if resto < 0:
            r.erros.append(f"{l.nome}: as pensões extras (R$ {valor_br(soma)}) passam "
                           f"do valor do DP (R$ {valor_br(l.centavos)}).")
            continue
        if resto > 0:
            brutas.append((l, cod, nome, resto))
        for pc, pn, pv in partes:
            if pv > 0:
                brutas.append((l, pc, pn, pv))

    # títulos: 1ª vez do fornecedor = MM-AAAA-SAL, 2ª = MM.AAAA-SAL
    usos: Dict[str, int] = {}
    for l, cod, nome, v in brutas:
        usos[cod] = usos.get(cod, 0) + 1
        n = usos[cod]
        if n == 1:
            tit = titulo_base(prep.competencia, sufixo)
        elif n == 2:
            tit = titulo_repetido(prep.competencia, sufixo)
        else:
            r.erros.append(f"{nome} (cód. {cod}) aparece {n} vezes — só existem 2 "
                           "títulos (com traço e com ponto). Ajuste à mão.")
            tit = titulo_repetido(prep.competencia, sufixo)
        venc = l.pagamento or prep.vencimento
        r.linhas.append(LinhaCSV(l.matricula, l.nome, venc, cod, nome, tit, v))

    if not r.erros and r.total != r.total_dp:
        r.erros.append(f"Total do CSV (R$ {valor_br(r.total)}) diferente do total "
                       f"do DP (R$ {valor_br(r.total_dp)}).")
    return r


# ====================================================================== #
# Saída                                                                   #
# ====================================================================== #
def gerar_csv(r: ResultadoPensoes) -> str:
    return "\r\n".join([CABECALHO_CSV] + [l.como_csv(r.cfg) for l in r.linhas]) + "\r\n"


def gravar(r: ResultadoPensoes, destino: Path) -> Path:
    if not r.ok:
        raise ValueError("há pendências — o CSV não foi gerado.")
    destino = Path(destino)
    destino.write_bytes(gerar_csv(r).encode("cp1252", errors="replace"))
    return destino


def processar(dp_path: Path, cadastro_path: Path) -> Preparacao:
    """Etapa pesada (roda em thread): lê os dois Excel e cruza."""
    return preparar(ler_dp(dp_path), ler_cadastro(cadastro_path))
