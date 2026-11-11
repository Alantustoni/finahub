"""
Pacotes de terceiros internos (código testado dos projetos originais).

  organizador_dda/  → core do DDA V7 (processamento, cruzamento, relatório)
  remessa_v3/       → core do SAPIENS X BANCO V3 (parsers, conciliação, export)

O remessa_v3 usa imports absolutos ('core', 'services'); bootstrap()
adiciona a pasta dele ao sys.path uma única vez.
"""
import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parent


def bootstrap() -> None:
    """Garante que os pacotes vendorizados são importáveis."""
    for p in (_VENDOR, _VENDOR / "remessa_v3"):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
