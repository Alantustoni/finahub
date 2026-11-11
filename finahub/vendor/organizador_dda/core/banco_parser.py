"""
banco_parser.py
Lê planilhas do banco (ConsultaPagamentos Bradesco/Itaú).
Retorna lista de PagamentoBanco para cruzamento com o DDA.

Estrutura identificada nas planilhas reais:
  - Linha 5:  Agência/conta + Nome da empresa
  - Linha 6:  CNPJ da empresa
  - Linha 18: Cabeçalho dos dados (favorecido, CPF/CNPJ, tipo, referência, data, valor, status)
  - Linha 19+: Dados
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import pandas as pd


# ------------------------------------------------------------------ #
# Remoção siderúrgica — FONTE ÚNICA DA VERDADE                         #
# Os nomes de empresa vêm de config.remover_texto (mesma lista do      #
# processor). Aqui adicionamos apenas uma rede de segurança genérica   #
# com fronteira de palavra (\b) para evitar falsos positivos — ex.:    #
# "USINAGEM PRECISAO" NÃO é mais removido por engano (o antigo         #
# "USINAS?" sem \b casava o prefixo "USINA").                          #
# ------------------------------------------------------------------ #
_GENERICOS_SIDERURGICOS = r"\bUSINAS?\b|\bSIDERURGICA\b|\bSIDERURGICO\b"

_RE_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _norm_termo(t: str) -> str:
    """Normaliza um termo para ASCII uppercase sem acentos (igual ao processor)."""
    s = str(t).strip().upper()
    return unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")


def construir_regex_siderurgico(termos_config=None) -> "re.Pattern":
    """
    Monta a regex de remoção a partir da MESMA lista usada pelo processor
    (config.remover_texto) + a rede de segurança genérica.

    Passe config.remover_texto aqui para manter uma única fonte da verdade.
    Sem argumento, cai num default que preserva o comportamento de
    chamadas diretas a parse_banco().
    """
    partes = [_GENERICOS_SIDERURGICOS]
    for t in (termos_config or []):
        tn = _norm_termo(t)
        if tn:
            partes.append(re.escape(tn))
    return re.compile("|".join(partes), re.IGNORECASE)


# Default sem config — usado apenas quando parse_banco é chamado sem termos.
_TERMOS_SIDERURGICOS = construir_regex_siderurgico(
    ["USIMINAS", "ARCELOR", "ARCELORMITTAL", "COMPANHIA SIDERURGICA"]
)


@dataclass
class PagamentoBanco:
    empresa_banco: str        # Nome da empresa dona da conta (Alfametal / Betaviaria)
    cnpj_empresa: str         # CNPJ da empresa dona da conta
    favorecido: str           # Nome do favorecido/fornecedor
    cnpj_favorecido: str      # CNPJ do favorecido
    tipo_pagamento: str
    referencia: str
    data: Optional[object]    # date
    valor: Optional[float]
    status: str
    favorecido_norm: str = field(default="", repr=False)  # normalizado para matching
    grupo: str = field(default="", repr=False)             # grupo p/ escopo (Alfametal/Betaviaria)

    def __post_init__(self):
        self.favorecido_norm = _normalizar(self.favorecido)


def _normalizar(texto: str) -> str:
    """ASCII uppercase sem acentos, sem palavras genéricas."""
    if not texto or str(texto).strip().lower() in ("nan", "none", ""):
        return ""
    s = str(texto).strip().upper()
    s = unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")
    # Remove sufixos jurídicos e palavras genéricas
    for palavra in (
        r"\bLTDA\.?\b", r"\bS/?A\.?\b", r"\bEIRELI\b", r"\bME\b", r"\bEPP\b",
        r"\bINDUSTRIA\b", r"\bINDUSTRIAL\b", r"\bCOMERCIO\b", r"\bCOMERCIAL\b",
        r"\bSERVICOS\b", r"\bIMPORTADORA\b", r"\bEXPORTADORA\b",
        r"\bDO BRASIL\b", r"\bDE BRASIL\b",
    ):
        s = re.sub(palavra, " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_valor(texto: str) -> Optional[float]:
    if not texto or str(texto).strip().lower() in ("nan", "none", "-", ""):
        return None
    texto = str(texto).replace("R$", "").replace(" ", "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except Exception:
        return None


def _parse_data(texto: str):
    """Retorna date ou None. Suporta DD/MM/YYYY e ISO."""
    if not texto or str(texto).strip().lower() in ("nan", "none", ""):
        return None
    texto = str(texto).strip()
    is_iso = bool(_RE_DATA_ISO.match(texto))
    ts = pd.to_datetime(texto, dayfirst=not is_iso, errors="coerce")
    return ts.date() if pd.notna(ts) else None


def _detectar_empresa(df: pd.DataFrame) -> tuple[str, str]:
    """Extrai nome e CNPJ da empresa dona da conta nas linhas de cabeçalho."""
    for i in range(min(10, len(df))):
        row = df.iloc[i]
        for j, val in enumerate(row.values):
            if "nome da empresa" in str(val).lower() and j + 1 < len(row):
                nome = str(row.iloc[j + 1]).strip()
                if nome.lower() not in ("nan", "none", ""):
                    # CNPJ geralmente na linha seguinte, col 1
                    cnpj = ""
                    if i + 1 < len(df):
                        cnpj_row = df.iloc[i + 1]
                        if len(cnpj_row) > 1:
                            cnpj = str(cnpj_row.iloc[1]).strip()
                    return nome, cnpj
    return "Desconhecido", ""


def _localizar_linha_cabecalho(df: pd.DataFrame) -> Optional[int]:
    """Encontra a linha que contém 'favorecido' no cabeçalho."""
    for i, row in df.iterrows():
        vals = [str(v).lower() for v in row.values]
        if any("favorecido" in v or "beneficiario" in v for v in vals):
            return i
    return None


def _engine_excel(path: Path) -> Optional[str]:
    """Escolhe a engine de leitura: xlrd/calamine para .xls, default para .xlsx."""
    if path.suffix.lower() != ".xls":
        return None
    try:
        import xlrd  # noqa
        return "xlrd"
    except ImportError:
        try:
            import python_calamine  # noqa
            return "calamine"
        except ImportError:
            raise ImportError(
                "Para ler arquivos .xls instale: pip install xlrd"
            )


def detectar_empresa_arquivo(path: Path) -> str:
    """
    Le apenas as primeiras linhas do extrato e retorna o nome da empresa
    dona da conta ('' se nao identificada). Leve o suficiente para rodar
    no momento da selecao do arquivo — permite um unico botao
    'Anexar banco' com classificacao automatica.
    """
    engine = _engine_excel(path)
    try:
        if engine:
            df = pd.read_excel(path, header=None, nrows=12,
                               dtype=str, engine=engine)
        else:
            df = pd.read_excel(path, header=None, nrows=12, dtype=str)
    except Exception:
        return ""
    nome, _ = _detectar_empresa(df.fillna(""))
    return "" if nome == "Desconhecido" else nome


def parse_banco(path: Path, termos_siderurgicos=None,
                cnpjs_excluidos=None, manter_termos=None) -> List[PagamentoBanco]:
    """
    Lê uma planilha ConsultaPagamentos do banco.
    Aceita .xls (converte via LibreOffice) e .xlsx.
    Ignora linhas de siderúrgicas automaticamente.

    termos_siderurgicos: lista opcional (use config.remover_texto) para
    manter a remoção alinhada com o processor. Se None, usa o default.
    cnpjs_excluidos: lista opcional (use config.cnpjs_excluidos) —
    exclusão determinística pela raiz do CNPJ do favorecido.
    """
    regex_sider = (
        construir_regex_siderurgico(termos_siderurgicos)
        if termos_siderurgicos is not None
        else _TERMOS_SIDERURGICOS
    )
    # [ALAN 29/10/2026] favorecidos que ficam mesmo batendo nos termos de
    # usina (ex.: SOLUÇÕES EM AÇO USIMINAS) — senão nunca casariam no banco
    _manter = [_norm_termo(t) for t in (manter_termos or []) if _norm_termo(t)]
    regex_manter = (re.compile("|".join(re.escape(t) for t in _manter), re.IGNORECASE)
                    if _manter else None)
    raizes_excluidas = set()
    for c in (cnpjs_excluidos or []):
        dig = re.sub(r"\D", "", str(c))
        if len(dig) >= 8:
            raizes_excluidas.add(dig[:8])

    engine = _engine_excel(path)
    if engine:
        sheets = pd.read_excel(path, header=None, sheet_name=None,
                               dtype=str, engine=engine)
    else:
        sheets = pd.read_excel(path, header=None, sheet_name=None, dtype=str)
    resultados: List[PagamentoBanco] = []

    for _, df in sheets.items():
        df = df.fillna("")

        empresa_nome, empresa_cnpj = _detectar_empresa(df)
        header_row = _localizar_linha_cabecalho(df)
        if header_row is None:
            continue

        # Mapeia índices das colunas pelo cabeçalho
        cabecalho = [str(v).lower().strip() for v in df.iloc[header_row].values]

        def idx(keywords):
            for i, c in enumerate(cabecalho):
                if any(k in c for k in keywords):
                    return i
            return None

        i_fav   = idx(["favorecido", "beneficiario"])
        i_cnpj  = idx(["cpf", "cnpj"])
        i_tipo  = idx(["tipo"])
        i_ref   = idx(["referencia", "refer"])
        i_data  = idx(["data"])
        i_valor = idx(["valor"])
        i_status= idx(["status"])

        if i_fav is None or i_data is None or i_valor is None:
            continue

        dados = df.iloc[header_row + 1:].reset_index(drop=True)

        for _, row in dados.iterrows():
            fav = str(row.iloc[i_fav]).strip()
            if not fav or fav.lower() in ("nan", "", "total:", "total"):
                continue
            # Ignora linha de total no rodapé
            if fav.lower().startswith("total"):
                continue
            # Ignora siderúrgicas — por CNPJ (determinístico) e por nome
            cnpj_fav_pre = str(row.iloc[i_cnpj]).strip() if i_cnpj is not None else ""
            if raizes_excluidas:
                dig_fav = re.sub(r"\D", "", cnpj_fav_pre)
                if len(dig_fav) >= 8 and dig_fav[:8] in raizes_excluidas:
                    continue
            if regex_sider.search(fav) and not (
                    regex_manter and regex_manter.search(_norm_termo(fav))):
                continue

            data_val  = _parse_data(str(row.iloc[i_data]).strip()  if i_data  is not None else "")
            valor_val = _parse_valor(str(row.iloc[i_valor]).strip() if i_valor is not None else "")
            cnpj_fav  = str(row.iloc[i_cnpj]).strip()  if i_cnpj  is not None else ""
            tipo      = str(row.iloc[i_tipo]).strip()  if i_tipo  is not None else ""
            ref       = str(row.iloc[i_ref]).strip()   if i_ref   is not None else ""
            status    = str(row.iloc[i_status]).strip()if i_status is not None else ""

            if data_val is None or valor_val is None:
                continue

            resultados.append(PagamentoBanco(
                empresa_banco=empresa_nome,
                cnpj_empresa=empresa_cnpj,
                favorecido=fav,
                cnpj_favorecido=cnpj_fav,
                tipo_pagamento=tipo,
                referencia=ref,
                data=data_val,
                valor=valor_val,
                status=status,
            ))

    return resultados
