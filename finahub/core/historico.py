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


# ── formatação para a tabela "Últimas execuções" ─────────────────────
# chave do resumo → (singular, plural). A ordem do resumo é mantida.
_ROTULOS = {
    "emails": ("e-mail", "e-mails"),
    "notas": ("nota", "notas"),
    "incluidas": ("incluída", "incluídas"),
    "ja_existiam": ("já existia", "já existiam"),
    "linhas": ("linha", "linhas"),
    "programados": ("programado", "programados"),
    "conciliados": ("conciliado", "conciliados"),
    "boletos_validos": ("boleto", "boletos"),
    "registros": ("registro", "registros"),
    "arquivos": ("arquivo", "arquivos"),
    "lotes": ("lote", "lotes"),
    "titulos_sem_usinas": ("título", "títulos"),
    "titulos_usinas": ("título de usina", "títulos de usina"),
    "divisoes": ("divisão", "divisões"),
}
# chaves que indicam algo a resolver → coluna Status
_ALERTAS = {
    "faltando": ("faltando", "faltando"),
    "pendentes": ("pendente", "pendentes"),
    "divergencias": ("divergência", "divergências"),
    "inconsistencias": ("inconsistência", "inconsistências"),
    "remessas_ausentes": ("remessa ausente", "remessas ausentes"),
}


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _qtd(n: int, rotulos: tuple) -> str:
    return f"{_milhar(n)} {rotulos[0] if n == 1 else rotulos[1]}"


def formatar_execucao(e: Dict[str, Any], max_itens: int = 3) -> Dict[str, str]:
    """Converte um evento do histórico nas colunas legíveis do dashboard.

    Retorna quando ("05/11 · 10:46"), modulo, resultado ("153 e-mails ·
    1.512 notas"), status ("✓ OK" / "⚠ 7 faltando"), arquivo (só o nome)
    e atencao (True quando o status tem alerta).
    """
    ts = str(e.get("ts", ""))
    try:
        d = datetime.fromisoformat(ts)
        quando = f"{d:%d/%m} · {d:%H:%M}"
    except ValueError:
        quando = ts or "—"

    r = e.get("resumo") or {}
    partes = []
    for chave, valor in r.items():
        if chave == "total" and isinstance(valor, (int, float)) and valor:
            from .utils import formatar_moeda
            partes.append(formatar_moeda(valor))
        elif chave in _ROTULOS and _int(valor):
            partes.append(_qtd(_int(valor), _ROTULOS[chave]))
        if len(partes) >= max_itens:
            break
    resultado = " · ".join(partes) or str(e.get("acao") or "—")

    alertas = [_qtd(_int(r.get(k)), rot) for k, rot in _ALERTAS.items()
               if _int(r.get(k))]
    status = ("⚠ " + " · ".join(alertas)) if alertas else "✓ OK"

    saida = str(e.get("saida") or "")
    arquivo = saida.replace("\\", "/").rsplit("/", 1)[-1] if saida else "—"

    modulo = e.get("modulo", "")
    return {
        "quando": quando,
        "modulo": MODULOS.get(modulo, modulo),
        "resultado": resultado,
        "status": status,
        "arquivo": arquivo,
        "atencao": bool(alertas),
    }


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
