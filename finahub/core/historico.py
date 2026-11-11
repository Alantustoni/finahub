"""
historico.py — Registro central de execuções (todos os módulos).

Cada execução gera um evento: quando, qual módulo, arquivos de entrada,
resumo (contagens/valores) e arquivo gerado. É o que alimenta o
dashboard — e responde ao clássico "eu processei ou não processei?".

Armazenamento: JSON em ~/.finahub/historico.json, escrita atômica,
mantém os últimos 500 eventos.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import date, datetime
from typing import Any, Dict, List

from .paths import HISTORICO_PATH, garantir_dirs

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_MAX_EVENTOS = 500

MODULOS = {
    "dda":     "Organizador DDA",
    "remessa": "Remessa × Banco",
    "ret":     "Juntador RET",
    "usinas":  "Organizador Usinas",
    "pensoes": "Pensões",
    "conferir_compras": "Conferir Compras",
    "importacao_usinas": "Importação Usinas",
    "retorno": "Retorno (SISPAG)",
    "filtrar_importacao": "Filtrar Importação (removido)",
}


def registrar(modulo: str, acao: str, resumo: Dict[str, Any] | None = None,
              arquivos: List[str] | None = None, saida: str | None = None) -> None:
    """Acrescenta um evento ao histórico. Nunca lança exceção para a UI."""
    evento = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "modulo": modulo,
        "acao": acao,
        "resumo": resumo or {},
        "arquivos": [str(a) for a in (arquivos or [])],
        "saida": str(saida) if saida else "",
    }
    try:
        with _LOCK:
            eventos = _ler()
            eventos.append(evento)
            _gravar(eventos[-_MAX_EVENTOS:])
    except Exception:
        logger.warning("Falha ao registrar histórico.", exc_info=True)


def listar(limite: int = 50) -> List[Dict[str, Any]]:
    with _LOCK:
        eventos = _ler()
    return list(reversed(eventos[-limite:]))


def resumo_hoje() -> Dict[str, Any]:
    """Métricas agregadas do dia para o dashboard."""
    hoje = date.today().isoformat()
    with _LOCK:
        eventos = [e for e in _ler() if e.get("ts", "").startswith(hoje)]

    modulos_usados = {e["modulo"] for e in eventos}
    total_prog = sum(_int(e["resumo"].get("programados")) +
                     _int(e["resumo"].get("conciliados")) for e in eventos)
    total_pend = sum(_int(e["resumo"].get("pendentes")) +
                     _int(e["resumo"].get("divergencias")) for e in eventos)
    total_inc  = sum(_int(e["resumo"].get("inconsistencias")) for e in eventos)
    return {
        "execucoes": len(eventos),
        "modulos_usados": len(modulos_usados),
        "conciliados": total_prog,
        "pendentes": total_pend,
        "inconsistencias": total_inc,
    }


def pendencias_abertas() -> List[Dict[str, Any]]:
    """
    Pendências da execução MAIS RECENTE de cada módulo — alimenta a
    lista "Pendências abertas" do dashboard (no lugar dos atalhos que
    duplicavam a sidebar).
    """
    vistos: set = set()
    out: List[Dict[str, Any]] = []
    for e in listar(120):
        m = e.get("modulo", "")
        if not m or m in vistos:
            continue
        vistos.add(m)
        r = e.get("resumo", {})
        partes = []
        if _int(r.get("pendentes")):
            partes.append(f'{_int(r.get("pendentes"))} pendente(s)')
        if _int(r.get("divergencias")):
            partes.append(f'{_int(r.get("divergencias"))} divergência(s)')
        if _int(r.get("inconsistencias")):
            partes.append(f'{_int(r.get("inconsistencias"))} inconsistência(s)')
        if _int(r.get("remessas_ausentes")):
            partes.append(
                f'{_int(r.get("remessas_ausentes"))} remessa(s) ausente(s)')
        if partes:
            out.append({
                "modulo": m,
                "ts": e.get("ts", ""),
                "descricao": " · ".join(partes),
            })
    return out


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _ler() -> List[Dict[str, Any]]:
    try:
        if HISTORICO_PATH.exists():
            dados = json.loads(HISTORICO_PATH.read_text(encoding="utf-8"))
            if isinstance(dados, list):
                return dados
    except Exception:
        logger.warning("historico.json ilegível — recomeçando.", exc_info=True)
    return []


def _gravar(eventos: List[Dict[str, Any]]) -> None:
    garantir_dirs()
    fd, tmp = tempfile.mkstemp(dir=HISTORICO_PATH.parent, suffix=".tmp.json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(eventos, f, ensure_ascii=False)
        os.replace(tmp, HISTORICO_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
