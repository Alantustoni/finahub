"""Testes do DataProcessorExt — planilha sem cabeçalho + grupos de usinas."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from finahub.modules.dda_ext import (DataProcessorExt, MAPA_POSICIONAL,
                                        semana_do_resultado)
from finahub.vendor.organizador_dda.core.config import Config


def _planilha(tmp_path, com_cabecalho: bool):
    """Planilha de teste com o layout A..L combinado (12 colunas)."""
    import pandas as pd

    linhas = [
        # FILIAL, EMPRESA, C, CNPJ, FORNECEDOR, NOTA, TIPO, H, VENC, J, K, VALOR
        ["MATRIZ", "ALFAMETAL", "", "11.222.333/0001-44", "METALFORTE LTDA",
         "10442", "NF", "", "20/07/2026", "", "", "1.234,56"],
        ["MG", "ALFAMETAL MG", "", "22.333.444/0001-55", "POSTO TREVO",
         "5501", "PROPOSTA", "", "21/07/2026", "", "", "800,00"],
        ["MATRIZ", "ALFAMETAL", "", "33.444.555/0001-66",
         "USIMINAS USINAS SIDERURGICAS DE MG", "9001", "NF", "",
         "22/07/2026", "", "", "50.000,00"],
        ["MATRIZ", "ALFAMETAL", "", "44.555.666/0001-77",
         "ARCELORMITTAL BRASIL", "9002", "NF", "", "23/07/2026", "", "",
         "30.000,00"],
        ["MATRIZ", "ALFAMETAL", "", "55.666.777/0001-88",
         "CSN COMPANHIA SIDERURGICA NACIONAL", "9003", "NF", "",
         "24/07/2026", "", "", "20.000,00"],
    ]
    caminho = tmp_path / ("com_cab.xlsx" if com_cabecalho else "sem_cab.xlsx")
    if com_cabecalho:
        cab = ["FILIAL", "EMPRESA", "X", "CNPJ", "FORNECEDOR", "NOTA",
               "TIPO", "H", "VENCIMENTO", "J", "K", "VALOR"]
        pd.DataFrame(linhas, columns=cab).to_excel(caminho, index=False)
    else:
        pd.DataFrame(linhas).to_excel(caminho, index=False, header=False)
    return caminho


def _proc():
    return DataProcessorExt(Config())


def test_mapa_posicional_cobre_colunas_combinadas():
    assert MAPA_POSICIONAL == {0: "FILIAL", 1: "EMPRESA", 3: "CNPJ",
                               4: "FORNECEDOR", 5: "NOTA", 6: "TIPO",
                               8: "VENCIMENTO", 11: "VALOR"}


def test_sem_cabecalho_processa_igual(tmp_path):
    proc = _proc()
    r = proc.processar(_planilha(tmp_path, com_cabecalho=False))
    assert proc.usou_mapa_posicional is True
    assert r.total_original == 5
    # 1 proposta + 3 usinas removidas → sobra 1
    assert r.removidas_proposta == 1
    assert r.removidas_siderurgicas == 3
    assert r.total_processado == 1
    assert r.df.iloc[0]["FORNECEDOR"] == "METALFORTE LTDA"


def test_com_cabecalho_continua_funcionando(tmp_path):
    proc = _proc()
    r = proc.processar(_planilha(tmp_path, com_cabecalho=True))
    assert proc.usou_mapa_posicional is False
    assert r.total_processado == 1


def test_captura_propostas_e_usinas(tmp_path):
    proc = _proc()
    proc.processar(_planilha(tmp_path, com_cabecalho=False))
    assert len(proc.df_propostas) == 1
    assert proc.df_propostas.iloc[0]["PRV NF"] == "5501"
    assert len(proc.df_usinas) == 3


def test_totais_por_grupo_de_usina(tmp_path):
    proc = _proc()
    proc.processar(_planilha(tmp_path, com_cabecalho=False))
    t = proc.totais_usinas
    assert t["USIMINAS"] == pytest.approx(50000.0)
    assert t["ARMAR"] == pytest.approx(30000.0)
    assert t["CSN"] == pytest.approx(20000.0)


def test_semana_do_resultado(tmp_path):
    proc = _proc()
    r = proc.processar(_planilha(tmp_path, com_cabecalho=False))
    # única linha restante vence em 20/07 → semana 20/07 a 20/07
    assert semana_do_resultado(r.df) == "20/07 a 20/07"


def _proc_real(tmp_path):
    """DataProcessorExt com config real de defaults num tmp."""
    from finahub.core.config_central import ConfigCentral
    from finahub.modules.dda_ext import DataProcessorExt
    cfgc = ConfigCentral(tmp_path / "config.json")
    cfgc.salvar()
    return (DataProcessorExt(cfgc.config_dda(),
                             cfgc.get("usinas", "padronizacao_empresa")),
            cfgc)


# ── layout NOVO do DDA (ago/2026) ─────────────────────────────────────
def _planilha_layout_novo(caminho, com_cabecalho=True):
    """Réplica do relatório novo: FILIAL·Pagador·Beneficiário·CPF/CNPJ·
    Venc.·Nº doc.·Até venc.·A pagar·Tipo de boleto·Banco·Observações."""
    import pandas as pd
    cab = ["FILIAL", "Pagador/Agregado", "Beneficiário", "CPF/CNPJ",
           "Venc.", "Nº doc.", "Até venc.", "A pagar", "Tipo de boleto",
           "Banco", "Observações"]
    def lin(filial, pagador, forn, nf, venc, valor):
        return [filial, pagador, forn, "90.100.600/0001-14",
                venc, nf, f"R$\xa0{valor}", f"R$\xa0{valor}",
                "DM Duplicata Mercantil", "341", ""]
    dados = [
        lin("MATRIZ", "ALFAMETAL SA INDUSTRIA E COMER",
            "GAMMA GASOTEC GASES INDUSTRIAIS LTDA", "1001",
            "2026-08-31 00:00:00", "433,27"),
        lin("MINAS", "ALFAMETAL S A IND COM METAIS",
            "KASTELO COMERCIAL E LTDA", "1002",
            "2026-09-01 00:00:00", "3.180,00"),
        lin("MATRIZ", "BETAVIARIA TRANSPORTES S A",
            "USINA SIDERURGICA MG USIMINAS", "1003",
            "2026-09-01 00:00:00", "9.999,99"),
    ]
    linhas = ([cab] + dados) if com_cabecalho else dados
    pd.DataFrame(linhas).to_excel(caminho, index=False, header=False)
    return caminho


def test_layout_novo_com_cabecalho(tmp_path):
    proc, cfgc = _proc_real(tmp_path)
    arq = _planilha_layout_novo(tmp_path / "novo.xlsx", com_cabecalho=True)
    res = proc.processar(arq)
    assert proc.usou_mapa_posicional is False
    # empresas normalizadas a partir de FILIAL + Pagador
    empresas = set(res.df["EMPRESA"])
    assert empresas == {"ALFAMETAL MATRIZ", "ALFAMETAL MG"} or         "ALFAMETAL MATRIZ" in empresas
    # a usina foi removida e classificada
    assert len(proc.df_usinas) == 1
    assert proc.totais_usinas.get("USIMINAS") == pytest.approx(9999.99)
    # valores com "R$ " (nbsp) parseados
    assert res.df["VALOR"].sum() == pytest.approx(433.27 + 3180.00)


def test_layout_novo_sem_cabecalho(tmp_path):
    proc, cfgc = _proc_real(tmp_path)
    arq = _planilha_layout_novo(tmp_path / "novo_sem.xlsx", com_cabecalho=False)
    res = proc.processar(arq)
    assert proc.usou_mapa_posicional is True     # decidiu pelo conteúdo
    assert res.total_processado == 2             # 2 notas (1 usina removida)
    assert res.df["VALOR"].sum() == pytest.approx(433.27 + 3180.00)


def test_layout_antigo_sem_cabecalho_continua(tmp_path):
    """A planilha ANTIGA (12 colunas, venc na I, valor na L) segue OK."""
    import pandas as pd
    proc, cfgc = _proc_real(tmp_path)
    def lin(filial, emp, forn, nf, venc, valor):
        row = [""] * 12
        row[0], row[1], row[3], row[4] = filial, emp, "90.100.600/0001-14", forn
        row[5], row[6], row[8], row[11] = nf, "Cobrança", venc, valor
        return row
    dados = [
        lin("MATRIZ", "ALFAMETAL", "GAMMA GASOTEC", "2001",
            "31/08/2026", "1.234,56"),
        lin("MG", "ALFAMETAL", "KASTELO COMERCIAL", "2002",
            "01/09/2026", "500,00"),
    ]
    arq = tmp_path / "antigo.xlsx"
    pd.DataFrame(dados).to_excel(arq, index=False, header=False)
    res = proc.processar(arq)
    assert proc.usou_mapa_posicional is True
    assert res.total_processado == 2
    assert res.df["VALOR"].sum() == pytest.approx(1234.56 + 500.00)
