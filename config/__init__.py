"""Pacote de configuracao do SGE.

Expõe o mapa de configuracoes por ambiente e a funcao utilitaria
:func:`obter_configuracao`, usada pela Application Factory.
"""

from config.settings import (
    CONFIGURACOES,
    BaseConfig,
    DevelopmentConfig,
    ProductionConfig,
    TestingConfig,
    obter_configuracao,
)

__all__ = [
    "BaseConfig",
    "DevelopmentConfig",
    "ProductionConfig",
    "TestingConfig",
    "CONFIGURACOES",
    "obter_configuracao",
]
