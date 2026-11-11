"""
Identidade visual do REMESSA x BANCO v2.
Centraliza cores, fontes e tokens de design.
"""

# ─── Paleta principal ────────────────────────────────────────────
COLORS = {
    # Fundos
    "bg_main":      "#EEF6FF",
    "bg_card":      "#FFFFFF",
    "bg_topbar":    "#D6E8FA",
    "bg_hover":     "#E0F0FF",
    "bg_subtle":    "#F0F7FF",
    "bg_row_alt":   "#F8FAFC",

    # Azuis (identidade)
    "blue_main":    "#073B63",
    "blue_sec":     "#1768AE",
    "blue_light":   "#A8C8E8",
    "blue_deep":    "#1E3A5F",

    # Bordas
    "border":       "#B8D4F3",
    "border_hover": "#1768AE",
    "border_soft":  "#E2E8F0",

    # Status — verde (OK / conciliado)
    "green_ok":     "#16A34A",
    "green_dark":   "#15803D",
    "green_bg":     "#DCFCE7",
    "green_border": "#BBF7D0",
    "green_row":    "#F0FDF4",

    # Status — amarelo/laranja (divergência)
    "warn":         "#D97706",
    "warn_dark":    "#C2410C",
    "warn_text":    "#B45309",
    "warn_bg":      "#FFEDD5",
    "warn_border":  "#FED7AA",
    "warn_row":     "#FFFBEB",
    "warn_alt":     "#FFF8E1",

    # Aliases (compatibilidade)
    "yellow":       "#D97706",
    "yellow_bg":    "#FEF3C7",

    # Status — vermelho (inconsistência)
    "red_err":      "#E31B23",
    "red_dark":     "#B91C1C",
    "red_bg":       "#FEE2E2",
    "red_border":   "#FECACA",
    "red_row":      "#FEF2F2",

    # Texto
    "text_main":    "#0F172A",
    "text_sec":     "#475569",
    "text_light":   "#94A3B8",
    "text_muted":   "#64748B",
    "white":        "#FFFFFF",
}

# ─── Tipografia ──────────────────────────────────────────────────
FONT_FAMILY = "Segoe UI"

FONT = {
    "xs":     (FONT_FAMILY, 10),
    "sm":     (FONT_FAMILY, 11),
    "base":   (FONT_FAMILY, 12),
    "md":     (FONT_FAMILY, 13),
    "lg":     (FONT_FAMILY, 14),
    "xl":     (FONT_FAMILY, 16),
    "2xl":    (FONT_FAMILY, 20),
    "3xl":    (FONT_FAMILY, 22),
    "4xl":    (FONT_FAMILY, 28),
    "5xl":    (FONT_FAMILY, 36),

    "xs_b":   (FONT_FAMILY, 10, "bold"),
    "sm_b":   (FONT_FAMILY, 11, "bold"),
    "base_b": (FONT_FAMILY, 12, "bold"),
    "md_b":   (FONT_FAMILY, 13, "bold"),
    "lg_b":   (FONT_FAMILY, 14, "bold"),
    "xl_b":   (FONT_FAMILY, 16, "bold"),
    "2xl_b": (FONT_FAMILY, 20, "bold"),
    "3xl_b": (FONT_FAMILY, 22, "bold"),
}

# ─── Raio / Espaçamento ──────────────────────────────────────────
RADIUS = {
    "sm":   6,
    "base": 10,
    "md":   12,
    "lg":   14,
    "xl":   20,
}

SPACING = {
    "xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 20, "2xl": 24,
}

# ─── Metadados ───────────────────────────────────────────────────
APP_NAME    = "REMESSA × BANCO"
APP_VERSION = "3.0.0"
APP_TAGLINE = "Conciliação inteligente entre Excel do sistema e Excel do banco"

# ─── Estados de Badge (header) ───────────────────────────────────
BADGE_STATES = {
    "neutral":    {"text": "  AGUARDANDO  ",      "fg": "#1E3A5F", "color": "#94A3B8"},
    "processing": {"text": "  ⏳ PROCESSANDO...  ", "fg": "#1768AE", "color": "#FFFFFF"},
    "ok":         {"text": "  ✅  TUDO OK  ",      "fg": "#16A34A", "color": "#FFFFFF"},
    "warn":       {"text": "  ⚠  DIVERGÊNCIAS  ", "fg": "#D97706", "color": "#FFFFFF"},
    "err":        {"text": "  ❌  INCONSISTÊNCIAS ", "fg": "#E31B23", "color": "#FFFFFF"},
    "mixed":      {"text": "  ⚠  ATENÇÃO  ",      "fg": "#D97706", "color": "#FFFFFF"},
}
