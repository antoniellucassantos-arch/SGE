"""Configuracao de log da aplicacao.

Em producao, um erro sem rastro e um erro que ninguem conserta. O arquivo
rotativo garante historico sem encher o disco, e o console so entra em
desenvolvimento — em producao quem coleta a saida padrao e o systemd.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from flask import Flask


def configurar_logging(app: Flask) -> None:
    """Configura log em arquivo rotativo + console."""
    if app.testing:
        return

    nivel = getattr(
        logging, app.config.get("LOG_NIVEL", "INFO").upper(), logging.INFO
    )

    # O Flask instala um handler proprio em app.logger no primeiro acesso.
    # Sem remove-lo, cada mensagem apareceria duas vezes no console.
    app.logger.handlers.clear()
    app.logger.propagate = False
    formato = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s "
        "[em %(pathname)s:%(lineno)d]",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    pasta_logs = app.config["PASTA_LOGS"]
    try:
        pasta_logs.mkdir(parents=True, exist_ok=True)
        arquivo = RotatingFileHandler(
            pasta_logs / app.config["LOG_ARQUIVO"],
            maxBytes=app.config["LOG_MAX_BYTES"],
            backupCount=app.config["LOG_BACKUP_COUNT"],
            encoding="utf-8",
        )
        arquivo.setFormatter(formato)
        arquivo.setLevel(nivel)
        app.logger.addHandler(arquivo)
    except OSError as erro:  # pragma: no cover - disco cheio/permissao
        app.logger.warning("Log em arquivo indisponivel: %s", erro)

    if app.debug:
        console = logging.StreamHandler()
        console.setFormatter(formato)
        console.setLevel(nivel)
        app.logger.addHandler(console)

    app.logger.setLevel(nivel)


__all__ = ["configurar_logging"]
