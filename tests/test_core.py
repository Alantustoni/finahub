"""Testes das funções de parse do core (utils) e do ConfigCentral.

Cobrem exatamente os casos que falhavam EM SILÊNCIO antes da auditoria:
valores 1000× menores ("1.234" → 1.234), formato US, datas BR com hora,
config.json com seção de tipo errado e a migração dos grupos de usina.
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from finahub.core.utils import formatar_moeda, parse_data_br, parse_valor_br
from finahub.core.config_central import DEFAULT, ConfigCentral


# ── parse_valor_br ────────────────────────────────────────────────────
def test_valor_br_com_centavos():
    assert parse_valor_br("1.234,56") == pytest.approx(1234.56)
    assert parse_valor_br("R$ 1.234,56") == pytest.approx(1234.56)
    assert parse_valor_br("78.115,20") == pytest.approx(78115.20)

def test_valor_milhar_sem_centavos_nao_divide_por_mil():
    # antes: "1.234" → 1.234 (mil vezes menor, em silêncio)
    assert parse_valor_br("1.234") == pytest.approx(1234.0)
    assert parse_valor_br("198.000") == pytest.approx(198000.0)
    assert parse_valor_br("12.345.678") == pytest.approx(12345678.0)

def test_valor_formato_us():
    # antes: "1,234.56" → 1.23456
    assert parse_valor_br("1,234.56") == pytest.approx(1234.56)

def test_valor_decimal_com_ponto():
    assert parse_valor_br("783.6") == pytest.approx(783.6)
    assert parse_valor_br("126908.69") == pytest.approx(126908.69)
    assert parse_valor_br("0.50") == pytest.approx(0.5)

def test_valor_lixo_vira_none():
    assert parse_valor_br("3R") is None       # antes: 3.0 (o R sumia)
    assert parse_valor_br("abc") is None
    assert parse_valor_br(True) is None       # bool não é dinheiro
    assert parse_valor_br("") is None
    assert parse_valor_br(float("nan")) is None

def test_valor_numerico_passa_direto():
    assert parse_valor_br(1234.56) == pytest.approx(1234.56)
    assert parse_valor_br(50) == pytest.approx(50.0)


# ── parse_data_br ─────────────────────────────────────────────────────
def test_data_br_simples():
    assert parse_data_br("29/07/2026") == datetime(2026, 7, 29)

def test_data_br_com_hora():
    # antes: None (linha ia para 'Verificar' mesmo válida)
    assert parse_data_br("29/07/2026 00:00:00") == datetime(2026, 7, 29)
    assert parse_data_br("29/07/2026 14:30") == datetime(2026, 7, 29)

def test_data_iso_e_iso_com_t():
    assert parse_data_br("2026-07-29") == datetime(2026, 7, 29)
    assert parse_data_br("2026-07-29 00:00:00") == datetime(2026, 7, 29)
    assert parse_data_br("2026-07-29T00:00:00") == datetime(2026, 7, 29)

def test_data_iso_nao_vira_dayfirst():
    # 2026-06-01 é 1º de JUNHO, não 6 de janeiro
    assert parse_data_br("2026-06-01") == datetime(2026, 6, 1)

def test_data_invalida_none():
    assert parse_data_br("nan") is None
    assert parse_data_br("31/02/2026") is None


def test_formatar_moeda():
    assert formatar_moeda(1234.5) == "R$ 1.234,50"
    assert formatar_moeda(None) == "—"


# ── ConfigCentral ─────────────────────────────────────────────────────
def test_config_secao_com_tipo_errado_nao_derruba(tmp_path):
    # antes: "usinas": null no JSON → TypeError na inicialização do app
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"usinas": None, "ret": "oops"}),
                 encoding="utf-8")
    cfg = ConfigCentral(p)                     # não pode explodir
    assert isinstance(cfg.get("usinas"), dict)
    assert cfg.get("usinas", "nf_tamanho_minimo") == 3

def test_config_json_corrompido_usa_defaults(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{ isso nao é json", encoding="utf-8")
    cfg = ConfigCentral(p)
    assert cfg.get("ret", "recalcular_trailer") is True

def test_migracao_une_termos_novos_preservando_do_usuario(tmp_path):
    # config antigo (v1): ARMAR sem 'ARMAR', grupo custom do usuário
    antigo = {
        "usinas": {"padronizacao_empresa": {
            "SOLUÇÕES": ["SOLUCOES"],
            "ARMAR": ["ARCELOR", "MITTAL", "TERMO_DO_ALAN"],
            "CSN": ["CSN", "SIDERURGICA NACIONAL"],
            "USIMINAS": ["USIMINAS"],
            "GRUPO_NOVO": ["XPTO"],
        }},
    }
    p = tmp_path / "config.json"
    p.write_text(json.dumps(antigo, ensure_ascii=False), encoding="utf-8")
    cfg = ConfigCentral(p)
    grupos = cfg.get("usinas", "padronizacao_empresa")
    assert "ARMAR" in grupos["ARMAR"]              # termo novo do código entrou
    assert "ARCELORMITTAL PLANOS" in grupos["ARMAR"]
    assert "TERMO_DO_ALAN" in grupos["ARMAR"]      # termo do usuário preservado
    assert "COMPANHIA SIDERURGICA" in grupos["CSN"]
    assert grupos.get("GRUPO_NOVO") == ["XPTO"]    # grupo custom preservado
    assert list(grupos)[0] == "SOLUÇÕES"           # precedência garantida
    # persistiu a versão — a migração não roda de novo
    salvo = json.loads(p.read_text(encoding="utf-8"))
    assert salvo.get("config_versao") == ConfigCentral._CONFIG_VERSAO

def test_lembrar_pasta_nao_clobbera_json_corrompido(tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{ corrompido", encoding="utf-8")
    cfg = ConfigCentral(p)
    cfg.lembrar_pasta("ret", str(tmp_path / "algum" / "arquivo.txt"))
    # o arquivo corrompido NÃO foi sobrescrito com defaults
    assert p.read_text(encoding="utf-8") == "{ corrompido"

def test_lembrar_pasta_persiste_so_a_chave_dela(tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"cnpjs_excluidos": ["123"]}), encoding="utf-8")
    cfg = ConfigCentral(p)
    # edição em memória AINDA NÃO salva (como faz a tela de Configurações)
    cfg.set(["999"], "cnpjs_excluidos")
    d = tmp_path / "pasta_x"
    d.mkdir()
    cfg.lembrar_pasta("ret", str(d / "arq.ret"))
    salvo = json.loads(p.read_text(encoding="utf-8"))
    assert salvo["cnpjs_excluidos"] == ["123"]     # edição não vazou p/ disco
    assert salvo["ui_ultimas_pastas"]["ret"] == str(d)

def test_chaves_motor_nao_vao_para_o_json(tmp_path):
    p = tmp_path / "config.json"
    cfg = ConfigCentral(p)
    cfg.salvar()
    salvo = json.loads(p.read_text(encoding="utf-8"))
    assert "mapa_posicional" not in salvo.get("usinas", {})
    assert "nf_regras_especiais" not in salvo.get("usinas", {})
    # mas em memória continuam vindo do código
    assert cfg.get("usinas", "mapa_posicional") == \
        DEFAULT["usinas"]["mapa_posicional"]


def test_migra_pasta_antiga_uma_vez(tmp_path):
    from finahub.core.paths import migrar_pasta_antiga
    antigo, novo = tmp_path / ".contas_a_pagar_suite", tmp_path / ".finahub"
    antigo.mkdir()
    (antigo / "config.json").write_text('{"x": 1}', encoding="utf-8")
    assert migrar_pasta_antiga(novo, antigo) is True
    assert (novo / "config.json").read_text(encoding="utf-8") == '{"x": 1}'
    assert (antigo / "config.json").exists()          # antiga fica como backup
    assert migrar_pasta_antiga(novo, antigo) is False  # não sobrescreve depois


def test_sem_pasta_antiga_nao_migra(tmp_path):
    from finahub.core.paths import migrar_pasta_antiga
    assert migrar_pasta_antiga(tmp_path / ".finahub", tmp_path / "nada") is False
