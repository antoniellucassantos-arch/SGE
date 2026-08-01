"""Ponto de entrada para o servidor de desenvolvimento.

Uso::

    python run.py

Para producao **nao** utilize este arquivo: o servidor embutido do Flask e
mono-processo e nao suporta carga real. Use ``wsgi.py`` com Gunicorn ou
Waitress (veja ``docs/implantacao.md``).
"""

from __future__ import annotations

import os

from app import create_app

app = create_app(os.environ.get("APP_ENV", "development"))


if __name__ == "__main__":
    porta = int(os.environ.get("PORTA", 5000))

    # host="0.0.0.0" permite testar de um celular ou tablet na mesma rede
    # local, que e como a escola vai efetivamente usar o sistema.
    app.run(
        host=os.environ.get("HOST", "0.0.0.0"),
        port=porta,
        debug=app.config.get("DEBUG", False),
    )
