"""
view_retorno.py — Combinar retornos de pagamento (SISPAG) num arquivo só.

Junta vários arquivos de retorno diários (Itaú, segmentos A/B/J, multi-lote)
num único arquivo íntegro: mantém a empresa da maioria, retira intrusos,
renumera os lotes em sequência e recalcula o trailer.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..core import historico, theme as T
from ..core.utils import (abrir_no_sistema, mensagem_erro_amigavel,
                          timestamp_arquivo)
from .widgets import (Badge, Card, EmptyState, MetricCard, StepBar,
                      ThreadRunner, botao, cabecalho)


class RetornoView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.runner = ThreadRunner(self)
        self.arquivos: list[Path] = []
        self.resultado = None  # ResultadoRetorno
        self.saida_gerada: Path | None = None

        cabecalho(self, "Retorno (SISPAG)",
                  "Junta vários arquivos de retorno diários num único — mantém "
                  "a empresa da maioria, renumera os lotes e recalcula o trailer.",
                  crumb="Módulo · combinar retornos de pagamento",
                  icone="🧾").pack(fill="x", pady=(0, 10))

        self.steps = StepBar(self, ["Anexar retornos", "Combinar",
                                    "Gerar arquivo"])
        self.steps.pack(fill="x", pady=(0, T.PAD))

        acoes = Card(self)
        acoes.pack(fill="x", pady=(0, T.PAD))
        box = ctk.CTkFrame(acoes, fg_color="transparent")
        box.pack(fill="x", padx=T.PAD, pady=T.PAD)
        self.b_cta = botao(box, "📎  Selecionar retornos", self._selecionar)
        self.b_cta.pack(side="left")
        self.b_trocar = botao(box, "Trocar arquivos", self._selecionar,
                              primario=False)
        self.b_cancelar = botao(box, "✕  Cancelar", self._cancelar,
                                primario=False)
        self.b_abrir = botao(box, "📂  Abrir", self._abrir_saida,
                             primario=False, width=104)
        self.b_pasta = botao(box, "📁  Pasta", self._abrir_pasta,
                             primario=False, width=104)
        self.badge = Badge(box, "aguardando arquivos", "info")
        self.badge.pack(side="right")

        # ── estado vazio ─────────────────────────────────────────────
        self.vazio = EmptyState(
            self, "🧾", "Nenhum retorno anexado ainda",
            "Selecione os arquivos de retorno diários (mesmo banco/empresa). "
            "O sistema confere a empresa pelo cabeçalho, empilha os lotes "
            "renumerando-os, recalcula o trailer e gera um arquivo único "
            "pronto para o SISPAG.")
        self.vazio.pack(fill="both", expand=True)

        # ── área de resultados ───────────────────────────────────────
        self.area = ctk.CTkFrame(self, fg_color="transparent")

        self.linha_cards = ctk.CTkFrame(self.area, fg_color="transparent")
        for i in range(3):
            self.linha_cards.grid_columnconfigure(i, weight=1, uniform="m")
        self.c_arq  = MetricCard(self.linha_cards, "Arquivos combinados")
        self.c_emp  = MetricCard(self.linha_cards, "Empresa", T.AZUL_ESCURO)
        self.c_lote = MetricCard(self.linha_cards, "Lotes", T.VERDE)
        for i, c in enumerate((self.c_arq, self.c_emp, self.c_lote)):
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0),
                   pady=(0, 10))
        self.c_reg = MetricCard(self.linha_cards, "Registros")
        self.c_det = MetricCard(self.linha_cards, "Detalhes (pagamentos)")
        self.c_int = MetricCard(self.linha_cards, "Intrusos retirados", T.AMARELO)
        for i, c in enumerate((self.c_reg, self.c_det, self.c_int)):
            c.grid(row=1, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))

        self.lbl_log = ctk.CTkLabel(self.area, text="Log de processamento",
                                    font=T.F_SECAO, text_color=T.INK, anchor="w")
        self.lbl_log.pack(fill="x", pady=(2, 6))
        self.log = ctk.CTkTextbox(self.area, height=240, font=T.F_MONO,
                                  fg_color=T.CARD, text_color=T.INK,
                                  border_width=1, border_color=T.BORDA,
                                  corner_radius=T.RAIO, wrap="none")
        self.log.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ #
    def _cta(self, texto: str, comando) -> None:
        self.b_cta.configure(text=texto, command=comando, state="normal")

    def _mostrar_area(self) -> None:
        if self.vazio.winfo_ismapped():
            self.vazio.pack_forget()
            self.area.pack(fill="both", expand=True)

    def _registrar_saida(self, caminho) -> None:
        self.saida_gerada = Path(caminho)
        self.b_abrir.pack(side="left", padx=8)
        self.b_pasta.pack(side="left", padx=(0, 8))

    def _esconder_saida(self) -> None:
        self.saida_gerada = None
        self.b_abrir.pack_forget()
        self.b_pasta.pack_forget()

    def _abrir_saida(self) -> None:
        self._abrir(self.saida_gerada)

    def _abrir_pasta(self) -> None:
        self._abrir(self.saida_gerada.parent if self.saida_gerada else None)

    def _abrir(self, alvo) -> None:
        if not alvo:
            return
        try:
            abrir_no_sistema(alvo)
        except Exception as exc:      # noqa: BLE001
            self.app.toast.show(f"Não consegui abrir: {exc}", "err", ms=6000)

    # ------------------------------------------------------------------ #
    def _selecionar(self) -> None:
        if self.runner.ocupado:
            return   # Ctrl+O/clique no meio de um processamento
        caminhos = filedialog.askopenfilenames(
            title="Selecione os arquivos de retorno",
            initialdir=self.app.config.ultima_pasta("retorno") or None,
            filetypes=[("Arquivos RET", "*.ret *.RET"),
                       ("Arquivos TXT", "*.txt"), ("Todos", "*.*")])
        if not caminhos:
            return
        self.app.config.lembrar_pasta("retorno", caminhos[0])
        self.arquivos = [Path(c) for c in caminhos]
        self.resultado = None
        self._esconder_saida()
        self._mostrar_area()
        self.linha_cards.pack_forget()
        self.badge.set(f"{len(self.arquivos)} arquivo(s)", "info")
        self._cta("⚙  Combinar", self._processar)
        self.b_trocar.pack(side="left", padx=8)
        self.b_cancelar.pack(side="left", padx=(0, 8))
        self.steps.set_ativo(1)
        self._log_set("\n".join(f"• {p.name}" for p in self.arquivos))

    def _cancelar(self) -> None:
        if self.runner.ocupado:
            return
        if self.resultado is not None and not messagebox.askyesno(
                "Cancelar", "Já existe resultado na tela. Descartar tudo e "
                "recomeçar?", parent=self):
            return
        self.arquivos = []
        self.resultado = None
        self._esconder_saida()
        if self.area.winfo_ismapped():
            self.area.pack_forget()
        if not self.vazio.winfo_ismapped():
            self.vazio.pack(fill="both", expand=True)
        self.linha_cards.pack_forget()
        self._log_set("")
        self.badge.set("aguardando arquivos", "info")
        self._cta("📎  Selecionar retornos", self._selecionar)
        self.b_trocar.pack_forget()
        self.b_cancelar.pack_forget()
        self.steps.set_ativo(0)

    def _processar(self) -> None:
        if not self.arquivos or self.runner.ocupado:
            return
        self.badge.set("combinando…", "info")
        for b in (self.b_cta, self.b_trocar, self.b_cancelar):
            b.configure(state="disabled")
        cfg = self.app.config.get("retorno", default={})
        arquivos = list(self.arquivos)
        from ..modules import retorno as mod
        self.runner.executar(
            lambda: mod.combinar(arquivos, cfg), self._concluido, self._falhou)

    def _concluido(self, r) -> None:
        self.resultado = r
        for b in (self.b_cta, self.b_trocar, self.b_cancelar):
            b.configure(state="normal")
        self.linha_cards.pack(fill="x", pady=(0, T.PAD), before=self.lbl_log)
        self.c_arq.set(r.total_arquivos,
                       f"de {r.arquivos_recebidos} anexados")
        self.c_emp.set(r.empresa_predominante or "—")
        self.c_lote.set(r.total_lotes, "renumerados em sequência")
        self.c_reg.set(r.total_registros)
        seg = " · ".join(f"{k}:{v}" for k, v in sorted(r.segmentos.items()))
        self.c_det.set(r.total_detalhes, seg)
        self.c_int.set(len(r.arquivos_fora_empresa))

        texto = "\n".join(r.log)
        if r.avisos:
            texto += "\n\n⚠ AVISOS:\n" + "\n".join(f"  • {a}" for a in r.avisos)
        self._log_set(texto)

        if r.arquivos_fora_empresa:
            self.app.toast.show(
                f"Empresa predominante: {r.empresa_predominante}. Retirei "
                f"{len(r.arquivos_fora_empresa)} arquivo(s) de outra empresa: "
                + "; ".join(r.arquivos_fora_empresa), "warn", ms=9000)

        if r.ok:
            self.badge.set(f"{r.total_lotes} lotes prontos",
                           "warn" if r.avisos else "ok")
            self._cta("⬇  Gerar arquivo único", self._gravar)
            self.steps.set_ativo(2)
        else:
            self.badge.set("nada para combinar", "err")
            self._cta("📎  Selecionar retornos", self._selecionar)

    def _falhou(self, exc: Exception) -> None:
        for b in (self.b_cta, self.b_trocar, self.b_cancelar):
            b.configure(state="normal")
        self.badge.set("erro", "err")
        self.app.toast.show(mensagem_erro_amigavel(exc), "err", ms=8000)

    def _gravar(self) -> None:
        if not self.resultado or not self.resultado.ok or self.runner.ocupado:
            return
        emp = (self.resultado.empresa_predominante or "retorno").lower()
        saida = filedialog.asksaveasfilename(
            title="Salvar arquivo de retorno combinado",
            defaultextension=".RET",
            initialdir=self.app.config.ultima_pasta("retorno_saida") or None,
            initialfile=f"retorno_{emp}_{timestamp_arquivo()}.RET",
            filetypes=[("Arquivo RET", "*.RET"), ("Todos", "*.*")])
        if not saida:
            return
        self.app.config.lembrar_pasta("retorno_saida", saida)
        from ..modules import retorno as mod
        try:
            mod.gravar(self.resultado, Path(saida))
        except Exception as exc:      # noqa: BLE001
            self.badge.set("erro ao gravar", "err")
            self.app.toast.show(mensagem_erro_amigavel(exc), "err", ms=8000)
            return
        historico.registrar(
            "retorno", "Combinação de retornos",
            resumo={
                "arquivos": self.resultado.total_arquivos,
                "lotes": self.resultado.total_lotes,
                "registros": self.resultado.total_registros,
                "empresa": self.resultado.empresa_predominante or "?",
            },
            arquivos=self.arquivos, saida=saida)
        self.steps.set_ativo(3)
        self.badge.set("arquivo gerado", "ok")
        self._registrar_saida(saida)
        self.app.toast.show("Arquivo combinado gerado. Suba no SISPAG e valide "
                            "a importação.", "ok", ms=6000)
        self.app.atualizar_dashboard()

    def _log_set(self, texto: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", texto)
        self.log.configure(state="disabled")
