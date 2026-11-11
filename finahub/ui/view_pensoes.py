"""
view_pensoes.py — Tela "Pensões".

1. Escolhe o Excel do DP (e, na 1ª vez, a planilha com a aba CADASTRO).
2. Mostra quem paga mais de uma pensão: o usuário digita o valor de cada
   pensão extra (só se sabe pela folha física); a principal fica com o resto.
3. Confere (total do CSV = total do DP) e salva o CSV de importação.
"""
from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog
from typing import Dict, List, Optional, Tuple

import customtkinter as ctk

from ..core import historico, theme as T
from ..core.utils import abrir_no_sistema, mensagem_erro_amigavel, parse_valor_br
from .widgets import (Badge, Card, EmptyState, MetricCard, StepBar, Tabela,
                      ThreadRunner, botao, cabecalho)

PASTA_IMPORTACAO_PADRAO = r"\\10.120.108.175\Scanner\Administrativo\CONTAS A PAGAR\IMPORTAÇÃO"


def _centavos_digitados(texto: str) -> Tuple[Optional[int], bool]:
    """('', ok) → (None, True) | ('abc') → (None, False) | ('100,50') → (10050, True)"""
    t = (texto or "").strip()
    if not t:
        return None, True
    f = parse_valor_br(t)
    if f is None:
        return None, False
    return int(round(f * 100)), True


