"""
test_conciliacao.py
Trava de conciliacao: a conta entrada == saida tem de fechar; se nao fecha,
tem de acusar problema (nada de nota sumindo em silencio).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finahub.vendor.organizador_dda.core.conciliacao import conciliar


class _Proc:
    def __init__(self, orig, proc, prop=0, sider=0):
        self.total_original = orig
        self.total_processado = proc
        self.removidas_proposta = prop
        self.removidas_siderurgicas = sider


class _Cruz:
    def __init__(self, dda, pend, prog, div=0):
        self.total_dda = dda
        self.total_pendente = pend
        self.total_programado = prog
        self.total_divergente = div


def test_ok_quando_conta_fecha():
    c = conciliar(_Proc(100, 90, prop=5, sider=5), _Cruz(90, 70, 20, 0))
    assert c.ok, c.resumo()


def test_acusa_perda_no_processamento():
    # 90 + 5 + 0 = 95 != 100 -> 5 notas sumiram
    c = conciliar(_Proc(100, 90, prop=5, sider=0))
    assert not c.ok
    assert any("Entrada" in p for p in c.problemas)


def test_acusa_perda_no_cruzamento():
    # 60 + 20 = 80 != 100
    c = conciliar(_Proc(100, 100), _Cruz(100, 60, 20, 0))
    assert not c.ok


def test_acusa_divergencia_processado_vs_cruzamento():
    # processadas=100 mas o cruzamento recebeu 95
    c = conciliar(_Proc(100, 100), _Cruz(95, 95, 0, 0))
    assert not c.ok


def _run_all():
    import traceback
    falhas = 0
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"OK  {nome}")
            except Exception:
                falhas += 1
                print(f"FALHOU  {nome}")
                traceback.print_exc()
    print("\n" + ("TODOS OS TESTES PASSARAM." if not falhas else f"{falhas} teste(s) falharam."))
    return falhas


if __name__ == "__main__":
    sys.exit(1 if _run_all() else 0)
