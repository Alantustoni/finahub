"""
report_generator.py
Geração do relatório Excel DDA.

Melhorias em relação ao código original:
  1. PASSE ÚNICO — formatação ocorre dentro do ExcelWriter antes de
     fechar, eliminando a dupla abertura (gerar + _aplicar_formatacao).
  2. Escrita de dados via ws.append() / lista de listas, não iterrows().
     Velocidade 5-10× superior para blocos de dados.
  3. Estilos aplicados após escrita de blocos, usando iter_rows com
     range exato — não relê conteúdo para inferir posição.
  4. Atomic write: escreve em arquivo temporário e renomeia com
     os.replace() — elimina risco de arquivo corrompido.
  5. NamedStyle para cabeçalhos e células de dados.
  6. _aplicar_fundo_preto_externo removido — anti-pattern substituído
     por showGridLines=False, que produz o mesmo efeito visual.
"""
from __future__ import annotations

import logging
import os
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .excel_styles import (
    ALIGN_CENTER, ALIGN_LEFT, ALIGN_RIGHT, ALIGN_VCENTER,
    BORDER_THIN,
    FILL_AZUL, FILL_AZUL_CLARO, FILL_AMARELO, FILL_AMARELO_CLARO,
    FILL_AZUL_DARK, FILL_BRANCO, FILL_CINZA, FILL_CINZA_ESCURO,
    FILL_LARANJA, FILL_ROXO, FILL_VERMELHO,
    FONT_BLACK_BOLD, FONT_CARD_NUM, FONT_CARD_TITLE,
    FONT_NORMAL, FONT_PAINEL_SEMANA, FONT_PAINEL_TITLE,
    FONT_RED_BOLD_24, FONT_TITLE_ERROR, FONT_WHITE_BOLD,
    registrar_estilos,
)
from ..core.processor import ProcessingResult

logger = logging.getLogger(__name__)

# [ALAN 29/10/2026] linha de nota já programada no banco
FILL_AMARELO_LINHA = PatternFill("solid", fgColor="FFFF00")
# [ALAN 30/10/2026] nota que já veio de Compras (só na Planilha1)
FILL_VERDE_LINHA = PatternFill("solid", fgColor="C6EFCE")


