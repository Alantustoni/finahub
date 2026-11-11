# core package
from .config import Config
from .processor import DataProcessor, ProcessingResult
from .metrics import calcular_metricas
from .utils import normalizar_texto, formatar_cnpj, tratar_nota, tratar_valor

__all__ = [
    "Config",
    "DataProcessor",
    "ProcessingResult",
    "calcular_metricas",
    "normalizar_texto",
    "formatar_cnpj",
    "tratar_nota",
    "tratar_valor",
]
