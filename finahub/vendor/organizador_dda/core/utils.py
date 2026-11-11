"""
utils.py
Funcoes utilitarias puras — sem estado, sem side-effects.
Todas sao testaveis de forma isolada.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

import pandas as pd


# Regex pre-compilado — compilado uma vez, reutilizado N vezes.
_RE_NAO_DIGITO = re.compile(r"\D")
_RE_NOTACAO_CIENTIFICA = re.compile(r"[Ee][+\-]?\d")


def normalizar_texto(texto: Any) -> str:
    """
    Normaliza para ASCII uppercase sem acentos.
    Retorna string vazia para NaN/None/valores em branco.
    """
    if texto is None:
        return ""
    if isinstance(texto, float):
        # Cobre o caso de NaN e floats vindos do pandas
        try:
            import math
            if math.isnan(texto):
                return ""
        except Exception:
            pass
        return str(int(texto)) if texto == int(texto) else str(texto)
    s = str(texto).strip().upper()
    if s in ("NAN", "NONE", "NAT", ""):
        return ""
    return unicodedata.normalize("NFKD", s).encode("ASCII", "ignore").decode("ASCII")


def cnpj_digitos(valor: Any) -> str:
    """
    Retorna apenas os digitos do CNPJ/CPF.
    Aceita valor formatado (XX.XXX.XXX/XXXX-XX), float vindo do pandas
    ou string crua. Retorna '' para NaN/None/vazio.
    """
    if valor is None:
        return ""
    texto = str(valor).strip()
    if texto.lower() in ("nan", "none", "nat", ""):
        return ""
    if texto.endswith(".0"):
        texto = texto[:-2]
    return _RE_NAO_DIGITO.sub("", texto)


def formatar_cnpj(valor: Any) -> str:
    """Formata 14 digitos como XX.XXX.XXX/XXXX-XX."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    texto = str(valor).strip()
    if texto.lower() in ("nan", "none", "nat", ""):
        return ""
    if texto.endswith(".0"):
        texto = texto[:-2]
    numeros = _RE_NAO_DIGITO.sub("", texto)
    if len(numeros) == 14:
        return (
            f"{numeros[:2]}.{numeros[2:5]}.{numeros[5:8]}"
            f"/{numeros[8:12]}-{numeros[12:]}"
        )
    return texto


def tratar_nota(nota: Any) -> str:
    """
    Retorna a nota fiscal como string limpa, sem casas decimais
    desnecessarias e sem notacao cientifica.
    """
    if nota is None:
        return ""
    if isinstance(nota, float):
        try:
            import math
            if math.isnan(nota):
                return ""
        except Exception:
            pass
        return str(int(nota)) if nota == int(nota) else str(nota)
    if isinstance(nota, int):
        return str(nota)
    texto = str(nota).strip()
    if texto.lower() in ("nan", "none", "nat", ""):
        return ""
    if texto.endswith(".0"):
        return texto[:-2]
    if _RE_NOTACAO_CIENTIFICA.search(texto):
        try:
            return str(int(float(texto.replace(",", "."))))
        except Exception:
            pass
    return texto


def tratar_valor(valor: Any) -> Optional[float]:
    """
    Converte string de valor monetario para float.
    Aceita formato BR (1.234,56) e US (1234.56).
    Retorna None para valores invalidos ou vazios.
    """
    if valor is None:
        return None
    if isinstance(valor, float):
        try:
            import math
            if math.isnan(valor):
                return None
        except Exception:
            pass
        return valor
    if isinstance(valor, int):
        return float(valor)
    texto = str(valor).strip()
    if texto.lower() in ("nan", "none", "nat", ""):
        return None
    # Remove simbolos de moeda e espacos
    texto = texto.replace("R$", "").replace(" ", "").strip()
    # Formato BR: ponto como separador de milhar, virgula como decimal
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except Exception:
        return None
