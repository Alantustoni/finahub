# FinaHub — Guia de Design "ERP Premium escuro"

Este documento tem duas partes: **(1)** o prompt que gerou este redesign
(guarde — serve para pedir ajustes ou refazer em outra ferramenta) e
**(2)** os tokens oficiais do design, que são a fonte da verdade do
`finahub/core/theme.py`.

---

## 1 · O prompt

> Redesenhe a interface do FinaHub (CustomTkinter, tela 1280×820)
> aplicando o design **"ERP Premium escuro"** da prévia
> `preview_designs_finahub.html`, reproduzindo curvas, cores e
> detalhes o mais fielmente possível dentro do que o CustomTkinter
> suporta. Regras:
>
> **Sidebar** — azul-noite `#0F1D2B`, 230px, sem borda. Logo em branco
> 19px bold com subtítulo 10px em `#B9CDE0`. Itens de navegação como
> pílulas (corner_radius 9, altura 42) com glifos `◉ ▤ ⇄ ⧉ ▦ ⚙`;
> texto `#B9CDE0`, hover `#1A2C3F`, item ativo com fundo `#1768AE` e
> texto branco em bold. Rodapé 9px em `#6E8095`.
>
> **Conteúdo** — fundo `#F4F7FB`. Cabeçalho de página com breadcrumb
> 10px caixa alta em `#8CA0B5`, título 22px bold em `#16283C` e
> subtítulo 13px em `#5B7089`.
>
> **Cards** — brancos, corner_radius **14**, borda 1px `#E3EAF3`
> (substitui a sombra difusa do navegador, que o Tk não desenha).
> Cards KPI com **filete colorido de 4px** encostado à esquerda
> (accent `#1768AE` por padrão; verde/âmbar/vermelho conforme o
> estado), rótulo 11px caixa alta em `#5B7089`, valor 26px extra-bold
> na cor do estado, subtítulo 11px em `#8CA0B5`.
>
> **Botões** — primário: fundo `#1768AE`, texto branco bold,
> corner_radius 9, altura 38, hover `#0F5A99`. Secundário: fundo
> transparente com borda 1.5px e texto no accent. Ghost: borda
> tracejada `#E3EAF3` com texto `#8CA0B5`.
>
> **Pílulas de status** — corner_radius 20, texto 11px bold; pares
> cor/fundo: ok `#16A34A`/`#E8F7EE`, atenção `#B45309`/`#FEF3E2`,
> erro `#DC2626`/`#FDEBEB`, info `#1768AE`/`#E8F1FB`.
>
> **Barra de passos** — pílulas 12px bold: concluído em verde sobre
> `#E8F7EE`, atual em branco sobre `#1768AE`, futuro em `#8CA0B5`
> sobre branco.
>
> **Tabelas** — cabeçalho azul-noite `#0F1D2B` com texto branco 11px
> caixa alta e pontas arredondadas na primeira/última coluna; linhas
> zebradas branco/`#F7FAFD`; números com tabular-nums.
>
> **Barras de progresso** — trilho `#E8F1FB`, preenchimento no accent
> (verde quando representa conclusão), altura 8-12px, cantos 4px.
>
> Nenhuma view define cor solta: tudo referencia `core/theme.py`.
> Limitações aceitas do CustomTkinter: sem sombra difusa (borda 1px no
> lugar), sem transições animadas de hover, sem gradientes.

---

## 2 · Tokens oficiais (fonte: prévia web → `theme.py`)

