"""Testes do DDA × Compras (abreviação, JÁ VEIO, programadas)."""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finahub.modules import dda_compras as DC


# ── abreviação ────────────────────────────────────────────────────────── #
def test_abrevia_sem_perder_identificacao():
    a = DC.abreviar_fornecedor
    assert a("GAMMA GASOTEC GASES INDUSTRIAIS LTDA") == "GAMMA GASOTEC GASES IND"
    assert a("ORBITA SISTEMAS INDUSTRIA E COMERCIO DE PECAS LTDA") == \
        "ORBITA SISTEMAS IND COM PECAS"
    assert a("POLIMERA RECICLAGEM INDUSTRIAL EIRELI") == "POLIMERA RECICLAGEM IND"
    assert a("PETROLUX PRODUTOS DE PETROLEO S A") == "PETROLUX PRODUTOS PETROLEO"
    assert a("NEXO S.A.") == "NEXO"
    assert a("Comércio São José Ltda") == "COM SAO JOSE"
    assert a("LTDA") == "LTDA"            # nunca devolve vazio
    assert a(None) == ""


# ── NF ────────────────────────────────────────────────────────────────── #
def test_nf_com_traco_fica_so_a_parte_antes_sem_zeros():
    assert DC.limpar_nf("00001957-610001") == "1957"
    assert DC.limpar_nf("00015571-613001") == "15571"
    assert DC.limpar_nf("000011/A") == "000011/A"      # outros formatos: iguais
    assert DC.limpar_nf("0417529701") == "0417529701"
    assert DC.limpar_nf(None) is None


def test_formas_da_nf():
    assert "4175297" in DC.nfs_do_dda("0417529701")       # tira a parcela 01
    assert {"9033", "669001"} <= DC.nfs_do_dda("00009033-669001")
    assert "11" in DC.nfs_do_dda("000011/A")
    assert DC.nfs_do_dda("0") == set()
    assert DC.nfs_de_compras("630/625/624") == {"630", "625", "624"}


def test_dia_util_empurra_sabado_e_feriado():
    du = DC.DiaUtil(["02/11"])
    assert du.ajustar(date(2026, 10, 31)) == date(2026, 11, 3)   # sáb → (2/11 feriado) → 3/11
    assert du.ajustar(date(2026, 10, 30)) == date(2026, 10, 30)


# ── JÁ VEIO ───────────────────────────────────────────────────────────── #
def _nota(nfs, forn, venc, emp="ALFAMETAL"):
    return DC.NotaCompras(0, set(nfs), emp, DC._nome_busca(forn), venc)


def _df(linhas):
    return pd.DataFrame(linhas, columns=["EMPRESA", "CNPJ", "FORNECEDOR",
                                         "PRV NF", "VENC", "VALOR"])


def test_ordem_das_regras_e_uso_unico():
    d = pd.Timestamp("2026-10-07")
    df = _df([
        ["ALFAMETAL MATRIZ", "11.111.111/0001-11", "LUMINA LTDA", "81393", d, 10],   # NF+nome+venc
        ["ALFAMETAL MATRIZ", "22.222.222/0001-22", "OUTRO NOME", "555", d, 10],      # NF+venc
        ["ALFAMETAL MATRIZ", "90.100.600/0001-14", "GAMMA GASOTEC GASES", "1", d, 10],
        ["ALFAMETAL MATRIZ", "90.100.600/0001-14", "GAMMA GASOTEC GASES", "2", d, 10],
        ["ALFAMETAL MATRIZ", "90.100.800/0001-77", "DELTA CONTABIL", "1834", d, 10],
        ["ALFAMETAL MATRIZ", "33.333.333/0001-33", "NINGUEM", "999", d, 10],
    ])
    notas = [
        _nota(["81393"], "LUMINA", date(2026, 10, 7)),
        _nota(["555"], "FORNECEDOR QUALQUER", date(2026, 10, 7)),
        # só UMA nota da Gamma Gasotec chegou, com vencimento no sábado anterior?
        # não: no domingo 04/10 → dia útil 05/10 ≠ 07/10; esta é do dia certo:
        _nota(["77"], "GAMMA GASOTEC GASES INDUSTRIAIS LTDA", date(2026, 10, 7)),
    ]
    r = DC.marcar_ja_veio(df, notas, ["90100800"])
    c = df[DC.COL_COMPRAS].tolist()
    assert c[0] == "JÁ VEIO (NF + NOME + VENC)"
    assert c[1] == "JÁ VEIO (NF + VENC)"
    # 1 nota da Gamma Gasotec → só 1 dos 2 boletos sai como JÁ VEIO
    assert sorted(c[2:4]) == ["", "JÁ VEIO (NOME + VENC - CONFERIR)"]
    assert c[4] == "JÁ VEIO (CNPJ NA LISTA)"
    assert c[5] == ""
    assert (r.por_nf_nome, r.por_nf_venc, r.por_nome_venc, r.por_cnpj) == (1, 1, 1, 1)


