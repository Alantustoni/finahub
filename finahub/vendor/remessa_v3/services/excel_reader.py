"""
Leitor universal de Excel — suporta XLS (BIFF2/BIFF8), XLSX e CSV.

Estratégia de fallback (na ordem):
  1. XLSX via ZIP+XML  (mais portável, suporta caminhos Windows)
  2. openpyxl          (XLSX padrão)
  3. xlrd              (XLS BIFF8)
  4. pandas            (qualquer engine disponível)
  5. Excel COM via VBS (Windows com Excel instalado, suporta BIFF2)
  6. LibreOffice       (Linux/Mac)
"""

import os
import re
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from core.logger import log
from core.utils import excel_serial_to_date


# ─── XML namespace para sheets XLSX ──────────────────────────────
NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class ExcelReadError(RuntimeError):
    """Erro ao tentar abrir arquivo Excel."""
    pass


def read_sheet_rows(filepath: str) -> list[list[str]]:
    """
    Lê a primeira planilha de um arquivo e retorna lista de listas de strings.
    Tenta múltiplos métodos até um funcionar.

    Raises:
        ExcelReadError: se nenhum método conseguir abrir o arquivo.
    """
    filepath = str(filepath)
    log.info(f"Lendo arquivo: {Path(filepath).name}")

    attempts = [
        ("xlsx_zip",      _try_xlsx_zip),
        ("openpyxl",      _try_openpyxl),
        ("xlrd",          _try_xlrd),
        ("pandas",        _try_pandas),
        ("excel_vbs",     _try_excel_vbs),
        ("libreoffice",   _try_libreoffice),
    ]

    for name, fn in attempts:
        try:
            rows = fn(filepath)
            if rows and _has_content(rows):
                log.info(f"  ✓ Lido via {name}: {len(rows)} linhas")
                return rows
        except Exception as e:
            log.debug(f"  ✗ Método {name} falhou: {e}")

    raise ExcelReadError(
        f"Não foi possível abrir o arquivo:\n{filepath}\n\n"
        "SOLUÇÃO RECOMENDADA:\n"
        "Abra o arquivo no Excel e salve novamente como .xlsx\n"
        "Em seguida, selecione esse novo arquivo .xlsx no sistema."
    )


def _has_content(rows: list[list[str]]) -> bool:
    """Verifica se há ao menos uma célula com conteúdo."""
    return any(any(c for c in r) for r in rows)


# ─────────────────────────────────────────────────────────────────
# Método 1: XLSX via ZIP+XML
# Funciona com xlsx gerado pelo Excel Windows (caminhos com \)
# ─────────────────────────────────────────────────────────────────
def _try_xlsx_zip(filepath: str) -> list[list[str]] | None:
    if not zipfile.is_zipfile(filepath):
        return None

    rows: list[list[str]] = []

    with zipfile.ZipFile(filepath, "r") as z:
        names = z.namelist()

        # Localiza sheet1 (caminho com / ou \)
        sheet_name = None
        for n in names:
            normalized = n.replace("\\", "/").lower()
            if "xl/worksheets/sheet1.xml" in normalized:
                sheet_name = n
                break
        if sheet_name is None:
            for n in names:
                if "sheet1" in n.lower() and n.endswith(".xml"):
                    sheet_name = n
                    break
        if sheet_name is None:
            return None

        # Shared strings
        shared_strings = _read_shared_strings(z, names)

        # Estilos (para detectar datas)
        date_style_ids = _read_date_styles(z, names)

        # Lê células
        with z.open(sheet_name) as f:
            tree = ET.parse(f)

        for row_el in tree.findall(".//x:row", NS):
            row_data = [""] * 16

            for c in row_el.findall("x:c", NS):
                col_idx = _col_letters_to_idx(c.get("r", ""))
                if col_idx < 0:
                    continue

                val = _extract_cell_value(c, shared_strings, date_style_ids)

                # Expande row_data se necessário
                while col_idx >= len(row_data):
                    row_data.append("")
                row_data[col_idx] = val

            rows.append(row_data)

    return rows


def _col_letters_to_idx(ref: str) -> int:
    """'A1' → 0, 'B1' → 1, 'AA1' → 26"""
    letters = re.sub(r"\d", "", ref)
    if not letters:
        return -1
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - ord("A") + 1)
    return idx - 1


