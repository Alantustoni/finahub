"""
dda_ext.py — Extensão do DataProcessor do DDA V7 (sem tocar no vendor).

O que acrescenta ao motor original:

  1. PLANILHA SEM CABEÇALHO — se a primeira linha não parecer um
     cabeçalho, as colunas são mapeadas pela POSIÇÃO fixa combinada:
       A=FILIAL · B=EMPRESA · D=CNPJ · E=FORNECEDOR · F=NOTA ·
       G=TIPO · I=VENCIMENTO · L=VALOR
     (basta colar a planilha a partir de A1, sem escrever cabeçalho).
     Se a primeira linha TIVER cabeçalho, funciona como sempre funcionou.

  2. CAPTURA DAS LINHAS REMOVIDAS — as notas de PROPOSTA e as notas de
     USINAS excluídas ficam guardadas (df_propostas / df_usinas) para a
     tela mostrar, em vez de existirem só como contagem.

  3. TOTAIS POR GRUPO DE USINA — cada linha de usina removida é
     classificada em USIMINAS / ARMAR / CSN / SOLUÇÕES / OUTRAS usando
     os mesmos critérios de nome que já existiam no projeto
     (config "remover_texto" do DDA + padronização do módulo Usinas),
     ajustáveis no config.json ("dda_grupos_usinas").
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Tuple

import pandas as pd

from ..vendor.organizador_dda.core.processor import DataProcessor
from ..vendor.organizador_dda.core.utils import normalizar_texto, tratar_valor

logger = logging.getLogger(__name__)

# Layout ANTIGO do DDA (0-based): A B D E F G I L
MAPA_POSICIONAL: Dict[int, str] = {
    0:  "FILIAL",
    1:  "EMPRESA",
    3:  "CNPJ",
    4:  "FORNECEDOR",
    5:  "NOTA",
    6:  "TIPO",
    8:  "VENCIMENTO",
    11: "VALOR",
}

# Layout NOVO do DDA (ago/2026): FILIAL · Pagador · Beneficiário · CPF/CNPJ ·
# Venc. · Nº doc. · Até venc. · A pagar · Tipo de boleto · Banco · Observações
MAPA_POSICIONAL_NOVO: Dict[int, str] = {
    0: "FILIAL",
    1: "EMPRESA",       # Pagador/Agregado
    2: "FORNECEDOR",    # Beneficiário
    3: "CNPJ",          # CPF/CNPJ
    4: "VENCIMENTO",    # Venc.
    5: "NOTA",          # Nº doc.
    7: "VALOR",         # A pagar (a col. 6 "Até venc." é idêntica — ignorada)
    8: "TIPO",          # Tipo de boleto
}

# Palavras que denunciam uma linha de cabeçalho (layout antigo E novo)
_TERMOS_CABECALHO = ("FILIAL", "CNPJ", "FORNECEDOR", "VENCIMENTO",
                     "VALOR", "EMPRESA", "NOTA",
                     "PAGADOR", "BENEFICIARIO", "VENC", "DOC",
                     "PAGAR", "BOLETO")


def _renomear_cabecalho_novo(colunas) -> list:
    """
    Traduz os cabeçalhos do layout NOVO para os nomes canônicos que o
    motor do DDA V7 conhece (EMPRESA/FORNECEDOR/CNPJ/VENCIMENTO/NOTA/
    VALOR/TIPO). Cabeçalhos antigos passam intactos; colunas ambíguas
    ("Até venc." contém VENC, mas não é o vencimento) viram COL_i para
    o motor nunca escolher a coluna errada.
    """
    regras = [                      # (nome canônico, termos, termos proibidos)
        ("FILIAL",     ("FILIAL",), ()),
        ("FORNECEDOR", ("FORNECEDOR", "BENEFICIARIO"), ()),
        ("EMPRESA",    ("PAGADOR", "AGREGADO", "EMPRESA"), ()),
        ("CNPJ",       ("CNPJ", "CPF"), ()),
        ("VENCIMENTO", ("VENCIMENTO", "VENC"), ("ATE",)),   # "Até venc." fora
        ("NOTA",       ("NOTA", "DOC", "PRV"), ()),
        ("VALOR",      ("VALOR", "PAGAR"), ("ATE",)),
        ("TIPO",       ("TIPO", "BOLETO"), ()),
    ]
    novos, usados = [], set()
    for i, col in enumerate(colunas):
        h = normalizar_texto(col)
        nome = None
        for canonico, termos, proibidos in regras:
            if canonico in usados or any(p in h for p in proibidos):
                continue
            casa = any(t in h for t in termos) \
                or (canonico == "NOTA" and h == "NF")
            if casa:
                nome = canonico
                break
        if nome:
            novos.append(nome)
            usados.add(nome)
        else:
            # neutraliza qualquer resto ambíguo (ex.: "Até venc.", "Banco")
            novos.append(f"COL_{i}")
    return novos


def _escolher_mapa_posicional(df) -> Dict[int, str]:
    """
    Sem cabeçalho, decide entre o layout ANTIGO e o NOVO pelo CONTEÚDO:
    conta quantas células parseiam como data/valor nas posições de
    vencimento/valor de cada mapa e fica com o que casa melhor.
    """
    amostra = df.head(50)
    ncols = df.shape[1]

    def pontua(mapa: Dict[int, str]) -> int:
        from ..core.utils import parse_data_br
        inv = {v: k for k, v in mapa.items()}
        if max(mapa) >= ncols:
            return -1                      # planilha nem chega nessa coluna
        pontos = 0
        for _, row in amostra.iterrows():
            if parse_data_br(row.iloc[inv["VENCIMENTO"]]) is not None:
                pontos += 1
            if tratar_valor(row.iloc[inv["VALOR"]]) is not None:
                pontos += 1
        return pontos

    p_novo, p_antigo = pontua(MAPA_POSICIONAL_NOVO), pontua(MAPA_POSICIONAL)
    escolhido = MAPA_POSICIONAL_NOVO if p_novo >= p_antigo else MAPA_POSICIONAL
    logger.info("DDA ext: mapa posicional %s (novo=%d × antigo=%d)",
                "NOVO" if escolhido is MAPA_POSICIONAL_NOVO else "ANTIGO",
                p_novo, p_antigo)
    return escolhido

# Critérios de grupo — mesmos nomes usados no restante do projeto.
# A ORDEM importa (o 1º grupo cujo termo casar vence): SOLUÇÕES vem ANTES
# de USIMINAS para "SOLUCOES USIMINAS" não ser engolido pelo termo genérico.
GRUPOS_USINAS_DEFAULT: Dict[str, List[str]] = {
    "SOLUÇÕES": ["SOLUCOES", "SOLUCOES EM ACO", "SOLUCOES USIMINAS"],
    "ARMAR":    ["ARCELORMITTAL PLANOS", "ARCELORMITTAL",
                 "ARCELOR", "ARMAR", "MITTAL"],
    "CSN":      ["COMPANHIA SIDERURGICA", "SIDERURGICA NACIONAL", "CSN"],
    "USIMINAS": ["USIMINAS", "USINA SIDERURGICA", "USINAS SIDERURGICA",
                 "USINAS SIDERURGICAS"],
}


class DataProcessorExt(DataProcessor):
    """DataProcessor do DDA V7 + cabeçalho opcional + captura de removidas."""

    def __init__(self, config, grupos_usinas: Dict[str, List[str]] | None = None,
                 manter_termos: List[str] | None = None):
        super().__init__(config)
        self.grupos_usinas = grupos_usinas or GRUPOS_USINAS_DEFAULT
        self.manter_termos = list(manter_termos or [])
        self.df_propostas: pd.DataFrame = pd.DataFrame()
        self.df_usinas: pd.DataFrame = pd.DataFrame()
        self.totais_usinas: Dict[str, float] = {}
        self.usou_mapa_posicional: bool = False

    # ------------------------------------------------------------------ #
    def processar(self, arquivo):
        """Motor original + limpeza da NF 'número-número' (Gamma Gasotec)."""
        from .dda_compras import limpar_nf
        result = super().processar(arquivo)
        for df in (result.df, getattr(result, "duplicatas", None), self.df_propostas):
            if df is not None and not df.empty and "PRV NF" in df.columns:
                df["PRV NF"] = df["PRV NF"].map(limpar_nf)
        return result

    # ------------------------------------------------------------------ #
    # 1) Carregamento com cabeçalho opcional                               #
    # ------------------------------------------------------------------ #
    def _carregar_dataframe(self, arquivo) -> pd.DataFrame:
        df = pd.read_excel(arquivo, dtype=str, header=None)
        # IMPORTANTE: não dropar colunas vazias ANTES do mapa posicional —
        # uma coluna em branco no meio (ex.: C) deslocaria o mapeamento.
        if df.empty:
            raise ValueError("A planilha está vazia.")

        primeira = " ".join(
            normalizar_texto(v) for v in df.iloc[0].fillna("").tolist())
        tem_cabecalho = sum(t in primeira for t in _TERMOS_CABECALHO) >= 3

        if tem_cabecalho:
            cabecalhos = [str(c).strip() for c in df.iloc[0].fillna("")]
            norm = " ".join(normalizar_texto(c) for c in cabecalhos)
            if "PAGADOR" in norm or "BENEFICIARIO" in norm:
                # layout NOVO (ago/2026): traduz Pagador/Beneficiário/Venc./
                # Nº doc./A pagar/Tipo de boleto p/ os nomes canônicos do motor
                df.columns = _renomear_cabecalho_novo(cabecalhos)
                logger.info("DDA ext: cabeçalho NOVO traduzido p/ canônico.")
            else:
                # layout antigo: intacto (o motor já sabe lidar com ele)
                df.columns = cabecalhos
            df = df.iloc[1:].reset_index(drop=True)
            self.usou_mapa_posicional = False
            logger.info("DDA ext: cabeçalho detectado na 1ª linha.")
        else:
            # Sem cabeçalho: escolhe entre o layout ANTIGO e o NOVO pelo
            # conteúdo (onde as datas/valores realmente parseiam)
            mapa = _escolher_mapa_posicional(df)
            df.columns = [
                mapa.get(i, f"COL_{i}") for i in range(df.shape[1])
            ]
            self.usou_mapa_posicional = True
            faltam = [n for i, n in mapa.items() if i >= df.shape[1]]
            if faltam:
                raise ValueError(
                    "A planilha colada tem menos colunas que o esperado — "
                    f"faltou chegar até: {', '.join(faltam)}.\n"
                    "Cole a partir de A1 com o layout do relatório DDA.")
            logger.info("DDA ext: sem cabeçalho — mapa posicional aplicado.")

        # limpeza padrão do motor original
        df = df.loc[:, df.columns.notna()]
        df = df.loc[:, ~df.columns.astype(str).str.contains(
            r"^UNNAMED", case=False, regex=True)]
        if self.usou_mapa_posicional:
            # nunca dropar uma coluna NOMEADA pelo mapa (ex.: TIPO toda
            # vazia) — o motor precisa dela; dropa só as COL_* de sobra
            vazias = [c for c in df.columns
                      if str(c).startswith("COL_") and df[c].isna().all()]
            df = df.drop(columns=vazias)
            df[[c for c in df.columns if not str(c).startswith("COL_")]] = \
                df[[c for c in df.columns
                    if not str(c).startswith("COL_")]].fillna("")
        else:
            df = df.dropna(axis=1, how="all")
        return df

    # ------------------------------------------------------------------ #
    # 2) Captura das removidas                                             #
    # ------------------------------------------------------------------ #
    def _remover_propostas(self, base: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
        mask = base["TIPO"].astype(str).str.upper().str.contains(
            "PROPOSTA", na=False)
        self.df_propostas = base[mask].copy()
        return base[~mask].copy(), int(mask.sum())

    def _remover_siderurgicas(self, base: pd.DataFrame):
        """Mesma lógica do motor original + captura e classificação."""
        if base.empty:
            self.df_usinas = pd.DataFrame()
            self.totais_usinas = {}
            return base, 0, 0.0

        mask_cnpj = pd.Series(False, index=base.index)
        if self._cnpjs_excluidos_raiz:
            raizes = (base["CNPJ"].astype(str)
                      .str.replace(r"\D", "", regex=True).str[:8])
            mask_cnpj = raizes.isin(self._cnpjs_excluidos_raiz)

        cols = list(base.columns)
        texto_completo = base[cols[0]].astype(str)
        for c in cols[1:]:
            texto_completo = texto_completo + " " + base[c].astype(str)
        mask_texto = texto_completo.str.contains(
            self._re_siderurgico, regex=True, na=False)

        mask = mask_cnpj | mask_texto
        # [29/10/2026] fornecedores que NÃO são retirados mesmo batendo nos
        # termos de usina (ex.: SOLUÇÕES EM AÇO USIMINAS volta a aparecer)
        if self.manter_termos:
            texto_norm = texto_completo.map(normalizar_texto)
            padrao = "|".join(re.escape(normalizar_texto(t)) for t in self.manter_termos if t)
            if padrao:
                mask = mask & ~texto_norm.str.contains(padrao, regex=True, na=False)
        qtd = int(mask.sum())

        self.df_usinas = base[mask].copy()
        valor = 0.0
        if qtd:
            valores = self.df_usinas["VALOR"].apply(tratar_valor)
            valor = float(valores.dropna().sum())
            self.df_usinas["_VALOR_NUM"] = valores
            # colunas podem faltar em planilhas fora do padrão — usa Series
            # vazia do MESMO tamanho (df.get(col, "") devolveria a string ""
            # e o zip produziria lista de tamanho errado → ValueError)
            vazia = pd.Series("", index=self.df_usinas.index)
            forns = self.df_usinas["FORNECEDOR"] \
                if "FORNECEDOR" in self.df_usinas else vazia
            emps = self.df_usinas["EMPRESA_ORIGINAL"] \
                if "EMPRESA_ORIGINAL" in self.df_usinas \
                else (self.df_usinas["EMPRESA"]
                      if "EMPRESA" in self.df_usinas else vazia)
            self.df_usinas["GRUPO_USINA"] = [
                self._classificar_grupo(f"{forn} {emp}")
                for forn, emp in zip(forns.fillna(""), emps.fillna(""))
            ]
            self.totais_usinas = (
                self.df_usinas.groupby("GRUPO_USINA")["_VALOR_NUM"]
                .sum().fillna(0.0).to_dict())
        else:
            self.totais_usinas = {}

        return base[~mask].copy(), qtd, valor

    # ------------------------------------------------------------------ #
    def _classificar_grupo(self, texto) -> str:
        t = normalizar_texto(texto)
        for grupo, termos in self.grupos_usinas.items():
            if any(normalizar_texto(termo) in t for termo in termos):
                return grupo
        return "OUTRAS"


def semana_do_resultado(df: pd.DataFrame) -> str:
    """'25/07 a 31/07' a partir do menor/maior vencimento tratado."""
    if df is None or df.empty or "VENC" not in df:
        return "—"
    # dayfirst=True: se VENC vier como texto BR, "01/02" é 1º de fevereiro
    vencs = pd.to_datetime(df["VENC"], errors="coerce", dayfirst=True).dropna()
    if vencs.empty:
        return "—"
    return f"{vencs.min():%d/%m} a {vencs.max():%d/%m}"
