"""
app.py — Janela principal da suíte: sidebar + navegação entre módulos.

As views são criadas sob demanda (lazy) — a janela abre instantânea e
cada módulo só importa pandas/openpyxl quando é usado pela primeira vez.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional

import customtkinter as ctk

from .. import __version__
from ..core import historico, theme as T
from ..core.config_central import ConfigCentral
from .widgets import Toast

logger = logging.getLogger(__name__)

# Ícones monocromáticos (Segoe UI Symbol) — ficam na cor do texto do menu,
# sem emoji colorido. A ordem define os atalhos Ctrl+1..9.
NAV = [
    ("inicio",  "⌂", "Início"),
    ("dda",     "☰", "Organizador DDA"),
    ("conferir_compras", "✉", "Conferir Compras"),
    ("remessa", "⇄", "Remessa × Banco"),
    ("ret",     "▥", "Código de barras"),
    ("import_usinas", "↓", "Importação Usinas"),
    ("retorno", "↺", "Retorno (SISPAG)"),
    ("pensoes", "⚖", "Pensões"),
    ("config",  "⚙", "Configurações"),
]

# grupos do menu (título → chaves, na ordem do NAV)
GRUPOS_NAV = [
    ("GERAL", ["inicio"]),
    ("CONTAS A PAGAR", ["dda", "conferir_compras", "remessa", "ret",
                        "import_usinas", "retorno"]),
    ("FOLHA", ["pensoes"]),
    ("SISTEMA", ["config"]),
]


class FinaHubApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__(fg_color=T.FUNDO)
        ctk.set_appearance_mode("light")
        self.geometry("1280x820")
        self.minsize(1080, 700)

        self.title(f"FinaHub — Contas a Pagar  ·  v{__version__}")
        self.config = ConfigCentral()
        self.toast = Toast(self)
        self._views: Dict[str, ctk.CTkFrame] = {}
        self._nav_botoes: Dict[str, ctk.CTkButton] = {}
        self._atual: Optional[str] = None

        self._nav_badges: Dict[str, ctk.CTkLabel] = {}
        self._montar_sidebar()
        self._badge_inicial()
        self._conteudo = ctk.CTkFrame(self, fg_color="transparent")
        self._conteudo.pack(side="left", fill="both", expand=True,
                            padx=T.PAD_G, pady=T.PAD_G)

        self._atalhos()
        self.navegar("inicio")

    # ------------------------------------------------------------------ #
    def _montar_sidebar(self) -> None:
        sb = ctk.CTkFrame(self, width=T.SIDEBAR_W, fg_color=T.SIDEBAR_BG,
                          corner_radius=0)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        # marca: quadradinho verde com "A" + nome
        marca = ctk.CTkFrame(sb, fg_color="transparent")
        marca.pack(fill="x", padx=18, pady=(22, 14))
        ctk.CTkLabel(marca, text="F", width=34, height=34, corner_radius=9,
                     fg_color=T.AZUL, text_color=T.BRANCO,
                     font=(T.FONTE, 16, "bold")).pack(side="left")
        txt = ctk.CTkFrame(marca, fg_color="transparent")
        txt.pack(side="left", padx=10)
        ctk.CTkLabel(txt, text="FinaHub", font=(T.FONTE, 16, "bold"),
                     text_color=T.BRANCO, anchor="w", height=18).pack(fill="x")
        ctk.CTkLabel(txt, text="Contas a Pagar", font=(T.FONTE, 11),
                     text_color=T.SIDEBAR_RODAPE, anchor="w", height=16).pack(fill="x")

        rotulos = {k: (ic, r) for k, ic, r in NAV}
        for titulo, chaves in GRUPOS_NAV:
            ctk.CTkLabel(sb, text=titulo, font=T.F_NAV_GRUPO,
                         text_color=T.SIDEBAR_RODAPE, anchor="w", height=18).pack(
                fill="x", padx=24, pady=(10, 2))
            for chave in chaves:
                icone, rotulo = rotulos[chave]
                btn = ctk.CTkButton(
                    sb, text=f"  {icone}    {rotulo}", font=T.F_NAV, anchor="w",
                    height=36, corner_radius=8,
                    fg_color="transparent", hover_color=T.SIDEBAR_HOVER,
                    text_color=T.SIDEBAR_ITEM,
                    command=lambda k=chave: self.navegar(k))
                btn.pack(fill="x", padx=12, pady=1)
                self._nav_botoes[chave] = btn

        # rodapé: usuário + versão
        rod = ctk.CTkFrame(sb, fg_color="transparent", corner_radius=10,
                           border_width=1, border_color=T.SIDEBAR_BORDA)
        rod.pack(side="bottom", fill="x", padx=12, pady=14)
        ctk.CTkLabel(rod, text="AL", width=30, height=30, corner_radius=15,
                     fg_color=T.SIDEBAR_HOVER, text_color=T.BRANCO,
                     font=(T.FONTE, 11, "bold")).pack(side="left", padx=(10, 8), pady=10)
        info = ctk.CTkFrame(rod, fg_color="transparent")
        info.pack(side="left", pady=8)
        ctk.CTkLabel(info, text="Alan", font=(T.FONTE, 12, "bold"),
                     text_color=T.BRANCO, anchor="w", height=16).pack(fill="x")
        ctk.CTkLabel(info, text=f"v{__version__} · uso interno", font=(T.FONTE, 10),
                     text_color=T.SIDEBAR_RODAPE, anchor="w", height=14).pack(fill="x")

    # ------------------------------------------------------------------ #
    # Número vermelho ao lado do item do menu (ex.: notas fora da planilha)
    # ------------------------------------------------------------------ #
    def marcar_nav(self, chave: str, n: int) -> None:
        btn = self._nav_botoes.get(chave)
        if btn is None:
            return
        lbl = self._nav_badges.get(chave)
        if not n:
            if lbl is not None:
                lbl.place_forget()
            return
        if lbl is None:
            lbl = ctk.CTkLabel(btn, text="", height=20, width=22, corner_radius=10,
                               fg_color=T.VERMELHO, text_color=T.BRANCO,
                               font=(T.FONTE, 11, "bold"))
            lbl.bind("<Button-1>", lambda _e, k=chave: self.navegar(k))
            self._nav_badges[chave] = lbl
        lbl.configure(text=str(n) if n < 100 else "99+",
                      bg_color=T.SIDEBAR_ATIVO if chave == self._atual else T.SIDEBAR_BG)
        lbl.place(relx=1.0, rely=0.5, x=-10, anchor="e")

    def _badge_inicial(self) -> None:
        """Mostra o resultado da última conferência de Compras (do histórico)."""
        try:
            for ev in historico.listar(300):
                if (ev.get("modulo") == "conferir_compras"
                        and "faltando" in (ev.get("resumo") or {})):
                    self.marcar_nav("conferir_compras",
                                    int(ev["resumo"]["faltando"] or 0))
                    break
        except Exception:      # noqa: BLE001 — só um aviso visual
            pass

    def _atalhos(self) -> None:
        for i, (chave, _, _) in enumerate(NAV, start=1):
            self.bind(f"<Control-Key-{i}>", lambda _e, k=chave: self.navegar(k))
        # Ações do módulo atual: Enter = ação primária, Esc = cancelar,
        # Ctrl+O = anexar arquivo. Reaproveita os botões da própria tela.
        self.bind("<Return>", lambda _e: self._atalho_view("primario"))
        self.bind("<Escape>", lambda _e: self._atalho_view("cancelar"))
        self.bind("<Control-o>", lambda _e: self._atalho_view("abrir"))
        self.bind("<Control-O>", lambda _e: self._atalho_view("abrir"))

    def _atalho_view(self, acao: str) -> None:
        view = self._views.get(self._atual)
        # não dispara "Enter" enquanto o foco está num campo de texto/busca
        if acao in ("primario",):
            w = self.focus_get()
            if w is not None and w.winfo_class() in ("Entry", "Text", "TEntry"):
                return
        if view is None:
            if acao == "cancelar":
                self.navegar("inicio")
            return
        if acao == "primario":
            b = getattr(view, "b_cta", None)
            if b is not None and str(b.cget("state")) != "disabled":
                b.invoke()
        elif acao == "abrir":
            if hasattr(view, "_selecionar"):
                view._selecionar()
        elif acao == "cancelar":
            b = getattr(view, "b_cancelar", None)
            if (b is not None and b.winfo_ismapped()
                    and str(b.cget("state")) != "disabled"):
                b.invoke()
            else:
                self.navegar("inicio")

    # ------------------------------------------------------------------ #
    def navegar(self, chave: str) -> None:
        if chave == self._atual:
            return
        # Telas empilhadas no mesmo lugar: trocar = só trazer para a frente.
        # Antes a tela antiga era desmontada (pack_forget) e a nova remontada,
        # o que obrigava o CustomTkinter a redesenhar tudo → "piscava".
        if chave not in self._views:
            view = self._criar_view(chave)
            view.place(x=0, y=0, relwidth=1, relheight=1)
            self._views[chave] = view
        self._views[chave].tkraise()
        self._atual = chave
        for k, btn in self._nav_botoes.items():
            if k == chave:
                btn.configure(fg_color=T.SIDEBAR_ATIVO,
                              text_color=T.SIDEBAR_ATIVO_TX,
                              font=(T.FONTE, 13, "bold"))
            else:
                btn.configure(fg_color="transparent",
                              text_color=T.SIDEBAR_ITEM, font=T.F_NAV)
            lbl = self._nav_badges.get(k)
            if lbl is not None:   # cantos do número acompanham o fundo do botão
                lbl.configure(bg_color=T.SIDEBAR_ATIVO if k == chave else T.SIDEBAR_BG)
        if chave == "inicio":
            self.atualizar_dashboard()

    def _criar_view(self, chave: str) -> ctk.CTkFrame:
        # imports locais: cada tela (e suas dependências pesadas)
        # só carrega quando é aberta pela primeira vez
        if chave == "inicio":
            from .view_dashboard import DashboardView
            return DashboardView(self._conteudo, self)
        if chave == "dda":
            from .view_dda import DdaView
            return DdaView(self._conteudo, self)
        if chave == "remessa":
            from .view_remessa import RemessaView
            return RemessaView(self._conteudo, self)
        if chave == "ret":
            from .view_ret import RetView
            return RetView(self._conteudo, self)
        if chave == "import_usinas":
            from .view_importacao_usinas import ImportacaoUsinasView
            return ImportacaoUsinasView(self._conteudo, self)
        if chave == "retorno":
            from .view_retorno import RetornoView
            return RetornoView(self._conteudo, self)
        if chave == "conferir_compras":
            from .view_conferir_compras import ConferirComprasView
            return ConferirComprasView(self._conteudo, self)
        if chave == "pensoes":
            from .view_pensoes import PensoesView
            return PensoesView(self._conteudo, self)
        if chave == "config":
            from .view_config import ConfigView
            return ConfigView(self._conteudo, self)
        raise ValueError(f"View desconhecida: {chave}")

    def atualizar_dashboard(self) -> None:
        view = self._views.get("inicio")
        if view is not None:
            view.atualizar()