def _extract_cell_value(c, shared_strings, date_style_ids) -> str:
    """Extrai o valor textual de uma célula XML."""
    t = c.get("t", "")
    s_attr = c.get("s", "")
    v_el = c.find("x:v", NS)
    is_el = c.find(".//x:t", NS)

    if t == "inlineStr" and is_el is not None:
        return (is_el.text or "").strip()

    if t == "s" and v_el is not None:
        try:
            idx = int(v_el.text)
            return shared_strings[idx] if idx < len(shared_strings) else ""
        except (ValueError, TypeError):
            return ""

    if v_el is not None:
        raw = (v_el.text or "").strip()
        # Se o estilo indica data, converte serial
        if s_attr and s_attr.isdigit() and int(s_attr) in date_style_ids:
            d = excel_serial_to_date(raw)
            return d if d else raw
        return raw

    return ""


def _read_shared_strings(z, names) -> list[str]:
    """Lê o arquivo sharedStrings.xml se existir."""
    shared = []
    for n in names:
        nl = n.lower().replace("\\", "/")
        if "sharedstrings.xml" in nl:
            try:
                with z.open(n) as f:
                    tree = ET.parse(f)
                for si in tree.findall(".//x:si", NS):
                    texts = si.findall(".//x:t", NS)
                    shared.append("".join(t.text or "" for t in texts))
            except Exception as e:
                log.debug(f"Erro lendo sharedStrings: {e}")
            break
    return shared


def _read_date_styles(z, names) -> set[int]:
    """
    Identifica IDs de estilos que representam datas.
    Lê numFmts (formatos customizados) e detecta por palavras-chave (d, m, y),
    em vez de assumir que numFmtId >= 164 é sempre data.
    """
    date_ids: set[int] = set()

    for n in names:
        nl = n.lower().replace("\\", "/")
        if not nl.endswith("styles.xml"):
            continue

        try:
            with z.open(n) as f:
                tree = ET.parse(f)
        except Exception as e:
            log.debug(f"Erro lendo styles: {e}")
            return date_ids

        # ── 1) Coleta numFmts customizados que são datas ─────────
        custom_date_fmts: set[int] = set()
        for nf in tree.findall(".//x:numFmts/x:numFmt", NS):
            try:
                fmt_id = int(nf.get("numFmtId", "0"))
                code = (nf.get("formatCode", "") or "").lower()
                # Heurística: contém d, m, y, h, s mas não % nem $
                if (any(ch in code for ch in ("y", "d")) and
                        "general" not in code and
                        "$" not in code and
                        "%" not in code):
                    custom_date_fmts.add(fmt_id)
            except (ValueError, TypeError):
                pass

        # ── 2) Identifica XFs (cellXfs) que apontam para data ────
        # Builtin date formats: 14-22 (DD/MM/YY, etc.) e 45-47 (h:mm:ss)
        BUILTIN_DATES = set(range(14, 23)) | {27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58}

        cell_xfs = tree.find(".//x:cellXfs", NS)
        if cell_xfs is None:
            return date_ids

        for i, xf in enumerate(cell_xfs.findall("x:xf", NS)):
            try:
                nfid = int(xf.get("numFmtId", "0"))
                if nfid in BUILTIN_DATES or nfid in custom_date_fmts:
                    date_ids.add(i)
            except (ValueError, TypeError):
                pass
        break

    return date_ids


# ─────────────────────────────────────────────────────────────────
# Método 2: openpyxl
# ─────────────────────────────────────────────────────────────────
def _try_openpyxl(filepath: str) -> list[list[str]] | None:
    ext = Path(filepath).suffix.lower()
    if ext not in (".xlsx", ".xlsm"):
        return None

    import openpyxl
    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    try:
        ws = wb.active
        rows = [
            [str(v).strip() if v is not None else "" for v in row]
            for row in ws.iter_rows(values_only=True)
        ]
        return rows
    finally:
        wb.close()


