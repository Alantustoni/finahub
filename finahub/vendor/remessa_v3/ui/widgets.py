"""
Widgets reutilizáveis do sistema.

Componentes:
  - PremiumCard       : card branco com borda azul e hover
  - MetricCard        : card de métrica do dashboard
  - FileDropZone      : área de seleção de arquivo
  - PremiumButton     : botão padrão do sistema
  - SectionTitle      : título de seção com linha divisória
  - StatusBadge       : badge OK/Erro
"""

import customtkinter as ctk
from tkinter import filedialog
from pathlib import Path

from core.theme import COLORS, FONT, RADIUS


# ═════════════════════════════════════════════════════════════════
# CARD BASE
# ═════════════════════════════════════════════════════════════════
class PremiumCard(ctk.CTkFrame):
    """Card branco com borda azul e hover suave."""

    def __init__(self, master, hoverable: bool = True, **kw):
        super().__init__(
            master,
            fg_color=COLORS["bg_card"],
            border_color=COLORS["border"],
            border_width=1,
            corner_radius=RADIUS["lg"],
            **kw,
        )
        if hoverable:
            self.bind("<Enter>", self._on_enter)
            self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _e):
        self.configure(border_color=COLORS["blue_sec"])

    def _on_leave(self, _e):
        self.configure(border_color=COLORS["border"])


# ═════════════════════════════════════════════════════════════════
# CARD DE MÉTRICA (Dashboard)
# ═════════════════════════════════════════════════════════════════
class MetricCard(PremiumCard):
    """Card de métrica: ícone, valor grande, label embaixo."""

    def __init__(self, master, icon: str, label: str,
                 value: str = "—", color: str | None = None, **kw):
        super().__init__(master, **kw)
        self._color = color or COLORS["blue_main"]
        self.grid_columnconfigure(0, weight=1)

        self._icon = ctk.CTkLabel(
            self, text=icon, font=FONT["3xl"], text_color=self._color,
        )
        self._icon.grid(row=0, column=0, padx=18, pady=(16, 2), sticky="w")

        self._val = ctk.CTkLabel(
            self, text=value, font=FONT["2xl_b"], text_color=self._color,
        )
        self._val.grid(row=1, column=0, padx=18, pady=(0, 2), sticky="w")

        ctk.CTkLabel(
            self, text=label, font=FONT["sm"],
            text_color=COLORS["text_muted"],
        ).grid(row=2, column=0, padx=18, pady=(0, 14), sticky="w")

    def update_value(self, value: str, color: str | None = None) -> None:
        self._val.configure(text=value)
        if color:
            self._val.configure(text_color=color)
            self._icon.configure(text_color=color)


# ═════════════════════════════════════════════════════════════════
# BOTÃO PADRÃO
# ═════════════════════════════════════════════════════════════════
class PremiumButton(ctk.CTkButton):
    """Botão padrão azul com hover."""

    def __init__(self, master, **kw):
        defaults = dict(
            font=FONT["md_b"],
            corner_radius=RADIUS["base"],
            height=42,
            fg_color=COLORS["blue_main"],
            hover_color=COLORS["blue_sec"],
            text_color=COLORS["white"],
            border_width=0,
        )
        defaults.update(kw)
        super().__init__(master, **defaults)


