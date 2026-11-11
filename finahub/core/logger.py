"""
logger.py — Logging da suíte em ~/.finahub/logs/ (rotação diária simples).
"""
from __future__ import annotations

import logging
from datetime import date

from .paths import LOG_DIR, garantir_dirs


def configurar_logging(nivel: int = logging.INFO) -> None:
    garantir_dirs()
    arquivo = LOG_DIR / f"finahub_{date.today().isoformat()}.log"
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(arquivo, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
