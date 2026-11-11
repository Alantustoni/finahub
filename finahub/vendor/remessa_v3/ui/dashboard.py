"""
Dashboard de métricas e Status por Dia.

Estrutura:
  - 2 cards de totais (Banco / Sistema)
  - 3 cards de status (Conciliados / Divergências / Inconsistências)
  - Grid de cards por dia (verde/amarelo/vermelho)
"""

import customtkinter as ctk

from core.theme import COLORS, FONT, RADIUS
from core.utils import format_brl
from services    import ResultadoConciliacao, DayStatus
from .widgets    import PremiumCard


# ═════════════════════════════════════════════════════════════════
# CARD DE STATUS COM PERCENTUAL
# ═════════════════════════════════════════════════════════════════
class StatusMetricCard(ctk.CTkFrame):
    """
    Card avançado de status (verde/amarelo/vermelho) com:
      - ícone colorido
      - badge de percentual
      - número grande
      - label e descrição
    """

    STATE_CONFIG = {
        "ok": {
            "border":  COLORS["green_ok"],
            "icon_bg": COLORS["green_bg"],
            "icon_fg": COLORS["green_dark"],
            "label_fg": COLORS["green_dark"],
            "icon": "✓",
        },
        "warn": {
            "border":  COLORS["yellow"],
            "icon_bg": "#FFEDD5",
            "icon_fg": "#C2410C",
            "label_fg": "#C2410C",
            "icon": "⚠",
        },
        "err": {
            "border":  COLORS["red_err"],
            "icon_bg": COLORS["red_bg"],
            "icon_fg": COLORS["red_dark"],
            "label_fg": COLORS["red_dark"],
            "icon": "✕",
        },
    }

    def __init__(self, master, state: str, label: str, desc: str, **kw):
        cfg = self.STATE_CONFIG[state]

        super().__init__(
            master,
            fg_color=COLORS["bg_card"],
            border_color=cfg["border"],
            border_width=1,
            corner_radius=RADIUS["lg"],
            **kw,
        )

        self.grid_columnconfigure(0, weight=1)

        # Linha superior: ícone + %
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, padx=18, pady=(16, 10), sticky="ew")
        top.grid_columnconfigure(1, weight=1)

        self._icon_lbl = ctk.CTkLabel(
            top, text=cfg["icon"], font=FONT["xl_b"],
            fg_color=cfg["icon_bg"], text_color=cfg["icon_fg"],
            corner_radius=RADIUS["base"], width=38, height=38,
        )
        self._icon_lbl.grid(row=0, column=0, sticky="w")

        self._pct_lbl = ctk.CTkLabel(
            top, text="—",
            font=FONT["xs_b"], text_color=COLORS["text_muted"],
            fg_color="#F8FAFC", corner_radius=RADIUS["sm"],
            padx=8, pady=2,
        )
        self._pct_lbl.grid(row=0, column=2, sticky="e")

        # Número grande
        self._count_lbl = ctk.CTkLabel(
            self, text="—", font=FONT["4xl"], text_color=COLORS["text_main"],
        )
        self._count_lbl.grid(row=1, column=0, padx=18, pady=(0, 4), sticky="w")

        # Label
        self._label_lbl = ctk.CTkLabel(
            self, text=label, font=FONT["md_b"], text_color=cfg["label_fg"],
        )
        self._label_lbl.grid(row=2, column=0, padx=18, pady=(0, 2), sticky="w")

        # Descrição
        ctk.CTkLabel(
            self, text=desc, font=FONT["xs"], text_color=COLORS["text_muted"],
            wraplength=220, justify="left",
        ).grid(row=3, column=0, padx=18, pady=(0, 14), sticky="w")

    def update_count(self, count: int, pct: int):
        self._count_lbl.configure(text=str(count))
        self._pct_lbl.configure(text=f"{pct}%")

    def reset(self):
        self._count_lbl.configure(text="—")
        self._pct_lbl.configure(text="—%")


# ═════════════════════════════════════════════════════════════════
# DASHBOARD COMPLETO (totais + status)
# ═════════════════════════════════════════════════════════════════
class MetricsDashboard(ctk.CTkFrame):
    """Dashboard de métricas: 3 cards de status."""

    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.grid_columnconfigure(0, weight=1)
        self._build_status()

    def _build_status(self):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=0, column=0, sticky="ew")
        for i in range(3):
            row.grid_columnconfigure(i, weight=1)

        self.s_ok = StatusMetricCard(
            row, state="ok", label="Conciliados",
            desc="Match perfeito · data e valor idênticos",
        )
        self.s_warn = StatusMetricCard(
            row, state="warn", label="Divergências",
            desc="Possível par no banco · verificar manualmente",
        )
        self.s_err = StatusMetricCard(
            row, state="err", label="Inconsistências",
            desc="Não encontrado · investigar no banco",
        )
        self.s_ok.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.s_warn.grid(row=0, column=1, padx=6, sticky="ew")
        self.s_err.grid(row=0, column=2, padx=(6, 0), sticky="ew")

    def reset(self):
        self.s_ok.reset()
        self.s_warn.reset()
        self.s_err.reset()

    def render(self, r: ResultadoConciliacao):
        self.s_ok.update_count(r.qtd_conciliados,      r.pct(r.qtd_conciliados))
        self.s_warn.update_count(r.qtd_divergencias,   r.pct(r.qtd_divergencias))
        self.s_err.update_count(r.qtd_inconsistencias, r.pct(r.qtd_inconsistencias))


