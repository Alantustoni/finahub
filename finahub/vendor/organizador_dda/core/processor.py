"""
processor.py
DataProcessor — logica de negocio pura, sem UI, sem Excel.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .config import Config
from .utils import cnpj_digitos, formatar_cnpj, normalizar_texto, tratar_nota, tratar_valor
from .aprendizado import carregar_abreviacoes_aprendidas

logger = logging.getLogger(__name__)

# Regex de modulo — compilado uma vez ao importar
_RE_ARTIGOS_PROC = re.compile(r"\b(DE|DA|DO|DAS|DOS|E)\b")
_RE_DATA_ISO     = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _calcular_pascoa(ano: int) -> datetime:
    """
    Domingo de Pascoa pelo algoritmo de Meeus/Jones/Butcher.
    Valido para todo o calendario gregoriano — sem dependencia externa.
    """
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return datetime(ano, mes, dia)


def feriados_moveis(ano: int) -> List[datetime]:
    """
    Feriados bancarios moveis do ano (FEBRABAN):
    segunda e terca de Carnaval, Sexta-feira Santa e Corpus Christi.
    A lista fixa do config so cobre feriados de data fixa — sem estes,
    o ajuste de data util empurra vencimento para dia sem expediente.
    """
    pascoa = _calcular_pascoa(ano)
    return [
        pascoa - timedelta(days=48),  # segunda de Carnaval
        pascoa - timedelta(days=47),  # terca de Carnaval
        pascoa - timedelta(days=2),   # Sexta-feira Santa
        pascoa + timedelta(days=60),  # Corpus Christi
    ]


class ProcessingResult:
    """Transporta o DataFrame tratado e todas as metricas de processamento."""

    __slots__ = (
        "df",
        "total_original",
        "total_processado",
        "removidas_proposta",
        "removidas_siderurgicas",
        "valor_siderurgicas_removidas",
        "resumo_remocoes",
        "error_counts",
        "duplicatas",
        "col_map",
        "col_warnings",
    )

    def __init__(self) -> None:
        self.df: pd.DataFrame = pd.DataFrame()
        self.total_original: int = 0
        self.total_processado: int = 0
        self.removidas_proposta: int = 0
        self.removidas_siderurgicas: int = 0
        self.valor_siderurgicas_removidas: float = 0.0
        self.resumo_remocoes: List[Tuple[str, int]] = []
        self.error_counts: pd.Series = pd.Series(dtype=int)
        self.duplicatas: pd.DataFrame = pd.DataFrame()
        # Transparencia de deteccao de colunas (item 4)
        self.col_map: Dict[str, str] = {}
        self.col_warnings: List[str] = []


class DataProcessor:
    """
    Responsabilidade unica: transformar o Excel DDA bruto no DataFrame
    tratado + metricas de processamento.
    """

    _COLS_BUSCA: Dict[str, List[str]] = {
        "FILIAL":     ["FILIAL"],
        "EMPRESA":    ["EMPRESA"],
        "CNPJ":       ["CNPJ"],
        "FORNECEDOR": ["FORNECEDOR"],
        "NOTA":       ["NOTA", "NF", "PRV"],
        "TIPO":       ["TIPO"],
        "VENC":       ["VENCIMENTO", "VENC"],
        "VALOR":      ["VALOR"],
    }

    def __init__(self, config: Config) -> None:
        self.config = config
        self._feriados_cache: Dict[int, List[datetime]] = {}
        termos = [normalizar_texto(t) for t in config.remover_texto]
        self._re_siderurgico = re.compile(
            "|".join(re.escape(t) for t in termos), re.IGNORECASE
        )
        self._palavras_remover: set = set(config.palavras_remover_fornecedor)
        # Exclusao deterministica por CNPJ: compara pela raiz (8 digitos),
        # cobrindo todas as filiais do mesmo grupo com uma unica entrada.
        self._cnpjs_excluidos_raiz: set = {
            cnpj_digitos(c)[:8]
            for c in config.cnpjs_excluidos
            if len(cnpj_digitos(c)) >= 8
        }
        # Merge: abreviações do config.json + aprendidas automaticamente
        abreviacoes_merged = {**config.abreviacoes, **carregar_abreviacoes_aprendidas()}
        self._abreviacoes_norm: Dict[str, str] = {
            normalizar_texto(k): v for k, v in abreviacoes_merged.items()
        }

    # ------------------------------------------------------------------ #
    # API publica                                                          #
    # ------------------------------------------------------------------ #

    def processar(self, arquivo: Path) -> ProcessingResult:
        result = ProcessingResult()

        logger.info("Carregando arquivo: %s", arquivo.name)
        df = self._carregar_dataframe(arquivo)
        col_map, col_warnings = self._identificar_colunas(df)
        result.col_map = dict(col_map)
        result.col_warnings = col_warnings

        # Transparencia (item 4): registra o que foi detectado e alerta.
        logger.info("Colunas detectadas: %s", col_map)
        for aviso in col_warnings:
            logger.warning("Deteccao de coluna: %s", aviso)

        base = self._extrair_colunas(df, col_map)
        result.total_original = len(base)

        logger.info("Padronizando empresas...")
        base["EMPRESA"] = self._padronizar_empresa_vetorizado(
            base["FILIAL"].astype(str),
            base["EMPRESA_ORIGINAL"].astype(str),
        )

        base, result.removidas_proposta = self._remover_propostas(base)

        base, result.removidas_siderurgicas, result.valor_siderurgicas_removidas = (
            self._remover_siderurgicas(base)
        )
        result.total_processado = len(base)
        result.resumo_remocoes = self._montar_resumo(
            result.removidas_proposta,
            result.removidas_siderurgicas,
        )

        logger.info("Transformando colunas...")
        base = self._transformar_colunas(base)

        logger.info("Validando linhas...")
        base["ERROS"] = self._validar_vetorizado(base)

        all_errors = base["ERROS"].str.split(" | ", expand=True).stack()
        result.error_counts = all_errors[all_errors != ""].value_counts()

        logger.info("Detectando duplicatas...")
        result.duplicatas = self._detectar_duplicatas(base)

        base = base.sort_values(
            by=["VENC", "VALOR", "FORNECEDOR"],
            ascending=[True, True, True],
            na_position="last",
        )

        result.df = base.reset_index(drop=True)
        logger.info("Processamento concluido — %d linhas tratadas.", len(base))
        return result

    # ------------------------------------------------------------------ #
    # Carregamento                                                         #
    # ------------------------------------------------------------------ #

    def _carregar_dataframe(self, arquivo: Path) -> pd.DataFrame:
        # dtype=str evita inferencia de tipos e e mais rapido que dtype=object
        df = pd.read_excel(arquivo, dtype=str)
        df = df.loc[:, df.columns.notna()]
        df = df.loc[
            :,
            ~df.columns.astype(str).str.contains(
                r"^UNNAMED", case=False, regex=True
            ),
        ]
        df = df.dropna(axis=1, how="all")
        return df

    def _localizar_coluna(self, df: pd.DataFrame, opcoes: List[str]) -> Optional[str]:
        for col in df.columns:
            nome = normalizar_texto(col)
            for opcao in opcoes:
                if normalizar_texto(opcao) in nome:
                    return col
        return None

    def _colunas_candidatas(self, df: pd.DataFrame, opcoes: List[str]) -> List[str]:
        """Todas as colunas do df que casam com alguma opcao (para detectar ambiguidade)."""
        achadas = []
        for col in df.columns:
            nome = normalizar_texto(col)
            if any(normalizar_texto(op) in nome for op in opcoes):
                achadas.append(col)
        return achadas

    def _identificar_colunas(
        self, df: pd.DataFrame
    ) -> Tuple[Dict[str, str], List[str]]:
        """
        Detecta as colunas obrigatorias e retorna (mapeamento, avisos).
        Os avisos tornam a deteccao transparente (item 4): ambiguidade,
        uso de fallback, etc. — para o usuario validar antes de confiar.
        """
        mapeamento: Dict[str, Optional[str]] = {}
        avisos: List[str] = []

        for alias, opcoes in self._COLS_BUSCA.items():
            candidatas = self._colunas_candidatas(df, opcoes)
            mapeamento[alias] = candidatas[0] if candidatas else None
            if len(candidatas) > 1 and alias != "FORNECEDOR":
                avisos.append(
                    f"{alias}: mais de uma coluna possivel {candidatas} — "
                    f"usei '{candidatas[0]}'. Confira se e a correta."
                )

        # FORNECEDOR: prefere ultima coluna com "FORNECEDOR" no nome
        colunas_forn = [c for c in df.columns if "FORNECEDOR" in normalizar_texto(c)]
        if colunas_forn:
            mapeamento["FORNECEDOR"] = colunas_forn[-1]
            if len(colunas_forn) > 1:
                avisos.append(
                    f"FORNECEDOR: varias colunas {colunas_forn} — usei a ultima "
                    f"'{colunas_forn[-1]}'."
                )

        # Fallback FILIAL <-> EMPRESA
        if mapeamento["FILIAL"] is None and mapeamento["EMPRESA"] is not None:
            mapeamento["FILIAL"] = mapeamento["EMPRESA"]
            avisos.append("FILIAL nao encontrada — usei a coluna de EMPRESA no lugar.")
        if mapeamento["EMPRESA"] is None and mapeamento["FILIAL"] is not None:
            mapeamento["EMPRESA"] = mapeamento["FILIAL"]
            avisos.append("EMPRESA nao encontrada — usei a coluna de FILIAL no lugar.")

        ausentes = [k for k, v in mapeamento.items() if v is None]
        if ausentes:
            raise ValueError(
                f"Colunas obrigatorias nao encontradas na planilha: "
                f"{', '.join(ausentes)}.\n"
                f"Verifique se o arquivo selecionado e uma planilha DDA valida."
            )
        return mapeamento, avisos  # type: ignore[return-value]

    def _extrair_colunas(
        self, df: pd.DataFrame, col_map: Dict[str, str]
    ) -> pd.DataFrame:
        base = df[
            [
                col_map["FILIAL"], col_map["EMPRESA"], col_map["CNPJ"],
                col_map["FORNECEDOR"], col_map["NOTA"], col_map["TIPO"],
                col_map["VENC"], col_map["VALOR"],
            ]
        ].copy()
        base.columns = [
            "FILIAL", "EMPRESA_ORIGINAL", "CNPJ",
            "FORNECEDOR", "PRV NF", "TIPO", "VENC", "VALOR",
        ]
        # Garantir que todas as colunas sao string nesta etapa
        for col in base.columns:
            base[col] = base[col].fillna("").astype(str).str.strip()
        # Remover linhas completamente vazias
        base = base[~(base == "").all(axis=1)].copy()
        return base.reset_index(drop=True)

    # ------------------------------------------------------------------ #
    # Transformacoes vetorizadas                                           #
    # ------------------------------------------------------------------ #

    def _padronizar_empresa_vetorizado(
        self, filial_col: pd.Series, empresa_col: pd.Series
    ) -> pd.Series:
        """
        Substitui apply(axis=1) por np.select — executa em C, nao Python puro.
        Speedup tipico: 20-50x para DataFrames > 1.000 linhas.
        """
        def norm_series(s: pd.Series) -> pd.Series:
            return (
                s.str.strip()
                 .str.upper()
                 .str.normalize("NFKD")
                 .str.encode("ascii", errors="ignore")
                 .str.decode("ascii")
                 .fillna("")
            )

        f = norm_series(filial_col)
        e = norm_series(empresa_col)
        combinado = f + " " + e

        for errado in ("RANSNOVAG", "TRASNOVAG", "TRANS NOVAG"):
            combinado = combinado.str.replace(errado, "BETAVIARIA", regex=False)

        is_betaviaria = combinado.str.contains("BETAVIARIA|TRANSPORTES", regex=True)
        is_alfametal  = combinado.str.contains("ALFAMETAL", regex=False)
        is_pe         = combinado.str.contains(r"\bPE\b", regex=True)
        is_mg         = combinado.str.contains(r"\bMG\b|\bMINAS\b|MINAS GERAIS", regex=True)
        is_f_mg       = f.isin(["MG", "MINAS", "MINAS GERAIS", "ALFAMETAL MG", "F-MG", "FMG"])
        is_f_matriz   = f.isin(["MATRIZ", "ALFAMETAL MATRIZ"])
        starts_f      = f.str.startswith("F") & ~is_f_mg & ~is_f_matriz
        starts_t      = f.str.startswith("T")

        conditions = [
            is_betaviaria & is_pe,
            is_betaviaria,
            is_alfametal & is_mg,
            is_alfametal,
            is_f_mg,
            is_f_matriz & combinado.str.contains("BETAVIARIA|TRANSPORTES", regex=True),
            is_f_matriz,
            starts_f & is_mg,
            starts_f,
            starts_t & is_pe,
            starts_t,
        ]
        choices = [
            "BETAVIARIA PE",
            "BETAVIARIA MATRIZ",
            "ALFAMETAL MG",
            "ALFAMETAL MATRIZ",
            "ALFAMETAL MG",
            "BETAVIARIA MATRIZ",
            "ALFAMETAL MATRIZ",
            "ALFAMETAL MG",
            "ALFAMETAL MATRIZ",
            "BETAVIARIA PE",
            "BETAVIARIA MATRIZ",
        ]
        return pd.Series(
            np.select(conditions, choices, default=e.values),
            index=filial_col.index,
        )

    def _remover_propostas(
        self, base: pd.DataFrame
    ) -> Tuple[pd.DataFrame, int]:
        mask = base["TIPO"].astype(str).str.upper().str.contains("PROPOSTA", na=False)
        return base[~mask].copy(), int(mask.sum())

    def _remover_siderurgicas(
        self, base: pd.DataFrame
    ) -> Tuple[pd.DataFrame, int, float]:
        """
        Exclusao em duas camadas:
          1. CNPJ (deterministica) — raiz de 8 digitos contra cnpjs_excluidos.
          2. Texto (rede de seguranca) — regex unico sobre a linha concatenada.
        Concatenacao vetorizada coluna a coluna — elimina o apply(axis=1)
        que era o ultimo passe linha-a-linha do pipeline.
        """
        if base.empty:
            return base, 0, 0.0

        # Camada 1 — CNPJ raiz
        mask_cnpj = pd.Series(False, index=base.index)
        if self._cnpjs_excluidos_raiz:
            raizes = (
                base["CNPJ"].astype(str)
                .str.replace(r"\D", "", regex=True)
                .str[:8]
            )
            mask_cnpj = raizes.isin(self._cnpjs_excluidos_raiz)

        # Camada 2 — texto (vetorizado: soma de Series de string, sem apply)
        cols = list(base.columns)
        texto_completo = base[cols[0]].astype(str)
        for c in cols[1:]:
            texto_completo = texto_completo + " " + base[c].astype(str)
        mask_texto = texto_completo.str.contains(
            self._re_siderurgico, regex=True, na=False
        )

        mask = mask_cnpj | mask_texto

        qtd = int(mask.sum())
        valor = 0.0
        if qtd:
            valor = float(
                base.loc[mask, "VALOR"]
                .apply(tratar_valor)
                .dropna()
                .sum()
            )
        return base[~mask].copy(), qtd, valor

    def _transformar_colunas(self, base: pd.DataFrame) -> pd.DataFrame:
        base = base.copy()
        base["CNPJ"]       = base["CNPJ"].apply(formatar_cnpj)
        base["FORNECEDOR"] = base["FORNECEDOR"].apply(self._abreviar_fornecedor)
        base["PRV NF"]     = base["PRV NF"].apply(tratar_nota)
        base["VENC"]       = base["VENC"].apply(self._ajustar_data_util)
        base["VALOR"]      = base["VALOR"].apply(tratar_valor)
        return base[
            ["FILIAL", "EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF", "TIPO", "VENC", "VALOR"]
        ]

    def _validar_vetorizado(self, base: pd.DataFrame) -> pd.Series:
        """
        Validacao por coluna inteira em vez de apply(axis=1) por linha.
        Garante que todas as comparacoes sao feitas com tipos corretos.
        """
        empresas_validas = set(self.config.empresas_validas)

        # Garantir tipos corretos antes de cada comparacao
        empresa_str    = base["EMPRESA"].fillna("").astype(str)
        fornecedor_str = base["FORNECEDOR"].fillna("").astype(str).str.strip()
        nota_str       = base["PRV NF"].fillna("").astype(str).str.strip()
        cnpj_str       = base["CNPJ"].fillna("").astype(str).str.strip()

        erros_empresa    = ~empresa_str.isin(empresas_validas)
        erros_fornecedor = fornecedor_str == ""
        # Nota "0" e' tao invalida quanto nota vazia (dado ausente vindo do ERP).
        erros_nota       = (nota_str == "") | (nota_str == "0")
        erros_venc       = base["VENC"].isna()
        erros_valor_na   = base["VALOR"].isna()
        erros_valor_zero = (~erros_valor_na) & (base["VALOR"].fillna(1) == 0)
        erros_cnpj       = cnpj_str == ""

        mapeamento_erros = {
            "Empresa nao reconhecida": erros_empresa,
            "Fornecedor vazio":        erros_fornecedor,
            "Nota vazia":              erros_nota,
            "Data invalida":           erros_venc,
            "Valor invalido":          erros_valor_na,
            "Valor zerado":            erros_valor_zero,
            "CNPJ vazio":              erros_cnpj,
        }

        # Construcao eficiente da coluna de erros
        erros_por_linha: List[List[str]] = [[] for _ in range(len(base))]
        for msg, mask_series in mapeamento_erros.items():
            # tolist() e mais rapido que iteracao com iloc
            mask_list = mask_series.tolist()
            for i, tem_erro in enumerate(mask_list):
                if tem_erro:
                    erros_por_linha[i].append(msg)

        return pd.Series(
            [" | ".join(erros) for erros in erros_por_linha],
            index=base.index,
        )

    # ------------------------------------------------------------------ #
    # Helpers de transformacao                                             #
    # ------------------------------------------------------------------ #

    def _detectar_duplicatas(self, base: pd.DataFrame) -> pd.DataFrame:
        """
        Detecta linhas com mesmo FORNECEDOR + VALOR + VENC dentro do mesmo DDA.
        Retorna DataFrame com as linhas duplicadas (excluindo a primeira ocorrência).
        """
        if base.empty:
            return pd.DataFrame()
        mask = base.duplicated(
            subset=["FORNECEDOR", "VALOR", "VENC"],
            keep=False,  # marca TODAS as ocorrências, inclusive a primeira
        )
        dupl = base[mask].copy()
        if not dupl.empty:
            dupl["GRUPO_DUPLICATA"] = (
                dupl.groupby(["FORNECEDOR", "VALOR", "VENC"]).ngroup() + 1
            )
            logger.warning(
                "%d linhas duplicadas detectadas em %d grupos.",
                len(dupl),
                dupl["GRUPO_DUPLICATA"].nunique(),
            )
        return dupl

    def _abreviar_fornecedor(self, nome: Any) -> str:
        # ABREVIACAO DESATIVADA a pedido do usuario.
        # O sistema NAO abrevia mais nomes de fornecedor: mantem o nome
        # COMPLETO. Nao aplica o dicionario de abreviacoes (config +
        # aprendidas), nao remove palavras/artigos/sufixos e nao corta
        # em 2 palavras. Faz apenas a normalizacao de formatacao
        # (maiusculas, sem acentos), igual ao resto do relatorio.
        return normalizar_texto(nome)

    def _ajustar_data_util(self, data: Any) -> Optional[pd.Timestamp]:
        if pd.isna(data) or str(data).strip() in ("", "NaT", "None", "nan"):
            return None

        texto = str(data).strip()

        # Detecta formato ISO (YYYY-MM-DD ou YYYY-MM-DD HH:MM:SS).
        # Com dayfirst=True o pandas inverte mes/dia nesses casos:
        # '2026-06-01' vira 01/junho correto com dayfirst=False,
        # mas vira 06/janeiro errado com dayfirst=True.
        use_dayfirst = not bool(_RE_DATA_ISO.match(texto))  # BR usa dayfirst=True; ISO usa False

        data_ts = pd.to_datetime(texto, dayfirst=use_dayfirst, errors="coerce")
        if pd.isna(data_ts):
            return None
        # Normaliza para meia-noite: vencimento com hora (ex: 14:30) nunca
        # seria igual ao feriado (meia-noite) e escaparia do ajuste.
        data_dt = datetime(data_ts.year, data_ts.month, data_ts.day)
        # Limitar loop para evitar loop infinito em caso de dados invalidos.
        # Feriados consultados pelo ano da data CORRENTE — cobre a virada
        # de ano (31/12 ajustado para 01/01 do ano seguinte).
        for _ in range(30):
            if data_dt.weekday() < 5 and data_dt not in self._feriados_do_ano(data_dt.year):
                break
            data_dt += timedelta(days=1)
        return pd.Timestamp(data_dt)

    def _feriados_do_ano(self, ano: int) -> List[datetime]:
        if ano not in self._feriados_cache:
            fixos = [
                datetime(ano, int(d.split("/")[1]), int(d.split("/")[0]))
                for d in self.config.feriados
            ]
            self._feriados_cache[ano] = fixos + feriados_moveis(ano)
        return self._feriados_cache[ano]

    @staticmethod
    def _montar_resumo(
        removidas_proposta: int,
        removidas_siderurgicas: int,
    ) -> List[Tuple[str, int]]:
        resumo = []
        if removidas_proposta:
            resumo.append(("Linhas removidas por PROPOSTA", removidas_proposta))
        if removidas_siderurgicas:
            resumo.append(("Linhas removidas por empresas siderurgicas", removidas_siderurgicas))
        return resumo
