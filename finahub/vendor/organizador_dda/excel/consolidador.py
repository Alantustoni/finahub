"""
consolidador.py
Lê as abas ALFAMETAL e BETAVIARIA de um arquivo Excel já revisado
e injeta a aba ALFAMETAL - BTV nesse mesmo arquivo.

Layout das abas de entrada (geradas pelo sistema):
  Colunas E:J — EMPRESA | CNPJ | FORNECEDOR | PRV NF | VENC | VALOR
  Dados começam na coluna 5 (E), terminam na 10 (J)
  Sem STATUS nas abas de entrada

Layout da aba ALFAMETAL - BTV gerada (modelo aprovado em 30/10/2026,
igual ao exemplo Pasta1.xlsx do usuário):
  Colunas D:I — EMPRESA | CNPJ | FORNECEDOR | PRV NF | VENC | VALOR
  Para cada dia: título do dia (uma vez), bloco ALFAMETAL e depois bloco
  BETAVIARIA (cabeçalho preto, letra branca), cada um com TOTAL.
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import timedelta
from pathlib import Path

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

from .excel_styles import (
    ALIGN_CENTER, ALIGN_RIGHT, ALIGN_VCENTER,
    BORDER_THIN,
    FILL_LARANJA,
    FONT_BLACK_BOLD, FONT_RED_BOLD_24, FONT_WHITE_BOLD,
)

logger = logging.getLogger(__name__)

_DIAS_SEMANA = {0: "SEGUNDA", 1: "TERÇA", 2: "QUARTA", 3: "QUINTA", 4: "SEXTA"}

# Layout de SAÍDA (aba ALFAMETAL - BTV) — colunas D:I, com CNPJ
_OUT_EMPRESA    = 4   # D
_OUT_CNPJ       = 5   # E
_OUT_FORNECEDOR = 6   # F
_OUT_PRV_NF     = 7   # G
_OUT_VENC       = 8   # H
_OUT_VALOR      = 9   # I
_OUT_FIM        = 9

_LARGURAS = {"D": 21, "E": 19, "F": 32, "G": 13, "H": 11, "I": 13}
_FILL_PRETO = PatternFill("solid", fgColor="000000")
_HEADERS  = ["EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF", "VENC", "VALOR"]

# Palavras que indicam linha não-dados nas abas de entrada
_IGNORAR = {"EMPRESA", "TOTAL", "TOTAL:", ""}


def _empresa_destaque(empresa) -> bool:
    """
    True quando a filial é MG/Minas ou PE — a linha recebe NEGRITO no
    consolidado, igual ao relatório principal (mesma regra do report_generator).
    """
    emp = str(empresa or "").upper()
    tokens = emp.replace("-", " ").replace("/", " ").split()
    return ("MG" in tokens) or ("PE" in tokens) or ("MINAS" in emp)


def _parse_valor(v) -> float | None:
    """Converte string ou número para float de forma segura."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    texto = str(v).strip().replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except Exception:
        # Tenta sem remover pontos (formato US: 1234.56)
        try:
            return float(str(v).strip())
        except Exception:
            return None


def _parse_data(v) -> pd.Timestamp | None:
    """Converte qualquer formato de data para Timestamp."""
    if v is None:
        return None
    if isinstance(v, pd.Timestamp):
        return v
    try:
        ts = pd.Timestamp(v)
        # Sanity check: data razoável
        if ts.year < 2020 or ts.year > 2035:
            return None
        return ts
    except Exception:
        return None


def _ler_aba_revisada(ws) -> pd.DataFrame:
    """
    Lê aba ALFAMETAL ou BETAVIARIA do relatório gerado pelo sistema.
    Layout: dados nas colunas E(5) a J(10)
    Ordem:  EMPRESA | CNPJ | FORNECEDOR | PRV NF | VENC | VALOR
    """
    linhas = []

    for row in ws.iter_rows(min_col=5, max_col=10, values_only=True):
        if len(row) < 6:
            continue

        empresa    = row[0]  # col E — EMPRESA
        cnpj       = row[1]  # col F — CNPJ
        fornecedor = row[2]  # col G — FORNECEDOR
        prv_nf     = row[3]  # col H — PRV NF
        venc       = row[4]  # col I — VENC
        valor      = row[5]  # col J — VALOR

        # Ignorar linhas sem empresa ou com empresa sendo cabeçalho/total
        if empresa is None:
            continue
        empresa_str = str(empresa).strip().upper()
        if empresa_str in _IGNORAR:
            continue
        # Ignorar títulos de dia (SEGUNDA - 08/06, etc.)
        if any(d in empresa_str for d in _DIAS_SEMANA.values()):
            continue
        # Ignorar linha de TOTAL (quando empresa é None mas venc="TOTAL")
        if venc is not None and str(venc).strip().upper() == "TOTAL":
            continue

        # Converter data — VENC está na coluna I (índice 4)
        venc_ts = _parse_data(venc)
        if venc_ts is None:
            continue

        # Converter valor — VALOR está na coluna J (índice 5)
        valor_f = _parse_valor(valor)

        linhas.append({
            "EMPRESA":    empresa_str,
            "CNPJ":       str(cnpj).strip() if cnpj else "",
            "FORNECEDOR": str(fornecedor).strip() if fornecedor else "",
            "PRV NF":     str(prv_nf).strip()     if prv_nf     else "",
            "VENC":       venc_ts,
            "VALOR":      valor_f,
        })

    return pd.DataFrame(linhas) if linhas else pd.DataFrame(
        columns=["EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF", "VENC", "VALOR"]
    )


