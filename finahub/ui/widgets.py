"""
widgets.py — Componentes reutilizáveis da suíte.

Tudo que aparece em mais de uma tela mora aqui: cards de métrica, badges,
tabela zebrada, barra de passos, toast, rodador de threads.
"""
from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import customtkinter as ctk

from ..core import theme as T


# ────────────────────────────────────────────────────────────────────── #
# Execução em thread com retorno seguro para a UI                        #
# ────────────────────────────────────────────────────────────────────── #
class ThreadRunner:
    """
    Roda trabalho pesado fora da thread da UI e entrega o resultado de
    volta via fila + after() — o padrão thread-safe do tkinter (mesma
    estratégia do DDA V7).
    """

    def __init__(self, widget: tk.Misc) -> None:
        self._widget = widget
        self._fila: "queue.Queue[tuple]" = queue.Queue()
        self._ativo = False

    def executar(
        self,
        trabalho: Callable[[], Any],
        ao_concluir: Callable[[Any], None],
        ao_falhar: Callable[[Exception], None],
    ) -> bool:
        if self._ativo:
            return False
        self._ativo = True

        def _worker() -> None:
            try:
                resultado = trabalho()
                self._fila.put(("ok", resultado))
            except Exception as exc:  # noqa: BLE001 — repassado para a UI
                self._fila.put(("erro", exc))

        threading.Thread(target=_worker, daemon=True).start()
        self._agendar_poll(ao_concluir, ao_falhar)
        return True

    def _agendar_poll(self, ao_concluir, ao_falhar) -> None:
        try:
            tipo, carga = self._fila.get_nowait()
        except queue.Empty:
            self._widget.after(80, lambda: self._agendar_poll(ao_concluir, ao_falhar))
            return
        self._ativo = False
        if tipo == "ok":
            try:
                ao_concluir(carga)
            except Exception as exc:  # noqa: BLE001
                # Erro ao MONTAR a tela não pode deixar a UI presa em
                # "processando…" — roteia para o tratador de falha da view.
                try:
                    ao_falhar(exc)
                except Exception:
                    pass
        else:
            ao_falhar(carga)

    @property
    def ocupado(self) -> bool:
        return self._ativo


# ────────────────────────────────────────────────────────────────────── #
# Cards e badges                                                         #
# ────────────────────────────────────────────────────────────────────── #
class Card(ctk.CTkFrame):
    def __init__(self, master, **kw) -> None:
        kw.setdefault("fg_color", T.CARD)
        kw.setdefault("corner_radius", T.RAIO)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", T.BORDA)
        super().__init__(master, **kw)


class MetricCard(Card):
    """
    Card 'KPI' do design Premium: filete colorido à esquerda + rótulo
    pequeno + número grande + subtítulo (igual à prévia web).
    """

    def __init__(self, master, rotulo: str, cor_valor: str = T.INK, **kw):
        # altura compacta: o conteúdo (rótulo + número + subtítulo) ocupa
        # ~90px; sem isso o CTkFrame fica com a altura-padrão de 200px e o
        # card aparece com um vão vazio embaixo do número.
        kw.setdefault("height", 104)
        super().__init__(master, **kw)
        # tema grafite: bolinha colorida ao lado do rótulo (cor do indicador)
        # e o número em grafite
        cor_ponto = T.AZUL if cor_valor in (T.INK, T.AZUL_ESCURO) else cor_valor

        corpo = ctk.CTkFrame(self, fg_color="transparent")
        corpo.pack(side="left", fill="both", expand=True, padx=(6, 0))
        linha = ctk.CTkFrame(corpo, fg_color="transparent")
        linha.pack(fill="x", padx=12, pady=(12, 0))
        self._filete = ctk.CTkFrame(linha, width=8, height=8, corner_radius=4,
                                    fg_color=cor_ponto)
        self._filete.pack(side="left", padx=(0, 8))
        self._rotulo = ctk.CTkLabel(linha, text=rotulo.upper(), font=T.F_CARD_LABEL,
                                    text_color=T.INK_2, anchor="w")
        self._rotulo.pack(side="left", fill="x")
        self._valor = ctk.CTkLabel(corpo, text="—", font=T.F_CARD_VALOR,
                                   text_color=T.INK, anchor="w")
        self._valor.pack(fill="x", padx=12)
        self._sub = ctk.CTkLabel(corpo, text="", font=T.F_PEQUENA,
                                 text_color=T.INK_3, anchor="w")
        self._sub.pack(fill="x", padx=12, pady=(0, 10))

    def set(self, valor: Any, sub: str = "") -> None:
        self._valor.configure(text=str(valor))
        self._sub.configure(text=sub)