# ─────────────────────────────────────────────────────────────────
# Método 3: xlrd (XLS BIFF8)
# ─────────────────────────────────────────────────────────────────
def _try_xlrd(filepath: str) -> list[list[str]] | None:
    """
    Lê XLS via xlrd. Atenção: xlrd marca como XL_CELL_DATE qualquer número
    que tenha formato de data — incluindo valores monetários que apenas
    coincidem com seriais válidos. Para evitar falsos positivos, só
    converte para data se o número for plausível como data (< 73000,
    cerca de 2099) E se nenhuma decimal estiver presente.
    """
    import xlrd

    wb = xlrd.open_workbook(filepath, formatting_info=False)
    ws = wb.sheet_by_index(0)
    rows = []

    for r in range(ws.nrows):
        row = []
        for c in range(ws.ncols):
            cell = ws.cell(r, c)

            if cell.ctype == xlrd.XL_CELL_EMPTY:
                row.append("")

            elif cell.ctype == xlrd.XL_CELL_DATE:
                v = cell.value
                # Salvaguarda contra falso positivo: só converte se for plausível data
                if 1 <= v < 73000 and abs(v - int(v)) < 0.001:
                    try:
                        dt = xlrd.xldate_as_datetime(v, wb.datemode)
                        row.append(dt.strftime("%d/%m/%Y"))
                    except Exception:
                        row.append(str(v))
                else:
                    row.append(str(int(v)) if v == int(v) else f"{v:.2f}")

            elif cell.ctype == xlrd.XL_CELL_NUMBER:
                v = cell.value
                row.append(str(int(v)) if v == int(v) else f"{v:.2f}")

            else:
                row.append(str(cell.value).strip())

        rows.append(row)
    return rows


# ─────────────────────────────────────────────────────────────────
# Método 4: pandas
# ─────────────────────────────────────────────────────────────────
def _try_pandas(filepath: str) -> list[list[str]] | None:
    import pandas as pd

    for engine in ("openpyxl", "xlrd"):
        try:
            df = pd.read_excel(filepath, header=None, engine=engine, dtype=str)
            return _df_to_rows(df)
        except Exception:
            continue
    return None


def _df_to_rows(df) -> list[list[str]]:
    rows = []
    for _, row in df.iterrows():
        rows.append([
            str(v).strip() if v is not None and str(v) != "nan" else ""
            for v in row
        ])
    return rows


# ─────────────────────────────────────────────────────────────────
# Método 5: Excel COM via VBScript (Windows, suporta BIFF2)
# ─────────────────────────────────────────────────────────────────
def _try_excel_vbs(filepath: str) -> list[list[str]] | None:
    if os.name != "nt":
        return None

    out_dir = tempfile.mkdtemp(prefix="rxb_vbs_")
    csv_path = os.path.join(out_dir, "output.csv")
    filepath_abs = str(Path(filepath).resolve())
    csv_abs = str(Path(csv_path).resolve())

    vbs = f'''Set xl = CreateObject("Excel.Application")
xl.Visible = False
xl.DisplayAlerts = False
On Error GoTo ErrHandler
Set wb = xl.Workbooks.Open("{filepath_abs}")
wb.SaveAs "{csv_abs}", 6
wb.Close False
xl.Quit
WScript.Quit 0
ErrHandler:
xl.Quit
WScript.Quit 1
'''
    vbs_file = os.path.join(out_dir, "convert.vbs")
    with open(vbs_file, "w", encoding="utf-8") as f:
        f.write(vbs)

    try:
        subprocess.run(
            ["cscript", "//Nologo", vbs_file],
            capture_output=True, timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except FileNotFoundError:
        return None

    if Path(csv_path).exists():
        return _read_csv_file(csv_path)
    return None


# ─────────────────────────────────────────────────────────────────
# Método 6: LibreOffice
# ─────────────────────────────────────────────────────────────────
def _try_libreoffice(filepath: str) -> list[list[str]] | None:
    for cmd in (["libreoffice"], ["soffice"]):
        try:
            out_dir = tempfile.mkdtemp(prefix="rxb_lo_")
            subprocess.run(
                cmd + ["--headless", "--convert-to", "xlsx", "--outdir", out_dir, filepath],
                capture_output=True, timeout=120,
            )
            xlsx_path = Path(out_dir) / (Path(filepath).stem + ".xlsx")
            if xlsx_path.exists():
                return _try_xlsx_zip(str(xlsx_path)) or _try_openpyxl(str(xlsx_path))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _read_csv_file(csv_path: str) -> list[list[str]]:
    """Lê CSV com auto-detecção de encoding."""
    import pandas as pd
    for enc in ("utf-8-sig", "cp1252", "latin1", "utf-8"):
        try:
            df = pd.read_csv(
                csv_path, header=None, encoding=enc,
                dtype=str, keep_default_na=False,
            )
            return _df_to_rows(df)
        except Exception:
            continue
    return []
