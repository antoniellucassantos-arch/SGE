"""Versao da aplicacao.

Modulo proprio, com uma linha, por um motivo pratico: ``app/__init__.py``
importa os configuradores (``app.errors``, ``app.hooks``, ``app.jinja_setup``)
e alguns deles precisam da versao. Se ela morasse no ``__init__``, cada um
teria de importa-lo de volta — import circular resolvido na base do
``import`` dentro da funcao, que e o tipo de gambiarra que funciona ate o dia
em que a ordem muda.
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