class PensoesView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.runner = ThreadRunner(self)
        self.dp_path: Optional[Path] = None
        self.prep = None
        self.resultado = None
        self.saida_gerada: Optional[Path] = None
        self._area_visivel = False
        # chave "100002-A" → campo digitado / label do restante
        self._entradas: Dict[str, ctk.CTkEntry] = {}
        self._restantes: Dict[str, ctk.CTkLabel] = {}
        # matrícula → campo da pensionista principal (casos com 2 pensionistas)
        self._principais: Dict[str, ctk.CTkEntry] = {}

        cabecalho(
            self, "Pensões",
            "Lê o Excel do DP, divide quem paga mais de uma pensão e gera o CSV "
            "de importação com o título do mês.",
            crumb="DP → CSV de importação", icone="👪").pack(fill="x", pady=(0, 10))

        self.steps = StepBar(self, ["Excel do DP", "Mais de uma pensão", "Gerar CSV"])
        self.steps.pack(fill="x", pady=(0, T.PAD))

        acoes = Card(self)
        acoes.pack(fill="x", pady=(0, T.PAD))
        box = ctk.CTkFrame(acoes, fg_color="transparent")
        box.pack(fill="x", padx=T.PAD, pady=(T.PAD, 6))
        self.b_dp = botao(box, "📄  Excel do DP", self._selecionar)
        self.b_dp.pack(side="left")
        self.b_cad = botao(box, "🗂  Planilha do cadastro", self._selecionar_cadastro,
                           primario=False)
        self.b_cad.pack(side="left", padx=8)
        self.badge = Badge(box, "aguardando Excel do DP", "info")
        self.badge.pack(side="right")

        info = ctk.CTkFrame(acoes, fg_color="transparent")
        info.pack(fill="x", padx=T.PAD, pady=(0, T.PAD))
        self.lbl_dp = ctk.CTkLabel(info, text="Excel do DP: nenhum selecionado",
                                   font=T.F_PEQUENA, text_color=T.INK_3, anchor="w")
        self.lbl_dp.pack(fill="x")
        self.lbl_cad = ctk.CTkLabel(info, text="", font=T.F_PEQUENA,
                                    text_color=T.INK_3, anchor="w")
        self.lbl_cad.pack(fill="x")
        self._atualizar_lbl_cadastro()

        self.vazio = EmptyState(
            self, "👪", "Selecione o Excel de pensão que o DP mandou",
            "Eu busco cada colaborador no CADASTRO da sua planilha de pensão, "
            "mostro quem paga mais de uma pensão para você digitar os valores "
            "e gero o CSV pronto para importar (título MM-AAAA-SAL, vencimento "
            "do DP).")
        self.vazio.pack(fill="both", expand=True)

        # ── área de trabalho (rolável) ───────────────────────────────
        self.area = ctk.CTkScrollableFrame(self, fg_color="transparent")

        cards = ctk.CTkFrame(self.area, fg_color="transparent")
        for i in range(4):
            cards.grid_columnconfigure(i, weight=1, uniform="m")
        self.c_qtd = MetricCard(cards, "Colaboradores")
        self.c_total = MetricCard(cards, "Total do DP")
        self.c_titulo = MetricCard(cards, "Título")
        self.c_venc = MetricCard(cards, "Vencimento")
        for i, c in enumerate((self.c_qtd, self.c_total, self.c_titulo, self.c_venc)):
            c.grid(row=0, column=i, sticky="nsew",
                   padx=(0 if i == 0 else 10, 0), pady=(0, 10))
        cards.pack(fill="x", pady=(0, 6))

        # avisos + quadro de divisões (re-empacotados a cada leitura)
        self.meio = ctk.CTkFrame(self.area, fg_color="transparent")
        self.meio.pack(fill="x")
        self.lbl_avisos = ctk.CTkLabel(self.meio, text="", font=T.F_NORMAL,
                                       text_color=T.AMARELO, anchor="w",
                                       justify="left", wraplength=900)

        # quadro "mais de uma pensão"
        self.card_div = Card(self.meio)
        ctk.CTkLabel(self.card_div, text="Mais de uma pensão", font=T.F_SECAO,
                     text_color=T.AZUL_ESCURO, anchor="w").pack(
            fill="x", padx=T.PAD, pady=(T.PAD, 0))
        ctk.CTkLabel(
            self.card_div,
            text="Digite o valor de UMA das pensionistas conforme a folha — a outra "
                 "recebe o restante sozinha. Quem não foi dividido neste mês: "
                 "use o botão abaixo depois de digitar os que têm divisão.",
            font=T.F_PEQUENA, text_color=T.INK_3, anchor="w").pack(
            fill="x", padx=T.PAD, pady=(0, 8))
        self.grade_div = ctk.CTkFrame(self.card_div, fg_color="transparent")
        self.grade_div.pack(fill="x", padx=T.PAD, pady=(0, 6))
        # nem todo mês o "-A" é dividido: zera de uma vez os que ficaram vazios
        botao(self.card_div, "0  Sem divisão nos vazios", self._zerar_vazios,
              primario=False, height=30).pack(anchor="w", padx=T.PAD, pady=(0, T.PAD))

        # ações
        barra = ctk.CTkFrame(self.area, fg_color="transparent")
        barra.pack(fill="x", pady=(T.PAD, 8))
        self.b_conferir = self.b_cta = botao(barra, "✔  Conferir", self._conferir)
        self.b_conferir.pack(side="left")
        self.b_salvar = botao(barra, "💾  Salvar CSV", self._gravar, state="disabled")
        self.b_salvar.pack(side="left", padx=8)
        self.b_abrir = botao(barra, "📂  Abrir", self._abrir_saida,
                             primario=False, width=104)
        self.b_pasta = botao(barra, "📁  Pasta", self._abrir_pasta,
                             primario=False, width=104)
        self.lbl_conf = ctk.CTkLabel(barra, text="", font=T.F_NORMAL,
                                     text_color=T.INK, anchor="w", justify="left")
        self.lbl_conf.pack(side="left", padx=12)

        self.tabela = Tabela(
            self.area,
            ["Matrícula", "Colaborador", "Cód.", "Pensionista", "Título", "Valor"],
            larguras=[80, 240, 70, 280, 110, 100], altura=300, busca=True,
            exportar=True, nome_export="pensoes",
            alinhamentos=["w", "w", "w", "w", "w", "e"])
        self.tabela.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ #
    # Cadastro                                                             #
    # ------------------------------------------------------------------ #
    def _cadastro_path(self) -> Optional[Path]:
        p = self.app.config.get("pensoes", "cadastro_path", default="") or ""
        return Path(p) if p else None

    def _atualizar_lbl_cadastro(self) -> None:
        p = self._cadastro_path()
        self.lbl_cad.configure(
            text=f"Cadastro (aba CADASTRO): {p}" if p
            else "Cadastro: ainda não escolhido — vou pedir a planilha PENSÃO - ALFAMETAL.xlsx")

    def _selecionar_cadastro(self) -> bool:
        atual = self._cadastro_path()
        c = filedialog.askopenfilename(
            title="Planilha com a aba CADASTRO (ex.: PENSÃO - ALFAMETAL.xlsx)",
            initialdir=str(atual.parent) if atual else None,
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("Todos", "*.*")])
        if not c:
            return False
        self.app.config.set(c, "pensoes", "cadastro_path")
        self.app.config.persistir_chave(c, "pensoes", "cadastro_path")
        self._atualizar_lbl_cadastro()
        if self.dp_path:
            self._carregar()
        return True

    # ------------------------------------------------------------------ #
    # Etapa 1 — ler DP + cadastro                                          #
    # ------------------------------------------------------------------ #
    def _selecionar(self) -> None:
        if self.runner.ocupado:
            return
        c = filedialog.askopenfilename(
            title="Excel de pensão do DP",
            initialdir=self.app.config.ultima_pasta("pensoes") or None,
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("Todos", "*.*")])
        if not c:
            return
        self.app.config.lembrar_pasta("pensoes", c)
        self.dp_path = Path(c)
        self.lbl_dp.configure(text=f"Excel do DP: {self.dp_path.name}")
        cad = self._cadastro_path()
        if not cad or not cad.exists():
            self.app.toast.show("Agora escolha a planilha com a aba CADASTRO.",
                                "info", ms=5000)
            if not self._selecionar_cadastro():
                return
        self._carregar()

    def _carregar(self) -> None:
        if self.runner.ocupado or not self.dp_path:
            return
        cad = self._cadastro_path()
        if not cad:
            return
        self.badge.set("lendo…", "info")
        dp = self.dp_path
        from ..modules import pensoes as P
        self.runner.executar(lambda: P.processar(dp, cad),
                             self._carregado, self._falhou)

    def _carregado(self, prep) -> None:
        from ..modules import pensoes as P
        self.prep = prep
        self.resultado = None
        self.saida_gerada = None
        self.b_abrir.pack_forget()
        self.b_pasta.pack_forget()
        if not self._area_visivel:
            self.vazio.pack_forget()
            self.area.pack(fill="both", expand=True)
            self._area_visivel = True

        dp = prep.dp
        self.c_qtd.set(len(dp.linhas),
                       f"{len(prep.casos)} com mais de uma pensão")
        bate = dp.total_rodape is None or dp.total_rodape == dp.total
        self.c_total.set(f"R$ {P.valor_br(dp.total)}",
                         "confere com o rodapé do DP" if bate else "⚠ difere do rodapé")
        if prep.competencia:
            self.c_titulo.set(P.titulo_base(prep.competencia),
                              f"2ª p/ mesma pensionista: {P.titulo_repetido(prep.competencia)}")
        else:
            self.c_titulo.set("—", "sem competência")
        self.c_venc.set(prep.vencimento.strftime("%d/%m/%Y") if prep.vencimento else "—",
                        "data de pagamento do DP")

        avisos = list(prep.avisos)
        for l in prep.sem_cadastro:
            avisos.append(f"⛔ Matrícula {l.matricula} ({l.nome}) não está no "
                          "CADASTRO — cadastre na planilha e selecione o DP de novo.")
        self.lbl_avisos.pack_forget()
        self.card_div.pack_forget()
        if avisos:
            self.lbl_avisos.configure(text="\n".join(avisos))
            self.lbl_avisos.pack(fill="x", pady=(0, 8))

        self._montar_grade_divisao()
        self.tabela.preencher([])
        self.lbl_conf.configure(text="")
        self.b_salvar.configure(state="disabled")
        self.steps.set_ativo(1)
        if prep.sem_cadastro:
            self.badge.set("falta cadastro", "err")
        elif prep.casos:
            self.badge.set(f"digite {sum(len(c.extras) for c in prep.casos)} valor(es)", "warn")
        else:
            self.badge.set("pronto para conferir", "ok")
        self._conferir(silencioso=True)

    def _entry_valor(self, dica: str = "") -> ctk.CTkEntry:
        e = ctk.CTkEntry(self.grade_div, width=120, font=T.F_NORMAL,
                         border_color=T.BORDA, fg_color=T.CARD,
                         placeholder_text=dica, justify="right")
        e.bind("<Return>", lambda _e: self._conferir())
        return e

    def _montar_grade_divisao(self) -> None:
        """
        Uma linha por pensionista. Com 2 pensionistas o usuário digita o valor
        de QUALQUER uma e a outra recebe o restante (DP − digitado).
        Com 3+ (-A, -B…) digita as extras e a principal fica com o restante.
        """
        from ..modules import pensoes as P
        for w in self.grade_div.winfo_children():
            w.destroy()
        self._entradas.clear()
        self._principais.clear()
        self._restantes.clear()
        if not self.prep.casos:
            return
        self.card_div.pack(fill="x", pady=(0, 4))

        ultimos = self.app.config.get("pensoes", "ultimos_valores", default={}) or {}
        cols = ["Colaborador", "Total DP", "Pensionista", "Valor"]
        larg = [300, 100, 380, 130]
        for c, (nome, w) in enumerate(zip(cols, larg)):
            self.grade_div.grid_columnconfigure(c, minsize=w)
            ctk.CTkLabel(self.grade_div, text=nome.upper(), font=(T.FONTE, 10, "bold"),
                         text_color=T.INK_2, anchor="w").grid(
                row=0, column=c, sticky="w", padx=4, pady=(0, 4))
        lin = 1
        for caso in self.prep.casos:
            mat = caso.linha.matricula
            dupla = len(caso.extras) == 1
            # separador entre colaboradores
            ctk.CTkFrame(self.grade_div, height=1, fg_color=T.BORDA).grid(
                row=lin, column=0, columnspan=4, sticky="ew", pady=(2, 2))
            lin += 1
            ctk.CTkLabel(self.grade_div, text=f"{mat} · {caso.linha.nome}",
                         font=(T.FONTE, 12, "bold"), text_color=T.INK, anchor="w").grid(
                row=lin, column=0, sticky="w", padx=4, pady=3)
            ctk.CTkLabel(self.grade_div, text=P.valor_br(caso.linha.centavos),
                         font=(T.FONTE, 12, "bold"), text_color=T.INK, anchor="e").grid(
                row=lin, column=1, sticky="e", padx=4)
            # pensionista principal
            ctk.CTkLabel(self.grade_div, text=caso.principal_nome, font=T.F_PEQUENA,
                         text_color=T.INK, anchor="w").grid(row=lin, column=2, sticky="w", padx=4)
            if dupla:
                ep = self._entry_valor()
                ep.grid(row=lin, column=3, sticky="w", padx=4, pady=3)
                ep.bind("<KeyRelease>", lambda _e, c=caso: self._sincronizar(c, "principal"))
                self._principais[mat] = ep
            else:
                rest = ctk.CTkLabel(self.grade_div, text="", font=T.F_PEQUENA,
                                    text_color=T.INK_3, anchor="e", width=120)
                rest.grid(row=lin, column=3, sticky="w", padx=4)
                self._restantes[mat] = rest
            lin += 1
            # pensões extras (-A, -B…)
            for ex in caso.extras:
                mesmo = ex.cod == caso.principal_cod
                ctk.CTkLabel(self.grade_div,
                             text=ex.pensionista + ("  (mesma pensionista, 2º título)" if mesmo else ""),
                             font=T.F_PEQUENA, text_color=T.INK, anchor="w").grid(
                    row=lin, column=2, sticky="w", padx=4)
                ant = ultimos.get(ex.chave)
                dica = f"mês passado {P.valor_br(int(ant))}" if ant is not None else ""
                e = self._entry_valor(dica)
                e.grid(row=lin, column=3, sticky="w", padx=4, pady=3)
                e.bind("<KeyRelease>", lambda _e, c=caso: self._sincronizar(c, "extra"))
                self._entradas[ex.chave] = e
                lin += 1
        self._atualizar_restantes()

    @staticmethod
    def _set_texto(e: ctk.CTkEntry, texto: str) -> None:
        e.delete(0, "end")
        if texto:
            e.insert(0, texto)

    def _sincronizar(self, caso, origem: str) -> None:
        """Dupla: o campo digitado define o outro (total DP − digitado)."""
        from ..modules import pensoes as P
        ep = self._principais.get(caso.linha.matricula)
        if ep is not None and len(caso.extras) == 1:
            ee = self._entradas[caso.extras[0].chave]
            fonte, alvo = (ep, ee) if origem == "principal" else (ee, ep)
            v, ok = _centavos_digitados(fonte.get())
            if v is None and ok:
                self._set_texto(alvo, "")
            elif ok:
                self._set_texto(alvo, P.valor_br(caso.linha.centavos - v))
        self._ao_digitar()

    def _valores(self) -> Tuple[Dict[str, Optional[int]], List[str]]:
        vals: Dict[str, Optional[int]] = {}
        invalidos: List[str] = []
        for chave, e in self._entradas.items():
            v, ok = _centavos_digitados(e.get())
            if not ok:
                invalidos.append(chave)
            vals[chave] = v
        return vals, invalidos

    def _atualizar_restantes(self) -> None:
        """Pinta a borda dos campos: verde = fechou com o DP, vermelho = erro."""
        from ..modules import pensoes as P
        vals, invalidos = self._valores()
        for caso in self.prep.casos:
            mat = caso.linha.matricula
            chaves = [ex.chave for ex in caso.extras]
            campos = [self._entradas[k] for k in chaves]
            if mat in self._principais:
                campos.append(self._principais[mat])
            if any(k in invalidos for k in chaves) or (
                    mat in self._principais
                    and not _centavos_digitados(self._principais[mat].get())[1]):
                estado, texto = "erro", "valor inválido"
            elif any(vals.get(k) is None for k in chaves):
                estado, texto = "vazio", "aguardando"
            else:
                resto = caso.linha.centavos - sum(vals[k] for k in chaves)
                negativo = resto < 0 or any(vals[k] < 0 for k in chaves)
                estado = "erro" if negativo else "ok"
                texto = P.valor_br(resto)
            cor = {"erro": T.VERMELHO, "ok": T.VERDE}.get(estado, T.BORDA)
            for c in campos:
                # só reconfigura se mudou — cada configure redesenha o campo
                if c.cget("border_color") != cor:
                    c.configure(border_color=cor)
            lbl = self._restantes.get(mat)
            if lbl is not None:
                lbl.configure(text=texto, text_color=T.INK_3 if estado == "vazio" else cor)

    def _zerar_vazios(self) -> None:
        """Quem ficou sem nada digitado: tudo para a principal (extra = 0)."""
        from ..modules import pensoes as P
        n = 0
        for caso in self.prep.casos:
            ep = self._principais.get(caso.linha.matricula)
            for ex in caso.extras:
                e = self._entradas[ex.chave]
                if not e.get().strip() and (ep is None or not ep.get().strip()):
                    e.insert(0, "0")
                    if ep is not None:
                        self._set_texto(ep, P.valor_br(caso.linha.centavos))
                    n += 1
        if n:
            self._ao_digitar()
            self._conferir(silencioso=True)

    def _ao_digitar(self) -> None:
        self._atualizar_restantes()
        # qualquer mudança invalida a conferência anterior
        if self.resultado is not None:
            self.resultado = None
            self.b_salvar.configure(state="disabled")
            self.lbl_conf.configure(text="valores alterados — clique em Conferir",
                                    text_color=T.INK_3)
            self.b_cta = self.b_conferir

    # ------------------------------------------------------------------ #
    # Etapa 2 — conferir                                                   #
    # ------------------------------------------------------------------ #
    def _conferir(self, silencioso: bool = False) -> None:
        if not self.prep:
            return
        from ..modules import pensoes as P
        vals, invalidos = self._valores()
        cfg = self.app.config.get("pensoes", default={}) or {}
        r = P.montar(self.prep, vals, cfg)
        if invalidos:
            r.erros.insert(0, f"{len(invalidos)} valor(es) digitado(s) inválido(s).")
        self.tabela.preencher([
            [l.matricula, l.colaborador, l.cod, l.fornecedor, l.titulo,
             P.valor_br(l.centavos)] for l in r.linhas])
        if r.ok and not invalidos:
            self.resultado = r
            self.b_salvar.configure(state="normal")
            self.b_cta = self.b_salvar
            self.lbl_conf.configure(
                text=f"✔ {len(r.linhas)} linhas · R$ {P.valor_br(r.total)} "
                     "— bate com o DP", text_color=T.VERDE)
            self.badge.set("pronto para salvar", "ok")
            self.steps.set_ativo(2)
        else:
            self.resultado = None
            self.b_salvar.configure(state="disabled")
            self.b_cta = self.b_conferir
            pend = r.erros[:4] + ([f"… e mais {len(r.erros) - 4}"] if len(r.erros) > 4 else [])
            self.lbl_conf.configure(text="\n".join(pend), text_color=T.VERMELHO)
            if not silencioso:
                self.app.toast.show("Há pendências — veja ao lado do botão Conferir.",
                                    "warn", ms=6000)

    def _falhou(self, exc: Exception) -> None:
        self.badge.set("erro", "err")
        self.app.toast.show(mensagem_erro_amigavel(exc), "err", ms=9000)

    # ------------------------------------------------------------------ #
    # Etapa 3 — gravar                                                     #
    # ------------------------------------------------------------------ #
    def _gravar(self) -> None:
        if not self.resultado or not self.resultado.ok:
            return
        from ..modules import pensoes as P
        r = self.resultado
        pasta = self.app.config.ultima_pasta("pensoes_saida")
        if not pasta and os.path.isdir(PASTA_IMPORTACAO_PADRAO):
            pasta = PASTA_IMPORTACAO_PADRAO
        mes = r.titulo.rsplit("-", 1)[0] if r.titulo else ""
        saida = filedialog.asksaveasfilename(
            title="Salvar CSV de importação",
            defaultextension=".csv",
            initialdir=pasta or None,
            initialfile=f"PENSÃO - ALFAMETAL - {mes}.csv",
            filetypes=[("CSV", "*.csv")])
        if not saida:
            return
        self.app.config.lembrar_pasta("pensoes_saida", saida)
        try:
            P.gravar(r, Path(saida))
        except Exception as exc:      # noqa: BLE001
            self.badge.set("erro ao gravar", "err")
            self.app.toast.show(mensagem_erro_amigavel(exc), "err", ms=8000)
            return
        self.saida_gerada = Path(saida)
        self.b_abrir.pack(side="left", padx=(0, 8), before=self.lbl_conf)
        self.b_pasta.pack(side="left", before=self.lbl_conf)

        # guarda os valores digitados como sugestão para o mês seguinte
        vals, _ = self._valores()
        ultimos = dict(self.app.config.get("pensoes", "ultimos_valores", default={}) or {})
        ultimos.update({k: v for k, v in vals.items() if v is not None})
        self.app.config.set(ultimos, "pensoes", "ultimos_valores")
        try:
            self.app.config.persistir_chave(ultimos, "pensoes", "ultimos_valores")
        except Exception:             # noqa: BLE001
            pass

        historico.registrar(
            "pensoes", f"CSV de pensão {r.titulo}",
            resumo={"linhas": len(r.linhas), "total": r.total / 100,
                    "divisoes": len(self.prep.casos), "titulo": r.titulo},
            arquivos=[self.dp_path], saida=str(saida))
        self.badge.set("CSV gerado", "ok")
        self.app.toast.show("CSV gerado. Importe no sistema e confira os títulos.",
                            "ok", ms=7000)
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
