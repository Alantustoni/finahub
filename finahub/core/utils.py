"""
utils.py — Utilitários compartilhados da suíte.

Concentra o que antes existia em 4 versões diferentes (uma por ferramenta):
parse de valor brasileiro, parse de data com detecção ISO, moeda formatada.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

_RE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")
# só dígitos e separadores depois da limpeza — letra sobrando = não é número
_RE_NUM_LIMPO    = re.compile(r"^[+-]?[\d.,]+$")
# "1.234" / "12.345.678" — ponto como separador de MILHAR (grupos de 3)
_RE_MILHAR_PONTO = re.compile(r"^\d{1,3}(\.\d{3})+$")


def parse_valor_br(valor: Any) -> Optional[float]:
    """
    '1.234,56' → 1234.56 | '1,234.56' → 1234.56 (US) | '1.234' → 1234.0
    '1234.56' → 1234.56  | 1234.56 → 1234.56
    Retorna None quando não dá para interpretar (nunca inventa 0).

    Regras (corrigem dois parses silenciosamente errados):
      • com ponto E vírgula, o ÚLTIMO separador é o decimal —
        "1.234,56" (BR) e "1,234.56" (US) dão ambos 1234.56;
      • só ponto: grupos de 3 dígitos ("1.234", "198.000") são MILHAR;
        caso contrário o ponto é decimal ("783.6", "126908.69").
    """
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        try:
            f = float(valor)
        except (TypeError, ValueError):
            return None
        return None if f != f else f  # NaN check
    texto = str(valor).strip()
    if not texto or texto.lower() in ("nan", "none", "nat", "-"):
        return None
    texto = re.sub(r"^\s*R\$\s*", "", texto, flags=re.IGNORECASE)
    texto = texto.replace(" ", "")
    if not _RE_NUM_LIMPO.match(texto):
        return None                      # letras/símbolos → não inventa número
    tem_ponto, tem_virgula = "." in texto, "," in texto
    if tem_ponto and tem_virgula:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")   # BR: 1.234,56
        else:
            texto = texto.replace(",", "")                     # US: 1,234.56
    elif tem_virgula:
        texto = texto.replace(",", ".")                        # decimal BR
    elif tem_ponto:
        if _RE_MILHAR_PONTO.match(texto.lstrip("+-")):
            texto = texto.replace(".", "")                     # 1.234 → 1234
    try:
        return float(texto)
    except ValueError:
        return None


def parse_data_br(valor: Any) -> Optional[datetime]:
    """
    Aceita datetime, texto BR (dayfirst) e ISO (YYYY-MM-DD) — com ou sem
    hora ("29/07/2026 00:00:00" e "2026-07-29T00:00:00" funcionam).
    A detecção ISO evita o clássico 2026-06-01 virar 6 de janeiro.
    """
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return datetime(valor.year, valor.month, valor.day)
    texto = str(valor).strip()
    if not texto or texto.lower() in ("nan", "none", "nat"):
        return None
    # descarta a parte de hora ANTES de escolher o formato (BR ou ISO)
    texto = re.split(r"[ T]", texto, maxsplit=1)[0]
    iso = bool(_RE_ISO.match(texto))
    formatos_iso = ("%Y-%m-%d",)
    formatos_br  = ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y")
    for fmt in (formatos_iso if iso else formatos_br):
        try:
            d = datetime.strptime(texto, fmt)
            return datetime(d.year, d.month, d.day)
        except ValueError:
            continue
    return None


def formatar_moeda(valor: Optional[float]) -> str:
    """1234.5 → 'R$ 1.234,50'"""
    if valor is None:
        return "—"
    txt = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {txt}"


def timestamp_arquivo() -> str:
    """Sufixo padrão para nome de arquivo gerado."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def abrir_no_sistema(caminho) -> None:
    """
    Abre um arquivo OU pasta no programa padrão do sistema.

    Windows: os.startfile. macOS: open. Linux: xdg-open. Falha silenciosa
    é evitada — quem chama trata a exceção para avisar o usuário.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    p = Path(caminho)
    if not p.exists():
        raise FileNotFoundError(f"não encontrei: {p}")
    if sys.platform.startswith("win"):
        os.startfile(str(p))          # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def mensagem_erro_amigavel(exc: Exception) -> str:
    """
    Traduz erros técnicos em mensagem acionável para o usuário final.

    Caso mais comum: gravar/consolidar um .xlsx (ou .txt) que está ABERTO
    no Excel → Windows devolve [WinError 5] Acesso negado. O usuário não
    precisa ver o caminho do arquivo temporário — precisa saber que basta
    fechar o arquivo e tentar de novo.
    """
    txt = str(exc)
    sinais = ("WinError 5", "Acesso negado", "Permission denied",
              "being used by another process", "Errno 13")
    if isinstance(exc, PermissionError) or any(s in txt for s in sinais):
        return ("o arquivo de destino está ABERTO em outro programa "
                "(provavelmente o Excel) ou sem permissão de escrita. "
                "Feche o arquivo e tente de novo.")
    return txt