def _estilizar_bloco(ws, linha_inicio: int, linha_fim: int) -> None:
    for row in ws.iter_rows(
        min_row=linha_inicio, max_row=linha_fim,
        min_col=_OUT_EMPRESA, max_col=_OUT_FIM,
    ):
        for cell in row:
            cell.border    = BORDER_THIN
            cell.alignment = ALIGN_VCENTER
        # VENC = índice 4 no tuple (D=0,E=1,F=2,G=3,H=4,I=5)
        if len(row) > 4 and row[4].value is not None:
            row[4].number_format = "DD/MM/YYYY"
            row[4].alignment     = ALIGN_CENTER
        # VALOR = índice 5
        if len(row) > 5 and row[5].value is not None:
            row[5].number_format = "#,##0.00"
            row[5].alignment     = ALIGN_RIGHT


def _gerar_aba_tng(ws, df: pd.DataFrame) -> None:
    """Escreve aba ALFAMETAL - BTV conforme layout aprovado."""
    ws.sheet_view.showGridLines = True

    if df.empty or df["VENC"].dropna().empty:
        ws.cell(row=1, column=_OUT_EMPRESA, value="SEM REGISTROS")
        return

    for col_letra, w in _LARGURAS.items():
        ws.column_dimensions[col_letra].width = w

    alfametal_empresas  = ["ALFAMETAL MATRIZ", "ALFAMETAL MG"]
    betaviaria_empresas = ["BETAVIARIA MATRIZ", "BETAVIARIA PE"]

    # CORRECAO: todos os dias com notas (todas as semanas), nao so a 1a.
    # Antes, notas com vencimento fora da 1a semana sumiam do consolidado.
    datas_semana = [
        pd.Timestamp(d)
        for d in sorted(df["VENC"].dropna().dt.normalize().unique())
    ]

    linha = 1

    for data in datas_semana:
        nome_dia = _DIAS_SEMANA.get(data.weekday(), "")
        titulo   = f"{nome_dia} - {data.strftime('%d/%m')}"

        mask_data = df["VENC"].dt.date == data.date()
        titulo_feito = False

        dados_alfametal  = df[df["EMPRESA"].isin(alfametal_empresas)  & mask_data] \
            .sort_values(["VALOR", "FORNECEDOR"], ascending=[True, True], na_position="last")
        dados_betaviaria = df[df["EMPRESA"].isin(betaviaria_empresas) & mask_data] \
            .sort_values(["VALOR", "FORNECEDOR"], ascending=[True, True], na_position="last")

        # [ALAN 30/10/2026] cabeçalho preto com letra branca nos dois blocos
        for grupo_df, fill_h, font_h in [
            (dados_alfametal,  _FILL_PRETO, FONT_WHITE_BOLD),
            (dados_betaviaria, _FILL_PRETO, FONT_WHITE_BOLD),
        ]:
            if grupo_df.empty:
                continue

            # Título do dia — só uma vez, antes do primeiro bloco do dia
            if not titulo_feito:
                ws.merge_cells(
                    start_row=linha, start_column=_OUT_EMPRESA,
                    end_row=linha,   end_column=_OUT_FIM,
                )
                cel           = ws.cell(row=linha, column=_OUT_EMPRESA, value=titulo)
                cel.font      = FONT_RED_BOLD_24
                cel.alignment = ALIGN_CENTER
                ws.row_dimensions[linha].height = 32.25
                linha += 1
                titulo_feito = True

            # Cabeçalho
            for col_idx, header in enumerate(_HEADERS, start=_OUT_EMPRESA):
                c           = ws.cell(row=linha, column=col_idx, value=header)
                c.fill      = fill_h
                c.font      = font_h
                c.alignment = ALIGN_CENTER
                c.border    = BORDER_THIN
            linha += 1

            # Dados
            inicio_dados = linha
            for _, r in grupo_df.iterrows():
                venc_val  = r["VENC"].date() if pd.notna(r["VENC"]) else None
                valor_val = float(r["VALOR"]) if pd.notna(r.get("VALOR")) else None

                cells = [
                    ws.cell(row=linha, column=_OUT_EMPRESA,    value=r["EMPRESA"]),
                    ws.cell(row=linha, column=_OUT_CNPJ,       value=r.get("CNPJ", "")),
                    ws.cell(row=linha, column=_OUT_FORNECEDOR, value=r["FORNECEDOR"]),
                    ws.cell(row=linha, column=_OUT_PRV_NF,     value=r["PRV NF"]),
                    ws.cell(row=linha, column=_OUT_VENC,       value=venc_val),
                    ws.cell(row=linha, column=_OUT_VALOR,      value=valor_val),
                ]
                # Negrito para a filial MG/PE — mesmo destaque do relatório
                if _empresa_destaque(r["EMPRESA"]):
                    for c in cells:
                        c.font = Font(bold=True)
                linha += 1

            if linha > inicio_dados:
                _estilizar_bloco(ws, inicio_dados, linha - 1)

            # TOTAL do bloco — fórmula, recalcula se apagar linha na revisão
            c_rot = ws.cell(row=linha, column=_OUT_VENC, value="TOTAL")
            c_tot = ws.cell(row=linha, column=_OUT_VALOR,
                            value=f"=SUM(I{inicio_dados}:I{linha - 1})")
            for c in (c_rot, c_tot):
                c.font      = FONT_BLACK_BOLD
                c.fill      = FILL_LARANJA
                c.border    = BORDER_THIN
                c.alignment = ALIGN_RIGHT
            c_tot.number_format = "#,##0.00"
            linha += 2  # TOTAL + 1 linha em branco antes do próximo bloco