class Badge(ctk.CTkLabel):
    """Pílula de status (border-radius alto, texto bold — igual à prévia)."""

    def __init__(self, master, texto: str = "", tipo: str = "info", **kw):
        cor, bg = T.STATUS_CORES.get(tipo, T.STATUS_CORES["info"])
        super().__init__(master, text=f"  {texto}  ", font=(T.FONTE, 11, "bold"),
                         text_color=cor, fg_color=bg,
                         corner_radius=T.RAIO_PILL, height=26, **kw)

    def set(self, texto: str, tipo: str = "info") -> None:
        cor, bg = T.STATUS_CORES.get(tipo, T.STATUS_CORES["info"])
        self.configure(text=f"  {texto}  ", text_color=cor, fg_color=bg)


# ────────────────────────────────────────────────────────────────────── #
# Barra de passos (fluxo 1-2-3-4, como no DDA)                           #
# ────────────────────────────────────────────────────────────────────── #
class StepBar(ctk.CTkFrame):
    def __init__(self, master, passos: Sequence[str], **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self._labels: List[ctk.CTkLabel] = []
        for i, passo in enumerate(passos):
            lbl = ctk.CTkLabel(
                self, text=f"  {i + 1}. {passo}  ", font=(T.FONTE, 12, "bold"),
                corner_radius=T.RAIO_BTN, fg_color=T.CARD, text_color=T.INK_3,
                height=30,
            )
            lbl.pack(side="left", padx=(0 if i == 0 else 7, 0), ipady=2)
            self._labels.append(lbl)
        self.set_ativo(0)

    def set_ativo(self, indice: int) -> None:
        for i, lbl in enumerate(self._labels):
            if i < indice:
                lbl.configure(fg_color=T.VERDE_BG, text_color=T.VERDE)
            elif i == indice:
                lbl.configure(fg_color=T.AZUL, text_color=T.BRANCO)
            else:
                lbl.configure(fg_color=T.CARD, text_color=T.INK_3)


# ────────────────────────────────────────────────────────────────────── #
# Tabela premium — busca em tempo real + ordenar por coluna + exportar    #
# ────────────────────────────────────────────────────────────────────── #
_RE_NUM = re.compile(r"[^\d,.-]")


_ALTURA_LINHA = 26          # px por linha da tabela (Treeview)
_ESTILO_PRONTO = False


def _estilo_tabela(widget: tk.Misc) -> None:
    """Estilo único do Treeview: cabeçalho azul-assinatura, zebra, Segoe UI."""
    global _ESTILO_PRONTO
    if _ESTILO_PRONTO:
        return
    st = ttk.Style(widget)
    try:
        st.theme_use("clam")       # o tema "clam" respeita cores customizadas
    except tk.TclError:
        pass
    st.configure("Alan.Treeview", background=T.CARD, fieldbackground=T.CARD,
                 foreground=T.INK, rowheight=_ALTURA_LINHA, borderwidth=0,
                 font=(T.FONTE, 10))
    st.configure("Alan.Treeview.Heading", background=T.AZUL_ESCURO,
                 foreground=T.BRANCO, font=(T.FONTE, 9, "bold"),
                 relief="flat", padding=(8, 6), borderwidth=0)
    st.map("Alan.Treeview.Heading",
           background=[("active", T.AZUL)], foreground=[("active", T.BRANCO)])
    st.map("Alan.Treeview", background=[("selected", T.INFO_BG)],
           foreground=[("selected", T.AZUL_ESCURO)])
    st.layout("Alan.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    _ESTILO_PRONTO = True


def _chave_ordenacao(valor: Any):
    """Ordena numérico quando dá (R$ 1.234,56 → 1234.56); senão texto."""
    s = str(valor).strip()
    limpo = _RE_NUM.sub("", s)
    if limpo and any(ch.isdigit() for ch in limpo):
        t = limpo
        if "," in t:                       # formato BR
            t = t.replace(".", "").replace(",", ".")
        try:
            return (0, float(t))
        except ValueError:
            pass
    return (1, s.lower())


class Tabela(ctk.CTkFrame):
    """
    Tabela zebrada com cabeçalho azul. Recursos opcionais (sem quebrar
    quem já usava): `busca=True` mostra um campo de filtro em tempo real,
    `exportar=True` mostra o botão "Exportar Excel", e o clique no
    cabeçalho ordena pela coluna (asc/desc). API mantida: preencher()/limpar().
    """

    def __init__(self, master, colunas: Sequence[str],
                 larguras: Optional[Sequence[int]] = None, altura: int = 220,
                 busca: bool = False, exportar: bool = False,
                 nome_export: str = "tabela",
                 alinhamentos: Optional[Sequence[str]] = None, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(master, **kw)
        self._colunas = list(colunas)
        self._larguras = list(larguras or [140] * len(colunas))
        # alinhamento por coluna: "w" (esquerda, padrão) ou "e" (direita p/ nº)
        self._alinhamentos = list(alinhamentos or ["w"] * len(colunas))
        if len(self._alinhamentos) < len(self._colunas):
            self._alinhamentos += ["w"] * (
                len(self._colunas) - len(self._alinhamentos))
        self._nome_export = nome_export
        self._dados: List[List[Any]] = []      # dataset completo
        self._tags: List[str] = []             # situação de cada linha ("" = zebra)
        self._filtro_tags: Optional[set] = None
        self._ordem_col: Optional[int] = None
        self._ordem_desc = False

        # ── toolbar (busca + contador + exportar) ────────────────────
        if busca or exportar:
            bar = ctk.CTkFrame(self, fg_color="transparent")
            bar.pack(fill="x", pady=(0, 6))
            if busca:
                self._entry = ctk.CTkEntry(
                    bar, placeholder_text="🔎  buscar…", height=30,
                    width=240, font=T.F_PEQUENA, border_color=T.BORDA,
                    fg_color=T.CARD)
                self._entry.pack(side="left")
                self._entry.bind("<KeyRelease>", lambda _e: self._agendar_render())
            self._lbl_cont = ctk.CTkLabel(bar, text="", font=T.F_PEQUENA,
                                          text_color=T.INK_3)
            self._lbl_cont.pack(side="left", padx=10)
            if exportar:
                botao(bar, "⬇  Exportar Excel", self._exportar_excel,
                      primario=False, height=30).pack(side="right")
        else:
            self._entry = None
            self._lbl_cont = None

        # ── grade: ttk.Treeview nativo ───────────────────────────────
        # Antes cada célula era um CTkLabel (400 linhas × 7 colunas = 2.800
        # widgets) destruído e recriado a cada tecla da busca → tremia e
        # travava. O Treeview desenha milhares de linhas sem recriar nada.
        _estilo_tabela(self)
        moldura = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=T.RAIO,
                               border_width=1, border_color=T.BORDA)
        moldura.pack(fill="both", expand=True)
        linhas_visiveis = max(3, int(altura // _ALTURA_LINHA))
        self._tree = ttk.Treeview(
            moldura, columns=[str(i) for i in range(len(self._colunas))],
            show="headings", height=linhas_visiveis, style="Alan.Treeview",
            selectmode="extended")
        sb = ctk.CTkScrollbar(moldura, command=self._tree.yview,
                              button_color=T.BORDA, button_hover_color=T.AZUL_CLARO)
        self._tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 4), pady=6)
        self._tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        for c, (nome, w) in enumerate(zip(self._colunas, self._larguras)):
            anc = "e" if self._alinhamentos[c] == "e" else "w"
            self._tree.heading(str(c), text=nome.upper(), anchor=anc,
                               command=lambda col=c: self._ordenar(col))
            self._tree.column(str(c), width=int(w), minwidth=40, anchor=anc,
                              stretch=True)
        self._tree.tag_configure("par", background=T.ZEBRA)
        self._tree.tag_configure("impar", background=T.CARD)
        # rolagem da roda do mouse fica na tabela (não arrasta a página junto)
        self._tree.bind("<MouseWheel>", self._rolar)
        self._busca_pendente: Optional[str] = None

    def _rolar(self, ev) -> str:
        self._tree.yview_scroll(int(-ev.delta / 120) * 3, "units")
        return "break"

    # ------------------------------------------------------------------ #
    def limpar(self) -> None:
        self._tree.delete(*self._tree.get_children())

    def selecionadas(self) -> List[List[str]]:
        """Valores (texto) das linhas selecionadas pelo usuário."""
        return [[str(v) for v in self._tree.item(i, "values")] for i in self._tree.selection()]

    def preencher(self, linhas: Sequence[Sequence[Any]],
                  max_linhas: int = 2000,
                  tags: Optional[Sequence[str]] = None) -> None:
        """`tags` (opcional): uma por linha — pinta a linha inteira com a cor
        registrada em cor_tag() e permite filtrar com filtrar_tags()."""
        self._dados = [list(l) for l in linhas][:max_linhas]
        t = list(tags or [])[:len(self._dados)]
        self._tags = t + [""] * (len(self._dados) - len(t))
        self._render()

    def cor_tag(self, nome: str, fundo: Optional[str] = None,
                texto: Optional[str] = None) -> None:
        opts = {}
        if fundo:
            opts["background"] = fundo
        if texto:
            opts["foreground"] = texto
        self._tree.tag_configure(nome, **opts)

    def filtrar_tags(self, tags: Optional[Iterable[str]]) -> None:
        """None = todas as linhas; senão só as linhas com essas tags."""
        self._filtro_tags = set(tags) if tags is not None else None
        self._render()

    def contar_tags(self) -> Dict[str, int]:
        cont: Dict[str, int] = {}
        for t in self._tags:
            cont[t] = cont.get(t, 0) + 1
        return cont

    def _agendar_render(self) -> None:
        # debounce: espera a pessoa parar de digitar (150 ms) antes de filtrar
        if self._busca_pendente is not None:
            self.after_cancel(self._busca_pendente)
        self._busca_pendente = self.after(150, self._render)

    # ------------------------------------------------------------------ #
    def _ordenar(self, col: int) -> None:
        if self._ordem_col == col:
            self._ordem_desc = not self._ordem_desc
        else:
            self._ordem_col, self._ordem_desc = col, False
        for c, nome in enumerate(self._colunas):
            seta = f"  {'▼' if self._ordem_desc else '▲'}" if c == col else ""
            self._tree.heading(str(c), text=nome.upper() + seta)
        self._render()

    def _filtradas_idx(self) -> List[int]:
        idx = list(range(len(self._dados)))
        if self._filtro_tags is not None:
            idx = [i for i in idx if self._tags[i] in self._filtro_tags]
        if self._entry is not None:
            termo = self._entry.get().strip().lower()
            if termo:
                idx = [i for i in idx
                       if any(termo in str(v).lower() for v in self._dados[i])]
        if self._ordem_col is not None:
            col = self._ordem_col
            idx.sort(key=lambda i: _chave_ordenacao(
                self._dados[i][col] if col < len(self._dados[i]) else ""),
                reverse=self._ordem_desc)
        return idx

    def _filtradas(self) -> List[List[Any]]:
        return [self._dados[i] for i in self._filtradas_idx()]

    def _render(self, max_visiveis: int = 2000) -> None:
        self._busca_pendente = None
        self.limpar()
        idx = self._filtradas_idx()
        linhas = idx                      # só p/ o contador abaixo
        n_col = len(self._colunas)
        for r, i in enumerate(idx[:max_visiveis]):
            valores = [str(v) for v in self._dados[i][:n_col]]
            valores += [""] * (n_col - len(valores))
            tag = self._tags[i] or ("par" if r % 2 else "impar")
            self._tree.insert("", "end", values=valores, tags=(tag,))
        if self._lbl_cont is not None:
            total = len(self._dados)
            vis = len(linhas)
            txt = f"{vis} de {total}" if vis != total else f"{total} linha(s)"
            if vis > max_visiveis:
                txt = f"{max_visiveis} de {vis} exibidas"
            self._lbl_cont.configure(text=txt)

    # ------------------------------------------------------------------ #
    def _exportar_excel(self) -> None:
        from tkinter import filedialog, messagebox
        from datetime import datetime
        linhas = self._filtradas()
        if not linhas:
            messagebox.showinfo("Exportar", "Não há linhas para exportar.")
            return
        caminho = filedialog.asksaveasfilename(
            title="Exportar tabela",
            defaultextension=".xlsx",
            initialfile=f"{self._nome_export}_"
                        f"{datetime.now():%Y%m%d_%H%M}.xlsx",
            filetypes=[("Excel", "*.xlsx")])
        if not caminho:
            return
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font, PatternFill
            wb = Workbook()
            ws = wb.active
            ws.title = self._nome_export[:31]
            ws.append(self._colunas)
            for cell in ws[1]:
                cell.fill = PatternFill("solid", fgColor="073B63")
                cell.font = Font(color="FFFFFF", bold=True, name="Segoe UI",
                                 size=10)
                cell.alignment = Alignment(horizontal="center")
            for linha in linhas:
                ws.append([str(v) for v in linha])
            for i, w in enumerate(self._larguras, start=1):
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter]\
                    .width = max(10, w / 7)
            wb.save(caminho)
            messagebox.showinfo("Exportado", f"Tabela salva em:\n{caminho}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Erro ao exportar", str(exc))


# ────────────────────────────────────────────────────────────────────── #
# Estado vazio ("comece aqui") — evita cards mortos mostrando "—"        #
# ────────────────────────────────────────────────────────────────────── #
class EmptyState(Card):
    """
    Área exibida ANTES do primeiro processamento: ícone + título + dica.
    As métricas e tabelas do módulo só aparecem quando existem de fato.
    """

    def __init__(self, master, icone: str, titulo: str, dica: str, **kw):
        super().__init__(master, **kw)
        ctk.CTkLabel(self, text=icone, font=(T.FONTE, 36),
                     text_color=T.INK_3).pack(pady=(34, 2))
        ctk.CTkLabel(self, text=titulo, font=(T.FONTE, 15, "bold"),
                     text_color=T.INK).pack()
        ctk.CTkLabel(self, text=dica, font=T.F_PEQUENA, text_color=T.INK_3,
                     wraplength=560, justify="center").pack(pady=(4, 36))


# ────────────────────────────────────────────────────────────────────── #
# Toast (aviso flutuante, como no DDA)                                   #
# ────────────────────────────────────────────────────────────────────── #
class Toast:
    def __init__(self, janela: tk.Misc) -> None:
        self._janela = janela
        self._atual: Optional[ctk.CTkFrame] = None

    def show(self, mensagem: str, tipo: str = "ok", ms: int = 4000) -> None:
        self._fechar()
        cor, bg = T.STATUS_CORES.get(tipo, T.STATUS_CORES["info"])
        frame = ctk.CTkFrame(self._janela, fg_color=bg, corner_radius=10,
                             border_width=1, border_color=cor)
        ctk.CTkLabel(frame, text=mensagem, font=(T.FONTE, 12, "bold"),
                     text_color=cor).pack(padx=18, pady=10)
        frame.place(relx=0.5, rely=0.94, anchor="s")
        self._atual = frame
        self._janela.after(ms, self._fechar)

    def _fechar(self) -> None:
        if self._atual is not None:
            try:
                self._atual.destroy()
            except tk.TclError:
                pass
            self._atual = None


# ────────────────────────────────────────────────────────────────────── #
# Cabeçalho de página + botões padrão                                    #
# ────────────────────────────────────────────────────────────────────── #
def cabecalho(master, titulo: str, subtitulo: str,
              crumb: Optional[str] = None,
              icone: Optional[str] = None) -> ctk.CTkFrame:
    """
    Cabeçalho de página como FAIXA AZUL (igual à do Remessa × Banco):
    ícone opcional + breadcrumb pequeno + título branco + subtítulo claro,
    sobre o azul-assinatura #073B63. Unifica todas as telas.

    O label do título fica em `band._titulo_label` (o dashboard usa para
    atualizar a saudação conforme o horário).
    """
    # Tema "Grafite e verde" (30/10/2026): sem faixa colorida — breadcrumb
    # discreto, título forte e subtítulo sobre o próprio fundo da tela.
    # (o ícone deixou de ser exibido; o parâmetro fica por compatibilidade)
    band = ctk.CTkFrame(master, fg_color="transparent")
    txt = ctk.CTkFrame(band, fg_color="transparent")
    txt.pack(side="left", fill="x", expand=True, padx=4, pady=(0, 2))
    if crumb:
        ctk.CTkLabel(txt, text=crumb.upper(), font=T.F_CRUMB,
                     text_color=T.INK_3, anchor="w", height=16).pack(fill="x")
    lbl = ctk.CTkLabel(txt, text=titulo, font=T.F_TITULO,
                       text_color=T.INK, anchor="w")
    lbl.pack(fill="x")
    ctk.CTkLabel(txt, text=subtitulo, font=T.F_SUBTITULO,
                 text_color=T.INK_2, anchor="w", justify="left",
                 wraplength=900).pack(fill="x")
    band._titulo_label = lbl
    return band


def botao(master, texto: str, comando, primario: bool = True, **kw) -> ctk.CTkButton:
    if primario:
        kw.setdefault("fg_color", T.AZUL)
        kw.setdefault("hover_color", T.AZUL_HOVER)
        kw.setdefault("text_color", T.BRANCO)
    else:
        kw.setdefault("fg_color", T.CARD)
        kw.setdefault("hover_color", T.INFO_BG)
        kw.setdefault("text_color", T.AZUL)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", T.AZUL)
    kw.setdefault("font", T.F_BOTAO)
    kw.setdefault("corner_radius", T.RAIO_BTN)
    kw.setdefault("height", 38)
    return ctk.CTkButton(master, text=texto, command=comando, **kw)
