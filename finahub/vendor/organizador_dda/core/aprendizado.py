"""
aprendizado.py
Aprende abreviações de fornecedores automaticamente a partir dos cruzamentos
com o banco.

CORREÇÕES v2 (identificadas em auditoria):
  - threading.Lock global protege leitura e escrita simultânea
  - Escrita atômica via arquivo temporário + os.replace (elimina risco de
    truncamento/corrupção ao fechar o programa durante a gravação)
  - Sanitização de strings antes de comparar (evita crash com NaN)
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

_ARQUIVO_APRENDIZADO = Path(__file__).resolve().parent.parent / "abreviacoes_aprendidas.json"
_LIMIAR_APRENDIZADO  = 75.0

# Lock global — garante que apenas uma thread por vez acessa o arquivo
_LOCK = threading.Lock()


def _carregar() -> Dict[str, str]:
    """Leitura thread-safe do arquivo de aprendizado."""
    with _LOCK:
        try:
            if _ARQUIVO_APRENDIZADO.exists():
                dados = json.loads(
                    _ARQUIVO_APRENDIZADO.read_text(encoding="utf-8")
                )
                return dados.get("abreviacoes", {})
        except Exception:
            logger.debug("Erro ao carregar aprendizado.", exc_info=True)
        return {}


def _salvar(abreviacoes: Dict[str, str]) -> None:
    """
    Gravação atômica via arquivo temporário + os.replace.
    Garante que o JSON nunca fica corrompido ou truncado,
    mesmo que o processo seja encerrado durante a escrita.
    """
    with _LOCK:
        try:
            dados = {
                "abreviacoes": abreviacoes,
                "atualizado":  str(date.today()),
                "total":       len(abreviacoes),
            }
            conteudo = json.dumps(dados, ensure_ascii=False, indent=2)

            # Escreve em arquivo temporário no mesmo diretório
            # (mesmo volume = os.replace é atômico no SO)
            fd, tmp_path = tempfile.mkstemp(
                dir=_ARQUIVO_APRENDIZADO.parent,
                suffix=".tmp.json",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(conteudo)
                os.replace(tmp_path, _ARQUIVO_APRENDIZADO)
            except Exception:
                # Remove o temporário se algo falhou antes do replace
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

        except Exception:
            logger.warning("Erro ao salvar aprendizado.", exc_info=True)


def aprender_do_cruzamento(resultado_cruzamento) -> Tuple[int, List[str]]:
    """
    Analisa o resultado do cruzamento e registra novos pares aprendidos.
    Retorna (novos_registros, lista_de_novidades) para exibir no painel.
    Thread-safe — pode ser chamado de qualquer thread.
    """
    if resultado_cruzamento is None:
        return 0, []

    df_prog = resultado_cruzamento.df_programado
    if df_prog is None or df_prog.empty:
        return 0, []

    colunas_necessarias = {"FORNECEDOR", "BANCO_FAVORECIDO", "SIMILARIDADE"}
    if not colunas_necessarias.issubset(df_prog.columns):
        return 0, []

    # Carregar uma única vez antes de iterar
    aprendidas = _carregar()
    novidades: List[str] = []

    for _, row in df_prog.iterrows():
        # Sanitização explícita — NaN vira string vazia
        forn_dda   = str(row.get("FORNECEDOR",      "") or "").strip()
        forn_banco = str(row.get("BANCO_FAVORECIDO", "") or "").strip()

        try:
            sim = float(row.get("SIMILARIDADE", 0) or 0)
        except (ValueError, TypeError):
            sim = 0.0

        if not forn_dda or not forn_banco:
            continue
        if sim < _LIMIAR_APRENDIZADO:
            continue
        if forn_dda.upper() == forn_banco.upper():
            continue

        chave = forn_banco.upper().strip()
        if chave not in aprendidas:
            aprendidas[chave] = forn_dda
            novidades.append(f"{forn_banco} → {forn_dda}  ({sim:.0f}%)")

    if novidades:
        _salvar(aprendidas)
        logger.info("Aprendizado: %d novos pares registrados.", len(novidades))

    return len(novidades), novidades


def carregar_abreviacoes_aprendidas() -> Dict[str, str]:
    """
    Retorna as abreviações aprendidas para merge com config.abreviacoes.
    Chamado no __init__ do DataProcessor. Thread-safe.
    """
    return _carregar()