def consolidar_arquivo(caminho_revisado: Path,
                       caminho_saida: Path | None = None) -> Path:
    """
    Lê ALFAMETAL e BETAVIARIA do arquivo revisado, gera a aba
    ALFAMETAL - BTV e grava num arquivo NOVO (por padrão
    '<nome>_consolidado.xlsx' na mesma pasta).

    Gravar num arquivo novo evita o erro "Acesso negado" do Windows quando
    o arquivo revisado está aberto no Excel — que é o caso comum, já que o
    usuário costuma revisar aberto e então consolidar. Devolve o caminho
    do arquivo gerado.
    """
    caminho_revisado = Path(caminho_revisado)
    if caminho_saida is None:
        caminho_saida = caminho_revisado.with_name(
            caminho_revisado.stem + "_consolidado.xlsx")
    caminho_saida = Path(caminho_saida)
    logger.info("Lendo: %s", caminho_revisado.name)
    wb   = load_workbook(caminho_revisado)
    abas = wb.sheetnames

    aba_f = next((a for a in abas if "ALFAMETAL" in a.upper() and "BTV" not in a.upper()), None)
    aba_t = next((a for a in abas if "BETAVIARIA" in a.upper()), None)

    if not aba_f:
        raise ValueError("Aba ALFAMETAL não encontrada. Verifique se é um arquivo gerado pelo Organizador DDA.")
    if not aba_t:
        raise ValueError("Aba BETAVIARIA não encontrada. Verifique se é um arquivo gerado pelo Organizador DDA.")

    df_f = _ler_aba_revisada(wb[aba_f])
    df_t = _ler_aba_revisada(wb[aba_t])

    logger.info("Alfametal: %d linhas | Betaviaria: %d linhas", len(df_f), len(df_t))

    df_total = pd.concat([df_f, df_t], ignore_index=True)
    if df_total.empty:
        raise ValueError("Nenhum dado encontrado. Verifique se o arquivo foi revisado corretamente.")

    # Remove aba BTV anterior se já existir (re-geração)
    aba_tng = "ALFAMETAL - BTV"
    if aba_tng in wb.sheetnames:
        del wb[aba_tng]

    # Inserir antes de ERROS para manter ordem das abas
    idx = next(
        (i for i, n in enumerate(wb.sheetnames) if "ERRO" in n.upper()),
        len(wb.sheetnames),
    )
    ws_tng = wb.create_sheet(aba_tng, index=idx)

    _gerar_aba_tng(ws_tng, df_total)

    # Escrita atômica no arquivo NOVO — não toca no revisado (que pode estar
    # aberto no Excel). O .tmp fica na pasta do destino para o os.replace ser
    # atômico (mesmo volume).
    tmp_fd, tmp_path = tempfile.mkstemp(dir=caminho_saida.parent, suffix=".tmp.xlsx")
    os.close(tmp_fd)
    try:
        wb.save(tmp_path)
        os.replace(tmp_path, caminho_saida)
        logger.info("Salvo: %s", caminho_saida.name)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return caminho_saida