# ═════════════════════════════════════════════════════════════════
# CARD DE UM DIA
# ═════════════════════════════════════════════════════════════════
class DayCard(ctk.CTkFrame):
    """Card individual de status de um dia (verde / amarelo / vermelho)."""

    STATE_CONFIG = {
        "ok": {
            "border": COLORS["green_ok"],
            "bg":     COLORS["green_bg"],
            "fg":     COLORS["green_dark"],
            "icon":   "✅",
        },
        "warn": {
            "border": COLORS["yellow"],
            "bg":     "#FFFBEB",
            "fg":     "#C2410C",
            "icon":   "⚠️",
        },
        "err": {
            "border": COLORS["red_err"],
            "bg":     COLORS["red_bg"],
            "fg":     COLORS["red_dark"],
            "icon":   "❌",
        },
    }

    def __init__(self, master, status: DayStatus, **kw):
        cfg = self.STATE_CONFIG[status.status_cor]

        super().__init__(
            master,
            fg_color=cfg["bg"],
            border_color=cfg["border"],
            border_width=1,
            corner_radius=RADIUS["md"],
            **kw,
        )

        # Ícone grande centralizado
        ctk.CTkLabel(self, text=cfg["icon"], font=FONT["4xl"]).pack(pady=(14, 4))

        # Nome do dia
        ctk.CTkLabel(
            self, text=status.dia_semana, font=FONT["md_b"], text_color=cfg["fg"],
        ).pack()

        # Data
        ctk.CTkLabel(
            self, text=status.data, font=FONT["sm"], text_color=COLORS["text_muted"],
        ).pack(pady=(2, 8))

        # Separador
        ctk.CTkFrame(self, height=1, fg_color=cfg["border"]).pack(fill="x", padx=16, pady=(0, 8))

        # Valor total
        ctk.CTkLabel(
            self, text=format_brl(status.valor_total),
            font=FONT["base_b"], text_color=COLORS["text_main"],
        ).pack()

        # Quantidade
        ctk.CTkLabel(
            self, text=f"{status.qtd_total} pagamentos",
            font=FONT["xs"], text_color=COLORS["text_muted"],
        ).pack(pady=(0, 4))

        # Atenções (se houver) — mesma altura sempre
        if not status.ok:
            partes = []
            if status.qtd_divergencias > 0:
                partes.append(f"{status.qtd_divergencias} div.")
            if status.qtd_inconsistencias > 0:
                partes.append(f"{status.qtd_inconsistencias} inc.")
            ctk.CTkLabel(
                self, text=" · ".join(partes), font=FONT["xs_b"],
                text_color=cfg["fg"],
            ).pack(pady=(2, 14))
        else:
            ctk.CTkLabel(
                self, text="OK", font=FONT["xs_b"],
                text_color=cfg["fg"],
            ).pack(pady=(2, 14))


# ═════════════════════════════════════════════════════════════════
# GRID DE DIAS
# ═════════════════════════════════════════════════════════════════
class DayStatusGrid(ctk.CTkFrame):
    """Grid de DayCards (até 5 colunas — semana útil)."""

    MAX_COLS = 5

    def __init__(self, master, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._show_empty()

    def _show_empty(self):
        for w in self.winfo_children():
            w.destroy()
        ctk.CTkLabel(
            self, text="Nenhum arquivo processado ainda.",
            font=FONT["sm"], text_color=COLORS["text_light"],
        ).pack(pady=16)

    def render(self, status_por_dia: dict[str, DayStatus]):
        for w in self.winfo_children():
            w.destroy()

        if not status_por_dia:
            self._show_empty()
            return

        for i, st in enumerate(status_por_dia.values()):
            card = DayCard(self, st)
            card.grid(row=i // self.MAX_COLS, column=i % self.MAX_COLS,
                      padx=6, pady=6, sticky="nsew")
            self.grid_columnconfigure(i % self.MAX_COLS, weight=1)

    def reset(self):
        self._show_empty()
