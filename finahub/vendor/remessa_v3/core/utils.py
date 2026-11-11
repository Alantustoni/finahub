"""
Utilitários puros — parsing de valores monetários, datas e nomes.
Nenhuma dependência de UI ou biblioteca pesada.
"""

import re
import unicodedata
from datetime import datetime, date as date_type, timedelta


# ─── Constantes ──────────────────────────────────────────────────
DAYS_PT = {
    0: "Segunda-feira",
    1: "Terça-feira",
    2: "Quarta-feira",
    3: "Quinta-feira",
    4: "Sexta-feira",
    5: "Sábado",
    6: "Domingo",
}

DATE_FORMATS = (
    "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y",
    "%d.%m.%Y", "%m/%d/%Y", "%d/%m/%y",
)


# ─── Texto ───────────────────────────────────────────────────────
def to_ascii_lower(text) -> str:
    """Converte para ASCII puro lowercase — seguro para qualquer encoding."""
    if not text:
        return ""
    s = str(text)
    s = s.encode("ascii", "ignore").decode("ascii")
    return s.strip().lower()


def normalize_text(text) -> str:
    """Remove acentos e normaliza espaços — para comparação."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().upper()


def clean_supplier(name) -> str:
    """Remove código numérico inicial: '12557 - NCOM...' → 'NCOM...'"""
    if not name:
        return ""
    s = re.sub(r"^\d+\s*[-–—]\s*", "", str(name).strip())
    return s.strip()


# ─── Valor monetário ─────────────────────────────────────────────
def parse_value(val):
    """
    Converte qualquer representação de valor para float.
    Suporta: int, float, '1.234,56' (BR), '1234.56' (US), 'R$ 100,00'.
    Retorna None se não conseguir converter ou se valor for ≤ 0.
    """
    if val is None:
        return None

    if isinstance(val, (int, float)):
        import math
        if isinstance(val, float) and math.isnan(val):
            return None
        v = round(float(val), 2)
        return v if v > 0 else None

    s = str(val).strip()
    if not s or s in ("-", "nan", "NaN", "None"):
        return None

    # Remove R$, espaços, etc
    s = re.sub(r"[R$\s]", "", s)
    if not s:
        return None

    # Formato BR: 1.234,56 → 1234.56
    if re.match(r"^-?\d{1,3}(\.\d{3})*,\d{1,2}$", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        # Vírgula simples como decimal: 1234,56 → 1234.56
        s = s.replace(",", ".")

    try:
        v = round(float(s), 2)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None


def format_brl(value: float) -> str:
    """Formata float como moeda brasileira: 1234.5 → 'R$ 1.234,50'"""
    if value is None:
        return "R$ —"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ─── Datas ───────────────────────────────────────────────────────
def excel_serial_to_date(serial) -> str | None:
    """
    Converte número serial do Excel para 'DD/MM/YYYY'.
    Ex: 46171 → '29/05/2026'
    """
    try:
        n = int(float(str(serial).strip()))
    except (ValueError, TypeError):
        return None

    if n < 1000:
        return None
    if n > 59:
        n -= 1  # Corrige bug do Excel (1900 como ano bissexto)
    try:
        result = date_type(1899, 12, 31) + timedelta(days=n)
        return result.strftime("%d/%m/%Y")
    except (ValueError, OverflowError):
        return None


def parse_date(val) -> str | None:
    """
    Converte qualquer representação de data para 'DD/MM/YYYY'.
    Suporta: datetime, date, Timestamp, strings em vários formatos, serial Excel.
    """
    if val is None:
        return None

    if isinstance(val, datetime):
        return val.strftime("%d/%m/%Y")
    if isinstance(val, date_type):
        return val.strftime("%d/%m/%Y")

    try:
        import pandas as pd
        if isinstance(val, pd.Timestamp):
            return val.strftime("%d/%m/%Y")
    except Exception:
        pass

    s = str(val).strip()
    if not s or s in ("-", "nan", "NaN", "None"):
        return None

    # Tenta formatos textuais
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s[:10], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue

    # Serial numérico do Excel (4-6 dígitos)
    if re.fullmatch(r"\d{4,6}", s):
        return excel_serial_to_date(s)

    return None


def date_to_weekday(date_str: str) -> str:
    """'29/05/2026' → 'Sexta-feira'"""
    try:
        d = datetime.strptime(date_str, "%d/%m/%Y")
        return DAYS_PT[d.weekday()]
    except (ValueError, KeyError):
        return ""


def date_sort_key(date_str: str):
    """Chave de ordenação cronológica para datas em DD/MM/YYYY."""
    try:
        return datetime.strptime(date_str, "%d/%m/%Y")
    except (ValueError, TypeError):
        return datetime.min


# ─── Dias úteis ──────────────────────────────────────────────────
def business_days_between(date1: str, date2: str) -> int:
    """
    Retorna a diferença em dias úteis entre duas datas (DD/MM/YYYY).
    Ignora sábados e domingos. Resultado é sempre positivo.
    """
    try:
        d1 = datetime.strptime(date1, "%d/%m/%Y").date()
        d2 = datetime.strptime(date2, "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return 999  # diferença "infinita" se inválido

    if d1 == d2:
        return 0

    start, end = (d1, d2) if d1 < d2 else (d2, d1)
    days = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0-4 = seg-sex, 5-6 = sab-dom
            days += 1
    return days


# ─── Similaridade de nomes ───────────────────────────────────────
def name_similarity(name1: str, name2: str) -> float:
    """
    Compara dois nomes de fornecedor e retorna similaridade 0.0 a 1.0.
    Normaliza (sem acentos, sem código, lowercase) antes de comparar.
    """
    from difflib import SequenceMatcher

    n1 = normalize_text(clean_supplier(name1))
    n2 = normalize_text(clean_supplier(name2))

    if not n1 or not n2:
        return 0.0
    if n1 == n2:
        return 1.0

    return SequenceMatcher(None, n1, n2).ratio()


def business_days_between(date_a: str, date_b: str) -> int | None:
    """
    Calcula dias úteis entre duas datas em formato 'DD/MM/YYYY'.
    Retorna valor absoluto (sempre ≥ 0) ou None se alguma data for inválida.
    Considera sábado e domingo como não-úteis.
    """
    try:
        da = datetime.strptime(date_a, "%d/%m/%Y").date()
        db = datetime.strptime(date_b, "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return None

    if da == db:
        return 0

    start, end = (da, db) if da < db else (db, da)
    days = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0-4 = seg-sex
            days += 1
    return days


def week_range_for_date(date_str: str) -> tuple[str, str] | None:
    """
    Dada uma data, retorna (segunda, sexta) da semana em formato 'DD/MM/YYYY'.
    Útil para montar os 5 cards de Status por Dia.
    """
    try:
        d = datetime.strptime(date_str, "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return None

    monday = d - timedelta(days=d.weekday())
    friday = monday + timedelta(days=4)
    return monday.strftime("%d/%m/%Y"), friday.strftime("%d/%m/%Y")


def all_business_days_of_week(date_str: str) -> list[str]:
    """
    Retorna lista das 5 datas (seg→sex) da semana que contém a data dada.
    """
    rng = week_range_for_date(date_str)
    if not rng:
        return []
    monday_s, _ = rng
    monday = datetime.strptime(monday_s, "%d/%m/%Y").date()
    return [(monday + timedelta(days=i)).strftime("%d/%m/%Y") for i in range(5)]


# ─── Similaridade de nomes (fuzzy matching) ─────────────────────
def name_similarity(name_a: str, name_b: str) -> float:
    """
    Compara similaridade entre dois nomes de fornecedor.
    Retorna float em [0.0, 1.0], onde 1.0 = idêntico.

    Estratégia:
      1. Normaliza ambos (sem acentos, uppercase, sem códigos numéricos)
      2. Usa SequenceMatcher.ratio() do difflib
      3. Bonus se um nome contém o outro (caso 'GAMMA GASOTEC' vs 'GAMMA GASOTEC GASES')
    """
    if not name_a or not name_b:
        return 0.0

    from difflib import SequenceMatcher

    a = normalize_text(clean_supplier(name_a))
    b = normalize_text(clean_supplier(name_b))

    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    # Similaridade base
    ratio = SequenceMatcher(None, a, b).ratio()

    # Bonus: se o nome menor está contido no maior, isso é sinal forte
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter in longer and len(shorter) >= 5:
        # Garante mínimo de 0.85 quando há containment relevante
        ratio = max(ratio, 0.85)

    return round(ratio, 3)