def test_vencimento_de_fim_de_semana_casa_com_dia_util(tmp_path):
    # Compras manda sábado 10/10; o DDA já ajustou para segunda 12/10?
    # 12/10 é feriado → 13/10. Os dois lados usam a mesma regra.
    du = DC.DiaUtil(["12/10"])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Notas recebidas"
    ws.append(["RELAÇÃO DE NOTAS RECEBIDAS"])
    ws.append([None, "NF", "Empresa", "Fornecedor", "FOR", "AF / Pedido", "Vencimento"])
    ws.append([None, "123/124", "ALFAMETAL", "ACME LTDA", "1", "2", date(2026, 10, 10)])
    p = tmp_path / "compras.xlsx"
    wb.save(p)
    notas = DC.ler_compras(p, du)
    assert notas[0].venc == date(2026, 10, 13) and notas[0].nfs == {"123", "124"}
    df = _df([["ALFAMETAL MG", "1", "ACME", "124", pd.Timestamp("2026-10-13"), 5]])
    DC.marcar_ja_veio(df, notas)
    assert df[DC.COL_COMPRAS][0].startswith("JÁ VEIO")


def test_le_tambem_a_aba_recuperadas(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Notas recebidas"
    ws.append([None, "NF", "Empresa", "Fornecedor", "FOR", "AF / Pedido", "Vencimento"])
    ws.append([None, "111", "ALFAMETAL", "ACME LTDA", "1", "2", date(2026, 10, 7)])
    rec = wb.create_sheet("Recuperadas")
    rec.append(["NOTAS RECUPERADAS PELO ALAN"])
    rec.append([])
    rec.append([])
    rec.append(["NF", "Empresa", "Fornecedor", "FOR", "AF / Pedido", "Vencimento", "Recebido em"])
    rec.append(["19830", "ALFAMETAL", "VIBRAMOL", "4149", "102069", date(2026, 11, 26)])
    p = tmp_path / "compras.xlsx"
    wb.save(p)
    notas = DC.ler_compras(p, DC.DiaUtil())
    assert {n for nt in notas for n in nt.nfs} == {"111", "19830"}


def test_empresa_diferente_nao_casa():
    d = pd.Timestamp("2026-10-07")
    df = _df([["BETAVIARIA MATRIZ", "1", "LUMINA", "81393", d, 10]])
    DC.marcar_ja_veio(df, [_nota(["81393"], "LUMINA", date(2026, 10, 7), "ALFAMETAL")])
    assert df[DC.COL_COMPRAS][0] == ""


# ── lista do relatório ────────────────────────────────────────────────── #
def test_relatorio_tem_pendentes_e_programadas_marcadas():
    cols = ["FILIAL", "EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF", "TIPO", "VENC",
            "VALOR", "ERROS"]
    pend = pd.DataFrame([["M", "ALFAMETAL MATRIZ", "1", "ACME LTDA", "1", "DM",
                          pd.Timestamp("2026-10-07"), 1.0, ""]], columns=cols)
    prog = pend.copy()
    prog["FORNECEDOR"] = "BETA INDUSTRIA LTDA"
    prog["BANCO_DATA"] = "x"
    rc = SimpleNamespace(df_pendente=pend, df_programado=prog)
    df = DC.montar_df_relatorio(pend, rc)
    assert len(df) == 2
    assert df[DC.COL_PROGRAMADA].tolist() == [False, True]
    assert df["FORNECEDOR"].tolist() == ["ACME", "BETA IND"]
    assert "BANCO_DATA" not in df.columns


def test_situacao_da_nota_na_tela():
    from datetime import datetime
    assert DC.situacao(True, "JÁ VEIO – E-MAIL 05/10/2026 11:25 (NF + VENC)",
                       datetime(2026, 10, 5)) == ("prog", "● Programada · banco 05/10")
    assert DC.situacao(False, "JÁ VEIO – E-MAIL 05/10/2026 11:25 (NF + NOME + VENC)") == \
        ("ok", "✓ Já veio · e-mail 05/10 11:25")
    assert DC.situacao(False, "JÁ VEIO (CNPJ NA LISTA)") == ("ok", "✓ Já veio · CNPJ na lista")
    assert DC.situacao(False, "JÁ VEIO – E-MAIL 02/10/2026 08:00 (NOME + VENC - CONFERIR)")[1] \
        == "✓ Já veio · e-mail 02/10 08:00 (conferir)"
    assert DC.situacao(False, "") == ("cob", "! Cobrar")
    assert DC.situacao(float("nan"), float("nan"), float("nan")) == ("cob", "! Cobrar")


def test_relatorio_leva_data_do_banco_so_nas_programadas():
    base = pd.DataFrame({"EMPRESA": ["A", "B"], "FORNECEDOR": ["X", "Y"],
                         "PRV NF": ["1", "2"], "VENC": ["05/10/2026"] * 2,
                         "VALOR": [10.0, 20.0]})
    rc = SimpleNamespace(df_pendente=base.iloc[[0]],
                         df_programado=base.iloc[[1]].assign(BANCO_DATA=["2026-10-05"]))
    df = DC.montar_df_relatorio(base, rc, abreviar=False)
    assert list(df[DC.COL_BANCO_DATA]) == ["", "2026-10-05"]
    assert DC.situacao(df.at[1, DC.COL_PROGRAMADA], "", df.at[1, DC.COL_BANCO_DATA])[0] == "prog"


def test_ja_veio_verde_na_planilha1_e_fora_da_cobranca(tmp_path):
    from finahub.vendor.organizador_dda.core.config import Config
    from finahub.vendor.organizador_dda.core.processor import ProcessingResult
    from finahub.vendor.organizador_dda.excel.report_generator import ExcelReportGenerator

    def nota(forn, prv, compras, prog=False):
        return {"FILIAL": "MATRIZ", "EMPRESA": "ALFAMETAL MATRIZ",
                "CNPJ": "90.100.600/0001-14", "FORNECEDOR": forn, "PRV NF": prv,
                "TIPO": "Cobranca", "VENC": pd.Timestamp("2026-11-03"),
                "VALOR": 100.0, "ERROS": "", DC.COL_COMPRAS: compras,
                DC.COL_PROGRAMADA: prog}

    df = pd.DataFrame([
        nota("COBRAR SA", "1", ""),
        nota("VEIO SA", "2", "JÁ VEIO – E-MAIL 30/10 10:00 (NF + NOME + VENC)"),
        nota("VEIO PROG SA", "3", "JÁ VEIO (CNPJ NA LISTA)", prog=True),
    ])
    result = ProcessingResult()
    result.df = df
    result.total_original = result.total_processado = len(df)
    result.error_counts = pd.Series(dtype=int)
    result.duplicatas = pd.DataFrame()
    result.resumo_remocoes = []
    result.col_map, result.col_warnings = {}, []

    saida = tmp_path / "rel.xlsx"
    ExcelReportGenerator(result, Config(), df_relatorio=df).gerar(saida)
    wb = openpyxl.load_workbook(saida)

    # Planilha1: todas as notas; já veio em verde, programada em amarelo
    p1 = wb["Planilha1"]
    assert p1["A1"].value == "NOTAS JÁ NO CONTAS A PAGAR"
    assert [c.value for c in p1[2]] == ["EMPRESA", "CNPJ", "FORNECEDOR", "PRV NF",
                                        "VENC", "VALOR", "ERROS"]
    cores = {r[2].value: r[0].fill.fgColor.rgb for r in p1.iter_rows(min_row=3)}
    assert cores["VEIO SA"].endswith("C6EFCE")
    assert cores["VEIO PROG SA"].endswith("FFFF00")
    assert not cores["COBRAR SA"].endswith("C6EFCE")

    # aba de cobrança: sem o que já veio (programada continua)
    textos = {str(c.value) for row in wb["ALFAMETAL"].iter_rows() for c in row if c.value}
    assert "COBRAR SA" in textos
    assert "VEIO PROG SA" in textos
    assert "VEIO SA" not in textos
