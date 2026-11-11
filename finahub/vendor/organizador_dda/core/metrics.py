"""
metrics.py
Cálculo de métricas do painel — extraído da Application para separar
responsabilidade de negócio da UI.

Recebe ProcessingResult + DataFrame e devolve um dict tipado de métricas,
sem nenhuma dependência de tkinter ou openpyxl.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict

import pandas as pd

from .processor import ProcessingResult


def calcular_metricas(result: ProcessingResult) -> Dict[str, Any]:
    """
    Retorna dicionário de métricas prontas para o painel de controle.
    Todas as chaves são garantidas — nunca KeyError na UI.
    """
    metricas: Dict[str, Any] = {
        "semana":               "Selecione uma planilha",
        "alfametal":            0.0,
        "betaviaria":           0.0,
        "total_geral":          0.0,
        "propostas":            result.removidas_proposta,
        "siderurgicas":         result.removidas_siderurgicas,
        "valor_siderurgicas":   result.valor_siderurgicas_removidas,
        "pagamentos_alfametal": 0,
        "pagamentos_betaviaria": 0,
        "pendencias_alfametal": 0,
        "pendencias_betaviaria": 0,
        "erros":                0,
    }

    df = result.df
    if df.empty:
        # Cruzamento com banco — preenchido em app.py após cruzamento
        metricas["programados_banco"]   = 0
        metricas["divergentes_banco"]   = 0
        metricas["valor_programado"]    = 0.0
        return metricas

    metricas["programados_banco"]   = 0
    metricas["divergentes_banco"]   = 0
    metricas["valor_programado"]    = 0.0

    metricas["erros"] = int((df.get("ERROS", pd.Series(dtype=str)) != "").sum())
    metricas["duplicatas"] = int(len(result.duplicatas)) if hasattr(result, "duplicatas") else 0

    df_validos = df[pd.notna(df["VENC"])].copy()
    if df_validos.empty:
        return metricas

    menor_data = df_validos["VENC"].min()
    segunda = menor_data - timedelta(days=menor_data.weekday())
    sexta   = segunda + timedelta(days=4)
    metricas["semana"] = f"Semana de {segunda.strftime('%d')} a {sexta.strftime('%d/%m/%Y')}"

    mask_semana = (
        df_validos["VENC"].dt.date >= segunda.date()
    ) & (
        df_validos["VENC"].dt.date <= sexta.date()
    )
    semana_df = df_validos[mask_semana]

    alfametal_empresas  = ["ALFAMETAL MATRIZ", "ALFAMETAL MG"]
    betaviaria_empresas = ["BETAVIARIA MATRIZ", "BETAVIARIA PE"]

    fdf = semana_df[semana_df["EMPRESA"].isin(alfametal_empresas)]
    tdf = semana_df[semana_df["EMPRESA"].isin(betaviaria_empresas)]

    metricas["alfametal"]             = float(fdf["VALOR"].dropna().sum())
    metricas["betaviaria"]            = float(tdf["VALOR"].dropna().sum())
    metricas["total_geral"]           = metricas["alfametal"] + metricas["betaviaria"]
    metricas["pagamentos_alfametal"]  = int(len(fdf))
    metricas["pagamentos_betaviaria"] = int(len(tdf))

    # Pendências = linhas com ERROS não vazios dentro de cada grupo
    if "ERROS" in df.columns:
        metricas["pendencias_alfametal"]  = int(
            ((df["EMPRESA"].isin(alfametal_empresas)) & (df["ERROS"] != "")).sum()
        )
        metricas["pendencias_betaviaria"] = int(
            ((df["EMPRESA"].isin(betaviaria_empresas)) & (df["ERROS"] != "")).sum()
        )

    return metricas
