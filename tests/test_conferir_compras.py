"""Testes do Conferir Compras (sem Outlook: e-mails e planilha simulados)."""
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finahub.modules import conferir_compras as CC

TABELA = """<p>Seguem as notas</p><table>
<tr><td>EMPRESA</td><td>FOR</td><td>NOME</td><td>AF</td><td>VENCIMENTO</td><td>NF</td></tr>
<tr><td style="x">ALFAMETAL</td><td>10611</td><td>CESTA BÁSICA</td><td>14918</td><td>26/11/2026</td><td>631207</td></tr>
<tr><td>BETAVIARIA</td><td>4149</td><td>VIBRAMOL</td><td>102069</td><td>26/11/2026</td><td>19830/</td></tr>
<tr><td>ALFAMETAL</td><td>7320</td><td>SERVNEWS</td><td>102085</td><td>26/11/2026</td><td>29229/1138</td></tr>
</table><p>Atenciosamente</p>"""


def test_le_tabela_por_cabecalho():
    n = CC.notas_da_tabela(TABELA, ["ALFAMETAL", "BETAVIARIA"])
    assert [x.nf for x in n] == ["631207", "19830", "29229/1138"]
    assert n[1].empresa == "BETAVIARIA" and n[1].codigo == "4149" and n[1].af == "102069"
    assert n[0].vencimento == "26/11/2026" and n[0].fornecedor == "CESTA BÁSICA"


def test_colunas_em_outra_ordem():
    html = """<table><tr><th>NF</th><th>FORNECEDOR</th><th>EMPRESA</th></tr>
    <tr><td>555</td><td>ACME</td><td>ALFAMETAL</td></tr></table>"""
    n = CC.notas_da_tabela(html, ["ALFAMETAL"])
    assert len(n) == 1 and n[0].nf == "555" and n[0].fornecedor == "ACME"


def test_nf_do_assunto_e_devolucao():
    a = CC.nota_do_assunto("AUTO POSTO RIO CLARO 6 - NF 127414 / AF 61727", ["ALFAMETAL", "BETAVIARIA"])
    assert (a.nf, a.af, a.fornecedor, a.origem) == ("127414", "61727", "AUTO POSTO RIO CLARO 6", "ASSUNTO")
    b = CC.nota_do_assunto("DESCONTO: GAMMA GASOTEC MG X ALFAMETAL NF 8994", ["ALFAMETAL", "BETAVIARIA"])
    assert (b.nf, b.empresa, b.fornecedor) == ("8994", "ALFAMETAL", "GAMMA GASOTEC MG")
    assert CC.nota_do_assunto("NF 927293 - FROMM - DEVOLUÇÃO PARCIAL", ["ALFAMETAL"]) is None
    assert CC.nota_do_assunto("PAGAMENTO - FORJAX FACAS", ["ALFAMETAL"]) is None


def test_tokens_nf():
    assert CC.tokens_nf("630/625/624") == {"630", "625", "624"}
    assert CC.tokens_nf("19830/") == {"19830"}
    assert CC.tokens_nf("0001234") == {"1234"}


def _planilha(tmp_path, linhas):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Notas recebidas"
    ws.append(["NOTAS RECEBIDAS"])
    ws.append([None, "NF", "Empresa", "Fornecedor", "FOR", "ID_Email", "Chave_Provisoria"])
    for l in linhas:
        ws.append([None] + list(l))
    p = tmp_path / "compras.xlsx"
    wb.save(p)
    return CC.ler_planilha(p)


def test_conferir_acha_o_que_falta(tmp_path):
    pl = _planilha(tmp_path, [
        ["631207", "ALFAMETAL", "CESTA", "10611", "<msg-1>", "ALFAMETAL|FOR:10611|NF:631207"],
        ["", "BETAVIARIA", "VIBRAMOL", "4149", "<msg-1>", "BETAVIARIA|FOR:4149|NF:"],   # NF em branco
        ["29229/1138", "ALFAMETAL", "SERVNEWS", "7320", "<msg-1>", "ALFAMETAL|FOR:7320|NF:29229/1138"],
        # nota reenviada: já entrou por outro e-mail
        ["777", "ALFAMETAL", "ACME", "1", "<msg-9>", "ALFAMETAL|FOR:1|NF:777"],
    ])
    emails = [
        CC.EmailCompras("2026-10-29 09:15", "compras1@x", "ENVIO DE NOTA FISCAL", "<MSG-1>", TABELA),
        CC.EmailCompras("2026-10-06 15:12", "compras4@x", "ENVIO DE NOTA FISCAL", "<msg-2>",
                        "<table><tr><td>EMPRESA</td><td>FOR</td><td>NOME</td><td>NF</td></tr>"
                        "<tr><td>ALFAMETAL</td><td>5</td><td>NOVO</td><td>108</td></tr>"
                        "<tr><td>ALFAMETAL</td><td>1</td><td>ACME</td><td>777</td></tr></table>"),
        CC.EmailCompras("2026-10-06 16:25", "compras4@x", "AUTO POSTO - NF 127414", "<msg-3>", "<p>oi</p>"),
        CC.EmailCompras("2026-10-08 08:45", "compras4@x", "PAGAMENTO - FORJAX", "<msg-4>", "<p>oi</p>"),
    ]
    r = CC.conferir(emails, pl)
    falt = {(f.nf, f.motivo.split()[0]) for f in r.faltando}
    assert falt == {("19830", "nota"), ("108", "e-mail"), ("127414", "e-mail")}
    assert r.emails == 4 and r.emails_fora == 2
    assert r.notas_email == 6 and r.notas_ok == 3       # 631207, 29229/1138, 777 (reenvio)
    assert [s[1] for s in r.sem_nota] == ["PAGAMENTO - FORJAX"]
    assert not r.tudo_certo


def test_tudo_certo(tmp_path):
    pl = _planilha(tmp_path, [["555", "ALFAMETAL", "ACME", "1", "<m>", "ALFAMETAL|FOR:1|NF:555"]])
    html = ("<table><tr><td>NF</td><td>FORNECEDOR</td><td>EMPRESA</td></tr>"
            "<tr><td>555</td><td>ACME</td><td>ALFAMETAL</td></tr></table>")
    r = CC.conferir([CC.EmailCompras("2026-10-01 10:00", "a", "x", "<m>", html)], pl)
    assert r.tudo_certo and r.notas_ok == 1
