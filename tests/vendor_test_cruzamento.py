"""
test_cruzamento.py
Regressao dos bugs de "notas somem" no cruzamento DDA x banco.

Roda com pytest (a partir da pasta DDA V7) ou direto:
    python organizador_dda/tests/test_cruzamento.py
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finahub.vendor.organizador_dda.core.banco_parser import PagamentoBanco
from finahub.vendor.organizador_dda.core.banco_cruzamento import cruzar

CNPJ_WM = "12345678000199"


def _pag(cnpj, data, valor, empresa="ALFAMETAL LTDA", fav="GAMMA GASOTEC GASES"):
    return PagamentoBanco(
        empresa_banco=empresa, cnpj_empresa="", favorecido=fav,
        cnpj_favorecido=cnpj, tipo_pagamento="", referencia="",
        data=data, valor=valor, status="",
    )


def _nota(prv, venc, valor, empresa="ALFAMETAL MATRIZ", cnpj=CNPJ_WM, forn="GAMMA GASOTEC"):
    return {"EMPRESA": empresa, "CNPJ": cnpj, "FORNECEDOR": forn,
            "PRV NF": prv, "VENC": pd.Timestamp(venc), "VALOR": valor}


def test_um_para_um_nao_colapsa():
    # 2 notas iguais (mesmo CNPJ/valor), 1 pagamento -> so 1 casa.
    df = pd.DataFrame([_nota("1", "2026-07-06", 500.0),
                       _nota("2", "2026-07-07", 500.0)])
    r = cruzar(df, [_pag(CNPJ_WM, date(2026, 7, 6), 500.0)])
    assert r.total_programado == 1
    assert r.total_pendente == 1


def test_escopo_por_empresa():
    # Nota Alfametal nao casa com pagamento da conta Betaviaria.
    df = pd.DataFrame([_nota("1", "2026-07-06", 500.0)])
    r = cruzar(df, [_pag(CNPJ_WM, date(2026, 7, 6), 500.0, empresa="BETAVIARIA TRANSPORTES")])
    assert r.total_pendente == 1
    assert r.total_programado == 0


def test_valor_diferente_continua_pendente():
    # CNPJ+data batem mas valor diferente -> nota fica PENDENTE (nao some).
    df = pd.DataFrame([_nota("1", "2026-07-07", 1033.61)])
    r = cruzar(df, [_pag(CNPJ_WM, date(2026, 7, 7), 482.00)])
    assert r.total_pendente == 1
    assert r.total_programado == 0
    assert r.total_divergente == 0


def test_match_legitimo_funciona():
    df = pd.DataFrame([_nota("1", "2026-07-07", 1033.61)])
    r = cruzar(df, [_pag(CNPJ_WM, date(2026, 7, 7), 1033.61)])
    assert r.total_programado == 1
    assert r.total_pendente == 0


def test_pagamentos_nao_casados():
    # Um pagamento sem nota correspondente aparece na lista de "sem nota".
    df = pd.DataFrame([_nota("1", "2026-07-07", 1033.61)])
    certo = _pag(CNPJ_WM, date(2026, 7, 7), 1033.61)
    orfao = _pag("99999999000199", date(2026, 7, 7), 200.0, fav="FORNECEDOR X")
    r = cruzar(df, [orfao, certo])
    assert r.total_programado == 1
    favs = [p.favorecido for p in r.pagamentos_nao_casados]
    assert favs == ["FORNECEDOR X"]


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
