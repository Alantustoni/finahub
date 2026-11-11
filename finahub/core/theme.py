"""
theme.py — Identidade visual do ALAN: "Grafite e verde" (escolhida em 30/10/2026).

Menu grafite, fundo cinza-pedra claro, cartões brancos com borda suave e
verde-esmeralda como cor de destaque (botões principais, item ativo, passo
atual). A tela Remessa × Banco (motor original) recebe a mesma paleta em
view_remessa.py.

Os NOMES das constantes ficaram os antigos (AZUL, AZUL_ESCURO…) para não
mexer nas telas: AZUL agora é o verde de destaque e AZUL_ESCURO o grafite.

Todas as cores moram aqui; nenhuma view define cor solta.
"""

# ── Menu lateral (grafite) ──────────────────────────────────────────
SIDEBAR_BG        = "#1F2937"
SIDEBAR_ITEM      = "#D1D5DB"   # texto dos itens
SIDEBAR_HOVER     = "#2C3748"
SIDEBAR_ATIVO     = "#047857"   # item ativo (verde)
SIDEBAR_ATIVO_TX  = "#FFFFFF"
SIDEBAR_RODAPE    = "#9CA3AF"   # rótulos de grupo e rodapé
SIDEBAR_BORDA     = "#2C3748"

# ── Superfícies ─────────────────────────────────────────────────────
FUNDO         = "#F5F5F4"
CARD          = "#FFFFFF"
BORDA         = "#E7E5E4"
ZEBRA         = "#FAFAF9"
TRACK         = "#E7E5E4"
CAMPO         = "#FAFAF9"   # fundo de caixas de texto grandes

# ── Tinta (texto) ───────────────────────────────────────────────────
INK           = "#1C1917"
INK_2         = "#57534E"
INK_3         = "#78716C"
BRANCO        = "#FFFFFF"

# ── Destaque e estados ──────────────────────────────────────────────
AZUL          = "#047857"   # destaque (verde-esmeralda): botões, ativo
AZUL_HOVER    = "#065F46"
AZUL_ESCURO   = "#1F2937"   # grafite: cabeçalho de tabela, títulos de seção
AZUL_CLARO    = "#10B981"
NEUTRO        = "#374151"   # badges "info"
NEUTRO_BG     = "#F3F4F6"

VERDE         = "#15803D"
VERDE_BG      = "#DCFCE7"
AMARELO       = "#B45309"
AMARELO_BG    = "#FEF3C7"
VERMELHO      = "#B91C1C"
VERMELHO_BG   = "#FEE2E2"
INFO_BG       = "#ECFDF5"   # hover suave (verde bem claro)

# retrocompatibilidade com nomes antigos usados nas views
FUNDO_SIDEBAR_ITEM = SIDEBAR_HOVER

# ── Tipografia ──────────────────────────────────────────────────────
FONTE         = "Segoe UI"
F_TITULO      = (FONTE, 24, "bold")
F_SUBTITULO   = (FONTE, 13)
F_SECAO       = (FONTE, 15, "bold")
F_CARD_LABEL  = (FONTE, 11, "bold")
F_CARD_VALOR  = (FONTE, 26, "bold")
F_NORMAL      = (FONTE, 13)
F_PEQUENA     = (FONTE, 11)
F_BOTAO       = (FONTE, 13, "bold")
F_NAV         = (FONTE, 13)
F_NAV_GRUPO   = (FONTE, 10, "bold")
F_MONO        = ("Consolas", 11)
F_CRUMB       = (FONTE, 10)

# ── Métricas de layout ──────────────────────────────────────────────
RAIO          = 12          # cartões
RAIO_BTN      = 9           # botões
RAIO_PILL     = 16          # badges/pílulas
FILETE_W      = 4           # filete colorido à esquerda dos cards KPI
SIDEBAR_W     = 236

# ── Escala de espaçamento ───────────────────────────────────────────
ESP = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "2xl": 32}
PAD           = ESP["lg"]
PAD_G         = ESP["xl"]

STATUS_CORES = {
    "ok":   (VERDE,    VERDE_BG),
    "warn": (AMARELO,  AMARELO_BG),
    "err":  (VERMELHO, VERMELHO_BG),
    "info": (NEUTRO,   NEUTRO_BG),
}
