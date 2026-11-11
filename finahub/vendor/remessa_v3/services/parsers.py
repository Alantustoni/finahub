"""
Parsers especializados para Excel do BANCO e do SISTEMA.

Cada parser:
  - Detecta automaticamente o layout (xls, xlsx, com/sem barras invertidas)
  - Identifica colunas dinamicamente pelo cabeçalho
  - Retorna registros normalizados (dict)
"""

import re
from dataclasses import dataclass

from core.logger import log
from core.utils import (
    parse_date, parse_value, clean_supplier, to_ascii_lower,
)
from .excel_reader import read_sheet_rows, ExcelReadError


# ─── Estruturas de dados ─────────────────────────────────────────
@dataclass(frozen=True)
class Record:
    """Registro normalizado, comum a Banco e Sistema."""
    data: str          # "DD/MM/YYYY"
    valor: float       # > 0
    fornecedor: str
    remessa: str = ""
    titulo: str = ""
    referencia: str = ""
    origem: str = ""   # 'sistema' ou 'banco'

    def chave(self) -> tuple[str, float]:
        """Chave de conciliação: (data, valor)."""
        return (self.data, self.valor)


# ─── Aliases de colunas ──────────────────────────────────────────
COL_ALIASES = {
    "fornecedor": {"fornecedor", "favorecido", "beneficiario",
                   "favorecido / beneficiario", "empresa", "razao social"},
    "valor":      {"valor", "valor (r$)", "vlr", "valor pago",
                   "liquido", "pagamento", "vl_pago", "importe"},
    "data":       {"data", "data do pagamento", "data pagamento",
                   "vencimento", "dt pagamento", "venc", "competencia"},
    "remessa":    {"remessa", "numero remessa", "id remessa", "nr remessa"},
    "titulo":     {"titulo", "numero titulo", "nr titulo"},
    "referencia": {"referencia", "referencia da empresa", "ref"},
}


def _find_col_by_aliases(row: list[str], aliases: set[str]) -> int:
    """Procura na linha um cabeçalho que corresponda a um dos aliases."""
    for i, cell in enumerate(row):
        ca = to_ascii_lower(cell)
        if ca in aliases:
            return i
    # Match parcial
    for i, cell in enumerate(row):
        ca = to_ascii_lower(cell)
        for alias in aliases:
            if alias in ca or ca in alias:
                if len(ca) >= 3:
                    return i
    return -1


# ═════════════════════════════════════════════════════════════════
# PARSER DO EXCEL DO BANCO
# ═════════════════════════════════════════════════════════════════
def parse_banco(filepath: str) -> list[Record]:
    """
    Lê o Excel do Banco e retorna lista de Record.

    Layout típico (Itaú):
      Linhas 0-17: cabeçalho institucional
      Linha 18:    cabeçalho da tabela (favorecido | CPF | tipo | ref | data | valor | status)
      Linha 19+:   dados
      Última:      'Total:' + valor total
    """
    rows = read_sheet_rows(filepath)
    if not rows:
        raise ExcelReadError("Arquivo do banco vazio.")

    # ── 1) Localiza cabeçalho ────────────────────────────────────
    header_row = -1
    for i, row in enumerate(rows):
        for cell in row:
            ca = to_ascii_lower(cell)
            if "favorecido" in ca or "beneficiario" in ca:
                header_row = i
                break
        if header_row >= 0:
            break

    if header_row < 0:
        raise ExcelReadError(
            "Cabeçalho não encontrado no Excel do Banco.\n"
            "Esperado: coluna 'favorecido / beneficiário'."
        )

    # ── 2) Identifica colunas dinamicamente ──────────────────────
    header = rows[header_row]
    col_forn = _find_col_by_aliases(header, COL_ALIASES["fornecedor"])
    col_data = _find_col_by_aliases(header, COL_ALIASES["data"])
    col_val  = _find_col_by_aliases(header, COL_ALIASES["valor"])
    col_ref  = _find_col_by_aliases(header, COL_ALIASES["referencia"])

    # Fallback posicional (layout fixo do Itaú)
    if col_forn < 0: col_forn = 0
    if col_data < 0: col_data = 4
    if col_val  < 0: col_val  = 5
    if col_ref  < 0: col_ref  = 3

    log.info(f"  Banco — colunas: forn={col_forn} data={col_data} valor={col_val} ref={col_ref}")

    # ── 3) Lê linhas de dados ────────────────────────────────────
    records: list[Record] = []
    skipped = 0

    for row in rows[header_row + 1:]:
        # Expande row se necessário
        max_col = max(col_forn, col_data, col_val, col_ref)
        while len(row) <= max_col:
            row.append("")

        forn = row[col_forn].strip()
        if not forn:
            continue

        # Pula linhas de total e cabeçalhos repetidos
        fa = to_ascii_lower(forn)
        if "total" in fa or "favorecido" in fa or "beneficiario" in fa:
            continue

        data  = parse_date(row[col_data])
        valor = parse_value(row[col_val])

        if data is None or valor is None:
            skipped += 1
            continue

        records.append(Record(
            data=data, valor=valor, fornecedor=forn,
            referencia=row[col_ref].strip(),
            origem="banco",
        ))

    log.info(f"  Banco — {len(records)} registros lidos, {skipped} ignorados")
    return records


