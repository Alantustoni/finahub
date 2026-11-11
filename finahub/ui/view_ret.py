"""
view_ret.py — Tela do Juntador RET (UX v1.2).

UX: botão primário único que muda por etapa, estado vazio antes da
seleção e o card "Trailer" substituído por um selo na barra de ações
(era informação, não métrica).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from ..core import historico, theme as T
from ..core.utils import (abrir_no_sistema, mensagem_erro_amigavel,
                          timestamp_arquivo)
from .widgets import (Badge, Card, EmptyState, MetricCard, StepBar,
                      ThreadRunner, botao, cabecalho)


class RetView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.runner = ThreadRunner(self)
        self.arquivos: list[Path] = []
        self.resultado = None  # ResultadoRET

        cabecalho(self, "Código de barras",
                  "Junta arquivos .RET (Bradesco/Itaú) num TXT único — com "
                  "validação, log visível e trailer recalculado.",
                  crumb="Módulo · reescrito e corrigido", icone="🔗").pack(
            fill="x", pady=(0, 10))

        self.steps = StepBar(self, ["Anexar arquivos", "Validar e juntar",
                                    "Gerar TXT"])
        self.steps.pack(fill="x", pady=(0, T.PAD))

        acoes = Card(self)
        acoes.pack(fill="x", pady=(0, T.PAD))
        box = ctk.CTkFrame(acoes, fg_color="transparent")
        box.pack(fill="x", padx=T.PAD, pady=T.PAD)
        self.b_cta = botao(box, "📎  Selecionar arquivos RET", self._selecionar)
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
        self.badge_trailer = Badge(box, "", "info")  # selo (ex-card "Trailer")
        self.saida_gerada: Path | None = None

        # ── filtro de vencimento inicial (o Alan escolhe a data) ─────
        flt = ctk.CTkFrame(acoes, fg_color="transparent")
        flt.pack(fill="x", padx=T.PAD, pady=(0, T.PAD))
        ctk.CTkLabel(flt, text="📅  Incluir vencimentos a partir de:",
                     font=T.F_NORMAL, text_color=T.INK).pack(side="left")
        self.e_venc_min = ctk.CTkEntry(flt, width=120, font=T.F_NORMAL,
                                       border_color=T.BORDA, fg_color=T.CARD,
                                       placeholder_text="DD/MM/AAAA")
        self.e_venc_min.pack(side="left", padx=8)
        self.e_venc_min.insert(0, datetime.now().strftime("%d/%m/%Y"))
        ctk.CTkLabel(
            flt, font=T.F_PEQUENA, text_color=T.INK_3, anchor="w",
            text="títulos com vencimento antes dessa data ficam de fora — "
                 "deixe em branco para incluir todos.").pack(side="left", padx=4)

        # ── modo SÓ USINAS (inverso de "ignorar usinas") ─────────────
        modo = ctk.CTkFrame(acoes, fg_color="transparent")
        modo.pack(fill="x", padx=T.PAD, pady=(0, T.PAD))
        self.sw_so_usinas = ctk.CTkSwitch(
            modo, text="🏭  Deixar SÓ as usinas (remover os demais fornecedores)",
            font=T.F_NORMAL, progress_color=T.AZUL)
        self.sw_so_usinas.pack(side="left")
        ctk.CTkLabel(
            modo, font=T.F_PEQUENA, text_color=T.INK_3, anchor="w",
            text="mantém no TXT apenas Usiminas, CSN, ArcelorMittal, ARMAR… "
                 "(o inverso de 'ignorar usinas').").pack(side="left", padx=8)

        # ── duplicar usinas por filial (vínculo por CNPJ) ────────────
        modo2 = ctk.CTkFrame(acoes, fg_color="transparent")
        modo2.pack(fill="x", padx=T.PAD, pady=(0, T.PAD))
        self.sw_duplicar = ctk.CTkSwitch(
            modo2, text="🔁  Duplicar usinas por filial (vincular boleto por CNPJ)",
            font=T.F_NORMAL, progress_color=T.AZUL)
        self.sw_duplicar.pack(side="left")
        # campo "limite p/ teste" retirado em 30/10/2026 — duplica sempre todas

        # (opção "Dividir a saída em N arquivos" retirada a pedido em 30/10/2026
        #  — o arquivo final sai sempre num arquivo só)

        # ── estado vazio ─────────────────────────────────────────────
        self.vazio = EmptyState(
            self, "⧉", "Nenhum arquivo RET selecionado",
            "Selecione os arquivos .RET do Bradesco e/ou Itaú. O sistema "
            "valida a estrutura, converte Itaú → Bradesco, mostra o log "
            "completo e recalcula o trailer antes de gerar o TXT final.")
        self.vazio.pack(fill="both", expand=True)

        # ── área de resultados (oculta até selecionar) ───────────────
        self.area = ctk.CTkFrame(self, fg_color="transparent")

        self.linha_cards = ctk.CTkFrame(self.area, fg_color="transparent")
        for i in range(3):
            self.linha_cards.grid_columnconfigure(i, weight=1, uniform="m")
        # linha 1: contagens
        self.c_arq  = MetricCard(self.linha_cards, "Arquivos")
        self.c_tit  = MetricCard(self.linha_cards, "Títulos no total")
        self.c_conv = MetricCard(self.linha_cards, "Convertidos Itaú→Bradesco")
        for i, c in enumerate((self.c_arq, self.c_tit, self.c_conv)):
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0),
                   pady=(0, 10))
        # linha 2: vencimentos + registros
        self.c_venc1 = MetricCard(self.linha_cards, "Primeiro vencimento",
                                  T.AZUL_ESCURO)
        self.c_venc2 = MetricCard(self.linha_cards, "Último vencimento",
                                  T.AZUL_ESCURO)
        self.c_reg   = MetricCard(self.linha_cards, "Títulos no TXT final",
                                  T.VERDE)
        for i, c in enumerate((self.c_venc1, self.c_venc2, self.c_reg)):
            c.grid(row=1, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))

        self.lbl_log = ctk.CTkLabel(self.area, text="Log de processamento",
                                    font=T.F_SECAO, text_color=T.INK, anchor="w")
        self.lbl_log.pack(fill="x", pady=(2, 6))
        self.log = ctk.CTkTextbox(self.area, height=260, font=T.F_MONO,
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
            title="Selecione os arquivos RET",
            initialdir=self.app.config.ultima_pasta("ret") or None,
            filetypes=[("Arquivos RET", "*.ret *.RET"),
                       ("Arquivos TXT", "*.txt"), ("Todos", "*.*")])
        if not caminhos:
            return
        self.app.config.lembrar_pasta("ret", caminhos[0])
        self.arquivos = [Path(c) for c in caminhos]
        self.resultado = None
        self._esconder_saida()
        self._mostrar_area()
        self.linha_cards.pack_forget()          # métricas só após validar
        self.badge_trailer.pack_forget()
        self.badge.set(f"{len(self.arquivos)} arquivo(s)", "info")
        self._cta("⚙  Validar e juntar", self._processar)
        self.b_trocar.pack(side="left", padx=8)
        self.b_cancelar.pack(side="left", padx=(0, 8))
        self.steps.set_ativo(1)
        self._log_set("\n".join(f"• {p.name}" for p in self.arquivos))

    def _cancelar(self) -> None:
        """Descarta os arquivos anexados e volta ao estado inicial."""
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
        self.badge_trailer.pack_forget()
        self._log_set("")
        self.badge.set("aguardando arquivos", "info")
        self._cta("📎  Selecionar arquivos RET", self._selecionar)
        self.b_trocar.pack_forget()
        self.b_cancelar.pack_forget()
        self.steps.set_ativo(0)

    def _processar(self) -> None:
        if not self.arquivos or self.runner.ocupado:
            return
        # data de vencimento inicial (opcional) — validação antes de rodar
        texto_venc = self.e_venc_min.get().strip()
        venc_min = None
        if texto_venc:
            try:
                venc_min = datetime.strptime(texto_venc, "%d/%m/%Y")
            except ValueError:
                self.app.toast.show(
                    "Data de vencimento inválida — use DD/MM/AAAA (ou deixe "
                    "em branco para incluir todos).", "err", ms=7000)
                return
        self.badge.set("processando…", "info")
        for b in (self.b_cta, self.b_trocar, self.b_cancelar):
            b.configure(state="disabled")
        # cópia do cfg para não mutar o config compartilhado; o seletor da
        # tela liga o modo "só usinas" por rodada (tem precedência sobre
        # "ignorar usinas" no motor).
        cfg = dict(self.app.config.get("ret", default={}) or {})
        cfg["somente_usinas"] = bool(self.sw_so_usinas.get())
        cfg["duplicar_usinas_por_filial"] = bool(self.sw_duplicar.get())
        cfg["duplicar_limite_teste"] = 0          # sempre todas
        # termos dos grupos de usina (Organizador Usinas) — para o RET
        # reconhecer as mesmas usinas (ARMAR, SOLUÇÕES, etc.)
        padr = self.app.config.get("usinas", "padronizacao_empresa", default={})
        termos_extra = [t for termos in (padr or {}).values() for t in termos]
        arquivos = list(self.arquivos)
        from ..modules import ret as mod_ret
        self.runner.executar(
            lambda: mod_ret.processar(arquivos, cfg, termos_extra, venc_min),
            self._concluido, self._falhou)

    def _concluido(self, r) -> None:
        self.resultado = r
        for b in (self.b_cta, self.b_trocar, self.b_cancelar):
            b.configure(state="normal")
        # métricas aparecem acima do log, só agora que existem
        self.linha_cards.pack(fill="x", pady=(0, T.PAD), before=self.lbl_log)
        self.c_arq.set(r.total_arquivos)
        # Card 1: TÍTULOS NO TOTAL (todas as notas lidas)
        sub_total = f"{r.titulos_usinas} de usinas"
        if getattr(r, "apenas_usinas", False):
            sub_total = f"{r.titulos_usinas} de usinas (só elas mantidas)"
        elif r.usinas_excluidas and r.titulos_usinas:
            sub_total = f"{r.titulos_usinas} de usinas (ignoradas)"
        self.c_tit.set(r.total_titulos, sub_total)
        # Card 2: TÍTULOS NO TXT FINAL (o que realmente vai no arquivo) —
        # já descontando usinas/outros e títulos vencidos filtrados.
        if getattr(r, "apenas_usinas", False):
            base_final = r.titulos_usinas             # só usinas ficam
        elif r.usinas_excluidas:
            base_final = r.titulos_sem_usinas         # usinas saem
        else:
            base_final = r.total_titulos              # tudo fica
        titulos_finais = base_final - r.titulos_vencidos_removidos
        self._titulos_finais = titulos_finais
        self.c_reg.set(titulos_finais,
                       f"{r.total_registros} linhas no arquivo")
        self.c_conv.set(r.convertidos_itau)
        sub_venc1 = "ordenado por vencimento" if r.ordenado_venc else ""
        if r.vencimento_minimo:
            sub_venc1 = (f"a partir de {r.vencimento_minimo} · "
                         f"{r.titulos_vencidos_removidos} vencidos fora")
        self.c_venc1.set(r.primeiro_vencimento or "—", sub_venc1)
        self.c_venc2.set(r.ultimo_vencimento or "—")

        # selo do trailer na barra de ações (ex-card)
        if r.trailer_recalculado:
            self.badge_trailer.set("trailer recalculado", "ok")
        else:
            self.badge_trailer.set("trailer em modo legado", "warn")
        self.badge_trailer.pack(side="right", padx=(0, 8))

        texto = "\n".join(r.log)
        if r.avisos:
            texto += "\n\n⚠ AVISOS:\n" + "\n".join(f"  • {a}" for a in r.avisos)
        self._log_set(texto)

        # aviso de segurança quando a duplicação por filial está ativa
        if getattr(r, "duplicar_usinas", False):
            self.app.toast.show(
                f"Duplicação por filial: {r.titulos_usina_duplicados} título(s) "
                f"de usina viraram {r.linhas_geradas_duplicacao} linha(s). "
                "Confira o vínculo no sistema ANTES de confirmar qualquer pagamento.",
                "warn", ms=10000)

        # aviso destacado quando arquivos de outra empresa foram retirados
        if r.arquivos_fora_empresa:
            self.app.toast.show(
                f"Empresa predominante: {r.empresa_predominante}. Retirei "
                f"{len(r.arquivos_fora_empresa)} arquivo(s) de outra empresa: "
                + "; ".join(r.arquivos_fora_empresa), "warn", ms=9000)

        if r.ok:
            self.badge.set(f"{self._titulos_finais} títulos prontos",
                           "warn" if r.avisos else "ok")
            self._cta("⬇  Gerar TXT final", self._gravar)
            self.steps.set_ativo(2)
        else:
            self.badge.set("nenhum registro válido", "err")
            self._cta("📎  Selecionar arquivos RET", self._selecionar)

    def _falhou(self, exc: Exception) -> None:
        for b in (self.b_cta, self.b_trocar, self.b_cancelar):
            b.configure(state="normal")
        self.badge.set("erro", "err")
        self.app.toast.show(mensagem_erro_amigavel(exc), "err", ms=8000)

    def _gravar(self) -> None:
        if not self.resultado or not self.resultado.ok or self.runner.ocupado:
            return
        prefixo = ("usinas" if getattr(self.resultado, "apenas_usinas", False)
                   else "arquivo_final_bradesco")
        saida = filedialog.asksaveasfilename(
            title="Salvar arquivo final",
            defaultextension=".txt",
            initialdir=self.app.config.ultima_pasta("ret_saida") or None,
            initialfile=f"{prefixo}_{timestamp_arquivo()}.txt",
            filetypes=[("Arquivo TXT", "*.txt")])
        if not saida:
            return
        self.app.config.lembrar_pasta("ret_saida", saida)
        from ..modules import ret as mod_ret
        try:
            caminhos = mod_ret.gravar_dividido(self.resultado, Path(saida), 1)
        except Exception as exc:      # noqa: BLE001
            self.badge.set("erro ao gravar", "err")
            self.app.toast.show(mensagem_erro_amigavel(exc), "err", ms=8000)
            return
        saida = str(caminhos[0])      # primeiro arquivo, para "Abrir/Pasta"
        historico.registrar(
            "ret", "Junção de arquivos RET",
            resumo={
                "modo": ("somente_usinas"
                         if getattr(self.resultado, "apenas_usinas", False)
                         else "normal"),
                "arquivos": self.resultado.total_arquivos,
                "titulos_sem_usinas": self.resultado.titulos_sem_usinas,
                "titulos_usinas": self.resultado.titulos_usinas,
                "registros": self.resultado.total_registros,
                "convertidos_itau": self.resultado.convertidos_itau,
                "trailer": "recalculado" if self.resultado.trailer_recalculado
                           else "legado",
            },
            arquivos=self.arquivos, saida=saida)
        self.steps.set_ativo(3)
        if len(caminhos) > 1:
            self.badge.set(f"{len(caminhos)} arquivos gerados", "ok")
            self.app.toast.show(
                f"Saída dividida em {len(caminhos)} arquivos "
                f"(…_parte1de{len(caminhos)}.txt, …) na mesma pasta. Importe um "
                "por vez e valide antes de confirmar pagamento.",
                "ok", ms=9000)
        else:
            self.badge.set("TXT gerado", "ok")
            self.app.toast.show("Arquivo final gerado. Valide a primeira importação "
                                "no sistema de destino.", "ok", ms=6000)
        self._registrar_saida(saida)
        self._cta("📎  Juntar outros arquivos", self._selecionar)
        self.app.atualizar_dashboard()

    def _log_set(self, texto: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", texto)
        self.log.configure(state="disabled")
