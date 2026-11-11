"""
view_config.py — Configuração central (compartilhada por todos os módulos).
Cada lista é editada "um item por linha"; a gravação é atômica.
"""
from __future__ import annotations

import customtkinter as ctk

from ..core import theme as T
from .widgets import Card, botao, cabecalho


class ConfigView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app

        cabecalho(self, "Configurações",
                  "Uma configuração só para todos os módulos — salva em "
                  "~/.finahub/config.json (gravação atômica)."
                  , crumb="Compartilhado por todos os módulos", icone="⚙️").pack(fill="x", pady=(0, T.PAD))

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        scroll.grid_columnconfigure(0, weight=1, uniform="c")
        scroll.grid_columnconfigure(1, weight=1, uniform="c")

        # ── listas compartilhadas (DDA / Remessa) ────────────────────
        self.t_empresas = self._secao_lista(
            scroll, 0, 0, "🏢 Empresas válidas (DDA)",
            "Uma por linha — usadas na validação do DDA.",
            self.app.config.get("empresas_validas", default=[]))
        self.t_cnpjs = self._secao_lista(
            scroll, 0, 1, "🚫 CNPJs excluídos",
            "Raiz de 8 dígitos ou CNPJ completo — exclusão determinística "
            "no DDA e nos extratos.",
            self.app.config.get("cnpjs_excluidos", default=[]))
        self.t_termos = self._secao_lista(
            scroll, 1, 0, "🔍 Termos de siderúrgicas (remoção por texto)",
            "Rede de segurança — linhas contendo estes termos saem do DDA.",
            self.app.config.get("remover_texto", default=[]))
        self.t_feriados = self._secao_lista(
            scroll, 1, 1, "📅 Feriados fixos (DD/MM)",
            "Feriados móveis (Carnaval, Sexta Santa, Corpus Christi) são "
            "calculados automaticamente.",
            self.app.config.get("feriados_nacionais", default=[]))

        # ── Juntador RET ─────────────────────────────────────────────
        card_ret = Card(scroll)
        card_ret.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=(0, T.PAD))
        self._titulo(card_ret, "🔗 Juntador RET")
        self.sw_trailer = ctk.CTkSwitch(
            card_ret, text="Recalcular trailer pelo conteúdo real (recomendado)",
            font=T.F_NORMAL, progress_color=T.AZUL)
        self.sw_trailer.pack(anchor="w", padx=T.PAD, pady=(4, 2))
        if self.app.config.get("ret", "recalcular_trailer", default=True):
            self.sw_trailer.select()
        self.sw_renum = ctk.CTkSwitch(
            card_ret, text="Renumerar sequencial dos registros tipo 3",
            font=T.F_NORMAL, progress_color=T.AZUL)
        self.sw_renum.pack(anchor="w", padx=T.PAD, pady=(2, 4))
        if self.app.config.get("ret", "renumerar_sequencial", default=False):
            self.sw_renum.select()
        self.sw_estrutural = ctk.CTkSwitch(
            card_ret, text="Filtro estrutural (mantém só registros de detalhe)",
            font=T.F_NORMAL, progress_color=T.AZUL)
        self.sw_estrutural.pack(anchor="w", padx=T.PAD, pady=(2, 4))
        if self.app.config.get("ret", "filtro_estrutural", default=True):
            self.sw_estrutural.select()
        self.sw_excluir_usinas = ctk.CTkSwitch(
            card_ret, text="Ignorar notas de usina (não entram no TXT final)",
            font=T.F_NORMAL, progress_color=T.AZUL)
        self.sw_excluir_usinas.pack(anchor="w", padx=T.PAD, pady=(2, 4))
        if self.app.config.get("ret", "excluir_usinas", default=True):
            self.sw_excluir_usinas.select()
        self.sw_separar_empresa = ctk.CTkSwitch(
            card_ret, text="Separar por empresa (mantém a maioria, tira intrusos)",
            font=T.F_NORMAL, progress_color=T.AZUL)
        self.sw_separar_empresa.pack(anchor="w", padx=T.PAD, pady=(2, 4))
        if self.app.config.get("ret", "separar_por_empresa", default=True):
            self.sw_separar_empresa.select()
        ctk.CTkLabel(
            card_ret, font=T.F_PEQUENA, text_color=T.INK_3, justify="left",
            anchor="w", wraplength=430,
            text="Desligado, o trailer usa as 2 linhas fixas do programa antigo "
                 "(modo legado). Valide o 1º arquivo recalculado no sistema de "
                 "destino antes de adotar de vez.").pack(
            fill="x", padx=T.PAD, pady=(0, T.PAD))

        # ── Usinas ───────────────────────────────────────────────────
        card_usi = Card(scroll)
        card_usi.grid(row=2, column=1, sticky="nsew", padx=(8, 0), pady=(0, T.PAD))
        self._titulo(card_usi, "🏭 Usinas — corte de sufixo da NF")
        linha = ctk.CTkFrame(card_usi, fg_color="transparent")
        linha.pack(fill="x", padx=T.PAD, pady=(4, 4))
        ctk.CTkLabel(linha, text="Dígitos cortados do fim da NF (padrão):",
                     font=T.F_NORMAL, text_color=T.INK).pack(side="left")
        self.e_sufixo = ctk.CTkEntry(linha, width=60, font=T.F_NORMAL)
        self.e_sufixo.pack(side="left", padx=8)
        self.e_sufixo.insert(
            0, str(self.app.config.get("usinas", "nf_digitos_sufixo_padrao",
                                       default=2)))
        ctk.CTkLabel(
            card_usi, font=T.F_PEQUENA, text_color=T.INK_3, justify="left",
            anchor="w", wraplength=430,
            text="Regra especial (config.json): CSN com NF começando em 195 "
                 "corta 3 dígitos. O corte nunca deixa a NF menor que o tamanho "
                 "mínimo configurado — a proteção que faltava no programa antigo."
        ).pack(fill="x", padx=T.PAD, pady=(0, T.PAD))

        # ── Grupos de usina (classificação) — largura total ──────────
        card_grp = Card(scroll)
        card_grp.grid(row=3, column=0, columnspan=2, sticky="nsew",
                      pady=(0, T.PAD))
        self._titulo(card_grp, "🏭 Grupos de usina (classificação por nome)")
        ctk.CTkLabel(
            card_grp, font=T.F_PEQUENA, text_color=T.INK_3, justify="left",
            anchor="w", wraplength=900,
            text="Um grupo por linha, no formato  GRUPO: termo1; termo2; termo3. "
                 "A ORDEM importa — o 1º grupo cujo termo aparecer no nome "
                 "vence. Deixe SOLUÇÕES acima de USIMINAS (senão 'SOLUÇÕES "
                 "USIMINAS' cai em USIMINAS). Acentos são ignorados na "
                 "comparação.").pack(fill="x", padx=T.PAD, pady=(0, 2))
        self.t_grupos = ctk.CTkTextbox(
            card_grp, height=140, font=T.F_MONO, fg_color=T.CAMPO,
            border_width=1, border_color=T.BORDA, text_color=T.INK,
            corner_radius=8)
        self.t_grupos.pack(fill="x", padx=T.PAD, pady=(6, T.PAD))
        self.t_grupos.insert("1.0", self._grupos_para_texto(
            self.app.config.get("usinas", "padronizacao_empresa", default={})))

        # ── DDA × Compras ────────────────────────────────────────────
        card_cmp = Card(scroll)
        card_cmp.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(0, T.PAD))
        self._titulo(card_cmp, "📬 Organizador DDA × notas de Compras")
        ctk.CTkLabel(
            card_cmp, font=T.F_PEQUENA, text_color=T.INK_3, justify="left",
            anchor="w", wraplength=900,
            text="No relatório, a coluna ERROS da 1ª aba (Planilha1) recebe "
                 "\"JÁ VEIO\" + data/hora do e-mail quando a nota está na planilha "
                 "de Compras, ou \"JÁ VEIO (CNPJ NA LISTA)\" para os CNPJs abaixo."
                 ).pack(fill="x", padx=T.PAD, pady=(0, 4))
        lin = ctk.CTkFrame(card_cmp, fg_color="transparent")
        lin.pack(fill="x", padx=T.PAD, pady=(2, 6))
        ctk.CTkLabel(lin, text="Planilha de Compras:", font=T.F_NORMAL,
                     text_color=T.INK).pack(side="left")
        self.e_compras = ctk.CTkEntry(lin, font=T.F_PEQUENA, border_color=T.BORDA,
                                      fg_color=T.CARD)
        self.e_compras.pack(side="left", fill="x", expand=True, padx=8)
        self.e_compras.insert(0, str(self.app.config.get("dda_compras_path", default="") or ""))
        botao(lin, "Escolher…", self._escolher_compras, primario=False,
              width=100, height=32).pack(side="left")
        duas = ctk.CTkFrame(card_cmp, fg_color="transparent")
        duas.pack(fill="x", padx=T.PAD, pady=(0, T.PAD))
        duas.grid_columnconfigure(0, weight=1, uniform="d")
        duas.grid_columnconfigure(1, weight=1, uniform="d")
        self.t_nao_cobrar = self._caixa_lista(
            duas, 0, "CNPJs que NÃO cobro de Compras (raiz — 8 primeiros dígitos)",
            "Coisas do Contas a Pagar ou de outras áreas. Saem como JÁ VEIO.",
            self.app.config.get("dda_cnpjs_ja_veio", default=[]))
        self.t_manter = self._caixa_lista(
            duas, 1, "Fornecedores que NÃO saem como usina",
            "Termo no nome (ex.: SOLUCOES). Ficam na lista e cruzam com o banco.",
            self.app.config.get("dda_usinas_manter", default=[]))

        # ── salvar ───────────────────────────────────────────────────
        rodape = ctk.CTkFrame(self, fg_color="transparent")
        rodape.pack(fill="x", pady=(8, 0))
        botao(rodape, "💾  Salvar configurações", self._salvar).pack(side="left")
        ctk.CTkLabel(rodape, text=str(self.app.config.path),
                     font=T.F_PEQUENA, text_color=T.INK_3).pack(side="left", padx=12)

    # ------------------------------------------------------------------ #
    def _secao_lista(self, master, row, col, titulo, dica, itens):
        card = Card(master)
        card.grid(row=row, column=col, sticky="nsew",
                  padx=(0, 8) if col == 0 else (8, 0), pady=(0, T.PAD))
        self._titulo(card, titulo)
        ctk.CTkLabel(card, text=dica, font=T.F_PEQUENA, text_color=T.INK_3,
                     anchor="w", wraplength=430, justify="left").pack(
            fill="x", padx=T.PAD)
        caixa = ctk.CTkTextbox(card, height=120, font=T.F_MONO, fg_color=T.CAMPO,
                               border_width=1, border_color=T.BORDA,
                               text_color=T.INK, corner_radius=8)
        caixa.pack(fill="x", padx=T.PAD, pady=(6, T.PAD))
        caixa.insert("1.0", "\n".join(str(i) for i in itens))
        return caixa

    def _caixa_lista(self, master, col, titulo, dica, itens):
        box = ctk.CTkFrame(master, fg_color="transparent")
        box.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (8, 0))
        ctk.CTkLabel(box, text=titulo, font=(T.FONTE, 12, "bold"),
                     text_color=T.INK, anchor="w").pack(fill="x")
        ctk.CTkLabel(box, text=dica, font=T.F_PEQUENA, text_color=T.INK_3,
                     anchor="w", wraplength=420, justify="left").pack(fill="x")
        caixa = ctk.CTkTextbox(box, height=110, font=T.F_MONO, fg_color=T.CAMPO,
                               border_width=1, border_color=T.BORDA,
                               text_color=T.INK, corner_radius=8)
        caixa.pack(fill="x", pady=(4, 0))
        caixa.insert("1.0", "\n".join(str(i) for i in itens))
        return caixa

    def _escolher_compras(self) -> None:
        from tkinter import filedialog
        c = filedialog.askopenfilename(
            title="Planilha de notas recebidas de Compras",
            filetypes=[("Excel", "*.xlsx *.xlsm"), ("Todos", "*.*")])
        if c:
            self.e_compras.delete(0, "end")
            self.e_compras.insert(0, c)

    @staticmethod
    def _titulo(card, texto: str) -> None:
        ctk.CTkLabel(card, text=texto, font=(T.FONTE, 13, "bold"),
                     text_color=T.AZUL_ESCURO, anchor="w").pack(
            fill="x", padx=T.PAD, pady=(12, 2))

    @staticmethod
    def _linhas(caixa: ctk.CTkTextbox) -> list:
        return [l.strip() for l in caixa.get("1.0", "end").splitlines() if l.strip()]

    @staticmethod
    def _grupos_para_texto(grupos: dict) -> str:
        """{'USIMINAS': ['A','B']} → 'USIMINAS: A; B' (uma linha por grupo)."""
        return "\n".join(f"{g}: {'; '.join(termos)}"
                         for g, termos in (grupos or {}).items())

    @staticmethod
    def _texto_para_grupos(texto: str) -> dict:
        """Faz o caminho inverso, preservando a ordem das linhas (prioridade)."""
        grupos: dict = {}
        for linha in texto.splitlines():
            linha = linha.strip()
            if not linha or ":" not in linha:
                continue
            nome, resto = linha.split(":", 1)
            nome = nome.strip()
            termos = [t.strip() for t in resto.split(";") if t.strip()]
            if nome and termos:
                grupos[nome] = termos
        return grupos

    def _salvar(self) -> None:
        cfg = self.app.config
        cfg.set(self._linhas(self.t_empresas), "empresas_validas")
        cfg.set(self._linhas(self.t_cnpjs), "cnpjs_excluidos")
        cfg.set(self._linhas(self.t_termos), "remover_texto")
        cfg.set(self._linhas(self.t_feriados), "feriados_nacionais")
        cfg.set(bool(self.sw_trailer.get()), "ret", "recalcular_trailer")
        cfg.set(bool(self.sw_renum.get()), "ret", "renumerar_sequencial")
        cfg.set(bool(self.sw_estrutural.get()), "ret", "filtro_estrutural")
        cfg.set(bool(self.sw_excluir_usinas.get()), "ret", "excluir_usinas")
        cfg.set(bool(self.sw_separar_empresa.get()), "ret", "separar_por_empresa")
        try:
            cfg.set(max(0, int(self.e_sufixo.get())),
                    "usinas", "nf_digitos_sufixo_padrao")
        except ValueError:
            self.app.toast.show("Dígitos de sufixo precisa ser um número.", "err")
            return
        grupos = self._texto_para_grupos(self.t_grupos.get("1.0", "end"))
        if grupos:
            cfg.set(grupos, "usinas", "padronizacao_empresa")
        cfg.set(self.e_compras.get().strip(), "dda_compras_path")
        raizes = []
        for l in self._linhas(self.t_nao_cobrar):
            dig = "".join(ch for ch in l if ch.isdigit())
            if len(dig) < 8:
                self.app.toast.show(f"CNPJ '{l}' tem menos de 8 dígitos.", "err")
                return
            raizes.append(dig[:8])
        cfg.set(sorted(set(raizes)), "dda_cnpjs_ja_veio")
        cfg.set(self._linhas(self.t_manter), "dda_usinas_manter")
        cfg.salvar()
        self.app.toast.show("Configurações salvas — valem para todos os módulos.",
                            "ok")
