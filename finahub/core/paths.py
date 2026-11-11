"""
paths.py — Resolução de caminhos da suíte.

Regra: dados do usuário (config, histórico, logs) NUNCA moram dentro do
.EXE/pasta do programa — vão para ~/.finahub. Assim o PyInstaller
onefile funciona e nada se perde em atualização de versão.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

APP_DIR = Path.home() / ".finahub"
# Pasta usada antes da troca de nome (Contas a Pagar Suite → FinaHub).
LEGACY_APP_DIR = Path.home() / ".contas_a_pagar_suite"
LOG_DIR = APP_DIR / "logs"

CONFIG_PATH    = APP_DIR / "config.json"
HISTORICO_PATH = APP_DIR / "historico.json"
SESSION_PATH   = APP_DIR / "session.json"


def resource_dir() -> Path:
    """Pasta dos recursos empacotados (suporta PyInstaller onefile)."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # raiz do projeto (pasta que contém main.py / config.json de fábrica)
    return Path(__file__).resolve().parent.parent.parent


def migrar_pasta_antiga(novo: Path | None = None, antigo: Path | None = None) -> bool:
    """Copia config/histórico da pasta antiga para a nova, uma única vez.

    Só age se a pasta nova ainda não existe e a antiga existe. A antiga é
    mantida intacta (backup). Retorna True se migrou.
    """
    novo = novo or APP_DIR
    antigo = antigo or LEGACY_APP_DIR
    if novo.exists() or not antigo.is_dir():
        return False
    shutil.copytree(antigo, novo)
    return True


def garantir_dirs() -> None:
    migrar_pasta_antiga()
    APP_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # Primeira execução: copia o config.json de fábrica para ~/.finahub
    if not CONFIG_PATH.exists():
        fabrica = resource_dir() / "config.json"
        if fabrica.exists():
            shutil.copy(fabrica, CONFIG_PATH)