# ═════════════════════════════════════════════════════════════════
# PARSER DO EXCEL DO SISTEMA
# ═════════════════════════════════════════════════════════════════
def parse_sistema(filepath: str) -> list[Record]:
    """
    Lê o Excel do Sistema (Remessa) e retorna lista de Record.

    Layout típico (por página):
      "Pág."                  → ignorar
      "Data Qtde Valor Banco" → cabeçalho de página
      número de página        → ignorar
      "DD/MM/YYYY  21  ..."   → captura DATA
      "Fornecedor Remessa..." → início dos dados
      linhas de dados
      "Grupo:" ou "Arquivo:"  → fim do bloco
    """
    rows = read_sheet_rows(filepath)
    if not rows:
        raise ExcelReadError("Arquivo do sistema vazio.")

    # ── 1) Detecta layout: descobre colunas pelo cabeçalho ───────
    col_forn, col_remessa, col_titulo, col_valor = _detect_sistema_layout(rows)

    log.info(f"  Sistema — colunas: forn={col_forn} rem={col_remessa} "
             f"tit={col_titulo} val={col_valor}")

    # ── 2) Itera linhas ──────────────────────────────────────────
    records: list[Record] = []
    current_date: str | None = None
    in_data_section = False

    max_col = max(col_forn, col_remessa, col_titulo, col_valor)

    for row in rows:
        while len(row) <= max_col:
            row.append("")

        v0 = row[col_forn].strip() if len(row) > col_forn else ""
        v0a = to_ascii_lower(v0)

        # ── Detecta linha de data ─────────────────────────────────
        # Caso A: data está em col_forn + qtde em col 1
        d = parse_date(v0)
        if d is not None and len(row) > 1:
            v1 = row[1].strip()
            if v1 and _looks_like_int(v1):
                current_date = d
                in_data_section = False
                continue

        # Caso B: col_forn vazio, data está em col C ou similar
        if not v0:
            for ci in range(1, min(len(row), 8)):
                cell = row[ci].strip()
                if not cell:
                    continue
                d = parse_date(cell)
                if d:
                    # Confirma com qtde inteira em coluna próxima
                    for cj in range(ci + 1, min(len(row), ci + 4)):
                        if _looks_like_int(row[cj]):
                            current_date = d
                            in_data_section = False
                            break
                    if current_date == d:
                        break
            continue

        # ── Cabeçalho da tabela ──────────────────────────────────
        if v0a == "fornecedor":
            in_data_section = True
            continue

        # ── Fim do bloco ─────────────────────────────────────────
        if (v0a.startswith("grupo") or v0a.startswith("arquivo") or
                v0a.startswith("total") or v0a in ("pag.", "pag", "data", "pagina")):
            in_data_section = False
            continue

        # Número de página puro
        if re.fullmatch(r"\d{1,3}", v0):
            continue

        # ── Linha de dado ────────────────────────────────────────
        if not in_data_section or current_date is None:
            continue

        # Ignora linhas que são só números (subtotais)
        if re.fullmatch(r"[\d.,]+", v0):
            continue

        valor = parse_value(row[col_valor])
        if valor is None:
            continue

        records.append(Record(
            data=current_date, valor=valor,
            fornecedor=clean_supplier(v0),
            remessa=row[col_remessa].strip() if col_remessa < len(row) else "",
            titulo=row[col_titulo].strip()   if col_titulo  < len(row) else "",
            origem="sistema",
        ))

    log.info(f"  Sistema — {len(records)} registros lidos, "
             f"data detectada: {current_date}")
    return records


def _looks_like_int(s: str) -> bool:
    """Verifica se string representa inteiro (pode ter espaços)."""
    s = s.strip()
    if not s:
        return False
    try:
        int(float(s))
        return True
    except (ValueError, TypeError):
        return False


def _detect_sistema_layout(rows: list[list[str]]) -> tuple[int, int, int, int]:
    """
    Detecta posição das colunas Fornecedor / Remessa / Título / Valor
    inspecionando a linha que tem cabeçalho "Fornecedor".
    Retorna (col_forn, col_remessa, col_titulo, col_valor).
    """
    # Defaults: layout xlsx Windows
    col_forn, col_remessa, col_titulo, col_valor = 0, 2, 3, 5

    for row in rows:
        if not row:
            continue
        v0 = to_ascii_lower(row[0])
        if v0 != "fornecedor":
            continue

        # Encontrou linha de cabeçalho — mapeia colunas
        for ci, cell in enumerate(row):
            ca = to_ascii_lower(cell)
            if ca == "valor":
                col_valor = ci
            elif ca == "remessa":
                col_remessa = ci
            elif ca in ("titulo", "titulos"):
                col_titulo = ci
        break

    return col_forn, col_remessa, col_titulo, col_valor
