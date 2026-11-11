"""
Exportação profissional do resultado para Excel.

Gera 3 abas:
  1. Pontos de Atenção  — divergências + inconsistências
  2. Conciliados        — registros que bateram perfeitamente
  3. Resumo por Dia     — totais e status por data
"""

from datetime import datetime
from pathlib import Path

from core.logger import log
from .reconciler import ResultadoConciliacao, Divergencia, Inconsistencia


def exportar_relatorio(resultado: ResultadoConciliacao, filepath: str) -> None:
    """Gera XLSX com 3 abas."""
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()

    _construir_aba_atencao(wb, resultado)
    _construir_aba_conciliados(wb, resultado)
    _construir_aba_resumo_dia(wb, resultado)

    # Remove a aba "Sheet" default
    if "Sheet" in wb.sheetnames:
        del wb["Sheet"]

    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    wb.save(filepath)
    log.info(
        f"Exportado: {filepath} ({resultado.qtd_atencao} atenções, "
        f"{resultado.qtd_conciliados} conciliados)"
    )


# ─── Estilos compartilhados ──────────────────────────────────────
def _estilos():
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    return {
        "fill_title":  PatternFill("solid", fgColor="1768AE"),
        "fill_header": PatternFill("solid", fgColor="073B63"),
        "fill_warn":   PatternFill("solid", fgColor="FFF8E1"),
        "fill_err":    PatternFill("solid", fgColor="FEF2F2"),
        "fill_ok":     PatternFill("solid", fgColor="F0FDF4"),
        "fill_even":   PatternFill("solid", fgColor="FFFFFF"),
        "font_title":  Font(color="FFFFFF", bold=True, name="Segoe UI", size=14),
        "font_header": Font(color="FFFFFF", bold=True, name="Segoe UI", size=11),
        "font_body":   Font(color="0F172A", name="Segoe UI", size=10),
        "font_warn":   Font(color="C2410C", bold=True, name="Segoe UI", size=10),
        "font_err":    Font(color="B91C1C", bold=True, name="Segoe UI", size=10),
        "font_ok":     Font(color="16A34A", bold=True, name="Segoe UI", size=10),
        "border":      Border(*[Side(style="thin", color="B8D4F3")]*4),
        "center":      Alignment(horizontal="center", vertical="center"),
        "left":        Alignment(horizontal="left", vertical="center", wrap_text=True),
        "right":       Alignment(horizontal="right", vertical="center"),
    }


