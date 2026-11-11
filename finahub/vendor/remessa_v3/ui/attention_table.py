"""
Tabela de Pontos de Atenção.

Mostra:
  - Divergências (amarelas) — com sugestão do banco
  - Inconsistências (vermelhas)
  - Conciliados ocultos com botão "Mostrar conciliados"

Recursos:
  - Ordenação clicável em cada coluna
  - Busca em tempo real (fornecedor, valor, motivo)
  - Banner informativo
"""

import customtkinter as ctk

from core.theme  import COLORS, FONT, RADIUS
from core.utils  import format_brl, date_sort_key
from services    import (
    Divergencia, Inconsistencia, Record, ResultadoConciliacao, TipoMotivo,
)
from .widgets    import PremiumCard


# ─── Configuração de colunas ─────────────────────────────────────
# (key, header_label, weight, min_width, align)
# weight controla proporção relativa — soma deve dar o total da tabela
COLUMNS = [
    ("status",     "STATUS",            0, 100, "center"),
    ("data",       "DATA",              0, 95,  "center"),
    ("fornecedor", "FORNECEDOR",        1, 160, "left"),
    ("remessa",    "REMESSA",           0, 85,  "center"),
    ("valor",      "VALOR",             0, 110, "right"),
    ("sugestao",   "SUGESTÃO DO BANCO", 1, 180, "left"),
    ("motivo",     "ANÁLISE",           0, 140, "left"),
]

# Máximo de caracteres antes de truncar com "..."
FORNECEDOR_MAX = 26
SUGESTAO_MAX   = 22


