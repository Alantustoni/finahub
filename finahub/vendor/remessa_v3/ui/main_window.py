"""
Janela principal — orquestra todos os componentes da UI.
"""

import customtkinter as ctk
import threading
import queue
from pathlib import Path
from tkinter import filedialog, messagebox
from datetime import datetime

from core.theme   import COLORS, FONT, RADIUS, APP_NAME, APP_VERSION, APP_TAGLINE
from core.logger  import log, log_path, log_exception
from core.session import Session

from services import (
    parse_banco, parse_sistema, reconciliar,
    exportar_relatorio, ResultadoConciliacao, ExcelReadError,
)

from .widgets         import PremiumButton, FileDropZone, SectionTitle, StatusBadge
from .dashboard       import MetricsDashboard, DayStatusGrid
from .attention_table import AttentionTable


class RemessaBancoApp(ctk.CTk):
    """Aplicação principal."""

    WIDTH  = 1180
    HEIGHT = 860

    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("light")

        self.session    = Session()
        self.resultado: ResultadoConciliacao | None = None
        self._banco_files: list[str]   = []
        self._sistema_files: list[str] = []
        self._queue: queue.Queue       = queue.Queue()

        self._setup_window()
        self._build_ui()
        self._bind_shortcuts()
        self._poll_queue()

        log.info(f"{APP_NAME} v{APP_VERSION} iniciado.")

    # ── Configuração da janela ────────────────────────────────────
    def _setup_window(self):
        self.title(f"{APP_NAME} — Conciliação Bancária")
        self.minsize(1000, 720)
        self.configure(fg_color=COLORS["bg_main"])
        self.resizable(True, True)

        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y = (sw - self.WIDTH) // 2, max(0, (sh - self.HEIGHT) // 2 - 20)
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

    def _bind_shortcuts(self):
        self.bind("<Control-o>",  lambda _e: self._zone_sistema._open_dialog())
        self.bind("<Control-O>",  lambda _e: self._zone_sistema._open_dialog())
        self.bind("<Control-l>",  lambda _e: self._clear())
        self.bind("<Control-L>",  lambda _e: self._clear())
        self.bind("<F5>",         lambda _e: self._start_reconciliation())
        self.bind("<Escape>",     lambda _e: self._confirm_exit())

    def _confirm_exit(self):
        if messagebox.askyesno("Sair", "Deseja fechar o sistema?", icon="question"):
            log.info("Aplicação encerrada pelo usuário.")
            self.destroy()

    # ═════════════════════════════════════════════════════════════
    # CONSTRUÇÃO DA UI
    # ═════════════════════════════════════════════════════════════
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_topbar()
        self._build_header()
        self._build_main_content()
        self._build_statusbar()

    def _build_topbar(self):
        bar = ctk.CTkFrame(
            self, fg_color=COLORS["bg_topbar"], height=36, corner_radius=0,
        )
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        bar.grid_propagate(False)

        ctk.CTkLabel(
            bar, text=f"  {APP_NAME}  v{APP_VERSION}",
            font=FONT["sm_b"], text_color=COLORS["blue_main"],
        ).grid(row=0, column=0, padx=12, pady=6, sticky="w")

        ctk.CTkLabel(
            bar, text="Ctrl+O: Abrir Sistema  |  F5: Conciliar  |  "
                      "Ctrl+L: Limpar  |  Esc: Fechar",
            font=FONT["xs"], text_color=COLORS["text_sec"],
        ).grid(row=0, column=1, padx=4, pady=6, sticky="w")

        bf = ctk.CTkFrame(bar, fg_color="transparent")
        bf.grid(row=0, column=2, padx=8, pady=4, sticky="e")

        ctk.CTkButton(
            bf, text="─", width=28, height=22, fg_color="transparent",
            hover_color="#C8DCEF", text_color=COLORS["blue_main"],
            corner_radius=RADIUS["sm"], command=self.iconify,
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            bf, text="✕", width=28, height=22, fg_color="transparent",
            hover_color=COLORS["red_bg"], text_color=COLORS["red_err"],
            corner_radius=RADIUS["sm"], command=self._confirm_exit,
        ).pack(side="left", padx=2)

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=COLORS["blue_main"], corner_radius=0)
        hdr.grid(row=1, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            hdr, text="🏦", font=FONT["5xl"],
        ).grid(row=0, column=0, padx=(28, 14), pady=20)

        tf = ctk.CTkFrame(hdr, fg_color="transparent")
        tf.grid(row=0, column=1, sticky="w", pady=20)

        ctk.CTkLabel(
            tf, text=APP_NAME, font=FONT["3xl_b"], text_color=COLORS["white"],
        ).pack(anchor="w")

        ctk.CTkLabel(
            tf, text=APP_TAGLINE, font=FONT["base"],
            text_color=COLORS["blue_light"],
        ).pack(anchor="w", pady=(2, 0))

        sf = ctk.CTkFrame(hdr, fg_color="transparent")
        sf.grid(row=0, column=2, padx=28, pady=20, sticky="e")

        self._badge = StatusBadge(sf, text="  AGUARDANDO  ", state="neutral")
        self._badge.pack()

    def _build_main_content(self):
        self._scroll = ctk.CTkScrollableFrame(
            self, fg_color=COLORS["bg_main"],
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["blue_sec"],
        )
        self._scroll.grid(row=2, column=0, sticky="nsew")
        self._scroll.grid_columnconfigure(0, weight=1)

        r = 0
        r = self._build_import_section(r)
        r = self._build_dashboard_section(r)
        r = self._build_days_section(r)
        r = self._build_table_section(r)

    # ── Seção de importação ──────────────────────────────────────
    def _build_import_section(self, r: int) -> int:
        SectionTitle(self._scroll, "📥  Importar Arquivos").grid(
            row=r, column=0, padx=20, pady=(20, 6), sticky="ew",
        )
        r += 1

        fr = ctk.CTkFrame(self._scroll, fg_color="transparent")
        fr.grid(row=r, column=0, padx=20, pady=(4, 0), sticky="ew")
        fr.grid_columnconfigure(0, weight=1)
        fr.grid_columnconfigure(1, weight=1)
        r += 1

        initial = self.session.last_dir

        self._zone_banco = FileDropZone(
            fr, "🏛  Excel do BANCO",
            "1 arquivo (.xls / .xlsx)",
            on_select=self._on_banco_selected,
            multi=False, initial_dir=initial,
        )
        self._zone_banco.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self._zone_sistema = FileDropZone(
            fr, "💼  Excel do SISTEMA",
            "1 a 5 arquivos — cada um representa um dia da semana",
            on_select=self._on_sistema_selected,
            multi=True, initial_dir=initial,
        )
        self._zone_sistema.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        bf = ctk.CTkFrame(self._scroll, fg_color="transparent")
        bf.grid(row=r, column=0, padx=20, pady=16, sticky="ew")
        bf.grid_columnconfigure(0, weight=1)
        r += 1

        self._btn_run = PremiumButton(
            bf, text="▶  Iniciar Conciliação",
            command=self._start_reconciliation, width=240,
        )
        self._btn_run.grid(row=0, column=1, padx=(8, 0))

        PremiumButton(
            bf, text="↺  Limpar", command=self._clear,
            fg_color="#64748B", hover_color="#475569", width=120,
        ).grid(row=0, column=2, padx=(8, 0))

        return r

    # ── Dashboard ────────────────────────────────────────────────
    def _build_dashboard_section(self, r: int) -> int:
        SectionTitle(self._scroll, "📊  Visão Geral").grid(
            row=r, column=0, padx=20, pady=(20, 6), sticky="ew",
        )
        r += 1

        self._dashboard = MetricsDashboard(self._scroll)
        self._dashboard.grid(row=r, column=0, padx=20, pady=(4, 0), sticky="ew")
        r += 1

        return r

    # ── Status por dia ───────────────────────────────────────────
    def _build_days_section(self, r: int) -> int:
        SectionTitle(self._scroll, "📆  Status por Dia").grid(
            row=r, column=0, padx=20, pady=(20, 6), sticky="ew",
        )
        r += 1

        self._days_grid = DayStatusGrid(self._scroll)
        self._days_grid.grid(row=r, column=0, padx=20, pady=(4, 0), sticky="ew")
        r += 1

        return r

    # ── Tabela ───────────────────────────────────────────────────
    def _build_table_section(self, r: int) -> int:
        sf = ctk.CTkFrame(self._scroll, fg_color="transparent")
        sf.grid(row=r, column=0, padx=20, pady=(20, 4), sticky="ew")
        sf.grid_columnconfigure(0, weight=1)
        r += 1

        ctk.CTkLabel(
            sf, text="⚠️  Pontos de Atenção",
            font=FONT["lg_b"], text_color=COLORS["blue_main"],
        ).grid(row=0, column=0, sticky="w")

        self._btn_export = PremiumButton(
            sf, text="📥  Exportar Excel", command=self._export,
            fg_color=COLORS["green_ok"], hover_color=COLORS["green_dark"],
            width=180,
        )
        self._btn_export.grid(row=0, column=1)
        self._btn_export.configure(state="disabled")

        self._table = AttentionTable(self._scroll)
        self._table.grid(row=r, column=0, padx=20, pady=(4, 24), sticky="nsew")
        r += 1

        return r

    # ── Statusbar ────────────────────────────────────────────────
    def _build_statusbar(self):
        sb = ctk.CTkFrame(
            self, fg_color=COLORS["bg_topbar"], height=30, corner_radius=0,
        )
        sb.grid(row=3, column=0, sticky="ew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)

        self._status_lbl = ctk.CTkLabel(
            sb, text="  Pronto. Selecione os arquivos.",
            font=FONT["xs"], text_color=COLORS["text_sec"],
        )
        self._status_lbl.grid(row=0, column=0, padx=12, sticky="w")

        self._progress = ctk.CTkProgressBar(
            sb, width=140, height=6,
            fg_color=COLORS["border"], progress_color=COLORS["blue_sec"],
            corner_radius=RADIUS["sm"],
        )
        self._progress.grid(row=0, column=1, padx=12)
        self._progress.set(0)

    # ═════════════════════════════════════════════════════════════
    # CALLBACKS
    # ═════════════════════════════════════════════════════════════
    def _on_banco_selected(self, files: list[str]):
        self._banco_files = files
        if files:
            self.session.last_dir = str(Path(files[0]).parent)
        self.session.set("last_banco", files)

    def _on_sistema_selected(self, files: list[str]):
        self._sistema_files = files
        if files:
            self.session.last_dir = str(Path(files[0]).parent)
        self.session.set("last_sistema", files)

    def _set_status(self, text: str):
        self._status_lbl.configure(text=f"  {text}")

    def _clear(self):
        self._banco_files = []
        self._sistema_files = []
        self._zone_banco.clear()
        self._zone_sistema.clear()
        self._dashboard.reset()
        self._days_grid.reset()
        self._table.reset()
        self.resultado = None
        self._btn_export.configure(state="disabled")
        self._badge.update_state("  AGUARDANDO  ", "neutral")
        self._set_status("Tudo limpo. Selecione os arquivos.")
        self._progress.set(0)

    # ═════════════════════════════════════════════════════════════
    # MOTOR DE CONCILIAÇÃO (com threading)
    # ═════════════════════════════════════════════════════════════
    def _start_reconciliation(self):
        if not self._banco_files:
            messagebox.showwarning("Atenção", "Selecione o arquivo do Banco.")
            return
        if not self._sistema_files:
            messagebox.showwarning("Atenção", "Selecione ao menos um arquivo do Sistema.")
            return

        self._btn_run.configure(state="disabled", text="⏳  Processando...")
        self._btn_export.configure(state="disabled")
        self._progress.set(0)
        self._badge.update_state("  PROCESSANDO...  ", "processing")
        self._set_status("Iniciando conciliação...")

        # Desabilita cliques nas dropzones durante processamento
        for zone in (self._zone_banco, self._zone_sistema):
            for w in (zone._drop, zone._icon, zone._hint):
                try:
                    w.unbind("<Button-1>")
                except Exception:
                    pass

        threading.Thread(target=self._reconciliation_thread, daemon=True).start()

    def _reconciliation_thread(self):
        try:
            self._queue.put(("progress", 0.1))
            self._queue.put(("status", "Lendo Excel do Banco..."))

            banco_records = parse_banco(self._banco_files[0])

            self._queue.put(("progress", 0.35))
            self._queue.put(("status", "Lendo Excel(s) do Sistema..."))

            sistema_records = []
            for i, fp in enumerate(self._sistema_files):
                recs = parse_sistema(fp)
                sistema_records.extend(recs)
                pct = 0.35 + 0.35 * (i + 1) / len(self._sistema_files)
                self._queue.put(("progress", pct))

            self._queue.put(("status", "Conciliando registros (3 passadas)..."))
            self._queue.put(("progress", 0.85))

            resultado = reconciliar(sistema_records, banco_records)

            self._queue.put(("progress", 1.0))
            self._queue.put(("resultado", resultado))

        except ExcelReadError as e:
            self._queue.put(("error_friendly", str(e)))
        except Exception as e:
            log_exception("Erro na conciliação", e)
            self._queue.put(("error", f"{e}\n\nVer log em:\n{log_path()}"))

    def _poll_queue(self):
        try:
            while True:
                kind, data = self._queue.get_nowait()
                if   kind == "progress":         self._progress.set(data)
                elif kind == "status":           self._set_status(data)
                elif kind == "resultado":        self._apply_result(data)
                elif kind == "error_friendly":   self._on_error(data, friendly=True)
                elif kind == "error":            self._on_error(data, friendly=False)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _on_error(self, msg: str, friendly: bool):
        self._btn_run.configure(state="normal", text="▶  Iniciar Conciliação")
        self._badge.update_state("  AGUARDANDO  ", "neutral")

        # Reabilita dropzones
        for zone in (self._zone_banco, self._zone_sistema):
            for w in (zone._drop, zone._icon, zone._hint):
                try:
                    w.bind("<Button-1>", lambda _e, z=zone: z._open_dialog())
                    w.bind("<Enter>", zone._hover_on)
                    w.bind("<Leave>", zone._hover_off)
                except Exception:
                    pass

        title = "Arquivo inválido" if friendly else "Erro no processamento"
        messagebox.showerror(title, msg)
        self._set_status("Erro — verifique os arquivos.")

    def _apply_result(self, r: ResultadoConciliacao):
        self.resultado = r
        self._btn_run.configure(state="normal", text="▶  Iniciar Conciliação")

        # Reabilita dropzones
        for zone in (self._zone_banco, self._zone_sistema):
            for w in (zone._drop, zone._icon, zone._hint):
                try:
                    w.bind("<Button-1>", lambda _e, z=zone: z._open_dialog())
                    w.bind("<Enter>", zone._hover_on)
                    w.bind("<Leave>", zone._hover_off)
                except Exception:
                    pass

        self._dashboard.render(r)
        self._days_grid.render(r.status_por_dia)
        self._table.render(r)

        # Badge dinâmico (5 estados)
        if r.tudo_ok:
            self._badge.update_state("  ✅  TUDO OK  ", "ok")
        elif r.qtd_inconsistencias > 0 and r.qtd_divergencias > 0:
            self._badge.update_state(
                f"  ⚠️  {r.qtd_divergencias} DIV · {r.qtd_inconsistencias} INC  ",
                "warning",
            )
        elif r.qtd_inconsistencias > 0:
            self._badge.update_state(
                f"  ❌  {r.qtd_inconsistencias} INCONSISTÊNCIA(S)  ", "error",
            )
        else:
            self._badge.update_state(
                f"  ⚠️  {r.qtd_divergencias} DIVERGÊNCIA(S)  ", "warning",
            )

        # Botão exportar: habilita sempre que há resultado
        self._btn_export.configure(state="normal")

        self._set_status(
            f"Concluído — {r.qtd_conciliados} conciliados, "
            f"{r.qtd_divergencias} divergências, "
            f"{r.qtd_inconsistencias} inconsistências."
        )
        log.info(
            f"Conciliação OK — sistema={r.total_sistema:.2f} banco={r.total_banco:.2f} "
            f"conc={r.qtd_conciliados} div={r.qtd_divergencias} inc={r.qtd_inconsistencias}"
        )

    # ═════════════════════════════════════════════════════════════
    # EXPORTAÇÃO
    # ═════════════════════════════════════════════════════════════
    def _export(self):
        if not self.resultado:
            messagebox.showinfo("Exportar", "Execute a conciliação primeiro.")
            return

        fp = filedialog.asksaveasfilename(
            title="Salvar relatório",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialdir=self.session.last_dir,
            initialfile=f"conciliacao_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
        )
        if not fp:
            return

        try:
            exportar_relatorio(self.resultado, fp)
            messagebox.showinfo("Exportado", f"Arquivo salvo em:\n{fp}")
            self._set_status(f"Exportado: {Path(fp).name}")
        except Exception as e:
            log_exception("Erro ao exportar", e)
            messagebox.showerror("Erro ao exportar", str(e))