# ═════════════════════════════════════════════════════════════════
# Aba 1: Pontos de Atenção
# ═════════════════════════════════════════════════════════════════
def _construir_aba_atencao(wb, r: ResultadoConciliacao):
    from openpyxl.utils import get_column_letter
    from openpyxl.styles import Font
    s = _estilos()

    ws = wb.create_sheet("Pontos de Atenção", 0)

    # Título
    ws.merge_cells("A1:H1")
    c = ws.cell(1, 1, "RELATÓRIO DE CONCILIAÇÃO — PONTOS DE ATENÇÃO")
    c.fill = s["fill_title"]; c.font = s["font_title"]; c.alignment = s["center"]
    ws.row_dimensions[1].height = 32

    # Metadados
    ws.cell(2, 1, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}").font = \
        Font(italic=True, color="475569", name="Segoe UI", size=10)

    # Resumo
    ws.cell(4, 1, "Total Banco:").font   = s["font_body"]
    ws.cell(4, 2, r.total_banco).number_format = '"R$" #,##0.00'
    ws.cell(4, 3, "Total Sistema:").font = s["font_body"]
    ws.cell(4, 4, r.total_sistema).number_format = '"R$" #,##0.00'
    ws.cell(4, 5, "Divergente:").font    = s["font_body"]
    ws.cell(4, 6, r.total_divergente).number_format = '"R$" #,##0.00'
    ws.cell(4, 6).font = s["font_warn"]
    ws.cell(4, 7, "Inconsistente:").font = s["font_body"]
    ws.cell(4, 8, r.total_inconsistente).number_format = '"R$" #,##0.00'
    ws.cell(4, 8).font = s["font_err"]

    for col in range(1, 9):
        cell = ws.cell(4, col)
        cell.alignment = s["left"]
        if cell.font.color is None:
            cell.font = Font(bold=True, color="073B63", name="Segoe UI", size=10)

    # Cabeçalho
    headers = ["STATUS", "DATA", "FORNECEDOR", "REMESSA", "TÍTULO",
               "VALOR (R$)", "SUGESTÃO NO BANCO", "MOTIVO"]
    header_row = 6
    for col, h in enumerate(headers, 1):
        cell = ws.cell(header_row, col, h)
        cell.fill = s["fill_header"]; cell.font = s["font_header"]
        cell.alignment = s["center"]; cell.border = s["border"]
    ws.row_dimensions[header_row].height = 26

    row_i = header_row + 1

    # Divergências (amarelas)
    for div in r.divergencias:
        rec = div.record
        sug_text = (
            f"{div.sugestao.fornecedor}\n"
            f"{div.sugestao.data} · R$ {div.sugestao.valor:,.2f}"
        ).replace(",", "X").replace(".", ",").replace("X", ".")

        motivo_text = _formatar_motivo_divergencia(div)
        _escrever_linha(
            ws, row_i,
            ["⚠ REVER", rec.data, rec.fornecedor, rec.remessa, rec.titulo,
             rec.valor, sug_text, motivo_text],
            fill=s["fill_warn"], font_status=s["font_warn"],
            border=s["border"], styles=s,
        )
        row_i += 1

    # Inconsistências (vermelhas)
    for inc in r.inconsistencias:
        rec = inc.record
        _escrever_linha(
            ws, row_i,
            ["✕ ERRO", rec.data, rec.fornecedor, rec.remessa, rec.titulo,
             rec.valor, "Nenhum candidato encontrado", "Não encontrado no banco"],
            fill=s["fill_err"], font_status=s["font_err"],
            border=s["border"], styles=s,
        )
        row_i += 1

    # Larguras
    widths = [12, 13, 36, 12, 14, 14, 38, 30]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # Freeze + filtro
    ws.freeze_panes = f"A{header_row + 1}"
    if r.qtd_atencao > 0:
        ws.auto_filter.ref = f"A{header_row}:H{header_row + r.qtd_atencao}"


def _escrever_linha(ws, row, values, fill, font_status, border, styles):
    """Helper para escrever uma linha da aba de atenção."""
    for col, val in enumerate(values, 1):
        cell = ws.cell(row, col, val)
        cell.fill = fill
        cell.border = border
        if col == 1:
            cell.font = font_status
            cell.alignment = styles["center"]
        elif col == 6:
            cell.font = styles["font_body"]
            cell.alignment = styles["right"]
            cell.number_format = '"R$" #,##0.00'
        else:
            cell.font = styles["font_body"]
            cell.alignment = styles["left"]
    ws.row_dimensions[row].height = 32


def _formatar_motivo_divergencia(div: Divergencia) -> str:
    """Gera texto descritivo do motivo da divergência."""
    parts = [div.motivo.value]

    if abs(div.diff_valor) > 0.005:
        sinal = "+" if div.diff_valor > 0 else "-"
        parts.append(
            f"Δvalor: {sinal}R$ {abs(div.diff_valor):,.2f}"
            .replace(",", "X").replace(".", ",").replace("X", ".")
        )
    if div.diff_dias_uteis > 0:
        plural = "s" if div.diff_dias_uteis > 1 else ""
        parts.append(f"+{div.diff_dias_uteis} dia útil{plural}")
    if div.similaridade < 1.0 and div.similaridade > 0:
        parts.append(f"Similaridade nome: {int(div.similaridade * 100)}%")

    return " · ".join(parts)


