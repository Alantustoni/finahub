"""
Sessão persistente — guarda preferências e últimos arquivos abertos.
"""

import json
from pathlib import Path
from typing import Any

from .logger import log


SESSION_DIR = Path.home() / ".remessa_banco"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

SESSION_FILE = SESSION_DIR / "session.json"


class Session:
    """Wrapper simples para persistência key-value."""

    def __init__(self):
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict:
        try:
            if SESSION_FILE.exists():
                return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"Falha ao carregar sessão: {e}")
        return {}

    def _save(self) -> None:
        try:
            SESSION_FILE.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning(f"Falha ao salvar sessão: {e}")

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self._save()

    def update(self, **kwargs) -> None:
        self._data.update(kwargs)
        self._save()

    @property
    def last_dir(self) -> str:
        return self._data.get("last_dir", str(Path.home()))

    @last_dir.setter
    def last_dir(self, value: str):
        self.set("last_dir", value)
