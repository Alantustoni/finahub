"""
conciliacao.py
Trava de conciliação (item 1): confere que NENHUMA nota some em silêncio.

A regra de ouro do sistema: toda nota que entra tem de terminar em algum
balde conhecido (pendente, programada no banco, ou removida com motivo).
Se a conta não fecha, isto é sinalizado — em vez de exportar calado.

Módulo puro (sem UI, sem Excel): recebe os resultados já calculados e
devolve um objeto com os números e a lista de problemas encontrados.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class Checagem:
    descricao: str
    esperado:  int
    obtido:    int

    @property
    def ok(self) -> bool:
        return self.esperado == self.obtido


@dataclass
class Conciliacao:
    checagens: List[Checagem] = field(default_factory=list)
    problemas: List[str]      = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problemas

    def resumo(self) -> str:
        if self.ok:
            return "Conciliacao OK: nenhuma nota se perdeu."
        return "Conciliacao COM PROBLEMA:\n  - " + "\n  - ".join(self.problemas)


def conciliar(processing_result, resultado_cruzamento=None) -> Conciliacao:
    """
    Reconciliação de contagens. Retorna Conciliacao com checagens e problemas.

    Checagens:
      1. Processamento: total_original == total_processado + removidas.
      2. Cruzamento (se houver): total_dda == pendente + programado + divergente.
      3. Coerência: o cruzamento recebeu exatamente as linhas processadas.
    """
    c = Conciliacao()

    # ── 1. Processamento ─────────────────────────────────────────────── #
    original    = int(getattr(processing_result, "total_original", 0) or 0)
    processado  = int(getattr(processing_result, "total_processado", 0) or 0)
    rem_prop    = int(getattr(processing_result, "removidas_proposta", 0) or 0)
    rem_sider   = int(getattr(processing_result, "removidas_siderurgicas", 0) or 0)

    chk1 = Checagem(
        "Entrada = processadas + removidas (proposta + siderurgicas)",
        esperado=original,
        obtido=processado + rem_prop + rem_sider,
    )
    c.checagens.append(chk1)
    if not chk1.ok:
        c.problemas.append(
            f"{chk1.descricao}: entrada={original}, "
            f"processadas+removidas={chk1.obtido} "
            f"(diferenca de {original - chk1.obtido} nota(s))."
        )

    # ── 2 e 3. Cruzamento ────────────────────────────────────────────── #
    if resultado_cruzamento is not None:
        total_dda   = int(getattr(resultado_cruzamento, "total_dda", 0) or 0)
        pendente    = int(getattr(resultado_cruzamento, "total_pendente", 0) or 0)
        programado  = int(getattr(resultado_cruzamento, "total_programado", 0) or 0)
        divergente  = int(getattr(resultado_cruzamento, "total_divergente", 0) or 0)

        chk2 = Checagem(
            "DDA = pendentes + programadas + divergentes",
            esperado=total_dda,
            obtido=pendente + programado + divergente,
        )
        c.checagens.append(chk2)
        if not chk2.ok:
            c.problemas.append(
                f"{chk2.descricao}: dda={total_dda}, soma={chk2.obtido} "
                f"(diferenca de {total_dda - chk2.obtido} nota(s))."
            )

        chk3 = Checagem(
            "Cruzamento recebeu todas as notas processadas",
            esperado=processado,
            obtido=total_dda,
        )
        c.checagens.append(chk3)
        if not chk3.ok:
            c.problemas.append(
                f"{chk3.descricao}: processadas={processado}, "
                f"no cruzamento={total_dda}."
            )

    # Log claro (a trava avisa, nao esconde)
    if c.ok:
        logger.info(c.resumo())
    else:
        logger.error(c.resumo())

    return c
