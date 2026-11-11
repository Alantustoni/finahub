"""
view_importacao_usinas.py — Tela "Importação Usinas".

Monta o arquivo de importação de códigos de barras a partir do CSV de
Boletos Recebidos (DDA), usando um RET só como molde do leiaute. Duplica
por filial, ordena por vencimento e recalcula os trailers — igual ao RET.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

from ..core import historico, theme as T
from ..core.utils import (abrir_no_sistema, mensagem_erro_amigavel,
                          timestamp_arquivo)
from .widgets import (Badge, Card, EmptyState, MetricCard, StepBar,
                      ThreadRunner, botao, cabecalho)


class ImportacaoUsinasView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.runner = ThreadRunner(self)
        self.csv_path: Path | None = None
        self.ret_path: Path | None = None
        self.resultado = None
        self.saida_gerada: Path | None = None

        cabecalho(
            self, "Importação Usinas",
            "Gera o arquivo de importação de códigos de barras a partir do CSV "
            "de Boletos Recebidos — mesmo formato do Juntador RET.",
            crumb="Novo · monta do CSV", icone="📥").pack(fill="x", pady=(0, 10))

        self.steps = StepBar(self, ["Selecionar CSV",
                                    "Ler e validar", "Gerar arquivo"])
        self.steps.pack(fill="x", pady=(0, T.PAD))

        acoes = Card(self)
        acoes.pack(fill="x", pady=(0, T.PAD))
        box = ctk.CTkFrame(acoes, fg_color="transparent")
        box.pack(fill="x", padx=T.PAD, pady=T.PAD)
        self.b_csv = botao(box, "📄  Selecionar planilha (CSV/XLSX)",
                           self._selecionar_csv)
        self.b_csv.pack(side="left")
        # botão "RET molde (opcional)" retirado em 30/10/2026: usa sempre o
        # leiaute padrão embutido (ret_path fica None)
        self.b_abrir = botao(box, "📂  Abrir", self._abrir_saida,
                             primario=False, width=104)
        self.b_pasta = botao(box, "📁  Pasta", self._abrir_pasta,
                             primario=False, width=104)
        self.badge = Badge(box, "aguardando arquivos", "info")
        self.badge.pack(side="right")

        info = ctk.CTkFrame(acoes, fg_color="transparent")
        info.pack(fill="x", padx=T.PAD, pady=(0, T.PAD))
        self.lbl_csv = ctk.CTkLabel(info, text="Planilha: nenhuma selecionada",
                                    font=T.F_PEQUENA, text_color=T.INK_3, anchor="w")
        self.lbl_csv.pack(fill="x")

        op = ctk.CTkFrame(acoes, fg_color="transparent")
        op.pack(fill="x", padx=T.PAD, pady=(0, T.PAD))
        # Troca de CNPJ por filial SEMPRE ATIVA (obrigatória): mantém a matriz
        # e acrescenta uma cópia por filial do cadastro (mesmo comportamento do
        # Código de barras). Fornecedores fora do cadastro passam intactos.
        ctk.CTkLabel(op, text="🔁 Troca de CNPJ por filial: sempre ativa",
                     font=T.F_NORMAL, text_color=T.VERDE).pack(side="left")
        # campo "limite teste" retirado em 30/10/2026 — processa sempre todas
        self.b_gerar = botao(op, "⚙  Ler e validar", self._processar, primario=True)
        self.b_gerar.pack(side="left", padx=16)
        self.b_salvar = botao(op, "💾  Salvar arquivo", self._gravar, primario=True)

        self.vazio = EmptyState(
            self, "📥", "Selecione o CSV de boletos",
            "O CSV (Boletos Recebidos) traz nota, valor, CNPJ, vencimento e "
            "código de barras. Eu monto o arquivo no leiaute padrão, duplico "
            "por filial e recalculo os trailers.")
        self.vazio.pack(fill="both", expand=True)

        self.area = ctk.CTkFrame(self, fg_color="transparent")
        cards = ctk.CTkFrame(self.area, fg_color="transparent")
        for i in range(3):
            cards.grid_columnconfigure(i, weight=1, uniform="m")
        self.c_lidos = MetricCard(cards, "Boletos lidos")
        self.c_val   = MetricCard(cards, "Válidos")
        self.c_reg   = MetricCard(cards, "Linhas no arquivo", T.VERDE)
        for i, c in enumerate((self.c_lidos, self.c_val, self.c_reg)):
            c.grid(row=0, column=i, sticky="nsew",
                   padx=(0 if i == 0 else 10, 0), pady=(0, 10))
        cards.pack(fill="x", pady=(0, T.PAD))
        self.log = ctk.CTkTextbox(self.area, height=250, font=T.F_MONO,
                                  fg_color=T.CARD, text_color=T.INK,
                                  border_width=1, border_color=T.BORDA,
                                  corner_radius=T.RAIO, wrap="none")
        self.log.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ #
    def _selecionar_csv(self) -> None:
        if self.runner.ocupado:
            return
        c = filedialog.askopenfilename(
            title="Selecione a planilha de Boletos Recebidos",
            initialdir=self.app.config.ultima_pasta("import_usinas") or None,
            filetypes=[("Planilhas", "*.csv *.xlsx *.xlsm"),
                       ("CSV", "*.csv"), ("Excel", "*.xlsx *.xlsm"),
                       ("Todos", "*.*")])
        if not c:
            return
        self.app.config.lembrar_pasta("import_usinas", c)
        self.csv_path = Path(c)
        self.lbl_csv.configure(text=f"Planilha: {self.csv_path.name}")
        self.badge.set("pronto para gerar", "info")
        self.steps.set_ativo(1)

    def _processar(self) -> None:
        if self.runner.ocupado:
            return
        if not self.csv_path:
            self.app.toast.show("Selecione a planilha de boletos primeiro.",
                                "err", ms=6000)
            return
        limite = 0                                 # sempre todas
        self.badge.set("processando…", "info")
        self.b_gerar.configure(state="disabled")
        cfg_ret = dict(self.app.config.get("ret", default={}) or {})
        filiais = self.app.config.get("ret", "filiais_por_raiz", default={}) or {}
        cfg_usinas = self.app.config.get("usinas", default={}) or {}
        csv_p, ret_p = self.csv_path, self.ret_path        # ret_p pode ser None
        from ..modules import importacao_usinas as imp
        duplicar = True          # troca de CNPJ por filial é OBRIGATÓRIA
        self.runner.executar(
            lambda: imp.processar(csv_p, cfg_ret, filiais, cfg_usinas=cfg_usinas,
                                  ret_molde_path=ret_p, ordenar_venc=True,
                                  duplicar_limite=limite, duplicar_filial=duplicar),
            self._concluido, self._falhou)

    def _concluido(self, r) -> None:
        self.resultado = r
        self.b_gerar.configure(state="normal")
        if self.vazio.winfo_ismapped():
            self.vazio.pack_forget()
            self.area.pack(fill="both", expand=True)
        self.c_lidos.set(r.total_lidos)
        self.c_val.set(r.total_validos, f"{r.titulos_duplicados} duplicados p/ filial")
        self.c_reg.set(r.total_registros,
                       f"{r.primeiro_vencimento or '—'} → {r.ultimo_vencimento or '—'}")
        texto = "\n".join(r.log)
        colisoes = getattr(r, "colisoes", [])
        if colisoes:
            texto += ("\n\n⛔ VALORES REPETIDOS (o sistema casa por valor e vai "
                      "confundir/errar estes — trate à mão):\n"
                      + "\n".join(f"  • {c}" for c in colisoes[:60]))
            if len(colisoes) > 60:
                texto += f"\n  … (+{len(colisoes) - 60} colisões)"
        if r.avisos:
            mostra = r.avisos[:50]
            texto += "\n\n⚠ AVISOS:\n" + "\n".join(f"  • {a}" for a in mostra)
            if len(r.avisos) > 50:
                texto += f"\n  … (+{len(r.avisos) - 50} avisos)"
        self._log_set(texto)
        if colisoes:
            self.app.toast.show(
                f"⛔ {getattr(r, 'total_colisoes', 0)} nota(s) com valor repetido — "
                "o sistema vai confundir essas. Confira a lista antes de importar.",
                "warn", ms=10000)
        if r.ok:
            self.badge.set(f"{r.total_registros} linhas prontas",
                           "warn" if r.avisos else "ok")
            self.b_salvar.pack(side="left", padx=8)
            self.steps.set_ativo(2)
        else:
            self.badge.set("nada a gerar", "err")

    def _falhou(self, exc: Exception) -> None:
        self.b_gerar.configure(state="normal")
        self.badge.set("erro", "err")
        self.app.toast.show(mensagem_erro_amigavel(exc), "err", ms=8000)

    def _gravar(self) -> None:
        if not self.resultado or not self.resultado.ok or self.runner.ocupado:
            return
        saida = filedialog.asksaveasfilename(
            title="Salvar arquivo de importação",
            defaultextension=".txt",
            initialdir=self.app.config.ultima_pasta("import_usinas_saida") or None,
            initialfile=f"importacao_usinas_{timestamp_arquivo()}.txt",
            filetypes=[("Arquivo TXT", "*.txt")])
        if not saida:
            return
        self.app.config.lembrar_pasta("import_usinas_saida", saida)
        from ..modules import importacao_usinas as imp
        try:
            caminhos = imp.gravar_dividido(self.resultado, Path(saida), 1)
        except Exception as exc:      # noqa: BLE001
            self.badge.set("erro ao gravar", "err")
            self.app.toast.show(mensagem_erro_amigavel(exc), "err", ms=8000)
            return
        self.saida_gerada = Path(caminhos[0])
        self.b_abrir.pack(side="left", padx=8)
        self.b_pasta.pack(side="left")
        historico.registrar(
            "importacao_usinas", "Importação Usinas (CSV → arquivo)",
            resumo={
                "boletos_validos": self.resultado.total_validos,
                "duplicados": self.resultado.titulos_duplicados,
                "registros": self.resultado.total_registros,
                "arquivos": len(caminhos),
            },
            arquivos=[self.csv_path], saida=str(caminhos[0]))
        self.steps.set_ativo(3)
        if len(caminhos) > 1:
            self.badge.set(f"{len(caminhos)} arquivos gerados", "ok")
            self.app.toast.show(
                f"Gerado em {len(caminhos)} arquivos. Importe um por vez e "
                "valide antes de confirmar pagamento.", "ok", ms=9000)
        else:
            self.badge.set("arquivo gerado", "ok")
            self.app.toast.show(
                "Arquivo gerado. Valide um lote pequeno no sistema antes de "
                "rodar tudo.", "ok", ms=7000)
        self.app.atualizar_dashboard()

    # ------------------------------------------------------------------ #
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

    def _log_set(self, texto: str) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", texto)
        self.log.configure(state="disabled")
