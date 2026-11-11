"""
config.py
Centraliza toda a configuração do sistema.
Suporta override via config.json externo.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional


class Config:
    """
    Responsabilidade única: gerenciar configurações.
    Lida com defaults, merge com arquivo externo e exposição
    tipada de cada seção.  Nenhuma lógica de negócio aqui.
    """

    DEFAULT: Dict[str, Any] = {
        "remover_texto": [
            "USINAS", "USIMINAS", "ARCELOR", "ARCELORMITTAL",
            "ARCELORMITTAL PLANOS", "USINA SIDERURGICA",
            "USINA SIDERÚRGICA", "COMPANHIA SIDERURGICA",
            "COMPANHIA SIDERÚRGICA",
        ],
        "empresas_validas": [
            "ALFAMETAL MATRIZ", "ALFAMETAL MG",
            "BETAVIARIA MATRIZ", "BETAVIARIA PE",
        ],
        # Exclusao deterministica por CNPJ (raiz de 8 digitos ou CNPJ completo).
        # Mais seguro que regex de nome: "USINAS" quase casa com "USINAGEM".
        # Preencha no config.json com os CNPJs das siderurgicas.
        "cnpjs_excluidos": [],
        # Grupos nomeados — única fonte da verdade para todos os módulos.
        "grupos_empresa": {
            "ALFAMETAL": ["ALFAMETAL MATRIZ", "ALFAMETAL MG"],
            "BETAVIARIA": ["BETAVIARIA MATRIZ", "BETAVIARIA PE"],
        },
        "abreviacoes_fornecedor": {
            "GAMMA GASOTEC GASES INDUSTRIAIS": "GAMMA GASOTEC",
            "GAMMA GASOTEC GASES": "GAMMA GASOTEC",
            "ORBITA SISTEMAS INDUSTRIA": "ORBITA SISTEMAS",
            "POLIMERA RECICLAGEM INDUSTRIAL": "POLIMERA RECICLAGEM",
            "CASA DE PNEUS PRIMATO": "CASA DE PNEUS PRIMATO",
            "ZK CERTIFICACAO": "ZK CERTIFICACAO",
            "ZK CERTIFICAÇÃO": "ZK CERTIFICACAO",
        },
        "remover_palavras_fornecedor": [
            "LTDA", "LTDA.", "S/A", "SA", "EIRELI", "ME", "EPP",
            "INDUSTRIA", "INDÚSTRIA", "INDUSTRIAL",
            "COMERCIO", "COMÉRCIO", "COMERCIAL",
            "SERVICOS", "SERVIÇOS", "PRESTADORA",
            "EMPRESA", "SOCIEDADE", "UNIPESSOAL",
        ],
        "dias_semana": {
            0: "SEGUNDA", 1: "TERÇA", 2: "QUARTA",
            3: "QUINTA", 4: "SEXTA",
        },
        "feriados_nacionais": [
            "01/01", "21/04", "01/05", "07/09",
            "12/10", "02/11", "15/11", "25/12",
        ],
    }

    def __init__(self, config_path: Optional[Path] = None) -> None:
        import copy
        self._data: Dict[str, Any] = copy.deepcopy(self.DEFAULT)
        if config_path and config_path.exists():
            self._merge_external(config_path)

    def _merge_external(self, path: Path) -> None:
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
            for key in self._data:
                if key in user:
                    self._data[key] = user[key]
            logging.debug("config.json carregado de %s", path)
        except Exception:
            logging.warning("Falha ao carregar config.json — usando defaults.")

    # ------------------------------------------------------------------ #
    # Propriedades tipadas — evita acesso direto ao dict interno          #
    # ------------------------------------------------------------------ #

    @property
    def remover_texto(self) -> List[str]:
        return self._data["remover_texto"]

    @property
    def empresas_validas(self) -> List[str]:
        return self._data["empresas_validas"]

    @property
    def cnpjs_excluidos(self) -> List[str]:
        return self._data.get("cnpjs_excluidos", [])

    @property
    def grupos_empresa(self) -> Dict[str, List[str]]:
        return self._data["grupos_empresa"]

    @property
    def abreviacoes(self) -> Dict[str, str]:
        return self._data["abreviacoes_fornecedor"]

    @property
    def palavras_remover_fornecedor(self) -> List[str]:
        return self._data["remover_palavras_fornecedor"]

    @property
    def dias_semana(self) -> Dict[int, str]:
        # JSON armazena chaves como string; normalizamos para int.
        raw = self._data["dias_semana"]
        return {int(k): v for k, v in raw.items()}

    @property
    def feriados(self) -> List[str]:
        return self._data["feriados_nacionais"]
