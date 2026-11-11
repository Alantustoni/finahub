# organizador_dda package
import sys
from pathlib import Path

# Garante que a pasta pai (raiz do projeto) está no sys.path
# Necessário para imports funcionarem em qualquer contexto (threads, scripts, etc.)
_PKG_ROOT = Path(__file__).resolve().parent.parent  # pasta que contém organizador_dda/
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))
