"""
FinaHub — entry point.

Startup rápido: só tkinter/customtkinter carregam aqui; pandas e openpyxl
são importados dentro das threads de trabalho de cada módulo.
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

# garante import do pacote rodando de qualquer diretório
sys.path.insert(0, str(Path(__file__).resolve().parent))

from finahub.core.logger import configurar_logging
from finahub.core.paths import garantir_dirs


def main() -> None:
    garantir_dirs()
    configurar_logging()
    logger = logging.getLogger("finahub")
    logger.info("Iniciando ALAN — Contas a Pagar…")

    try:
        from finahub.ui.app import FinaHubApp
        app = FinaHubApp()
        app.mainloop()
    except Exception:
        logger.critical("Erro fatal na inicialização:\n%s", traceback.format_exc())
        # último recurso: mostra o erro numa janela nativa
        try:
            import tkinter.messagebox as mb
            mb.showerror(
                "FinaHub — erro fatal",
                "O programa encontrou um erro ao iniciar.\n\n"
                + traceback.format_exc(limit=5)
                + "\n\nO log completo está em ~/.finahub/logs/")
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