class AttentionTable(PremiumCard):
    """Tabela rica com divergências, inconsistências e toggle de conciliados."""

    SORT_ARROWS = {"asc": "▲", "desc": "▼", None: ""}

    def __init__(self, master, **kw):
        super().__init__(master, hoverable=False, **kw)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        # Estado
        self._resultado: ResultadoConciliacao | None = None
        self._show_conciliados = False
        self._sort_col = "status"
        self._sort_dir = "asc"

        # UI
        self._build_searchbar()     # row 0
        self._build_info_banner()   # row 1
        self._build_alerts_area()   # row 2  ← alertas de remessa
        self._build_header()        # row 3
        self._build_scroll_area()   # row 4

        self._render_empty()

    # ── Barra de busca ───────────────────────────────────────────
    def _build_searchbar(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, padx=12, pady=(12, 8), sticky="ew")
        bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            bar, text="🔍", font=FONT["base"], text_color=COLORS["text_muted"],
        ).grid(row=0, column=0, padx=(2, 6))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._render_rows())

        ctk.CTkEntry(
            bar, textvariable=self._search_var,
            placeholder_text="Buscar por fornecedor, valor, remessa ou motivo...",
            font=FONT["sm"], height=32,
            border_color=COLORS["border"],
            corner_radius=RADIUS["sm"],
        ).grid(row=0, column=1, sticky="ew")

        self._count_lbl = ctk.CTkLabel(
            bar, text="", font=FONT["xs"], text_color=COLORS["text_muted"],
        )
        self._count_lbl.grid(row=0, column=2, padx=(8, 2))

    # ── Banner informativo ───────────────────────────────────────
    def _build_info_banner(self):
        self._info_frame = ctk.CTkFrame(
            self, fg_color=COLORS["bg_main"],
            border_color=COLORS["border"], border_width=1,
            corner_radius=RADIUS["base"],
        )
        self._info_frame.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")
        self._info_frame.grid_columnconfigure(0, weight=1)

        self._info_lbl = ctk.CTkLabel(
            self._info_frame, text="",
            font=FONT["xs"], text_color=COLORS["text_sec"],
            justify="left", anchor="w",
        )
        self._info_lbl.grid(row=0, column=0, padx=14, pady=10, sticky="ew")

        self._toggle_btn = ctk.CTkButton(
            self._info_frame, text="Mostrar conciliados ▾",
            font=FONT["xs_b"], width=170, height=26,
            fg_color=COLORS["blue_main"], hover_color=COLORS["blue_sec"],
            corner_radius=RADIUS["sm"],
            command=self._toggle_conciliados,
        )
        self._toggle_btn.grid(row=0, column=1, padx=(8, 10), pady=8, sticky="e")

    # ── Área de alertas de remessa ───────────────────────────────
    def _build_alerts_area(self):
        """Container para os alertas de remessa ausente. Começa vazio."""
        self._alerts_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._alerts_frame.grid(row=2, column=0, padx=12, pady=(0, 0), sticky="ew")
        self._alerts_frame.grid_columnconfigure(0, weight=1)

    def _render_alerts(self, remessas_ausentes: list[str]):
        """Reconstrói os alertas de remessa ausente."""
        for w in self._alerts_frame.winfo_children():
            w.destroy()

        if not remessas_ausentes:
            self._alerts_frame.grid_remove()
            return

        self._alerts_frame.grid()

        for i, remessa in enumerate(remessas_ausentes):
            # Padding embaixo só no último alerta
            pad_bottom = (6, 8) if i == len(remessas_ausentes) - 1 else (6, 0)

            alert = ctk.CTkFrame(
                self._alerts_frame,
                fg_color="#FFF1F2",
                border_color=COLORS["red_err"],
                border_width=1,
                corner_radius=RADIUS["base"],
            )
            alert.grid(row=i, column=0, pady=pad_bottom, sticky="ew")

            # Conteúdo centralizado com pack
            inner = ctk.CTkFrame(alert, fg_color="transparent")
            inner.pack(fill="x", padx=16, pady=12)

            ctk.CTkLabel(
                inner, text="🚨",
                font=FONT["lg"],
                fg_color="#FEE2E2",
                corner_radius=RADIUS["sm"],
                width=34, height=34,
            ).pack(side="left", padx=(0, 12))

            ctk.CTkLabel(
                inner,
                text=f"REMESSA {remessa} NÃO ENVIADA AO BANCO",
                font=FONT["md_b"],
                text_color=COLORS["red_dark"],
                anchor="w",
            ).pack(side="left", fill="x", expand=True)

    # ── Cabeçalho da tabela ──────────────────────────────────────
    def _build_header(self):
        hf = ctk.CTkFrame(
            self, fg_color=COLORS["blue_main"], corner_radius=RADIUS["base"],
        )
        hf.grid(row=3, column=0, padx=12, sticky="ew")

        # Configura colunas com mesmo weight das linhas
        for i, (_, _, weight, min_w, _) in enumerate(COLUMNS):
            hf.grid_columnconfigure(i, weight=weight, minsize=min_w)

        self._sort_labels: dict[str, ctk.CTkLabel] = {}

        for i, (key, title, weight, min_w, align) in enumerate(COLUMNS):
            anchor = "center" if align == "center" else ("e" if align == "right" else "w")
            lbl = ctk.CTkLabel(
                hf, text=title, font=FONT["sm_b"],
                text_color=COLORS["white"],
                anchor=anchor,
            )
            lbl.grid(row=0, column=i, padx=6, pady=10, sticky="ew")
            self._sort_labels[key] = lbl

            hf.bind("<Button-1>", lambda _e, k=key: self._toggle_sort(k))
            lbl.bind("<Button-1>", lambda _e, k=key: self._toggle_sort(k))

        self._update_sort_indicators()

    # ── Área de scroll ───────────────────────────────────────────
    def _build_scroll_area(self):
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color="transparent", height=300,
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["blue_sec"],
        )
        self._scroll.grid(row=4, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)

    # ── Sorting ──────────────────────────────────────────────────
    def _toggle_sort(self, col: str):
        if self._sort_col == col:
            self._sort_dir = "desc" if self._sort_dir == "asc" else "asc"
        else:
            self._sort_col = col
            self._sort_dir = "asc"
        self._update_sort_indicators()
        self._render_rows()

    def _update_sort_indicators(self):
        for key, lbl in self._sort_labels.items():
            title = next(t for k, t, *_ in COLUMNS if k == key)
            arrow = self.SORT_ARROWS[self._sort_dir] if key == self._sort_col else ""
            lbl.configure(text=f"{title} {arrow}".strip())

    # ── Toggle conciliados ───────────────────────────────────────
    def _toggle_conciliados(self):
        self._show_conciliados = not self._show_conciliados
        if self._show_conciliados:
            self._toggle_btn.configure(text="Ocultar conciliados ▴")
        else:
            self._toggle_btn.configure(text="Mostrar conciliados ▾")
        self._render_rows()

    # ── Render principal ─────────────────────────────────────────
    def render(self, resultado: ResultadoConciliacao):
        self._resultado = resultado
        self._update_info_banner()
        self._render_alerts(resultado.remessas_ausentes)
        self._render_rows()

    def _update_info_banner(self):
        if not self._resultado:
            return
        r = self._resultado
        if r.tudo_ok:
            self._info_lbl.configure(
                text=f"✅ Conciliação perfeita — todos os {r.qtd_conciliados} pagamentos bateram.",
                text_color=COLORS["green_ok"],
            )
            self._toggle_btn.grid_remove() if r.qtd_conciliados == 0 else self._toggle_btn.grid()
        else:
            partes = []
            if r.qtd_divergencias > 0:
                partes.append(f"{r.qtd_divergencias} divergência(s)")
            if r.qtd_inconsistencias > 0:
                partes.append(f"{r.qtd_inconsistencias} inconsistência(s)")
            atencao = " · ".join(partes)
            self._info_lbl.configure(
                text=f"💡 Mostrando {atencao} que precisam de revisão. "
                     f"({r.qtd_conciliados} conciliados ocultos)",
                text_color=COLORS["text_sec"],
            )
            self._toggle_btn.grid()

    # ── Itens unificados pra exibição ────────────────────────────
    def _build_items(self) -> list[dict]:
        """
        Constrói lista unificada de itens pra renderizar.
        Cada item é um dict com: status_text, status_state, record, sugestao_text, motivo_text.
        """
        if not self._resultado:
            return []

        items = []
        r = self._resultado

        # Divergências (amarelas)
        for div in r.divergencias:
            items.append({
                "type":         "warn",
                "status_text":  "⚠ REVER",
                "data":         div.record.data,
                "fornecedor":   div.record.fornecedor,
                "remessa":      div.record.remessa or "—",
                "valor":        div.record.valor,
                "sugestao":     div.sugestao,
                "motivo":       div.motivo.value,
                "motivo_detail": self._format_motivo_detail(div),
            })

        # Inconsistências (vermelhas)
        for inc in r.inconsistencias:
            items.append({
                "type":         "err",
                "status_text":  "✕ ERRO",
                "data":         inc.record.data,
                "fornecedor":   inc.record.fornecedor,
                "remessa":      inc.record.remessa or "—",
                "valor":        inc.record.valor,
                "sugestao":     None,
                "motivo":       "Não encontrado",
                "motivo_detail": "no extrato do banco",
            })

        # Conciliados (verdes) — só se toggle ativo
        if self._show_conciliados:
            for rec in r.conciliados:
                items.append({
                    "type":         "ok",
                    "status_text":  "✓ OK",
                    "data":         rec.data,
                    "fornecedor":   rec.fornecedor,
                    "remessa":      rec.remessa or "—",
                    "valor":        rec.valor,
                    "sugestao":     None,
                    "motivo":       "Conciliado",
                    "motivo_detail": "",
                })

        return items

    def _format_motivo_detail(self, div: Divergencia) -> str:
        """Gera texto secundário do motivo."""
        partes = []
        if abs(div.diff_valor) > 0.005:
            sinal = "+" if div.diff_valor > 0 else "-"
            partes.append(f"Δ {sinal}{format_brl(abs(div.diff_valor))}")
        if div.diff_dias_uteis > 0:
            plural = "s" if div.diff_dias_uteis > 1 else ""
            partes.append(f"+{div.diff_dias_uteis} dia útil{plural}")
        if div.motivo == TipoMotivo.NOME_SIMILAR and div.similaridade < 1.0:
            partes.append(f"sim. {int(div.similaridade * 100)}%")
        return " · ".join(partes) if partes else "valor idêntico"

    # ── Render de linhas ─────────────────────────────────────────
    def _render_rows(self):
        for w in self._scroll.winfo_children():
            w.destroy()

        items = self._build_items()

        # Filtro de busca
        query = self._search_var.get().lower().strip()
        if query:
            items = [
                it for it in items
                if (query in it["fornecedor"].lower() or
                    query in it["remessa"].lower() or
                    query in f"{it['valor']:.2f}".replace(".", ",") or
                    query in it["motivo"].lower() or
                    query in it["data"].lower())
            ]

        # Ordena
        items.sort(key=self._sort_key, reverse=(self._sort_dir == "desc"))

        # Contador
        total_disp = self._get_total_disponivel()
        self._count_lbl.configure(text=f"{len(items)} de {total_disp}" if total_disp else "")

        # Empty states
        if not items:
            if not self._resultado:
                self._render_empty()
                return
            if self._resultado.tudo_ok and not self._show_conciliados:
                self._render_perfect()
                return
            self._render_no_results()
            return

        # Renderiza cada linha direto no grid do scroll
        for ri, item in enumerate(items):
            self._render_row(ri, item)
            # Separador visual entre linhas
            self._scroll.grid_rowconfigure(ri, weight=0)

    def _get_total_disponivel(self) -> int:
        if not self._resultado:
            return 0
        n = self._resultado.qtd_divergencias + self._resultado.qtd_inconsistencias
        if self._show_conciliados:
            n += self._resultado.qtd_conciliados
        return n

    def _sort_key(self, item: dict):
        col = self._sort_col
        if col == "status":
            return {"err": 0, "warn": 1, "ok": 2}.get(item["type"], 99)
        if col == "data":       return (date_sort_key(item["data"]), item["valor"])
        if col == "fornecedor": return item["fornecedor"].lower()
        if col == "remessa":    return item["remessa"].lower()
        if col == "valor":      return item["valor"]
        if col == "sugestao":
            return item["sugestao"].fornecedor.lower() if item["sugestao"] else "zzz"
        if col == "motivo":     return item["motivo"]
        return 0

    # ── Empty states ─────────────────────────────────────────────
    def _render_empty(self):
        ctk.CTkLabel(
            self._scroll,
            text="Selecione os arquivos e clique em Iniciar Conciliação.",
            font=FONT["sm"], text_color=COLORS["text_light"],
        ).grid(row=0, column=0, columnspan=len(COLUMNS), pady=32)

    def _render_perfect(self):
        ctk.CTkLabel(
            self._scroll,
            text="✅  Conciliação perfeita — tudo bateu!",
            font=FONT["lg_b"], text_color=COLORS["green_ok"],
        ).grid(row=0, column=0, columnspan=len(COLUMNS), pady=32)
        ctk.CTkLabel(
            self._scroll,
            text="Use o botão acima para visualizar os conciliados.",
            font=FONT["sm"], text_color=COLORS["text_muted"],
        ).grid(row=1, column=0, columnspan=len(COLUMNS), pady=(0, 24))

    def _render_no_results(self):
        ctk.CTkLabel(
            self._scroll, text="Nenhum resultado para a busca.",
            font=FONT["sm"], text_color=COLORS["text_light"],
        ).grid(row=0, column=0, columnspan=len(COLUMNS), pady=24)

    # ── Render de UMA linha ──────────────────────────────────────
    ROW_BG = {
        "ok":   ("#F0FDF4", "#F7FEF9"),
        "warn": ("#FFFBEB", "#FFFEF6"),
        "err":  ("#FEF2F2", "#FFF8F8"),
    }
    STATUS_COLORS = {
        "ok":   (COLORS["green_dark"], COLORS["green_bg"]),
        "warn": ("#C2410C", "#FFEDD5"),
        "err":  (COLORS["red_dark"], COLORS["red_bg"]),
    }

    def _render_row(self, ri: int, item: dict):
        bg = self.ROW_BG[item["type"]][ri % 2]

        # Frame da linha ocupa toda a largura do scroll
        rf = ctk.CTkFrame(self._scroll, fg_color=bg, corner_radius=0)
        rf.grid(row=ri, column=0, columnspan=len(COLUMNS), padx=0, pady=0, sticky="ew")

        # Configura colunas do frame com os mesmos weights do header
        for i, (_, _, weight, min_w, _) in enumerate(COLUMNS):
            rf.grid_columnconfigure(i, weight=weight, minsize=min_w)

        PADX = 6

        # ── 1) STATUS ────────────────────────────────────────────
        text_color, badge_bg = self.STATUS_COLORS[item["type"]]
        status_frame = ctk.CTkFrame(rf, fg_color=bg)
        status_frame.grid(row=0, column=0, padx=PADX, pady=10, sticky="ew")
        status_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            status_frame, text=item["status_text"],
            font=FONT["xs_b"], text_color=text_color,
            fg_color=badge_bg, corner_radius=RADIUS["xl"],
            padx=8, pady=3, anchor="center",
        ).grid(row=0, column=0, sticky="")

        # ── 2) DATA ──────────────────────────────────────────────
        ctk.CTkLabel(
            rf, text=item["data"],
            font=FONT["sm"], text_color=COLORS["text_sec"],
            fg_color=bg, anchor="center",
        ).grid(row=0, column=1, padx=PADX, pady=10, sticky="ew")

        # ── 3) FORNECEDOR ────────────────────────────────────────
        forn = item["fornecedor"]
        forn_display = (forn[:FORNECEDOR_MAX] + "…") if len(forn) > FORNECEDOR_MAX else forn
        ctk.CTkLabel(
            rf, text=forn_display,
            font=FONT["sm_b"], text_color=COLORS["text_main"],
            fg_color=bg, anchor="w",
        ).grid(row=0, column=2, padx=PADX, pady=10, sticky="ew")

        # ── 4) REMESSA ───────────────────────────────────────────
        remessa = item["remessa"]
        rem_frame = ctk.CTkFrame(rf, fg_color=bg)
        rem_frame.grid(row=0, column=3, padx=PADX, pady=10, sticky="ew")
        rem_frame.grid_columnconfigure(0, weight=1)

        if remessa and remessa != "—":
            ctk.CTkLabel(
                rem_frame, text=remessa,
                font=FONT["xs_b"], text_color=COLORS["white"],
                fg_color=COLORS["blue_sec"], corner_radius=RADIUS["sm"],
                padx=8, pady=3, anchor="center",
            ).grid(row=0, column=0, sticky="")
        else:
            ctk.CTkLabel(
                rem_frame, text="—", font=FONT["xs"],
                text_color=COLORS["text_light"],
                fg_color=bg, anchor="center",
            ).grid(row=0, column=0, sticky="ew")

        # ── 5) VALOR ─────────────────────────────────────────────
        valor_color = (
            COLORS["green_dark"] if item["type"] == "ok" else
            "#C2410C"            if item["type"] == "warn" else
            COLORS["red_dark"]
        )
        ctk.CTkLabel(
            rf, text=format_brl(item["valor"]),
            font=FONT["sm_b"], text_color=valor_color,
            fg_color=bg, anchor="e",
        ).grid(row=0, column=4, padx=PADX, pady=10, sticky="ew")

        # ── 6) SUGESTÃO DO BANCO ─────────────────────────────────
        sugestao = item["sugestao"]
        if sugestao:
            sug_nome = sugestao.fornecedor
            sug_display = (sug_nome[:SUGESTAO_MAX] + "…") if len(sug_nome) > SUGESTAO_MAX else sug_nome
            sug_frame = ctk.CTkFrame(
                rf, fg_color=COLORS["white"],
                border_color="#FED7AA" if item["type"] == "warn" else COLORS["border"],
                border_width=1, corner_radius=RADIUS["sm"],
            )
            sug_frame.grid(row=0, column=5, padx=PADX, pady=6, sticky="ew")
            ctk.CTkLabel(
                sug_frame, text=f"🏛 {sug_display}",
                font=FONT["xs_b"], text_color=COLORS["text_main"], anchor="w",
            ).pack(padx=8, pady=(4, 0), anchor="w")
            ctk.CTkLabel(
                sug_frame,
                text=f"{sugestao.data} · {format_brl(sugestao.valor)}",
                font=FONT["xs"], text_color=COLORS["text_muted"], anchor="w",
            ).pack(padx=8, pady=(0, 4), anchor="w")
        else:
            empty_text = "—" if item["type"] == "ok" else "Nenhum candidato"
            ctk.CTkLabel(
                rf, text=empty_text, font=FONT["xs"],
                text_color=COLORS["text_light"],
                fg_color=bg, anchor="w",
            ).grid(row=0, column=5, padx=PADX, pady=10, sticky="ew")

        # ── 7) ANÁLISE ───────────────────────────────────────────
        motivo_color = (
            COLORS["green_dark"] if item["type"] == "ok" else
            "#C2410C"            if item["type"] == "warn" else
            COLORS["red_dark"]
        )
        motivo_frame = ctk.CTkFrame(rf, fg_color=bg)
        motivo_frame.grid(row=0, column=6, padx=PADX, pady=10, sticky="ew")

        ctk.CTkLabel(
            motivo_frame, text=item["motivo"],
            font=FONT["sm_b"], text_color=motivo_color, anchor="w",
        ).pack(anchor="w")

        if item["motivo_detail"]:
            ctk.CTkLabel(
                motivo_frame, text=item["motivo_detail"],
                font=FONT["xs"], text_color=COLORS["text_muted"], anchor="w",
            ).pack(anchor="w")

    # ── Reset ────────────────────────────────────────────────────
    def reset(self):
        self._resultado = None
        self._search_var.set("")
        self._show_conciliados = False
        self._toggle_btn.configure(text="Mostrar conciliados ▾")
        self._info_lbl.configure(
            text="Aguardando conciliação...",
            text_color=COLORS["text_muted"],
        )
        self._count_lbl.configure(text="")
        self._render_alerts([])
        self._render_rows()