| Token | Valor | CSS da prévia | Uso |
|---|---|---|---|
| `SIDEBAR_BG` | `#0F1D2B` | `--sb` | fundo da sidebar |
| `SIDEBAR_ITEM` | `#B9CDE0` | `--sb-item` | texto dos itens |
| `SIDEBAR_HOVER` | `#1A2C3F` | hover | hover dos itens |
| `SIDEBAR_ATIVO` | `#1768AE` | `--sb-active` | pílula do item ativo |
| `FUNDO` | `#F4F7FB` | `--bg` | fundo do conteúdo |
| `CARD` | `#FFFFFF` | `--card` | fundo dos cards |
| `BORDA` | `#E3EAF3` | `--card-border` | borda dos cards |
| `ZEBRA` | `#F7FAFD` | `--zebra` | linhas pares de tabela |
| `TRACK` | `#E8F1FB` | `--track` | trilho de progresso |
| `INK` / `INK_2` / `INK_3` | `#16283C` / `#5B7089` / `#8CA0B5` | `--ink*` | textos |
| `AZUL` | `#1768AE` | `--accent` | botões, ativo, filete |
| `AZUL_HOVER` | `#0F5A99` | — | hover primário |
| `AZUL_ESCURO` | `#0F1D2B` | `--th` | cabeçalho de tabela |
| `VERDE`/`VERDE_BG` | `#16A34A`/`#E8F7EE` | `--ok*` | sucesso |
| `AMARELO`/`AMARELO_BG` | `#B45309`/`#FEF3E2` | `--warn*` | atenção |
| `VERMELHO`/`VERMELHO_BG` | `#DC2626`/`#FDEBEB` | `--err*` | erro |
| `INFO_BG` | `#E8F1FB` | `--info-bg` | fundo info |
| `RAIO` | 14 | `border-radius:14px` | cards |
| `RAIO_BTN` | 9 | `border-radius:9px` | botões/pílulas de nav |
| `RAIO_PILL` | 20 | `border-radius:20px` | badges |
| `FILETE_W` | 4 | `::before width:4px` | filete dos KPI |

Fonte: **Segoe UI** em todo o sistema; monoespaçada **Consolas** para logs.

---

## 3 · O que difere da prévia web (limitações do CustomTkinter)

- **Sombra difusa dos cards** → substituída por borda 1px `#E3EAF3`.
- **Transições de hover (0.15s)** → troca de cor instantânea.
- **`:hover` de linha de tabela** → não implementado (tabela é leitura).
- Todo o resto — curvas, cores, filete, pílulas, zebra, cabeçalhos — é
  reprodução fiel.

---

## 4 · UX v1.2 — menos cards, mais sinal

- **Estados vazios**: cada módulo abre com uma área "comece aqui"
  (`EmptyState`); métricas e tabelas só aparecem após o processamento.
- **Dashboard**: os 4 atalhos de módulo (duplicavam a sidebar) deram
  lugar à lista **Pendências abertas**, alimentada pelo histórico
  (`historico.pendencias_abertas()`), com botão "Abrir →" por módulo.
- **Cards enxutos**: DDA fundiu "tratadas/removidas" num card só e
  "Linhas com erro" só aparece quando > 0; Programadas/Pendentes só
  aparecem após o cruzamento; no RET o card "Trailer" virou selo na
  barra de ações; no Usinas a seção "Verificar" só aparece com
  linhas problemáticas.
- **CTA único por etapa**: um botão primário que muda de rótulo/ação
  conforme o passo (Anexar → Processar → Cruzar → Exportar), com ações
  secundárias ("Trocar arquivo", "Consolidar revisado", "Exportar sem
  cruzar") aparecendo apenas quando fazem sentido.

---

## 5 · Unificação com Remessa × Banco (v1.6) + polimento (v1.7–1.8)

A partir da v1.6 a suíte adota a **paleta exata do Remessa × Banco**
(o `theme.py` espelha `vendor/remessa_v3/core/theme.py`): fundo `#EEF6FF`,
cards `#FFFFFF` com borda `#B8D4F3`, sidebar e cabeçalhos no azul-assinatura
`#073B63`, acento `#1768AE`. O módulo Remessa passou a rodar **embutido** na
central (sem janela separada), reusando os componentes originais.

- **v1.7** — `cabecalho()` virou uma **faixa azul** (ícone + título branco +
  subtítulo) igual à do Remessa, aplicada a todas as telas.
- **v1.8 — polimento inspirado na review externa:**
  - **Tabela premium**: `Tabela` ganhou `busca=` (filtro em tempo real),
    clique no cabeçalho para **ordenar** (asc/desc, numérico BR ou texto) e
    `exportar=` (botão "Exportar Excel" que respeita filtro/ordenação).
    Ligada nas tabelas de programadas/pendentes (DDA), prévia (Usinas) e
    histórico (dashboard). A tabela do Remessa já tinha busca/ordenação nativas.
  - **Escala de espaçamento** formal em `theme.ESP` (4/8/12/16/24/32) —
    `PAD`/`PAD_G` agora derivam dela; nada de valor solto.
  - **Mini-gráfico de atividade** no dashboard (execuções por módulo nos
    últimos 7 dias, `historico.contagem_por_modulo`).

> Nota: as seções 1–3 acima descrevem o design "ERP Premium escuro" original
> (sidebar `#0F1D2B`). A partir da v1.6 esses tokens foram remapeados para a
> paleta do Remessa — os NOMES dos tokens continuam, só os valores mudaram.
