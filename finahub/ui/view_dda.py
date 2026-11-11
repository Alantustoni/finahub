"""
view_dda.py — Tela do Organizador DDA (v1.3).

Motor: DataProcessorExt (motor original do DDA V7 + cabeçalho opcional +
captura das notas removidas). Novidades da tela:
  • cards Semana / Propostas excluídas / Usinas excluídas;
  • totais de usinas por grupo (USIMINAS · ARMAR · CSN · SOLUÇÕES);
  • listas na tela: propostas excluídas e notas programadas — sem
    precisar abrir o Excel;
  • planilha SEM cabeçalho aceita (mapa posicional A/B/D/E/F/G/I/L).
"""
from __future__ import annotations

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Dict, List

import customtkinter as ctk

from ..core import historico, theme as T
from ..core.utils import (abrir_no_sistema, formatar_moeda,
                          mensagem_erro_amigavel, parse_valor_br,
                          timestamp_arquivo)
from .widgets import (Badge, Card, EmptyState, MetricCard, StepBar, Tabela,
                      ThreadRunner, botao, cabecalho)

# situação da nota → (fundo da linha, cor do número no cartão)
COR_SIT = {
    "prog": (T.AMARELO_BG, T.AMARELO),   # programada: amarela, como no Excel
    "ok":   ("#ECFDF5", T.VERDE),        # já veio (Compras / CNPJ da lista)
    "cob":  ("", T.VERMELHO),            # cobrar: linha branca/zebra
}
_PILULAS = [("todas", "Todas"), ("cob", "A cobrar"),
            ("ok", "Já vieram"), ("prog", "Programadas")]


