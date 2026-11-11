"""
config_central.py — Configuração única da suíte.

Um só config.json (em ~/.finahub) alimenta TODOS os módulos:
  • as chaves que o core do DDA conhece (empresas, feriados, exclusões…)
    são repassadas ao Config do organizador_dda sem alteração;
  • as chaves novas ("usinas", "ret") configuram os módulos reescritos.

Escrita atômica (tmp + os.replace) — o arquivo nunca fica corrompido.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

from .paths import CONFIG_PATH, garantir_dirs

logger = logging.getLogger(__name__)

DEFAULT: Dict[str, Any] = {
    # ── chaves compartilhadas com o core do DDA (mesmos nomes) ──────
    "empresas_validas": [
        "ALFAMETAL MATRIZ", "ALFAMETAL MG",
        "BETAVIARIA MATRIZ", "BETAVIARIA PE",
    ],
    "cnpjs_excluidos": [],
    "grupos_empresa": {
        "ALFAMETAL":  ["ALFAMETAL MATRIZ", "ALFAMETAL MG"],
        "BETAVIARIA": ["BETAVIARIA MATRIZ", "BETAVIARIA PE"],
    },
    "remover_texto": [
        "USINAS", "USIMINAS", "ARCELOR", "ARCELORMITTAL",
        "ARCELORMITTAL PLANOS", "USINA SIDERURGICA",
        "USINA SIDERÚRGICA", "COMPANHIA SIDERURGICA",
        "COMPANHIA SIDERÚRGICA",
    ],
    "abreviacoes_fornecedor": {
        "GAMMA GASOTEC GASES INDUSTRIAIS": "GAMMA GASOTEC",
        "GAMMA GASOTEC GASES": "GAMMA GASOTEC",
        "ORBITA SISTEMAS INDUSTRIA": "ORBITA SISTEMAS",
        "POLIMERA RECICLAGEM INDUSTRIAL": "POLIMERA RECICLAGEM",
        "ZK CERTIFICACAO": "ZK CERTIFICACAO",
        "ZK CERTIFICAÇÃO": "ZK CERTIFICACAO",
    },
    "feriados_nacionais": [
        "01/01", "21/04", "01/05", "07/09",
        "12/10", "02/11", "15/11", "25/12",
    ],

    # ── Organizador Usinas ──────────────────────────────────────────
    "usinas": {
        # nome padronizado → termos que identificam a empresa na planilha.
        # A ORDEM importa: o 1º grupo cujo termo aparece no nome vence.
        # SOLUÇÕES vem ANTES de USIMINAS para 'SOLUÇÕES USIMINAS' não ser
        # engolido pelo termo genérico 'USINAS'. Comparação ignora acento.
        "padronizacao_empresa": {
            # SOLUÇÕES: termos reais ainda a confirmar com o Alan
            "SOLUÇÕES": ["SOLUCOES", "SOLUCOES USIMINAS", "SOLUCOES EM ACO"],
            "ARMAR":    ["ARCELORMITTAL PLANOS", "ARCELORMITTAL",
                         "ARCELOR", "ARMAR", "MITTAL"],
            "CSN":      ["COMPANHIA SIDERURGICA", "SIDERURGICA NACIONAL", "CSN"],
            "USIMINAS": ["USIMINAS", "USINA SIDERURGICA",
                         "USINAS SIDERURGICA", "USINAS"],
        },
        # Planilha SEM cabeçalho, colada a partir de A1. O leiaute das USINAS
        # é como o do DDA, porém SEM a coluna FILIAL — então tudo desloca uma
        # coluna à esquerda. Mapa posicional (0-based) medido no arquivo real:
        #   D=usina/fornecedor(3) · E=NOTA(4) · H=VENCIMENTO(7) · J=VALOR(9)
        # (a coluna EMPRESA é confirmada pelo conteúdo — ver _detectar_coluna_usina)
        "mapa_posicional": {"EMPRESA": 3, "NF": 4, "VENCIMENTO": 7, "VALOR": 9},
        # corte de sufixo da NF (dígitos de série/parcela no fim do número).
        # Padrão: corta 2 (parcela "01"). Quando a NF termina em "001" a
        # parcela é de 3 dígitos — corta 3, senão sobra um zero a mais no fim
        # (ex.: 198131001 → 198131). Vale para USIMINAS/ARMAR/CSN — foi
        # confirmado que nenhuma NF terminada em "01" (sem ser "001") fica
        # com zero ao cortar 2.
        "nf_digitos_sufixo_padrao": 2,
        "nf_regras_especiais": [
            {"nf_termina_com": "001", "digitos_sufixo": 3},
        ],
        # tamanho mínimo que a NF precisa ter DEPOIS do corte
        "nf_tamanho_minimo": 3,
    },

    # ── Juntador RET ────────────────────────────────────────────────
    "ret": {
        # True  → trailer de lote/arquivo RECALCULADO pelo conteúdo real
        # False → mantém as 2 linhas fixas do programa antigo (modo legado)
        "recalcular_trailer": True,
        # True  → mantém só registros de detalhe (tipo 3) — corrige o corte
        #         posicional antigo, que comia o 1º título de cada arquivo
        "filtro_estrutural": True,
        # Ordena o arquivo final por vencimento (mantém G + complementares juntos)
        "ordenar_por_vencimento": True,
        # Ignora (remove do TXT final) os títulos de usina — reconhecidos pelo
        # nome do favorecido, usando termos_usinas + os grupos do Org. Usinas.
        "excluir_usinas": True,
        # DUPLICAR USINAS POR FILIAL: para o sistema vincular o boleto por
        # CNPJ+título+vencimento, cada título de usina é expandido numa cópia
        # por CNPJ de filial (o boleto vem com o CNPJ da matriz; a nota no
        # sistema está numa filial). Quando ligado, as usinas NÃO são excluídas.
        "duplicar_usinas_por_filial": False,
        # limite para TESTE: só duplica os primeiros N títulos de usina
        # (0 = todos). Comece pequeno (ex.: 10) para validar no sistema.
        "duplicar_limite_teste": 0,
        # cadastro raiz de CNPJ (8 díg) -> lista de CNPJs de filial (14 díg).
        # O boleto da usina vem com a matriz; aqui ficam as filiais em que a
        # nota pode estar lançada no sistema.
        "filiais_por_raiz": {
            "90100200": [                       # USIMINAS
                "90100200002586", "90100200006069",
                "90100200006301", "90100200004015",
            ],
            "90100300": [                       # CSN
                "90100300013032", "90100300001700",
                "90100300003584", "90100300004807",
            ],
            "90100400": [                       # ARMAR
                "90100400000838",
            ],
            "90100500": [                       # ARCELORMITTAL / ARCELOR
                "90100500026235",
            ],
        },
        # Separa por empresa: se misturar arquivos de empresas diferentes,
        # mantém a MAIORIA e retira os intrusos (empate não remove nada).
        "separar_por_empresa": True,
        "empresas_ret": ["ALFAMETAL", "BETAVIARIA"],
        # Renumera o sequencial (pos. 9-13) dos registros tipo 3 ao juntar
        # vários arquivos. Deixe False até validar com um arquivo aceito.
        "renumerar_sequencial": False,
        # linhas removidas do início/fim de cada arquivo de entrada
        "linhas_cabecalho": 3,
        "linhas_rodape": 2,
        # prefixos de linha descartados (mesma regra do programa antigo)
        "prefixos_ignorados": ["23700015", "23700021I03"],
        # termos que identificam USINAS no nome do favorecido (segmento G)
        # — títulos de usinas não entram na contagem principal
        "termos_usinas": [
            "USIMINAS", "USINAS SIDERURGICAS", "USINA SIDERURGICA",
            "ARCELOR", "MITTAL", "COMPANHIA SIDERURGICA",
            "SIDERURGICA NACIONAL",
        ],
        # linhas fixas usadas no modo legado (as originais do juntador v2)
        "trailer_lote_legado":    "23700025         000032000000000000000000000000000000000000000000",
        "trailer_arquivo_legado": "23799999         000002000108",
    },

    # ── Retorno (combinar retornos de pagamento / SISPAG) ───────────────
    "retorno": {
        # junta vários dias num arquivo só; mantém a MAIORIA por empresa e
        # retira intrusos (empate não remove); ordena por data do header.
        "separar_por_empresa": True,
        "empresas": ["ALFAMETAL", "BETAVIARIA"],
        "ordenar_por_data": True,
    },

    # ── Organizador DDA × Compras (29/10/2026) ──────────────────────────
    # planilha que a automação do e-mail de Compras alimenta
    "dda_compras_path": str(Path.home() / "OneDrive - ALFAMETAL" / "NOTAS - COMPRAS.xlsx"),
    # raízes de CNPJ (8 díg.) que não se cobra de Compras → "JÁ VEIO"
    "dda_cnpjs_ja_veio": [],
    # termos de fornecedor que NÃO são retirados como usina
    "dda_usinas_manter": ["SOLUCOES"],
    "dda_abreviar_fornecedor": True,

    # ── Conferir Compras (Outlook × planilha NOTAS - COMPRAS) ────────────
    "conferir_compras": {
        "conta": "contasapagar@alfametal.example",
        "pasta": "COMPRAS",
        "remetentes": ["compras1@alfametal.example", "compras4@alfametal.example"],
        "empresas": ["ALFAMETAL", "BETAVIARIA"],
        "dias": 30,
        # a automação começou nesta data — e-mails anteriores não são cobrados
        "inicio_automacao": "2026-09-28",
    },

    # ── Pensões (Excel do DP → CSV de importação) ───────────────────────
    "pensoes": {
        # planilha que tem a aba CADASTRO (matrícula → pensionista)
        "cadastro_path": "",
        # campos fixos da linha do CSV
        "regt": "0", "empresa": "1", "observacao": "0", "tipo": "SAL",
        "g_contas": "19", "transacao": "90540", "sufixo_titulo": "SAL",
        # último valor digitado por pensão extra (sugestão no mês seguinte)
        "ultimos_valores": {},
    },
}


class ConfigCentral:
    """Carrega/salva o config.json único e expõe as seções."""

    # Chaves de "motor" (não editáveis pela UI): vêm SEMPRE do código, mesmo
    # que exista valor antigo salvo no config.json. Sem isto, um config.json
    # gravado numa versão anterior congelava melhorias (foi o que aconteceu
    # com o mapa das colunas e a regra de corte da NF das usinas).
    _CHAVES_MOTOR = {
        "usinas": ("mapa_posicional", "nf_regras_especiais"),
    }

    # Versão do config. Quando o código evolui listas que o usuário TAMBÉM
    # edita (ex.: grupos de usina), um config salvo por versão anterior
    # congelava os termos novos. A migração roda UMA vez por versão:
    # une os termos novos do DEFAULT aos grupos salvos (preservando os
    # termos/grupos que o usuário adicionou) e grava a nova versão.
    _CONFIG_VERSAO = 2

    def __init__(self, path: Path | None = None) -> None:
        garantir_dirs()
        self.path = path or CONFIG_PATH
        self._data: Dict[str, Any] = copy.deepcopy(DEFAULT)
        self.recarregar()

    # ------------------------------------------------------------------ #
    def recarregar(self) -> None:
        self._data = copy.deepcopy(DEFAULT)
        versao_salva = 0
        carregou_ok = False       # só migra/salva se o JSON do disco carregou
        try:
            if self.path.exists():
                user = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(user, dict):
                    versao_salva = int(user.get("config_versao", 1) or 1)
                    self._merge(self._data, user)
                    carregou_ok = True
        except Exception:
            logger.warning("config.json inválido — usando defaults.", exc_info=True)
        try:
            # motor sempre do código (config antigo não sobrescreve)
            for secao, chaves in self._CHAVES_MOTOR.items():
                if not isinstance(self._data.get(secao), dict):
                    self._data[secao] = copy.deepcopy(DEFAULT.get(secao, {}))
                for chave in chaves:
                    if secao in DEFAULT and chave in DEFAULT[secao]:
                        self._data[secao][chave] = \
                            copy.deepcopy(DEFAULT[secao][chave])
            # migração única por versão (une termos novos sem apagar edições).
            # NUNCA roda sobre um JSON que não carregou — senão o salvar()
            # sobrescreveria o arquivo (possivelmente recuperável) c/ defaults.
            if carregou_ok and versao_salva < self._CONFIG_VERSAO:
                self._migrar(versao_salva)
        except Exception:
            logger.warning("falha ao normalizar o config — usando defaults.",
                           exc_info=True)
            self._data = copy.deepcopy(DEFAULT)
        self._data["config_versao"] = self._CONFIG_VERSAO

    def _migrar(self, versao_salva: int) -> None:
        """v<2 → v2: une os grupos de usina do DEFAULT aos salvos."""
        logger.info("config: migrando v%d → v%d", versao_salva,
                    self._CONFIG_VERSAO)
        salvo = self._data.get("usinas", {}).get("padronizacao_empresa")
        padrao = DEFAULT["usinas"]["padronizacao_empresa"]
        if isinstance(salvo, dict):
            novo: Dict[str, Any] = {}
            for grupo, termos_padrao in padrao.items():   # ordem do DEFAULT
                termos_usuario = [t for t in (salvo.get(grupo) or [])
                                  if isinstance(t, str)]
                extras = [t for t in termos_usuario if t not in termos_padrao]
                novo[grupo] = list(termos_padrao) + extras
            for grupo, termos in salvo.items():           # grupos do usuário
                if grupo not in novo and isinstance(termos, list):
                    novo[grupo] = termos
            self._data["usinas"]["padronizacao_empresa"] = novo
        self._data["config_versao"] = self._CONFIG_VERSAO
        try:
            self.salvar()
        except Exception:
            logger.warning("não consegui persistir a migração do config.",
                           exc_info=True)

    def salvar(self) -> None:
        """Escrita atômica: tmp no mesmo diretório + os.replace.

        As chaves de MOTOR não são gravadas — elas vêm sempre do código,
        e mantê-las no JSON sugeriria que são editáveis (não são).
        """
        dados = copy.deepcopy(self._data)
        for secao, chaves in self._CHAVES_MOTOR.items():
            if isinstance(dados.get(secao), dict):
                for chave in chaves:
                    dados[secao].pop(chave, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp.json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(dados, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _merge(base: Dict, extra: Dict) -> None:
        for k, v in extra.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                ConfigCentral._merge(base[k], v)
            elif k in base and base[k] is not None and v is not None \
                    and isinstance(base[k], (dict, list)) != isinstance(v, (dict, list)):
                # tipo incompatível com o DEFAULT (ex.: seção virou null/str
                # num JSON editado à mão) — ignora em vez de quebrar o app
                logger.warning("config: chave %r com tipo inesperado — ignorada.", k)
            else:
                base[k] = v

    # ------------------------------------------------------------------ #
    def get(self, *chaves: str, default: Any = None) -> Any:
        node: Any = self._data
        for c in chaves:
            if not isinstance(node, dict) or c not in node:
                return default
            node = node[c]
        return node

    def set(self, valor: Any, *chaves: str) -> None:
        node = self._data
        for c in chaves[:-1]:
            node = node.setdefault(c, {})
        node[chaves[-1]] = valor

    @property
    def dados(self) -> Dict[str, Any]:
        return self._data

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Memória da última pasta usada por módulo (conveniência de UI)        #
    # ------------------------------------------------------------------ #
    def ultima_pasta(self, modulo: str) -> str:
        """Última pasta usada no módulo (''  se ainda não houver)."""
        pastas = self.get("ui_ultimas_pastas", default={}) or {}
        caminho = pastas.get(modulo, "")
        return caminho if caminho and os.path.isdir(caminho) else ""

    def lembrar_pasta(self, modulo: str, caminho: Any) -> None:
        """
        Guarda a pasta de um arquivo escolhido e persiste em disco.

        IMPORTANTE: persiste APENAS a chave "ui_ultimas_pastas" (lendo o
        JSON do disco e regravando só ela). Salvar o config inteiro aqui
        teria dois efeitos colaterais: persistir edições ainda não
        confirmadas da tela de Configurações e, se o JSON do disco
        estivesse corrompido, sobrescrevê-lo com os defaults.
        """
        try:
            caminho = str(caminho)
            pasta = caminho if os.path.isdir(caminho) else os.path.dirname(caminho)
            if not pasta:
                return
            pastas = dict(self.get("ui_ultimas_pastas", default={}) or {})
            if pastas.get(modulo) == pasta:
                return  # nada mudou — evita regravar o config à toa
            pastas[modulo] = pasta
            self.set(pastas, "ui_ultimas_pastas")   # memória desta sessão
            self._persistir_ui_pastas(pastas)       # disco: só esta chave
        except Exception:
            logger.warning("não consegui lembrar a última pasta", exc_info=True)

    def persistir_chave(self, valor: Any, *chaves: str) -> None:
        """Grava só UMA chave no JSON do disco (mesma cautela de lembrar_pasta:
        não persiste edições pendentes da tela de Configurações)."""
        disco: Dict[str, Any] = {}
        if self.path.exists():
            try:
                lido = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return              # JSON corrompido — não clobbera o arquivo
            if not isinstance(lido, dict):
                return
            disco = lido
        node = disco
        for c in chaves[:-1]:
            if not isinstance(node.get(c), dict):
                node[c] = {}
            node = node[c]
        node[chaves[-1]] = valor
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp.json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(disco, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _persistir_ui_pastas(self, pastas: Dict[str, str]) -> None:
        """Regrava só "ui_ultimas_pastas" no JSON do disco (atômico)."""
        disco: Dict[str, Any] = {}
        if self.path.exists():
            try:
                lido = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(lido, dict):
                    disco = lido
                else:
                    return          # conteúdo estranho — não sobrescreve
            except Exception:
                return              # JSON corrompido — não clobbera o arquivo
        disco["ui_ultimas_pastas"] = pastas
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp.json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(disco, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def config_dda(self):
        """
        Constrói o Config do organizador_dda a partir DESTE config.json —
        o core do DDA lê apenas as chaves que conhece.
        """
        from ..vendor.organizador_dda.core.config import Config
        return Config(self.path)
