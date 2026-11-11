"""
Sistema de logs para auditoria e debug.
Grava em arquivo na pasta do usuário e expõe via API simples.
"""

import logging
import sys
from pathlib import Path
from datetime import datetime


LOG_DIR  = Path.home() / ".remessa_banco" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / f"remessa_banco_{datetime.now().strftime('%Y-%m')}.log"


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("remessa_banco")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_h = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_h.setFormatter(fmt)
    file_h.setLevel(logging.INFO)
    logger.addHandler(file_h)

    # Console handler só se rodando com console (desenvolvimento)
    if sys.stderr and sys.stderr.isatty():
        stream_h = logging.StreamHandler()
        stream_h.setFormatter(fmt)
        stream_h.setLevel(logging.DEBUG)
        logger.addHandler(stream_h)

    return logger


log = _build_logger()


def log_exception(prefix: str, exc: Exception) -> None:
    """Loga uma exceção com traceback completo."""
    import traceback
    log.error(f"{prefix}: {exc}\n{traceback.format_exc()}")


def log_path() -> Path:
    """Retorna o caminho do arquivo de log atual."""
    return LOG_FILE
