"""Ponto de entrada WSGI para servidores de producao.

Exemplos::

    # Linux (recomendado)
    gunicorn --workers 4 --bind 0.0.0.0:8000 wsgi:app

    # Windows
    waitress-serve --port=8000 wsgi:app

O ambiente e resolvido pela variavel ``APP_ENV`` (padrao: ``production``).
"""

from __future__ import annotations

import os

from app import create_app

app = create_app(os.environ.get("APP_ENV", "production"))