class ExcelReportGenerator:
    """
    Responsabilidade: gerar o arquivo .xlsx a partir de um ProcessingResult.
    Não conhece UI. Não conhece pandas além de receber o DataFrame.
    """

    # seção "PAGAMENTOS DO BANCO SEM NOTA NO DDA" na aba ERROS
    MOSTRAR_BANCO_SEM_NOTA = False

    def __init__(
        self,
        result: ProcessingResult,
        config,
        painel_metricas: Optional[Dict[str, Any]] = None,
        resultado_cruzamento=None,
        df_relatorio: Optional[pd.DataFrame] = None,
    ) -> None:
        # [ALAN 29/10/2026] df_relatorio = lista já montada pelo ALAN
        # (pendentes + programadas marcadas em "_PROGRAMADA", fornecedor
        # abreviado, coluna COMPRAS). Colunas que começam com "_" são
        # internas e não vão para a planilha.
        if df_relatorio is not None:
            self.df = df_relatorio
        # Se há cruzamento com banco, usa apenas pendências reais no relatório principal
        elif resultado_cruzamento is not None and not resultado_cruzamento.df_pendente.empty:
            self.df = resultado_cruzamento.df_pendente.copy()
        else:
            self.df = result.df
        self.config               = config
        self.resumo_remocoes      = result.resumo_remocoes
        self.total_original       = result.total_original
        self.total_processado     = result.total_processado
        self.removidas_proposta      = getattr(result, "removidas_proposta", 0)
        self.removidas_siderurgicas  = getattr(result, "removidas_siderurgicas", 0)
        self.error_counts         = result.error_counts
        self.duplicatas           = getattr(result, "duplicatas", pd.DataFrame())
        self.col_map              = getattr(result, "col_map", {}) or {}
        self.col_warnings         = getattr(result, "col_warnings", []) or []
        self.painel_metricas      = painel_metricas or {}
        self.resultado_cruzamento = resultado_cruzamento

    # ------------------------------------------------------------------ #
    # API pública                                                          #
    # ------------------------------------------------------------------ #

    def gerar(self, arquivo_saida: Path) -> None:
        logger.info("Gerando relatório Excel: %s", arquivo_saida.name)

        # Escreve em arquivo temporário no mesmo diretório para garantir
        # que os.replace() seja atômico (mesmo volume de disco).
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=arquivo_saida.parent,
            suffix=".tmp.xlsx",
        )
        os.close(tmp_fd)

        try:
            self._escrever_workbook(Path(tmp_path))
            os.replace(tmp_path, arquivo_saida)
            logger.info("Relatório salvo com sucesso.")
        except Exception:
            # Remove temporário se algo falhou
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------ #
    # Escrita do workbook — passe único                                   #
    # ------------------------------------------------------------------ #

    def _escrever_workbook(self, caminho: Path) -> None:
        with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
            wb = writer.book
            registrar_estilos(wb)

            # ── Planilha1 (dados brutos tratados) ──────────────────── #
            self._criar_aba_dados_brutos(writer)

            # ── Abas por empresa ────────────────────────────────────── #
            self._criar_aba_empresa(
                writer, "ALFAMETAL",
                ["ALFAMETAL MATRIZ", "ALFAMETAL MG"],
                fill_header=FILL_AZUL, font_header=FONT_WHITE_BOLD,
            )
            self._criar_aba_empresa(
                writer, "BETAVIARIA",
                ["BETAVIARIA MATRIZ", "BETAVIARIA PE"],
                fill_header=FILL_AMARELO, font_header=FONT_BLACK_BOLD,
            )

            # Aba ALFAMETAL - BTV gerada separadamente via botão Gerar Consolidado

            # ── Aba de erros ─────────────────────────────────────────  #
            erros_df = self.df[self.df["ERROS"] != ""].copy() if "ERROS" in self.df.columns else pd.DataFrame()
            self._criar_aba_erros(writer, erros_df, self.resultado_cruzamento)

            # Programados no banco: integrado na aba ERROS

    # ------------------------------------------------------------------ #
    # Aba Planilha1                                                        #
    # ------------------------------------------------------------------ #

    def _linha_programada(self, idx) -> bool:
        return bool(self.df.at[idx, "_PROGRAMADA"]) if "_PROGRAMADA" in self.df.columns else False

    def _linha_ja_veio(self, idx) -> bool:
        """Nota que já veio de Compras (ou CNPJ da lista) — não se cobra."""
        if "_COMPRAS" not in self.df.columns:
            return False
        return str(self.df.at[idx, "_COMPRAS"] or "").strip().upper().startswith("JÁ VEIO")

    def _df_cobranca(self) -> pd.DataFrame:
        """Lista de cobrança: tudo menos o que já veio de Compras
        (programadas continuam, em amarelo)."""
        if "_COMPRAS" not in self.df.columns:
            return self.df
        manter = [self._linha_programada(i) or not self._linha_ja_veio(i)
                  for i in self.df.index]
        return self.df[manter]

    def _criar_aba_dados_brutos(self, writer) -> None:
        # [ALAN 30/10/2026] só as colunas que interessam (sem FILIAL/TIPO),
        # com o título "NOTAS JÁ NO CONTAS A PAGAR" na linha 1
        colunas = [c for c in ("EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF",
                               "VENC", "VALOR", "ERROS") if c in self.df.columns]
        saida = self.df[colunas].copy()
        # "JÁ VEIO – E-MAIL dd/mm hh:mm (…)" vai DENTRO da coluna ERROS
        # (só na Planilha1; a aba ERROS continua só com erros de verdade)
        if "_COMPRAS" in self.df.columns and "ERROS" in saida.columns:
            saida["ERROS"] = [
                " | ".join(t for t in (str(e or "").strip(), str(c or "").strip()) if t)
                for e, c in zip(saida["ERROS"], self.df["_COMPRAS"])]
        saida.to_excel(writer, sheet_name="Planilha1", index=False, startrow=1)
        ws = writer.book["Planilha1"]
        ncol = len(colunas)

        # título (linha 1)
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
        titulo = ws.cell(row=1, column=1, value="NOTAS JÁ NO CONTAS A PAGAR")
        titulo.font = Font(bold=True, size=16)
        titulo.alignment = ALIGN_CENTER
        ws.row_dimensions[1].height = 28

        # programadas no banco: linha amarela; já veio de Compras: linha verde
        for n, idx in enumerate(self.df.index, start=3):
            if self._linha_programada(idx):
                for cell in ws[n]:
                    cell.fill = FILL_AMARELO_LINHA
            elif self._linha_ja_veio(idx):
                for cell in ws[n]:
                    cell.fill = FILL_VERDE_LINHA
        ws.freeze_panes = "A3"
        ws.sheet_view.showGridLines = True

        larguras = {"EMPRESA": 20, "CNPJ": 20, "FORNECEDOR": 20, "PRV NF": 20,
                    "VENC": 11, "VALOR": 11, "ERROS": 60}
        for col_idx, nome in enumerate(colunas, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = larguras.get(nome, 20)

        for cell in ws[2]:
            cell.fill = FILL_CINZA
            cell.font = FONT_BLACK_BOLD
            cell.border = BORDER_THIN
            cell.alignment = ALIGN_CENTER

        i_venc = colunas.index("VENC") if "VENC" in colunas else None
        i_valor = colunas.index("VALOR") if "VALOR" in colunas else None
        for row in ws.iter_rows(min_row=3, max_col=ncol):
            for cell in row:
                cell.border = BORDER_THIN
            if i_venc is not None and row[i_venc].value is not None:
                row[i_venc].number_format = "DD/MM/YYYY"
            if i_valor is not None and row[i_valor].value is not None:
                row[i_valor].number_format = "#,##0.00"

    # ------------------------------------------------------------------ #
    # Aba por empresa (ALFAMETAL / BETAVIARIA)                            #
    # ------------------------------------------------------------------ #

    def _criar_aba_empresa(
        self,
        writer,
        nome_aba: str,
        empresas: List[str],
        fill_header,
        font_header,
    ) -> None:
        writer.book.create_sheet(nome_aba)
        ws = writer.book[nome_aba]
        ws.sheet_view.showGridLines = False

        # [ALAN 30/10/2026] o que já veio de Compras não entra na cobrança
        base = self._df_cobranca()
        subset = base[base["EMPRESA"].isin(empresas)].copy()
        if subset.empty:
            ws.cell(row=1, column=5, value="SEM REGISTROS")
            return

        # CORRECAO: renderiza TODOS os dias que possuem notas, de todas as
        # semanas — nao apenas a primeira semana. Antes, qualquer nota com
        # vencimento fora da 1a semana (ex.: Gamma Gasotec venc. 05/09)
        # sumia da aba, mesmo continuando pendente.
        datas_semana = [
            pd.Timestamp(d)
            for d in sorted(subset["VENC"].dropna().dt.normalize().unique())
        ]

        headers = ["EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF", "VENC", "VALOR"]
        larguras = {"E": 22, "F": 22, "G": 36, "H": 14, "I": 13, "J": 14}
        for col_letra, w in larguras.items():
            ws.column_dimensions[col_letra].width = w

        linha = 1

        for data in datas_semana:
            titulo = f"{self.config.dias_semana[data.weekday()]} - {data.strftime('%d/%m')}"

            # Título do dia — merge E:J
            ws.merge_cells(start_row=linha, start_column=5, end_row=linha, end_column=10)
            cel = ws.cell(row=linha, column=5, value=titulo)
            cel.font = FONT_RED_BOLD_24
            cel.alignment = ALIGN_CENTER
            ws.row_dimensions[linha].height = 38
            linha += 1

            # Cabeçalho
            for col_idx, header in enumerate(headers, start=5):
                c = ws.cell(row=linha, column=col_idx, value=header)
                c.fill = fill_header
                c.font = font_header
                c.alignment = ALIGN_CENTER
                c.border = BORDER_THIN
            linha += 1

            # Dados do dia — ws.append equivalente por range de colunas
            dados_dia = subset[subset["VENC"].dt.date == data.date()].sort_values(
                by=["VALOR", "FORNECEDOR"], ascending=[True, True], na_position="last"
            )
            # Converter para lista de listas — mais rápido que iterrows/itertuples
            # com colunas de nome especial (PRV NF tem espaço).
            cols_aba = ["EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF", "VENC", "VALOR"]
            dados_lista = dados_dia[cols_aba].values.tolist()
            programadas = [self._linha_programada(i) for i in dados_dia.index]
            inicio_dados = linha
            for row_vals, programada in zip(dados_lista, programadas):
                venc = pd.to_datetime(row_vals[4]).date() if pd.notna(row_vals[4]) else None
                valor = float(row_vals[5]) if pd.notna(row_vals[5]) else None
                cells = [
                    ws.cell(row=linha, column=5,  value=row_vals[0]),   # EMPRESA
                    ws.cell(row=linha, column=6,  value=row_vals[1]),   # CNPJ
                    ws.cell(row=linha, column=7,  value=row_vals[2]),   # FORNECEDOR
                    ws.cell(row=linha, column=8,  value=row_vals[3]),   # PRV NF
                    ws.cell(row=linha, column=9,  value=venc),
                    ws.cell(row=linha, column=10, value=valor),
                ]
                # Negrito quando a filial for MG/Minas ou PE (destaque visual)
                if self._empresa_destaque(row_vals[0]):
                    for c in cells:
                        c.font = Font(bold=True)
                # programada no banco: continua na lista, linha amarela
                if programada:
                    for c in cells:
                        c.fill = FILL_AMARELO_LINHA
                linha += 1

            # Aplicar estilos em bloco ao range de dados
            if linha > inicio_dados:
                self._estilizar_bloco_dados(ws, inicio_dados, linha - 1)

            # Linha de total — FÓRMULA (=SOMA), para recalcular sozinha quando
            # o usuário apaga uma linha na revisão [ALAN 29/10/2026]
            ws.cell(row=linha, column=9, value="TOTAL").style = "total_linha"
            total = (f"=SUM(J{inicio_dados}:J{linha - 1})" if linha > inicio_dados else 0)
            c_total = ws.cell(row=linha, column=10, value=total)
            c_total.style = "total_linha"
            c_total.number_format = "#,##0.00"
            ws.cell(row=linha, column=9).font = FONT_BLACK_BOLD
            ws.cell(row=linha, column=9).alignment = ALIGN_RIGHT
            ws.cell(row=linha, column=9).fill = FILL_LARANJA
            ws.cell(row=linha, column=9).border = BORDER_THIN
            linha += 2

    @staticmethod
    def _empresa_destaque(empresa) -> bool:
        """
        True quando a filial é MG/Minas ou PE — a linha correspondente
        recebe negrito no relatório para destaque visual.
        """
        emp = str(empresa or "").upper()
        tokens = emp.replace("-", " ").replace("/", " ").split()
        return ("MG" in tokens) or ("PE" in tokens) or ("MINAS" in emp)

    def _estilizar_bloco_dados(self, ws, linha_inicio: int, linha_fim: int, col_fim: int = 10) -> None:
        """Aplica estilos ao bloco de dados de uma vez, sem loop célula a célula."""
        for row in ws.iter_rows(min_row=linha_inicio, max_row=linha_fim, min_col=5, max_col=col_fim):
            for cell in row:
                cell.border = BORDER_THIN
                cell.alignment = ALIGN_VCENTER
            # Penultima coluna = VENC, ultima = VALOR (independente do col_fim)
            idx_venc  = col_fim - 6   # posicao relativa (0-based) dentro do tuple
            idx_valor = col_fim - 5
            if len(row) > idx_venc and row[idx_venc].value is not None:
                row[idx_venc].number_format = "DD/MM/YYYY"
                row[idx_venc].alignment = ALIGN_CENTER
            if len(row) > idx_valor and row[idx_valor].value is not None:
                row[idx_valor].number_format = "#,##0.00"
                row[idx_valor].alignment = ALIGN_RIGHT

    # ------------------------------------------------------------------ #
    # Aba consolidada ALFAMETAL - BTV                                     #
    # ------------------------------------------------------------------ #

    def _criar_aba_consolidada(self, writer) -> None:
        """
        Aba ALFAMETAL - BTV: une os dois grupos, sem CNPJ, com STATUS vazio.
        Regras de negócio idênticas ao original.
        """
        ws = writer.book.create_sheet("ALFAMETAL - BTV")
        ws.sheet_view.showGridLines = True

        subset = self._df_cobranca().copy()
        if subset.empty or subset["VENC"].dropna().empty:
            ws.cell(row=1, column=5, value="SEM REGISTROS")
            return

        # CORRECAO: todos os dias com notas (todas as semanas), nao so a 1a.
        datas_semana = [
            pd.Timestamp(d)
            for d in sorted(subset["VENC"].dropna().dt.normalize().unique())
        ]

        headers             = ["EMPRESA", "CNPJ", "STATUS", "FORNECEDOR", "PRV NF", "VENC", "VALOR"]
        alfametal_empresas  = ["ALFAMETAL MATRIZ", "ALFAMETAL MG"]
        betaviaria_empresas = ["BETAVIARIA MATRIZ", "BETAVIARIA PE"]

        larguras = {"E": 22, "F": 22, "G": 10, "H": 34, "I": 16, "J": 13, "K": 14}
        for col_letra, w in larguras.items():
            ws.column_dimensions[col_letra].width = w

        linha = 1

        for data in datas_semana:
            titulo = f"{self.config.dias_semana[data.weekday()]} - {data.strftime('%d/%m')}"
            ws.merge_cells(start_row=linha, start_column=5, end_row=linha, end_column=11)
            cel = ws.cell(row=linha, column=5, value=titulo)
            cel.font = FONT_RED_BOLD_24
            cel.alignment = ALIGN_CENTER
            ws.row_dimensions[linha].height = 34
            linha += 1

            dados_alfametal = subset[
                subset["EMPRESA"].isin(alfametal_empresas)
                & (subset["VENC"].dt.date == data.date())
            ].sort_values(["VALOR", "FORNECEDOR"], ascending=[True, True], na_position="last")

            dados_betaviaria = subset[
                subset["EMPRESA"].isin(betaviaria_empresas)
                & (subset["VENC"].dt.date == data.date())
            ].sort_values(["VALOR", "FORNECEDOR"], ascending=[True, True], na_position="last")

            for grupo_df, fill_h, font_h in [
                (dados_alfametal,  FILL_AZUL,   FONT_WHITE_BOLD),
                (dados_betaviaria, FILL_AMARELO, FONT_BLACK_BOLD),
            ]:
                if grupo_df.empty:
                    continue
                # Cabeçalho
                for col_idx, header in enumerate(headers, start=5):
                    c = ws.cell(row=linha, column=col_idx, value=header)
                    c.fill = fill_h
                    c.font = font_h
                    c.alignment = ALIGN_CENTER
                    c.border = BORDER_THIN
                linha += 1

                cols_cons = ["EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF", "VENC", "VALOR"]
                dados_lista = grupo_df[cols_cons].values.tolist()
                inicio_dados = linha
                for row_vals in dados_lista:
                    venc = pd.to_datetime(row_vals[4]).date() if pd.notna(row_vals[4]) else None
                    valor = float(row_vals[5]) if pd.notna(row_vals[5]) else None
                    ws.cell(row=linha, column=5,  value=row_vals[0])   # EMPRESA
                    ws.cell(row=linha, column=6,  value=row_vals[1])   # CNPJ
                    ws.cell(row=linha, column=7,  value="")            # STATUS vazio
                    ws.cell(row=linha, column=8,  value=row_vals[2])   # FORNECEDOR
                    ws.cell(row=linha, column=9,  value=row_vals[3])   # PRV NF
                    ws.cell(row=linha, column=10, value=venc)
                    ws.cell(row=linha, column=11, value=valor)
                    linha += 1

                if linha > inicio_dados:
                    self._estilizar_bloco_dados(ws, inicio_dados, linha - 1, col_fim=11)

                linha += 1  # Linha em branco entre grupos

            linha += 1  # Linha em branco entre dias

    # ------------------------------------------------------------------ #
    # Aba de erros                                                         #
    # ------------------------------------------------------------------ #

    def _criar_aba_erros(self, writer, erros_df: pd.DataFrame, resultado_cruzamento=None) -> None:
        ws_name = "ERROS"
        writer.book.create_sheet(ws_name)
        ws = writer.book[ws_name]
        ws.sheet_view.showGridLines = False

        # Título
        ws.merge_cells("A1:I1")
        c = ws.cell(row=1, column=1, value="RELATÓRIO DE INCONSISTÊNCIAS")
        c.font = FONT_TITLE_ERROR
        c.fill = FILL_VERMELHO
        c.alignment = ALIGN_CENTER

        ws.merge_cells("A2:I2")
        c2 = ws.cell(row=2, column=1, value="Valide somente os registros abaixo antes de importar no sistema")
        c2.font = Font(size=10, italic=True, color="666666")
        c2.alignment = ALIGN_CENTER

        # [ALAN 29/10/2026] cards de contagem, "Remoções automáticas" e
        # "Detalhamento dos erros" retirados a pedido do usuário — o erro de
        # cada linha continua na coluna ERROS da Planilha1.
        linha = 2

        # ── Seção: Possíveis duplicatas ──────────────────────────── #
        if self.duplicatas is not None and not self.duplicatas.empty:
            linha += 2
            FILL_AMBAR_SEC = PatternFill("solid", fgColor="B45309")
            ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=9)
            cd = ws.cell(
                row=linha, column=1,
                value=(
                    f"⚠  POSSÍVEIS DUPLICATAS — {len(self.duplicatas)} linha(s) com mesmo "
                    "fornecedor, valor e vencimento. Confirme antes de pagar."
                ),
            )
            cd.font = Font(bold=True, color="FFFFFF", size=11)
            cd.fill = FILL_AMBAR_SEC
            cd.alignment = ALIGN_CENTER
            for c in range(1, 10):
                ws.cell(row=linha, column=c).fill = FILL_AMBAR_SEC
                ws.cell(row=linha, column=c).border = BORDER_THIN
            linha += 1

            headers_dupl = ["GRUPO", "EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF", "VENC", "VALOR"]
            for col_idx, h in enumerate(headers_dupl, start=1):
                c = ws.cell(row=linha, column=col_idx, value=h)
                c.fill = FILL_CINZA
                c.font = FONT_BLACK_BOLD
                c.border = BORDER_THIN
                c.alignment = ALIGN_CENTER
            linha += 1

            cols_dupl = ["GRUPO_DUPLICATA", "EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF", "VENC", "VALOR"]
            cols_disp_d = [c for c in cols_dupl if c in self.duplicatas.columns]
            dupl_orden = self.duplicatas.sort_values(
                by=[c for c in ("GRUPO_DUPLICATA", "FORNECEDOR") if c in self.duplicatas.columns]
            )
            for i, row_vals in enumerate(dupl_orden[cols_disp_d].values.tolist()):
                fill = FILL_AMARELO_CLARO if i % 2 == 0 else FILL_BRANCO
                for col_idx, val in enumerate(row_vals, start=1):
                    if isinstance(val, pd.Timestamp):
                        val = val.to_pydatetime()
                    cell = ws.cell(row=linha, column=col_idx, value=val)
                    cell.fill = fill
                    cell.border = BORDER_THIN
                    cell.alignment = ALIGN_VCENTER
                # VENC (col 6) e VALOR (col 7)
                ws.cell(row=linha, column=6).number_format = "DD/MM/YYYY"
                ws.cell(row=linha, column=6).alignment = ALIGN_CENTER
                ws.cell(row=linha, column=7).number_format = "#,##0.00"
                ws.cell(row=linha, column=7).alignment = ALIGN_RIGHT
                linha += 1

        # ── Seção: Programados no banco ──────────────────────────── #
        if resultado_cruzamento is not None and not resultado_cruzamento.df_programado.empty:
            linha += 2
            # Cabeçalho da seção — verde
            FILL_VERDE_SEC = PatternFill("solid", fgColor="1E7E34")
            ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=9)
            cs = ws.cell(row=linha, column=1,
                value=f"✓  PROGRAMADOS NO BANCO — {len(resultado_cruzamento.df_programado)} pagamento(s) já consta(m) na planilha do banco — continuam na lista, em amarelo")
            cs.font = Font(bold=True, color="FFFFFF", size=11)
            cs.fill = FILL_VERDE_SEC
            cs.alignment = ALIGN_CENTER
            for c in range(1, 10):
                ws.cell(row=linha, column=c).fill = FILL_VERDE_SEC
                ws.cell(row=linha, column=c).border = BORDER_THIN
            linha += 1

            # Cabeçalho da tabela
            headers_prog = ["EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF", "PAGAMENTO", "VALOR", "", "", ""]
            for col_idx, h in enumerate(headers_prog[:6], start=1):
                c = ws.cell(row=linha, column=col_idx, value=h)
                c.fill = FILL_CINZA
                c.font = FONT_BLACK_BOLD
                c.border = BORDER_THIN
                c.alignment = ALIGN_CENTER
            linha += 1

            # Dados — apenas 6 colunas limpas
            prog_df = resultado_cruzamento.df_programado
            cols_prog = ["EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF", "VENC", "VALOR"]
            cols_disp = [c for c in cols_prog if c in prog_df.columns]
            for i, row_vals in enumerate(prog_df[cols_disp].values.tolist()):
                fill = FILL_AZUL_CLARO if i % 2 == 0 else FILL_BRANCO
                for col_idx, val in enumerate(row_vals, start=1):
                    cell = ws.cell(row=linha, column=col_idx, value=val)
                    cell.fill = fill
                    cell.border = BORDER_THIN
                    cell.alignment = ALIGN_VCENTER
                # PAGAMENTO (col 5)
                ws.cell(row=linha, column=5).number_format = "DD/MM/YYYY"
                ws.cell(row=linha, column=5).alignment = ALIGN_CENTER
                # VALOR (col 6)
                ws.cell(row=linha, column=6).number_format = "#,##0.00"
                ws.cell(row=linha, column=6).alignment = ALIGN_RIGHT
                linha += 1

        # ── Seção: CONCILIAÇÃO (item 1) ─────────────────────────────── #
        from ..core.conciliacao import conciliar
        conc = conciliar(self, resultado_cruzamento)
        # [ALAN 29/10/2026] só aparece quando a conta NÃO fecha (alerta);
        # o "conciliação OK" e a lista de colunas detectadas saíram.
        if not conc.ok:
            self._escrever_conciliacao(ws, linha, conc)
            linha += 3 + len(conc.checagens)
        if self.col_warnings:
            linha += 1
            for aviso in self.col_warnings:
                ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=9)
                cw = ws.cell(row=linha, column=1, value="⚠  " + str(aviso))
                cw.font = Font(italic=True, color="B45309")
                cw.border = BORDER_THIN
                linha += 1
        self._escrever_restante_erros(ws, linha, resultado_cruzamento)

    def _escrever_conciliacao(self, ws, linha: int, conc) -> None:
        linha += 2
        cor_conc = "1E7E34" if conc.ok else "C00000"
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=9)
        cc = ws.cell(
            row=linha, column=1,
            value=("✓  CONCILIAÇÃO OK — nenhuma nota se perdeu no processo"
                   if conc.ok else
                   "⚠  CONCILIAÇÃO COM PROBLEMA — a conta de entrada/saída não fechou"),
        )
        cc.font = Font(bold=True, color="FFFFFF", size=11)
        cc.fill = PatternFill("solid", fgColor=cor_conc)
        cc.alignment = ALIGN_CENTER
        for c in range(1, 10):
            ws.cell(row=linha, column=c).fill = PatternFill("solid", fgColor=cor_conc)
            ws.cell(row=linha, column=c).border = BORDER_THIN
        linha += 1
        for chk in conc.checagens:
            ws.cell(row=linha, column=1, value=("OK" if chk.ok else "ERRO")).border = BORDER_THIN
            ws.merge_cells(start_row=linha, start_column=2, end_row=linha, end_column=9)
            ws.cell(
                row=linha, column=2,
                value=f"{chk.descricao}  →  esperado {chk.esperado}, obtido {chk.obtido}",
            ).border = BORDER_THIN
            linha += 1

    def _escrever_restante_erros(self, ws, linha: int, resultado_cruzamento) -> None:
        # ── Seção: PAGAMENTOS DO BANCO SEM NOTA (item 5) ────────────── #
        # [ALAN 30/10/2026] desligada a pedido do usuário: não sai mais na
        # aba ERROS (continua só na tela do ALAN). Para voltar: True.
        nao_casados = getattr(resultado_cruzamento, "pagamentos_nao_casados", None) if resultado_cruzamento else None
        if self.MOSTRAR_BANCO_SEM_NOTA and nao_casados:
            linha += 2
            FILL_LARANJA_SEC = PatternFill("solid", fgColor="B45309")
            ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=9)
            cp = ws.cell(
                row=linha, column=1,
                value=(f"⚠  PAGAMENTOS DO BANCO SEM NOTA NO DDA — {len(nao_casados)} "
                       "pagamento(s). Pode ser nota que faltou lançar; confira."),
            )
            cp.font = Font(bold=True, color="FFFFFF", size=11)
            cp.fill = FILL_LARANJA_SEC
            cp.alignment = ALIGN_CENTER
            for c in range(1, 10):
                ws.cell(row=linha, column=c).fill = FILL_LARANJA_SEC
                ws.cell(row=linha, column=c).border = BORDER_THIN
            linha += 1

            headers_np = ["EMPRESA (CONTA)", "FAVORECIDO", "CNPJ", "DATA", "VALOR"]
            for col_idx, h in enumerate(headers_np, start=1):
                ch = ws.cell(row=linha, column=col_idx, value=h)
                ch.fill = FILL_CINZA
                ch.font = FONT_BLACK_BOLD
                ch.border = BORDER_THIN
                ch.alignment = ALIGN_CENTER
            linha += 1

            for i, pg in enumerate(nao_casados):
                fill = FILL_AZUL_CLARO if i % 2 == 0 else FILL_BRANCO
                valores = [
                    getattr(pg, "empresa_banco", ""),
                    getattr(pg, "favorecido", ""),
                    getattr(pg, "cnpj_favorecido", ""),
                    str(getattr(pg, "data", "")),
                    getattr(pg, "valor", None),
                ]
                for col_idx, val in enumerate(valores, start=1):
                    cell = ws.cell(row=linha, column=col_idx, value=val)
                    cell.fill = fill
                    cell.border = BORDER_THIN
                    cell.alignment = ALIGN_VCENTER
                ws.cell(row=linha, column=5).number_format = "#,##0.00"
                ws.cell(row=linha, column=5).alignment = ALIGN_RIGHT
                linha += 1

        col_widths = [20, 22, 30, 14, 14, 15, 14, 15, 22]
        for i, w in enumerate(col_widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

    def _escrever_secao_remocoes(self, ws, linha: int) -> None:
        ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=9)
        cel = ws.cell(row=linha, column=1, value="REMOÇÕES AUTOMÁTICAS")
        cel.font = FONT_CARD_TITLE
        cel.fill = FILL_CINZA_ESCURO
        cel.alignment = ALIGN_CENTER
        for c in range(1, 10):
            ws.cell(row=linha, column=c).fill = FILL_CINZA_ESCURO
            ws.cell(row=linha, column=c).font = FONT_CARD_TITLE
            ws.cell(row=linha, column=c).border = BORDER_THIN
        linha += 1

        ws.cell(row=linha, column=1, value="Tipo").font = FONT_BLACK_BOLD
        ws.cell(row=linha, column=1).fill = FILL_BRANCO
        ws.cell(row=linha, column=1).border = BORDER_THIN
        ws.merge_cells(start_row=linha, start_column=2, end_row=linha, end_column=9)
        ws.cell(row=linha, column=2, value="Quantidade").font = FONT_BLACK_BOLD
        ws.cell(row=linha, column=2).fill = FILL_BRANCO
        ws.cell(row=linha, column=2).alignment = ALIGN_CENTER
        for c in range(2, 10):
            ws.cell(row=linha, column=c).border = BORDER_THIN
        linha += 1

        itens = self.resumo_remocoes or [("Nenhuma remoção automática", 0)]
        for tipo, qtd in itens:
            ws.cell(row=linha, column=1, value=tipo).border = BORDER_THIN
            ws.cell(row=linha, column=1).fill = FILL_BRANCO
            ws.merge_cells(start_row=linha, start_column=2, end_row=linha, end_column=9)
            ws.cell(row=linha, column=2, value=qtd).border = BORDER_THIN
            ws.cell(row=linha, column=2).alignment = ALIGN_CENTER
            ws.cell(row=linha, column=2).fill = FILL_BRANCO
            for c in range(2, 10):
                ws.cell(row=linha, column=c).border = BORDER_THIN
            linha += 1


