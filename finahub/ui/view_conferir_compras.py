"""
view_conferir_compras.py — Tela "Conferir Compras".

Bate a pasta COMPRAS do Outlook com a planilha NOTAS - COMPRAS e mostra as
notas que a automação deixou de fora (inclusive quando o fluxo nem rodou).
"Incluir na planilha" coloca essas notas em "Notas recebidas" pelo Excel,
com backup antes.
"""
from __future__ import annotations

from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from ..core import historico, theme as T
from ..core.paths import APP_DIR
from ..core.utils import mensagem_erro_amigavel
from .widgets import (Badge, Card, EmptyState, MetricCard, Tabela, ThreadRunner,
                      botao, cabecalho)

_COLS = ["Recebido", "Remetente", "Empresa", "Fornecedor", "AF", "Vencimento",
         "NF", "Como achou", "Motivo"]


class ConferirComprasView(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.runner = ThreadRunner(self)
        self.resultado = None
        self._area_visivel = False

        cabecalho(
            self, "Conferir Compras",
            "Confere se todas as notas que Compras mandou por e-mail (pasta "
            "COMPRAS do Outlook) estão na planilha NOTAS - COMPRAS.",
            crumb="Outlook × planilha de notas", icone="📬").pack(fill="x", pady=(0, T.PAD))

        acoes = Card(self)
        acoes.pack(fill="x", pady=(0, T.PAD))
        box = ctk.CTkFrame(acoes, fg_color="transparent")
        box.pack(fill="x", padx=T.PAD, pady=(T.PAD, 6))
        self.b_conferir = self.b_cta = botao(box, "🔍  Conferir agora", self._conferir)
        self.b_conferir.pack(side="left")
        ctk.CTkLabel(box, text="Últimos", font=T.F_NORMAL, text_color=T.INK).pack(side="left", padx=(16, 4))
        self.e_dias = ctk.CTkEntry(box, width=56, font=T.F_NORMAL, justify="center",
                                   border_color=T.BORDA, fg_color=T.CARD)
        self.e_dias.pack(side="left")
        self.e_dias.insert(0, str(self._cfg().get("dias", 30)))
        ctk.CTkLabel(box, text="dias", font=T.F_NORMAL, text_color=T.INK).pack(side="left", padx=4)
        self.badge = Badge(box, "não conferido ainda", "info")
        self.badge.pack(side="right")

        cfg = self._cfg()
        ctk.CTkLabel(
            acoes, font=T.F_PEQUENA, text_color=T.INK_3, anchor="w", justify="left",
            text=(f"Outlook: {cfg.get('conta', '')} › pasta {cfg.get('pasta', 'COMPRAS')} · "
                  f"remetentes: {', '.join(cfg.get('remetentes', []))} · "
                  f"desde no mínimo {self._inicio_br()} (início da automação) · só leitura")
        ).pack(fill="x", padx=T.PAD, pady=(0, T.PAD))

        self.vazio = EmptyState(
            self, "📬", "Clique em Conferir agora",
            "O ALAN lê os e-mails de Compras no seu Outlook (sem mexer neles), "
            "extrai as notas de cada um e compara com a planilha. Se alguma nota "
            "ficou de fora, você pode incluí-la na planilha com um clique.")
        self.vazio.pack(fill="both", expand=True)

        self.area = ctk.CTkScrollableFrame(self, fg_color="transparent")
        cards = ctk.CTkFrame(self.area, fg_color="transparent")
        for i in range(4):
            cards.grid_columnconfigure(i, weight=1, uniform="m")
        self.c_emails = MetricCard(cards, "E-mails lidos")
        self.c_notas = MetricCard(cards, "Notas nos e-mails")
        self.c_ok = MetricCard(cards, "Na planilha", T.VERDE)
        self.c_falta = MetricCard(cards, "Fora da planilha", T.VERMELHO)
        for i, c in enumerate((self.c_emails, self.c_notas, self.c_ok, self.c_falta)):
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 10, 0), pady=(0, 10))
        cards.pack(fill="x")

        self.lbl_status = ctk.CTkLabel(self.area, text="", font=(T.FONTE, 15, "bold"),
                                       anchor="w", justify="left")
        self.lbl_status.pack(fill="x", pady=(4, 8))

        barra = ctk.CTkFrame(self.area, fg_color="transparent")
        barra.pack(fill="x", pady=(0, 6))
        self.b_incluir = botao(barra, "➕  Incluir na planilha", self._incluir, state="disabled")
        self.b_incluir.pack(side="left")
        ctk.CTkLabel(barra, font=T.F_PEQUENA, text_color=T.INK_3, anchor="w",
                     text="Selecione linhas (Ctrl/Shift + clique) para incluir só elas; "
                          "sem seleção, inclui todas.").pack(side="left", padx=12)

        self.tabela = Tabela(self.area, _COLS,
                             larguras=[115, 170, 95, 220, 80, 85, 80, 90, 210], altura=300,
                             busca=True, exportar=True, nome_export="notas_fora_da_planilha")
        self.tabela.pack(fill="both", expand=True)

        ctk.CTkLabel(self.area, text="E-mails sem nota reconhecida (só para informação)",
                     font=T.F_SECAO, text_color=T.INK_2, anchor="w").pack(fill="x", pady=(14, 4))
        ctk.CTkLabel(self.area, font=T.F_PEQUENA, text_color=T.INK_3, anchor="w", justify="left",
                     text="Pedidos de pagamento/desconto, devoluções e e-mails sem tabela nem NF "
                          "no assunto. Confira no Outlook se algum deles era nota.").pack(fill="x")
        self.tab_sem = Tabela(self.area, ["Recebido", "Assunto"], larguras=[120, 700], altura=150)
        self.tab_sem.pack(fill="x", pady=(4, 0))

    # ------------------------------------------------------------------ #
    def _cfg(self) -> dict:
        return dict(self.app.config.get("conferir_compras", default={}) or {})

    def _inicio_br(self) -> str:
        s = str(self._cfg().get("inicio_automacao", "") or "")
        return f"{s[8:10]}/{s[5:7]}/{s[:4]}" if len(s) >= 10 else "—"

    def _planilha(self) -> Path:
        return Path(self.app.config.get("dda_compras_path", default="") or "")

    def _conferir(self) -> None:
        if self.runner.ocupado:
            return
        p = self._planilha()
        if not p.name or not p.exists():
            self.app.toast.show("Planilha de Compras não encontrada — ajuste em Configurações.",
                                "err", ms=8000)
            return
        try:
            dias = max(1, int(self.e_dias.get().strip() or 30))
        except ValueError:
            self.app.toast.show("Dias precisa ser um número.", "err")
            return
        self.badge.set("lendo Outlook e planilha…", "info")
        self.b_conferir.configure(state="disabled")
        self.b_incluir.configure(state="disabled")
        from ..modules import conferir_compras as CC
        cfg = self._cfg()
        self.runner.executar(lambda: CC.executar(cfg, p, dias), self._conferido, self._falhou)

    def _conferido(self, r) -> None:
        self.resultado = r
        self.b_conferir.configure(state="normal")
        if not self._area_visivel:
            self.vazio.pack_forget()
            self.area.pack(fill="both", expand=True)
            self._area_visivel = True
        self.c_emails.set(r.emails, f"desde {r.desde}")
        self.c_notas.set(r.notas_email)
        self.c_ok.set(r.notas_ok)
        self.c_falta.set(len(r.faltando),
                         f"{r.emails_fora} e-mail(s) não registrado(s)" if r.emails_fora else "")
        self.tabela.preencher([self._linha(f) for f in r.faltando])
        self.tab_sem.preencher([[a, b] for a, b in r.sem_nota])
        if r.tudo_certo:
            self.lbl_status.configure(text=f"✔  Tudo certo — todas as {r.notas_email} notas "
                                           f"dos e-mails estão na planilha.", text_color=T.VERDE)
            self.badge.set("tudo certo", "ok")
        else:
            self.lbl_status.configure(text=f"⚠  {len(r.faltando)} nota(s) dos e-mails de Compras "
                                           f"NÃO estão na planilha.", text_color=T.VERMELHO)
            self.badge.set(f"{len(r.faltando)} fora da planilha", "warn")
            self.b_incluir.configure(state="normal")
        self.app.marcar_nav("conferir_compras", len(r.faltando))
        historico.registrar("conferir_compras", "Conferência Outlook × planilha",
                            resumo={"emails": r.emails, "notas": r.notas_email,
                                    "faltando": len(r.faltando)})

    @staticmethod
    def _linha(f) -> list:
        return [f.recebido[8:10] + "/" + f.recebido[5:7] + " " + f.recebido[11:16], f.remetente,
                f.empresa, f.fornecedor, f.af, f.vencimento, f.nf,
                "assunto (conferir)" if f.origem == "ASSUNTO" else "tabela", f.motivo]

    def _escolhidas(self):
        r = self.resultado
        sel = self.tabela.selecionadas()
        if not sel:
            return list(r.faltando)
        chaves = {(s[0], s[6], s[3]) for s in sel}
        return [f for f in r.faltando if (self._linha(f)[0], f.nf, f.fornecedor) in chaves]

    def _incluir(self) -> None:
        if self.runner.ocupado or not self.resultado or not self.resultado.faltando:
            return
        itens = self._escolhidas()
        if not itens:
            return
        if not messagebox.askyesno(
                "Incluir na planilha",
                f"Incluir {len(itens)} nota(s) na aba 'Notas recebidas' da planilha "
                f"{self._planilha().name}?\n\n"
                "• Elas entram na posição da data do e-mail, no mesmo formato das outras.\n"
                "• Antes, é salva uma cópia de segurança da planilha.\n"
                "• Notas que já existirem (mesma empresa/fornecedor/NF) não são repetidas.",
                parent=self):
            return
        self.badge.set("incluindo pelo Excel…", "info")
        self.b_incluir.configure(state="disabled")
        self.b_conferir.configure(state="disabled")
        from ..modules import conferir_compras as CC
        p = self._planilha()
        self.runner.executar(lambda: CC.incluir_na_planilha(p, itens, APP_DIR / "backups"),
                             self._incluido, self._falhou)

    def _incluido(self, carga) -> None:
        ins, pul, backup = carga
        self.b_conferir.configure(state="normal")
        historico.registrar("conferir_compras", "Inclusão na planilha de Compras",
                            resumo={"incluidas": ins, "ja_existiam": pul}, saida=backup)
        extra = f" ({pul} já existiam)" if pul else ""
        self.app.toast.show(f"{ins} nota(s) incluída(s) na planilha{extra}. Conferindo de novo…",
                            "ok", ms=7000)
        # o OneDrive leva alguns segundos para trazer a planilha atualizada
        self.after(20000, self._conferir)

    def _falhou(self, exc: Exception) -> None:
        self.b_conferir.configure(state="normal")
        if self.resultado and self.resultado.faltando:
            self.b_incluir.configure(state="normal")
        self.badge.set("erro", "err")
        self.app.toast.show(mensagem_erro_amigavel(exc), "err", ms=10000)
