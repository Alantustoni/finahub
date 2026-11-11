"""
excel_styles.py
Centraliza TODOS os estilos openpyxl do sistema.

Padrões aplicados:
  - Objetos de estilo criados UMA VEZ e reutilizados como constantes.
  - NamedStyle disponíveis para registrar no workbook, o que reduz
    serialização XML redundante e o tamanho do arquivo gerado.
  - Nenhuma lógica de negócio aqui — apenas definições visuais.
"""
from __future__ import annotations

from openpyxl.styles import Alignment, Border, Font, NamedStyle, PatternFill, Side

# ------------------------------------------------------------------ #
# Bordas                                                               #
# ------------------------------------------------------------------ #
_SIDE_THIN = Side(style="thin", color="333333")
BORDER_THIN = Border(
    left=_SIDE_THIN, right=_SIDE_THIN,
    top=_SIDE_THIN,  bottom=_SIDE_THIN,
)

# ------------------------------------------------------------------ #
# Preenchimentos                                                       #
# ------------------------------------------------------------------ #
FILL_AZUL          = PatternFill("solid", fgColor="0070C0")
FILL_AMARELO       = PatternFill("solid", fgColor="FFC000")
FILL_VERMELHO      = PatternFill("solid", fgColor="C00000")
FILL_CINZA         = PatternFill("solid", fgColor="D9D9D9")
FILL_VERDE         = PatternFill("solid", fgColor="C6EFCE")
FILL_LARANJA       = PatternFill("solid", fgColor="FCE4D6")
FILL_BRANCO        = PatternFill("solid", fgColor="FFFFFF")
FILL_AZUL_CLARO    = PatternFill("solid", fgColor="DAEEF3")
FILL_CINZA_ESCURO  = PatternFill("solid", fgColor="A6A6A6")
FILL_LARANJA_ESCURO= PatternFill("solid", fgColor="F4B183")
FILL_AMARELO_CLARO = PatternFill("solid", fgColor="FFF2CC")
FILL_PRETO         = PatternFill("solid", fgColor="000000")
FILL_AZUL_DARK     = PatternFill("solid", fgColor="1F4E78")
FILL_ROXO          = PatternFill("solid", fgColor="7030A0")

# ------------------------------------------------------------------ #
# Fontes                                                               #
# ------------------------------------------------------------------ #
FONT_WHITE_BOLD    = Font(bold=True, color="FFFFFF", size=11)
FONT_BLACK_BOLD    = Font(bold=True, color="000000", size=11)
FONT_RED_BOLD_24   = Font(size=24,  bold=True, color="FF0000")
FONT_TITLE_ERROR   = Font(size=18,  bold=True, color="FFFFFF")
FONT_CARD_TITLE    = Font(size=12,  bold=True, color="FFFFFF")
FONT_NORMAL        = Font(color="000000", size=10)
FONT_PAINEL_TITLE  = Font(bold=True, color="FFFFFF", size=16)
FONT_PAINEL_SEMANA = Font(bold=True, color="C00000", size=13)
FONT_CARD_NUM      = Font(bold=True, color="000000", size=15)

# ------------------------------------------------------------------ #
# Alinhamentos                                                         #
# ------------------------------------------------------------------ #
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_RIGHT  = Alignment(horizontal="right",  vertical="center")
ALIGN_LEFT   = Alignment(horizontal="left",   vertical="center")
ALIGN_VCENTER= Alignment(vertical="center")

# ------------------------------------------------------------------ #
# NamedStyles — registrados uma vez no workbook, eliminam XML          #
# redundante e reduzem tamanho do arquivo gerado.                      #
# ------------------------------------------------------------------ #

def _make_named_style(
    name: str,
    font: Font,
    fill: PatternFill,
    alignment: Alignment,
    border: Border | None = None,
    number_format: str = "General",
) -> NamedStyle:
    ns = NamedStyle(name=name)
    ns.font = font
    ns.fill = fill
    ns.alignment = alignment
    if border:
        ns.border = border
    ns.number_format = number_format
    return ns


def registrar_estilos(wb) -> None:
    """
    Registra os NamedStyles no workbook.
    Deve ser chamado UMA VEZ após criar o workbook,
    antes de qualquer escrita de células.

    Os estilos registrados permitem atribuição por nome:
        ws.cell(...).style = "header_azul"
    """
    estilos = [
        _make_named_style(
            "header_azul",
            font=FONT_WHITE_BOLD,
            fill=FILL_AZUL,
            alignment=ALIGN_CENTER,
            border=BORDER_THIN,
        ),
        _make_named_style(
            "header_amarelo",
            font=FONT_BLACK_BOLD,
            fill=FILL_AMARELO,
            alignment=ALIGN_CENTER,
            border=BORDER_THIN,
        ),
        _make_named_style(
            "header_cinza",
            font=FONT_BLACK_BOLD,
            fill=FILL_CINZA,
            alignment=ALIGN_CENTER,
            border=BORDER_THIN,
        ),
        _make_named_style(
            "dado_padrao",
            font=FONT_NORMAL,
            fill=FILL_BRANCO,
            alignment=ALIGN_VCENTER,
            border=BORDER_THIN,
        ),
        _make_named_style(
            "dado_data",
            font=FONT_NORMAL,
            fill=FILL_BRANCO,
            alignment=ALIGN_CENTER,
            border=BORDER_THIN,
            number_format="DD/MM/YYYY",
        ),
        _make_named_style(
            "dado_valor",
            font=FONT_NORMAL,
            fill=FILL_BRANCO,
            alignment=ALIGN_RIGHT,
            border=BORDER_THIN,
            number_format="#,##0.00",
        ),
        _make_named_style(
            "total_linha",
            font=FONT_BLACK_BOLD,
            fill=FILL_LARANJA,
            alignment=ALIGN_RIGHT,
            border=BORDER_THIN,
            number_format="#,##0.00",
        ),
        _make_named_style(
            "dado_azul_claro",
            font=FONT_NORMAL,
            fill=FILL_AZUL_CLARO,
            alignment=ALIGN_VCENTER,
            border=BORDER_THIN,
        ),
    ]
    for estilo in estilos:
        try:
            wb.add_named_style(estilo)
        except ValueError:
            pass  # Já registrado (ex: múltiplos arquivos na sessão)