class DdaView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.runner = ThreadRunner(self)
        self.arquivo: Path | None = None
        self.arquivos_banco: List[Path] = []
        self.result = None
        self.metricas: Dict[str, Any] = {}
        self.extras: Dict[str, Any] = {}
        self.rc = None

        cabecalho(self, "Organizador DDA",
                  "Cole a planilha a partir de A1 — com ou sem cabeçalho. "
                  "Tratamento, cruzamento com extratos e relatório semanal.",
                  crumb="Módulo · motor original DDA V7", icone="📋").pack(
            fill="x", pady=(0, 10))

        self.steps = StepBar(self, ["Anexar DDA", "Processar",
                                    "Anexar banco e cruzar", "Exportar"])
        self.steps.pack(fill="x", pady=(0, T.PAD))

        # ── barra de ações ───────────────────────────────────────────
        acoes = Card(self)
        acoes.pack(fill="x", pady=(0, T.PAD))
        box = ctk.CTkFrame(acoes, fg_color="transparent")
        box.pack(fill="x", padx=T.PAD, pady=T.PAD)
        self.b_cta = botao(box, "📎  Anexar DDA", self._selecionar)
        self.b_cta.pack(side="left")
        self.b_trocar = botao(box, "Trocar arquivo", self._selecionar,
                              primario=False)
        self.b_alt = botao(box, "⬇  Exportar sem cruzar", self._exportar,
                           primario=False)
        self.b_cancelar = botao(box, "✕  Cancelar", self._cancelar,
                                primario=False)
        self.b_abrir = botao(box, "📂  Abrir", self._abrir_saida,
                             primario=False, width=104)
        self.b_pasta = botao(box, "📁  Pasta", self._abrir_pasta,
                             primario=False, width=104)
        self.b_cons = botao(box, "📑  Consolidar revisado", self._consolidar,
                            primario=False)
        self.b_cons.pack(side="right", padx=(8, 0))
        self.badge = Badge(box, "aguardando arquivo", "info")
        self.badge.pack(side="right")
        self.saida_gerada: Path | None = None

        self.progresso = ctk.CTkProgressBar(self, height=8, corner_radius=4,
                                            fg_color=T.TRACK,
                                            progress_color=T.AZUL)
        self.progresso.set(0)
        self.lbl_status = ctk.CTkLabel(self, text="", font=T.F_PEQUENA,
                                       text_color=T.INK_2, anchor="w")

        # ── estado vazio ─────────────────────────────────────────────
        self.vazio = EmptyState(
            self, "▤", "Nenhum DDA processado ainda",
            "Anexe a planilha DDA (pode colar sem cabeçalho — o sistema "
            "reconhece as colunas pela posição). Depois de processar, tudo "
            "aparece aqui: semana, propostas e usinas excluídas, notas "
            "programadas e pendentes.")
        self.vazio.pack(fill="both", expand=True)

        # ── área de resultados (rolável — tem bastante conteúdo) ─────
        self.area = ctk.CTkScrollableFrame(self, fg_color="transparent")

        # linha 1: números principais
        self.l1 = l1 = ctk.CTkFrame(self.area, fg_color="transparent")
        l1.pack(fill="x", pady=(0, 10))
        for i in range(4):                       # 4 cards fixos + erro opcional
            l1.grid_columnconfigure(i, weight=1, uniform="m")
        l1.grid_columnconfigure(4, weight=0, uniform="")    # col do erro: só com erro
        self.c_linhas = MetricCard(l1, "Notas tratadas")
        self.c_prog   = MetricCard(l1, "Programadas", COR_SIT["prog"][1])
        self.c_ok     = MetricCard(l1, "Já vieram", COR_SIT["ok"][1])
        self.c_pend   = MetricCard(l1, "A cobrar", COR_SIT["cob"][1])
        self.c_erros  = MetricCard(l1, "Linhas com erro", T.VERMELHO)
        # os 4 primeiros já aparecem (com "—" até cruzar), evitando
        # colunas vazias no meio da linha.
        for i, c in enumerate((self.c_linhas, self.c_prog, self.c_ok, self.c_pend)):
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))

        # linha 2: semana + exclusões
        l2 = ctk.CTkFrame(self.area, fg_color="transparent")
        l2.pack(fill="x", pady=(0, 10))
        for i in range(3):
            l2.grid_columnconfigure(i, weight=1, uniform="n")
        self.c_semana = MetricCard(l2, "Semana")
        self.c_prop   = MetricCard(l2, "Propostas excluídas", T.AMARELO)
        self.c_usi    = MetricCard(l2, "Usinas excluídas", T.AMARELO)
        for i, c in enumerate((self.c_semana, self.c_prop, self.c_usi)):
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0))

        # card: usinas por grupo
        self.card_grupos = Card(self.area)
        ctk.CTkLabel(self.card_grupos, text="VALOR DE USINAS POR GRUPO",
                     font=T.F_CARD_LABEL, text_color=T.INK_2,
                     anchor="w").pack(fill="x", padx=T.PAD, pady=(12, 2))
        self.linha_grupos = ctk.CTkFrame(self.card_grupos,
                                         fg_color="transparent")
        self.linha_grupos.pack(fill="x", padx=T.PAD, pady=(0, 12))
        self._widgets_grupos: list = []

        # seção: propostas excluídas
        self.sec_prop = ctk.CTkFrame(self.area, fg_color="transparent")
        ctk.CTkLabel(self.sec_prop, text="Propostas excluídas",
                     font=T.F_SECAO, text_color=T.AMARELO, anchor="w").pack(
            fill="x", pady=(4, 6))
        self.tab_prop = Tabela(
            self.sec_prop, ["Empresa", "Fornecedor", "NF", "Vencimento",
                            "Valor"],
            larguras=[160, 240, 110, 110, 130], altura=160,
            alinhamentos=["w", "w", "w", "w", "e"])
        self.tab_prop.pack(fill="x")

        # seção: notas da semana — uma lista só (cobrar + já vieram +
        # programadas), linha tingida pela situação e pílulas de filtro
        self.sec_pend = ctk.CTkFrame(self.area, fg_color="transparent")
        topo = ctk.CTkFrame(self.sec_pend, fg_color="transparent")
        topo.pack(fill="x", pady=(4, 6))
        ctk.CTkLabel(topo, text="Notas da semana", font=T.F_SECAO,
                     text_color=T.INK, anchor="w").pack(side="left")
        self._pilulas: Dict[str, ctk.CTkButton] = {}
        self._filtro = "todas"
        for chave, _rot in _PILULAS:
            b = ctk.CTkButton(
                topo, text=_rot, height=30, width=10, corner_radius=15,
                border_width=1, font=(T.FONTE, 12, "bold"),
                command=lambda k=chave: self._filtrar(k))
            b.pack(side="left", padx=(12 if not self._pilulas else 6, 0))
            self._pilulas[chave] = b
        self.tabela = Tabela(
            self.sec_pend, ["Empresa", "Fornecedor", "NF", "Vencimento",
                            "Valor", "Situação"],
            larguras=[150, 230, 100, 100, 120, 230], altura=320,
            busca=True, exportar=True, nome_export="notas_da_semana",
            alinhamentos=["w", "w", "w", "w", "e", "w"])
        for tag, (fundo, _cor) in COR_SIT.items():
            self.tabela.cor_tag(tag, fundo=fundo)
        self.tabela.pack(fill="x")
        self._pintar_pilulas({})

        # seção: pagamentos do banco SEM nota no DDA (melhoria vinda do DDA V7)
        self.sec_semnota = ctk.CTkFrame(self.area, fg_color="transparent")
        ctk.CTkLabel(self.sec_semnota,
                     text="Pagamentos do banco sem nota no DDA",
                     font=T.F_SECAO, text_color=T.VERMELHO, anchor="w").pack(
            fill="x", pady=(4, 6))
        self.tab_semnota = Tabela(
            self.sec_semnota, ["Empresa (banco)", "Favorecido", "Data",
                               "Valor"],
            larguras=[180, 250, 110, 130], altura=160,
            alinhamentos=["w", "w", "w", "e"])
        self.tab_semnota.pack(fill="x")

    # ------------------------------------------------------------------ #
    # Pílulas de filtro (Todas · A cobrar · Já vieram · Programadas)      #
    # ------------------------------------------------------------------ #
    def _filtrar(self, chave: str) -> None:
        self._filtro = chave
        self.tabela.filtrar_tags(None if chave == "todas" else {chave})
        self._pintar_pilulas(self.tabela.contar_tags())

    def _pintar_pilulas(self, cont: Dict[str, int]) -> None:
        total = sum(cont.values())
        for chave, rot in _PILULAS:
            n = total if chave == "todas" else cont.get(chave, 0)
            ativo = chave == self._filtro
            self._pilulas[chave].configure(
                text=f"{rot}  {n}",
                fg_color=T.AZUL if ativo else T.CARD,
                hover_color=T.AZUL_HOVER if ativo else T.FUNDO,
                text_color=T.BRANCO if ativo else T.INK_2,
                border_color=T.AZUL if ativo else T.BORDA)

    # ------------------------------------------------------------------ #
    def _cta(self, texto: str, comando) -> None:
        self.b_cta.configure(text=texto, command=comando, state="normal")

    def _mostrar_resultados(self) -> None:
        if self.vazio.winfo_ismapped():
            self.vazio.pack_forget()
            self.area.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ #
    # Abrir arquivo/pasta gerado + memória da última pasta                 #
    # ------------------------------------------------------------------ #
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
        caminho = filedialog.askopenfilename(
            title="Selecione a planilha DDA (com ou sem cabeçalho)",
            initialdir=self.app.config.ultima_pasta("dda") or None,
            filetypes=[("Excel", "*.xlsx *.xls")])
        if not caminho:
            return
        self.app.config.lembrar_pasta("dda", caminho)
        self.arquivo = Path(caminho)
        self.result = self.rc = None
        self._esconder_saida()
        self.badge.set(self.arquivo.name, "info")
        self._cta("▶  Processar", self._processar)
        self.b_trocar.pack(side="left", padx=8)
        self.b_cancelar.pack(side="left", padx=(0, 8))
        self.b_alt.pack_forget()
        self.steps.set_ativo(1)

    def _cancelar(self) -> None:
        """Descarta o DDA/extratos anexados e volta ao estado inicial."""
        if self.runner.ocupado:
            return
        if self.result is not None and not _confirmar_descarte(self):
            return
        self.arquivo = None
        self.arquivos_banco = []
        self.result = self.rc = None
        self.metricas = {}
        self.extras = {}
        if self.area.winfo_ismapped():
            self.area.pack_forget()
        if not self.vazio.winfo_ismapped():
            self.vazio.pack(fill="both", expand=True)
        self.progresso.pack_forget()
        self.lbl_status.pack_forget()
        self.badge.set("aguardando arquivo", "info")
        self._cta("📎  Anexar DDA", self._selecionar)
        self.b_trocar.pack_forget()
        self.b_cancelar.pack_forget()
        self.b_alt.pack_forget()
        self._esconder_saida()
        self.steps.set_ativo(0)

    # ------------------------------------------------------------------ #
    def _processar(self) -> None:
        if not self.arquivo or self.runner.ocupado:
            return
        self._fase = "processar"
        self._ocupado("Processando DDA…")
        arquivo = self.arquivo
        config_dda = self.app.config.config_dda()
        # mesmos grupos do Organizador Usinas (editáveis nas Configurações);
        # "dda_grupos_usinas" continua como override opcional no config.json
        grupos = (self.app.config.get("dda_grupos_usinas", default=None)
                  or self.app.config.get("usinas", "padronizacao_empresa",
                                         default=None))
        manter = self.app.config.get("dda_usinas_manter", default=[]) or []

        def trabalho():
            from ..modules.dda_ext import (DataProcessorExt,
                                           semana_do_resultado)
            from ..vendor.organizador_dda.core.metrics import calcular_metricas
            proc = DataProcessorExt(config_dda, grupos, manter_termos=manter)
            result = proc.processar(arquivo)
            extras = {
                "semana": semana_do_resultado(result.df),
                "df_propostas": proc.df_propostas,
                "totais_usinas": proc.totais_usinas,
                "qtd_usinas": len(proc.df_usinas),
                "posicional": proc.usou_mapa_posicional,
            }
            return result, calcular_metricas(result), extras

        self.runner.executar(trabalho, self._processado, self._falhou)

    def _processado(self, carga) -> None:
        self.result, self.metricas, self.extras = carga
        self._livre()
        self._mostrar_resultados()
        r = self.result

        self.c_linhas.set(r.total_processado, f"de {r.total_original} originais")
        # DDA novo: a lista e os números do cruzamento anterior saem da tela
        for c in (self.c_prog, self.c_ok, self.c_pend):
            c.set("—")
        self.sec_pend.pack_forget()
        self.sec_semnota.pack_forget()
        self.c_semana.set(self.extras["semana"],
                          "menor → maior vencimento tratado")
        self.c_prop.set(r.removidas_proposta)
        self.c_usi.set(self.extras["qtd_usinas"],
                       formatar_moeda(r.valor_siderurgicas_removidas))

        # usinas por grupo
        self._montar_grupos(self.extras["totais_usinas"])

        # propostas excluídas na tela
        dfp = self.extras["df_propostas"]
        if dfp is not None and not dfp.empty:
            self.tab_prop.preencher([
                [row.get("EMPRESA", row.get("EMPRESA_ORIGINAL", "")),
                 row.get("FORNECEDOR", ""), row.get("PRV NF", ""),
                 _fmt_data(row.get("VENC")), _fmt_valor(row.get("VALOR"))]
                for _, row in dfp.head(150).iterrows()
            ])
            self.sec_prop.pack(fill="x")
        else:
            self.sec_prop.pack_forget()

        n_erros = int((r.df["ERROS"] != "").sum()) if "ERROS" in r.df else 0
        if n_erros:
            self.l1.grid_columnconfigure(4, weight=1, uniform="m")
            self.c_erros.grid(row=0, column=4, sticky="nsew", padx=(10, 0))
            self.c_erros.set(n_erros)
        else:
            self.c_erros.grid_remove()
            self.l1.grid_columnconfigure(4, weight=0, uniform="")   # colapsa a coluna

        aviso_pos = (" · colunas mapeadas pela posição (sem cabeçalho)"
                     if self.extras["posicional"] else "")
        self.badge.set(f"processado{aviso_pos}",
                       "warn" if n_erros else "ok")
        self._cta("🏦  Anexar banco e cruzar", self._cruzar)
        self.b_alt.pack(side="left", padx=8)
        self.steps.set_ativo(2)
        self.app.toast.show(
            "DDA processado" + aviso_pos + ". Anexe os extratos para cruzar.",
            "ok", ms=5000)

    def _montar_grupos(self, totais: Dict[str, float]) -> None:
        for w in self._widgets_grupos:
            w.destroy()
        self._widgets_grupos.clear()
        ordem = ["USIMINAS", "ARMAR", "CSN", "SOLUÇÕES", "OUTRAS"]
        mostrados = [g for g in ordem if totais.get(g)]
        if not mostrados:
            self.card_grupos.pack_forget()
            return
        if self.sec_prop.winfo_manager():      # reprocessamento: mantém ordem
            self.card_grupos.pack(fill="x", pady=(0, 10), before=self.sec_prop)
        else:
            self.card_grupos.pack(fill="x", pady=(0, 10))
        for i, g in enumerate(mostrados):
            bloco = ctk.CTkFrame(self.linha_grupos, fg_color="transparent")
            bloco.pack(side="left", expand=True, fill="x")
            self._widgets_grupos.append(bloco)
            ctk.CTkLabel(bloco, text=g, font=(T.FONTE, 12, "bold"),
                         text_color=T.INK_2).pack(anchor="w")
            ctk.CTkLabel(bloco, text=formatar_moeda(totais[g]),
                         font=(T.FONTE, 17, "bold"),
                         text_color=T.AZUL_ESCURO).pack(anchor="w")

    # ------------------------------------------------------------------ #
    def _cruzar(self) -> None:
        if self.result is None or self.runner.ocupado:
            return
        caminhos = filedialog.askopenfilenames(
            title="Selecione os extratos do banco (a empresa é detectada "
                  "automaticamente)",
            initialdir=self.app.config.ultima_pasta("dda_banco") or None,
            filetypes=[("Excel", "*.xlsx *.xls")])
        if not caminhos:
            return
        self.arquivos_banco = [Path(c) for c in caminhos]
        self.app.config.lembrar_pasta("dda_banco", caminhos[0])
        self._fase = "cruzar"
        self._ocupado("Cruzando com o banco…")
        df = self.result.df
        config_dda = self.app.config.config_dda()
        manter = self.app.config.get("dda_usinas_manter", default=[]) or []
        cfg = self.app.config
        compras_path = cfg.get("dda_compras_path", default="") or ""
        nao_cobrar = cfg.get("dda_cnpjs_ja_veio", default=[]) or []
        feriados = cfg.get("feriados_nacionais", default=[]) or []

        def progresso(pct: float, msg: str) -> None:
            # chamado da THREAD de trabalho — o after() agenda para a thread
            # da UI; protegido para nunca derrubar o cruzamento por um
            # detalhe de exibição (ex.: janela sendo fechada no meio)
            try:
                self.after(0, lambda: (self.progresso.set(pct),
                                       self.lbl_status.configure(text=msg)))
            except Exception:   # noqa: BLE001 — só exibição
                pass

        def trabalho():
            from ..vendor.organizador_dda.core.banco_parser import (
                detectar_empresa_arquivo, parse_banco)
            from ..vendor.organizador_dda.core.banco_cruzamento import cruzar
            from ..vendor.organizador_dda.core.aprendizado import (
                aprender_do_cruzamento)

            pagamentos = []
            detectados = []
            for p in self.arquivos_banco:
                empresa = detectar_empresa_arquivo(p)
                detectados.append(f"{p.name} → {empresa or 'não identificada'}")
                pagamentos.extend(parse_banco(
                    p,
                    termos_siderurgicos=config_dda.remover_texto,
                    cnpjs_excluidos=config_dda.cnpjs_excluidos,
                    manter_termos=manter))
            rc = cruzar(df, pagamentos, callback_progresso=progresso)
            try:
                aprender_do_cruzamento(rc)
            except Exception:
                pass
            # situação de cada nota na tela: confere já com a planilha de
            # Compras (o relatório refaz a mesma conta na hora de exportar)
            from ..modules import dda_compras as DC
            df_sit = DC.montar_df_relatorio(df, rc, abreviar=True)
            notas, erro = [], ""
            if compras_path:
                try:
                    notas = DC.ler_compras(Path(compras_path), DC.DiaUtil(feriados))
                except Exception as exc:       # noqa: BLE001 — a tela sai mesmo assim
                    erro = mensagem_erro_amigavel(exc)
            else:
                erro = "planilha de Compras não configurada"
            resumo = DC.marcar_ja_veio(df_sit, notas, nao_cobrar)
            resumo.erro = erro
            return rc, detectados, df_sit, resumo

        self.runner.executar(trabalho, self._cruzado, self._falhou)

    def _cruzado(self, carga) -> None:
        self.rc, detectados, df_sit, resumo = carga
        self._livre()
        rc = self.rc

        # ── AVANÇA O FLUXO PRIMEIRO ───────────────────────────────────
        # O cruzamento deu certo: o botão passa a ser "Exportar" JÁ, antes
        # de montar as tabelas. Assim, mesmo que a montagem de alguma
        # tabela tropece, o usuário nunca fica preso em "Anexar banco".
        self._cta("⬇  Exportar relatório", self._exportar)
        self.b_alt.pack_forget()
        self.steps.set_ativo(3)

        # a partir daqui é só apresentação — protegido para não travar nada
        try:
            self._render_cruzado(rc, detectados, df_sit, resumo)
        except Exception as exc:      # noqa: BLE001
            self.badge.set(f"{rc.total_programado} programadas · "
                           f"{rc.total_pendente} pendentes", "ok")
            try:   # a lista da tela sem a situação, para não ficar vazia
                self.tabela.preencher([
                    [r.get("EMPRESA", ""), r.get("FORNECEDOR", ""), r.get("PRV NF", ""),
                     _fmt_data(r.get("VENC")), _fmt_valor(r.get("VALOR")), ""]
                    for _, r in df_sit.head(2000).iterrows()])
                self.sec_pend.pack(fill="x")
            except Exception:   # noqa: BLE001 — só exibição
                pass
            self.app.toast.show(
                "Cruzamento concluído. Já dá para exportar — mas houve um "
                f"erro ao montar as tabelas da tela: {exc}", "warn", ms=8000)

    def _render_cruzado(self, rc, detectados, df_sit, resumo) -> None:
        from ..modules import dda_compras as DC

        # uma lista só: a cobrar + já vieram + programadas
        linhas, tags = [], []
        valores = {"prog": 0.0, "ok": 0.0, "cob": 0.0}
        for _, row in df_sit.head(2000).iterrows():
            tag, texto = DC.situacao(row.get(DC.COL_PROGRAMADA),
                                     row.get(DC.COL_COMPRAS),
                                     row.get(DC.COL_BANCO_DATA, ""))
            linhas.append([row.get("EMPRESA", ""), row.get("FORNECEDOR", ""),
                           row.get("PRV NF", ""), _fmt_data(row.get("VENC")),
                           _fmt_valor(row.get("VALOR")), texto])
            tags.append(tag)
            v = parse_valor_br(row.get("VALOR")) if not isinstance(
                row.get("VALOR"), (int, float)) else row.get("VALOR")
            if v is not None and v == v:
                valores[tag] += float(v)
        self.tabela.preencher(linhas, tags=tags)
        self._filtro = "todas"
        self.tabela.filtrar_tags(None)
        cont = self.tabela.contar_tags()
        self._pintar_pilulas(cont)
        if linhas:
            self.sec_pend.pack(fill="x", before=self.sec_semnota
                               if self.sec_semnota.winfo_manager() else None)
        else:
            self.sec_pend.pack_forget()

        # cartões (já estão na grade desde o início, mostrando "—")
        self.c_prog.set(cont.get("prog", 0), formatar_moeda(valores["prog"]))
        self.c_ok.set(cont.get("ok", 0),
                      "Compras + CNPJs da lista" if not resumo.erro
                      else "só CNPJs da lista — Compras não lida")
        self.c_pend.set(cont.get("cob", 0), formatar_moeda(valores["cob"]))

        # pagamentos do banco sem nota (melhoria vinda do DDA V7)
        sem_nota = getattr(rc, "pagamentos_nao_casados", []) or []
        if sem_nota:
            self.tab_semnota.preencher([
                [getattr(pg, "empresa_banco", ""),
                 getattr(pg, "favorecido", ""),
                 str(getattr(pg, "data", "")),
                 formatar_moeda(getattr(pg, "valor", None))]
                for pg in sem_nota[:200]
            ])
            self.sec_semnota.pack(fill="x")
        else:
            self.sec_semnota.pack_forget()

        # trava de conciliação: a conta entrada = saída fechou?
        conc = self._conciliar(rc)
        tipo = "ok" if (conc is None or conc.ok) else "err"
        a_cobrar = cont.get("cob", 0)
        base = f"{cont.get('prog', 0)} programadas · {a_cobrar} a cobrar"
        if sem_nota:
            base += f" · {len(sem_nota)} banco s/ nota"
        if conc is not None and not conc.ok:
            base += " · ⚠ conciliação não fechou"
        self.badge.set(base, tipo if a_cobrar == 0 or sem_nota else "warn")

        # (o botão "Exportar" e o passo 3 já foram ativados em _cruzado)
        msg = "Cruzamento concluído — " + " | ".join(detectados[:3])
        if resumo.erro:
            msg += (f". Não consegui ler a planilha de Compras ({resumo.erro}) — "
                    "'Já vieram' tem só os CNPJs da lista.")
        if conc is not None and not conc.ok:
            msg = ("⚠ CONCILIAÇÃO NÃO FECHOU — alguma nota pode ter se "
                   "perdido. Confira a aba ERROS do relatório.")
            self.app.toast.show(msg, "err", ms=9000)
        else:
            self.app.toast.show(msg, "warn" if resumo.erro else "ok",
                                ms=9000 if resumo.erro else 6000)

    def _conciliar(self, rc):
        """Roda a trava de conciliação do DDA V7 (nenhuma nota some calada)."""
        try:
            from ..vendor.organizador_dda.core.conciliacao import conciliar
            return conciliar(self.result, rc)
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    def _exportar(self) -> None:
        if self.result is None or self.runner.ocupado:
            return
        saida = filedialog.asksaveasfilename(
            title="Salvar relatório",
            defaultextension=".xlsx",
            initialdir=self.app.config.ultima_pasta("dda_saida") or None,
            initialfile=f"relatorio_dda_{timestamp_arquivo()}.xlsx",
            filetypes=[("Excel", "*.xlsx")])
        if not saida:
            return
        self.app.config.lembrar_pasta("dda_saida", saida)
        self._fase = "exportar"
        self._ocupado("Gerando relatório…")
        config_dda = self.app.config.config_dda()
        result, metricas, rc = self.result, self.metricas, self.rc
        cfg = self.app.config
        compras_path = cfg.get("dda_compras_path", default="") or ""
        nao_cobrar = cfg.get("dda_cnpjs_ja_veio", default=[]) or []
        abreviar = bool(cfg.get("dda_abreviar_fornecedor", default=True))
        feriados = cfg.get("feriados_nacionais", default=[]) or []

        def trabalho():
            from ..modules import dda_compras as DC
            from ..vendor.organizador_dda.excel.report_generator import (
                ExcelReportGenerator)
            # pendentes + programadas (amarelas), fornecedor abreviado
            df_rel = DC.montar_df_relatorio(result.df, rc, abreviar=abreviar)
            # "JÁ VEIO": planilha de Compras + CNPJs que não se cobra
            notas, erro = [], ""
            if compras_path:
                try:
                    notas = DC.ler_compras(Path(compras_path), DC.DiaUtil(feriados))
                except Exception as exc:       # noqa: BLE001 — relatório sai mesmo assim
                    erro = mensagem_erro_amigavel(exc)
            else:
                erro = "planilha de Compras não configurada"
            resumo = DC.marcar_ja_veio(df_rel, notas, nao_cobrar)
            resumo.erro = erro
            ExcelReportGenerator(result, config_dda, metricas, rc,
                                 df_relatorio=df_rel).gerar(Path(saida))
            return saida, resumo

        self.runner.executar(trabalho, self._exportado, self._falhou)

    def _exportado(self, carga) -> None:
        saida, resumo = carga
        self._livre()
        rc = self.rc
        historico.registrar(
            "dda", "Relatório semanal",
            resumo={
                "linhas": self.result.total_processado,
                "programados": rc.total_programado if rc else 0,
                "pendentes": rc.total_pendente if rc else self.result.total_processado,
                "ja_vieram_compras": resumo.total,
            },
            arquivos=[self.arquivo] + self.arquivos_banco, saida=saida)
        self.steps.set_ativo(4)
        self.b_alt.pack_forget()          # não faz sentido "Exportar sem cruzar" aqui
        self._registrar_saida(saida)
        if resumo.erro:
            self.badge.set("relatório exportado · sem Compras", "warn")
            self.app.toast.show(
                f"Relatório gerado, mas NÃO consegui ler a planilha de Compras "
                f"({resumo.erro}). A coluna COMPRAS só tem os CNPJs da lista.",
                "warn", ms=10000)
        else:
            conferir = (f", {resumo.por_nome_venc} por nome+venc (conferir)"
                        if resumo.por_nome_venc else "")
            self.badge.set(f"relatório exportado · {resumo.total} já vieram", "ok")
            self.app.toast.show(
                f"Relatório gerado. {resumo.total} nota(s) marcadas JÁ VEIO na "
                f"Planilha1 ({resumo.por_nf_nome + resumo.por_nf_venc} pela NF"
                f"{conferir}, {resumo.por_cnpj} pelo CNPJ).", "ok", ms=9000)
        self.app.atualizar_dashboard()

    def _consolidar(self) -> None:
        if self.runner.ocupado:
            return
        caminho = filedialog.askopenfilename(
            title="Selecione o relatório REVISADO para consolidar",
            initialdir=self.app.config.ultima_pasta("dda_saida") or None,
            filetypes=[("Excel", "*.xlsx")])
        if not caminho:
            return
        self.app.config.lembrar_pasta("dda_saida", caminho)
        self._fase = "consolidar"
        self._ocupado("Consolidando…")

        def trabalho():
            from ..vendor.organizador_dda.excel.consolidador import consolidar_arquivo
            # grava num arquivo NOVO (_consolidado.xlsx) — devolve o caminho
            return str(consolidar_arquivo(Path(caminho)))

        def concluido(saida):
            self._livre()
            historico.registrar("dda", "Consolidação",
                                arquivos=[caminho], saida=saida)
            self.badge.set("consolidado", "ok")
            self._registrar_saida(saida)
            self.app.toast.show(
                "Consolidação concluída num arquivo novo "
                f"({Path(saida).name}). Use 'Abrir arquivo'.", "ok", ms=7000)
            self.app.atualizar_dashboard()

        self.runner.executar(trabalho, concluido, self._falhou)

    # ------------------------------------------------------------------ #
    _ROTULO_FASE = {
        "processar":  "processamento do DDA",
        "cruzar":     "cruzamento com o banco",
        "exportar":   "geração do relatório",
        "consolidar": "consolidação",
    }

    def _falhou(self, exc: Exception) -> None:
        # libera os botões e esconde a barra de progresso, MAS mantém a
        # mensagem de erro visível na tela (o toast some em segundos e o
        # usuário ficava sem entender por que o botão não mudou).
        self.progresso.pack_forget()
        for b in (self.b_cta, self.b_trocar, self.b_cancelar,
                  self.b_alt, self.b_cons):
            b.configure(state="normal")
        rotulo = self._ROTULO_FASE.get(getattr(self, "_fase", ""), "operação")
        msg = mensagem_erro_amigavel(exc)
        self.badge.set(f"erro no {rotulo}", "err")
        self.lbl_status.configure(text=f"⚠  Falha no {rotulo}:  {msg}",
                                  text_color=T.VERMELHO)
        self.lbl_status.pack(fill="x", pady=(0, 8), after=self.steps)
        self.app.toast.show(f"Falha no {rotulo}: {msg}", "err", ms=9000)

    def _ocupado(self, msg: str) -> None:
        self.progresso.pack(fill="x", pady=(0, 2), after=self.steps)
        self.lbl_status.pack(fill="x", pady=(0, 8), after=self.progresso)
        self.progresso.set(0)
        self.lbl_status.configure(text=msg, text_color=T.INK_2)   # limpa erro
        for b in (self.b_cta, self.b_trocar, self.b_cancelar,
                  self.b_alt, self.b_cons):
            b.configure(state="disabled")

    def _livre(self) -> None:
        self.progresso.pack_forget()
        self.lbl_status.pack_forget()
        self.lbl_status.configure(text_color=T.INK_2)
        for b in (self.b_cta, self.b_trocar, self.b_cancelar,
                  self.b_alt, self.b_cons):
            b.configure(state="normal")


def _confirmar_descarte(parent) -> bool:
    """Pergunta antes de descartar dados já processados na tela."""
    return messagebox.askyesno(
        "Cancelar",
        "Já existe resultado na tela. Descartar tudo e recomeçar?",
        parent=parent)


def _fmt_data(v) -> str:
    if hasattr(v, "strftime"):
        return v.strftime("%d/%m/%Y")
    txt = str(v or "").strip()
    if not txt or txt.lower() in ("nan", "nat", "none"):
        return ""
    # datetime que veio como texto: "2026-07-29 00:00:00" → "29/07/2026"
    if len(txt) >= 10 and txt[4] == "-" and txt[7] == "-":
        a, m, d = txt[:4], txt[5:7], txt[8:10]
        return f"{d}/{m}/{a}"
    return txt


def _fmt_valor(v) -> str:
    """Valor robusto: aceita float, str ('783.6' / '1.234,56') ou vazio."""
    if v is None or (isinstance(v, float) and v != v):   # None ou NaN
        return ""
    if isinstance(v, (int, float)):
        return formatar_moeda(float(v))
    parsed = parse_valor_br(v)
    return formatar_moeda(parsed) if parsed is not None else str(v)
