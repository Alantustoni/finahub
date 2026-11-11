"""
view_dashboard.py — Painel inicial: métricas do dia, pendências abertas
e histórico central. (Os atalhos de módulo saíram — a sidebar já navega;
no lugar entrou informação que trabalha: a lista de pendências.)
"""
from __future__ import annotations

from datetime import datetime

import customtkinter as ctk

from ..core import historico, theme as T
from .widgets import Card, MetricCard, Tabela, cabecalho


_HIST_PARA_MENU = {"importacao_usinas": "import_usinas"}


def _saudacao() -> str:
    h = datetime.now().hour
    if 5 <= h < 12:
        return "Bom dia, Alan"
    if 12 <= h < 18:
        return "Boa tarde, Alan"
    return "Boa noite, Alan"


class DashboardView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app

        self._cab = cabecalho(
            self, _saudacao(),
            "Resumo do dia — atualizado a cada execução dos módulos.",
            crumb="Painel geral", icone="🏦")
        self._cab.pack(fill="x", pady=(0, T.PAD))
        self._lbl_titulo = self._cab._titulo_label

        # ── métricas do dia ──────────────────────────────────────────
        linha = ctk.CTkFrame(self, fg_color="transparent")
        linha.pack(fill="x", pady=(0, T.PAD))
        for i in range(4):
            linha.grid_columnconfigure(i, weight=1, uniform="m")

        self.c_exec = MetricCard(linha, "Execuções hoje")
        self.c_conc = MetricCard(linha, "Conciliados / programados", T.VERDE)
        self.c_pend = MetricCard(linha, "Pendências", T.AMARELO)
        self.c_inc  = MetricCard(linha, "Inconsistências", T.VERMELHO)
        for i, c in enumerate((self.c_exec, self.c_conc, self.c_pend, self.c_inc)):
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))

        # ── pendências abertas ───────────────────────────────────────
        ctk.CTkLabel(self, text="Pendências abertas", font=T.F_SECAO,
                     text_color=T.INK, anchor="w").pack(fill="x", pady=(4, 8))
        self.card_pend = Card(self)
        self.card_pend.pack(fill="x", pady=(0, T.PAD))
        self._linhas_pend: list = []

        # ── histórico (com busca + exportar) ─────────────────────────
        ctk.CTkLabel(self, text="Últimas execuções", font=T.F_SECAO,
                     text_color=T.INK, anchor="w").pack(fill="x", pady=(4, 8))
        self.tabela = Tabela(
            self, ["Quando", "Módulo", "Resultado", "Status", "Arquivo"],
            larguras=[110, 150, 290, 140, 260], altura=300,
            busca=True, exportar=True, nome_export="historico",
            estilo="leve", unidade="execuções")
        self.tabela.pack(fill="both", expand=True)

        self._marca = None
        self.atualizar()

    # ------------------------------------------------------------------ #
    def atualizar(self) -> None:
        # saudação acompanha o horário real (bom dia / boa tarde / boa noite)
        try:
            self._lbl_titulo.configure(text=_saudacao())
        except Exception:
            pass
        # Só redesenha se o histórico mudou (nova execução) ou virou o dia.
        # Antes tudo era destruído e recriado a cada volta ao Início → piscava.
        try:
            from ..core.paths import HISTORICO_PATH
            marca = (HISTORICO_PATH.stat().st_mtime_ns
                     if HISTORICO_PATH.exists() else 0, datetime.now().date())
        except OSError:
            marca = None
        if marca is not None and marca == self._marca:
            return
        self._marca = marca
        m = historico.resumo_hoje()
        self.c_exec.set(m["execucoes"], f'{m["modulos_usados"]} módulo usado' if m["modulos_usados"] == 1
                       else f'{m["modulos_usados"]} módulos usados')
        self.c_conc.set(m["conciliados"])
        self.c_pend.set(m["pendentes"])
        self.c_inc.set(m["inconsistencias"])

        self._montar_pendencias()

        linhas = []
        for e in historico.listar(60):
            f = historico.formatar_execucao(e)
            linhas.append([f["quando"], f["modulo"], f["resultado"],
                           f["status"], f["arquivo"]])
        if not linhas:
            linhas = [["—", "Nenhuma execução registrada ainda",
                       "abra um módulo na barra lateral para começar", "", ""]]
        self.tabela.preencher(linhas)

    # ------------------------------------------------------------------ #
    def _montar_pendencias(self) -> None:
        for w in self._linhas_pend:
            w.destroy()
        self._linhas_pend.clear()

        pendencias = historico.pendencias_abertas()
        if not pendencias:
            lbl = ctk.CTkLabel(
                self.card_pend, text="✔  Nenhuma pendência aberta — tudo em dia.",
                font=T.F_NORMAL, text_color=T.VERDE, anchor="w")
            lbl.pack(fill="x", padx=T.PAD, pady=14)
            self._linhas_pend.append(lbl)
            return

        for p in pendencias:
            row = ctk.CTkFrame(self.card_pend, fg_color="transparent")
            row.pack(fill="x", padx=T.PAD, pady=(10, 0))
            self._linhas_pend.append(row)

            ctk.CTkLabel(row, text="⚠", font=(T.FONTE, 14),
                         text_color=T.AMARELO).pack(side="left", padx=(0, 10))
            nome = historico.MODULOS.get(p["modulo"], p["modulo"])
            data = p["ts"][:16].replace("T", " ")
            ctk.CTkLabel(
                row, text=f"{nome} — {p['descricao']}",
                font=(T.FONTE, 12, "bold"), text_color=T.INK,
                anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=f"última execução: {data}",
                         font=T.F_PEQUENA, text_color=T.INK_3).pack(
                side="left", padx=10)
            # nome no histórico ≠ chave do menu em alguns módulos; módulo que
            # saiu do menu não ganha botão (antes dava erro ao clicar)
            from .app import NAV
            chave = _HIST_PARA_MENU.get(p["modulo"], p["modulo"])
            if chave in {k for k, _, _ in NAV}:
                ctk.CTkButton(
                    row, text="Abrir →", width=70, height=26,
                    font=(T.FONTE, 11, "bold"), corner_radius=T.RAIO_BTN,
                    fg_color=T.INFO_BG, text_color=T.AZUL, hover_color=T.BORDA,
                    command=lambda k=chave: self.app.navegar(k)).pack(
                    side="right")

        # respiro no fim do card
        fim = ctk.CTkFrame(self.card_pend, fg_color="transparent", height=12)
        fim.pack(fill="x")
        self._linhas_pend.append(fim)