# ═════════════════════════════════════════════════════════════════
# DROPZONE DE ARQUIVO
# ═════════════════════════════════════════════════════════════════
class FileDropZone(PremiumCard):
    """Área de seleção de arquivo com visual de drop premium."""

    def __init__(self, master, label: str, subtitle: str,
                 on_select, multi: bool = False,
                 initial_dir: str | None = None, **kw):
        super().__init__(master, hoverable=False, **kw)
        self._on_select  = on_select
        self._multi      = multi
        self._files: list[str] = []
        self._initial_dir = initial_dir

        self.grid_columnconfigure(0, weight=1)

        # Título
        ctk.CTkLabel(
            self, text=label, font=FONT["md_b"], text_color=COLORS["blue_main"],
        ).grid(row=0, column=0, padx=20, pady=(16, 2), sticky="w")

        # Subtítulo
        ctk.CTkLabel(
            self, text=subtitle, font=FONT["sm"], text_color=COLORS["text_sec"],
        ).grid(row=1, column=0, padx=20, pady=(0, 8), sticky="w")

        # Área visual de drop
        self._drop = ctk.CTkFrame(
            self, fg_color=COLORS["bg_subtle"],
            border_color=COLORS["border"], border_width=1,
            corner_radius=RADIUS["base"],
        )
        self._drop.grid(row=2, column=0, padx=20, pady=(0, 8), sticky="ew")
        self._drop.grid_columnconfigure(0, weight=1)

        self._icon = ctk.CTkLabel(self._drop, text="📂", font=FONT["3xl"])
        self._icon.grid(row=0, column=0, pady=(14, 2))

        self._hint = ctk.CTkLabel(
            self._drop, text="Clique para selecionar o arquivo",
            font=FONT["sm"], text_color=COLORS["text_sec"],
        )
        self._hint.grid(row=1, column=0, pady=(0, 14))

        for w in (self._drop, self._icon, self._hint):
            w.bind("<Button-1>", lambda _e: self._open_dialog())
            w.bind("<Enter>", self._hover_on)
            w.bind("<Leave>", self._hover_off)

        # Lista de arquivos selecionados
        self._files_lbl = ctk.CTkLabel(
            self, text="", font=FONT["xs"],
            text_color=COLORS["blue_sec"],
            wraplength=320, justify="left",
        )
        self._files_lbl.grid(row=3, column=0, padx=20, pady=(0, 16), sticky="w")

    def _hover_on(self, _e):
        self._drop.configure(
            fg_color=COLORS["bg_hover"],
            border_color=COLORS["blue_sec"],
        )

    def _hover_off(self, _e):
        self._drop.configure(
            fg_color=COLORS["bg_subtle"],
            border_color=COLORS["border"],
        )

    def _open_dialog(self):
        kwargs = dict(
            filetypes=[("Excel", "*.xlsx *.xls *.XLS *.XLSX"), ("Todos", "*.*")],
            initialdir=self._initial_dir or str(Path.home()),
        )
        if self._multi:
            files = filedialog.askopenfilenames(
                title="Selecionar arquivos do Sistema", **kwargs,
            )
            if files:
                self.set_files(list(files))
        else:
            f = filedialog.askopenfilename(
                title="Selecionar arquivo do Banco", **kwargs,
            )
            if f:
                self.set_files([f])

    def set_files(self, files: list[str]):
        self._files = files
        if files:
            names = [Path(f).name for f in files]
            if len(names) == 1:
                # Trunca nome longo com reticências
                name = names[0]
                txt = (name[:35] + "…") if len(name) > 35 else name
            elif len(names) <= 3:
                txt = " | ".join(
                    (n[:20] + "…") if len(n) > 20 else n for n in names
                )
            else:
                txt = f"{len(names)} arquivos selecionados"
            self._files_lbl.configure(
                text=f"✓ {txt}", text_color=COLORS["green_ok"],
            )
            self._icon.configure(text="✅")
        else:
            self._files_lbl.configure(text="")
            self._icon.configure(text="📂")
        if self._on_select:
            self._on_select(files)

    def get_files(self) -> list[str]:
        return self._files

    def clear(self):
        self.set_files([])


# ═════════════════════════════════════════════════════════════════
# TÍTULO DE SEÇÃO
# ═════════════════════════════════════════════════════════════════
class SectionTitle(ctk.CTkFrame):
    """Título de seção com linha divisória à direita."""

    def __init__(self, master, text: str, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self, text=text, font=FONT["lg_b"], text_color=COLORS["blue_main"],
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkFrame(
            self, height=1, fg_color=COLORS["border"], corner_radius=0,
        ).grid(row=0, column=1, padx=(12, 0), sticky="ew")


# ═════════════════════════════════════════════════════════════════
# BADGE DE STATUS
# ═════════════════════════════════════════════════════════════════
class StatusBadge(ctk.CTkLabel):
    """
    Badge colorido com 5 estados possíveis:
      - neutral    : cinza (aguardando)
      - processing : azul (processando)
      - ok         : verde (tudo certo)
      - warning    : laranja (divergências)
      - error      : vermelho (inconsistências)
    """

    @staticmethod
    def colors_for(state: str) -> tuple[str, str]:
        """Retorna (text_color, fg_color) para um estado."""
        if state == "ok":
            return COLORS["white"], COLORS["green_ok"]
        if state == "error":
            return COLORS["white"], COLORS["red_err"]
        if state == "warning":
            return COLORS["white"], COLORS["yellow"]
        if state == "processing":
            return COLORS["white"], COLORS["blue_sec"]
        return COLORS["text_muted"], COLORS["blue_deep"]

    def __init__(self, master, text: str, state: str = "neutral", **kw):
        tc, fc = self.colors_for(state)
        super().__init__(
            master, text=text, font=FONT["base_b"],
            text_color=tc, fg_color=fc, corner_radius=RADIUS["xl"],
            padx=14, pady=6, **kw,
        )

    def update_state(self, text: str, state: str):
        tc, fc = self.colors_for(state)
        self.configure(text=text, text_color=tc, fg_color=fc)