# ═════════════════════════════════════════════════════════════════
# Aba 2: Conciliados
# ═════════════════════════════════════════════════════════════════
def _construir_aba_conciliados(wb, r: ResultadoConciliacao):
    from openpyxl.utils import get_column_letter
    s = _estilos()

    ws = wb.create_sheet("Conciliados", 1)

    ws.merge_cells("A1:E1")
    c = ws.cell(1, 1, f"CONCILIADOS — {r.qtd_conciliados} REGISTROS")
    c.fill = s["fill_title"]; c.font = s["font_title"]; c.alignment = s["center"]
    ws.row_dimensions[1].height = 32

    headers = ["DATA", "FORNECEDOR", "REMESSA", "TÍTULO", "VALOR (R$)"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(3, col, h)
        cell.fill = s["fill_header"]; cell.font = s["font_header"]
        cell.alignment = s["center"]; cell.border = s["border"]
    ws.row_dimensions[3].height = 26

    for idx, rec in enumerate(r.conciliados, 4):
        ws.cell(idx, 1, rec.data).alignment = s["center"]
        ws.cell(idx, 2, rec.fornecedor).alignment = s["left"]
        ws.cell(idx, 3, rec.remessa).alignment = s["left"]
        ws.cell(idx, 4, rec.titulo).alignment = s["left"]
        vc = ws.cell(idx, 5, rec.valor)
        vc.alignment = s["right"]
        vc.number_format = '"R$" #,##0.00'
        vc.font = s["font_ok"]

        fill = s["fill_ok"] if idx % 2 == 0 else s["fill_even"]
        for col in range(1, 6):
            cell = ws.cell(idx, col)
            cell.fill = fill
            cell.border = s["border"]
            if cell.font.color is None:
                cell.font = s["font_body"]
        ws.row_dimensions[idx].height = 20

    for col, w in enumerate([13, 38, 13, 16, 15], 1):
        ws.column_dimensions[get_column_letter(col)].width = w

    ws.freeze_panes = "A4"
    if r.qtd_conciliados > 0:
        ws.auto_filter.ref = f"A3:E{3 + r.qtd_conciliados}"


# ═════════════════════════════════════════════════════════════════
# Aba 3: Resumo por Dia
# ═════════════════════════════════════════════════════════════════
def _construir_aba_resumo_dia(wb, r: ResultadoConciliacao):
    from openpyxl.utils import get_column_letter
    s = _estilos()

    ws = wb.create_sheet("Resumo por Dia", 2)

    ws.merge_cells("A1:G1")
    c = ws.cell(1, 1, "RESUMO POR DIA")
    c.fill = s["fill_title"]; c.font = s["font_title"]; c.alignment = s["center"]
    ws.row_dimensions[1].height = 32

    headers = ["DATA", "DIA DA SEMANA", "STATUS", "TOTAL",
               "CONCILIADOS", "DIVERGÊNCIAS", "INCONSISTÊNCIAS"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(3, col, h)
        cell.fill = s["fill_header"]; cell.font = s["font_header"]
        cell.alignment = s["center"]; cell.border = s["border"]
    ws.row_dimensions[3].height = 26

    for idx, (date_str, st) in enumerate(r.status_por_dia.items(), 4):
        if st.status_cor == "err":
            fill = s["fill_err"]
            status_text = "❌ COM INCONSISTÊNCIAS"
            font_status = s["font_err"]
        elif st.status_cor == "warn":
            fill = s["fill_warn"]
            status_text = "⚠ COM DIVERGÊNCIAS"
            font_status = s["font_warn"]
        else:
            fill = s["fill_ok"]
            status_text = "✓ TUDO OK"
            font_status = s["font_ok"]

        ws.cell(idx, 1, st.data).alignment = s["center"]
        ws.cell(idx, 2, st.dia_semana).alignment = s["left"]
        sc = ws.cell(idx, 3, status_text)
        sc.alignment = s["center"]
        sc.font = font_status
        ws.cell(idx, 4, st.qtd_total).alignment = s["center"]
        ws.cell(idx, 5, st.qtd_conciliados).alignment = s["center"]
        ws.cell(idx, 6, st.qtd_divergencias).alignment = s["center"]
        ws.cell(idx, 7, st.qtd_inconsistencias).alignment = s["center"]

        for col in range(1, 8):
            cell = ws.cell(idx, col)
            cell.fill = fill
            cell.border = s["border"]
            if col != 3 and cell.font.color is None:
                cell.font = s["font_body"]
        ws.row_dimensions[idx].height = 22

    for col, w in enumerate([13, 22, 24, 10, 14, 16, 18], 1):
        ws.column_dimensions[get_column_letter(col)].width = w

    ws.freeze_panes = "A4"
