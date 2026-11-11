"""Testes do módulo Pensões (Excel do DP → CSV de importação)."""
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finahub.modules import pensoes as P


def _dp(path, linhas, total=None):
    """Relatório FPRF004 sintético (mesmas colunas do arquivo real)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Plan1"
    ws.append(["0001", "-", "ALFAMETAL SA INDUSTRIA E COM METAIS"])
    ws.append(["RELATÓRIO PENSÃO"])
    ws.append(["Evento", "Colaborador", None, None, None, "SIT", "Competência",
               "Pagamento", None, "Referência", None, "Valor"])
    ws.append(["0276", "-", "Pensão Judicial"])
    for mat, nome, valor in linhas:
        ws.append([mat, nome, None, None, None, "001", 46296, "30/10/2026",
                   None, "30.00", valor])
    soma = sum(v for _, _, v in linhas) if total is None else total
    ws.append([None, None, None, "Total de Colaboradores:", None, len(linhas),
               None, None, 0, None, soma])
    wb.save(path)
    return Path(path)


def _cadastro(path, linhas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PENSÃO"
    cad = wb.create_sheet("CADASTRO")
    cad.append(["COD", "FUNCIONARIO", "COD", "PENSIONISTA"])
    for l in linhas:
        cad.append(list(l))
    wb.save(path)
    return Path(path)


CAD = [
    ("100001", "CARLOS", "20001", "MARIA APARECIDA SOUZA"),
    ("100002", "PAULO ROBERTO", "20002", "ANA PAULA COSTA"),
    ("100002-A", "PAULO ROBERTO", "20002", "ANA PAULA COSTA"),
    ("100003", "RAFAEL", "20003", "BEATRIZ GOMES ROCHA"),
    ("100003-A", "RAFAEL", "20004", "LUCIANA DIAS PRADO"),
]
DP = [("100001", "CARLOS ALBERTO NUNES", 1000.50),
      ("100002", "PAULO ROBERTO LIMA", 1250.40),
      ("100003", "RAFAEL MOREIRA SANTOS", 1380.20)]


@pytest.fixture
def prep(tmp_path):
    return P.processar(_dp(tmp_path / "dp.xlsx", DP),
                       _cadastro(tmp_path / "cad.xlsx", CAD))


def test_le_dp_e_confere_rodape(prep):
    assert len(prep.dp.linhas) == 3
    assert prep.dp.total == 100050 + 125040 + 138020
    assert prep.dp.total_rodape == prep.dp.total
    assert prep.competencia.month == 10 and prep.competencia.year == 2026
    assert prep.vencimento.strftime("%d/%m/%Y") == "30/10/2026"
    assert not prep.avisos and not prep.sem_cadastro


def test_detecta_quem_paga_mais_de_uma(prep):
    assert {c.linha.matricula for c in prep.casos} == {"100002", "100003"}


def test_bloqueia_sem_valor_digitado(prep):
    r = P.montar(prep, {})
    assert not r.ok
    assert any("falta digitar" in e for e in r.erros)


def test_divide_e_aplica_titulo_com_ponto_so_na_mesma_pensionista(prep):
    r = P.montar(prep, {"100002-A": 40000, "100003-A": 70000})
    assert r.ok, r.erros
    assert r.total == r.total_dp
    por = [(l.fornecedor, l.titulo, l.centavos) for l in r.linhas]
    # mesma pensionista → 2ª linha com ponto
    assert ("ANA PAULA COSTA", "10-2026-SAL", 125040 - 40000) in por
    assert ("ANA PAULA COSTA", "10.2026-SAL", 40000) in por
    # pensionista diferente → os dois com traço (fornecedores distintos)
    assert ("BEATRIZ GOMES ROCHA", "10-2026-SAL", 138020 - 70000) in por
    assert ("LUCIANA DIAS PRADO", "10-2026-SAL", 70000) in por


def test_extra_maior_que_dp_bloqueia(prep):
    r = P.montar(prep, {"100002-A": 200000, "100003-A": 0})
    assert not r.ok
    assert any("passam" in e for e in r.erros)


def test_extra_zero_nao_gera_linha(prep):
    r = P.montar(prep, {"100002-A": 0, "100003-A": 0})
    assert r.ok
    assert len(r.linhas) == 3


def test_matricula_sem_cadastro_bloqueia(tmp_path):
    dp = _dp(tmp_path / "dp.xlsx", DP + [("999999", "NOVO COLABORADOR", 100.0)])
    p = P.processar(dp, _cadastro(tmp_path / "cad.xlsx", CAD))
    assert [l.matricula for l in p.sem_cadastro] == ["999999"]
    r = P.montar(p, {"100002-A": 0, "100003-A": 0})
    assert not r.ok
    assert any("999999" in e for e in r.erros)


def test_rodape_divergente_avisa(tmp_path):
    p = P.processar(_dp(tmp_path / "dp.xlsx", DP, total=1.0),
                    _cadastro(tmp_path / "cad.xlsx", CAD))
    assert any("rodapé" in a for a in p.avisos)


def test_csv_no_leiaute_da_importacao(prep, tmp_path):
    r = P.montar(prep, {"100002-A": 40000, "100003-A": 70000})
    saida = P.gravar(r, tmp_path / "out.csv")
    bruto = saida.read_bytes()
    assert b"\r\n" in bruto
    texto = bruto.decode("cp1252")
    linhas = texto.split("\r\n")
    assert linhas[0] == P.CABECALHO_CSV
    assert linhas[1] == ("0;1;30/10/2026;SEX;20001;MARIA APARECIDA SOUZA;"
                         "10-2026-SAL;1.000,50;0;SAL;19;90540;;;")
    assert all(l.count(";") == 14 for l in linhas if l)


def test_nao_grava_com_pendencia(prep, tmp_path):
    with pytest.raises(ValueError):
        P.gravar(P.montar(prep, {}), tmp_path / "x.csv")


def test_valor_br():
    assert P.valor_br(195000) == "1.950,00"
    assert P.valor_br(18558) == "185,58"
    assert P.valor_br(931909) == "9.319,09"
