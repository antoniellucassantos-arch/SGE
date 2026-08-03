"""Application Factory do SGE.

Toda a aplicacao e construida por :func:`create_app`, que recebe o nome do
ambiente e devolve uma instancia Flask pronta. Nenhum objeto ``Flask`` e
criado no momento do import, o que permite:

* subir a aplicacao com configuracoes diferentes (dev, teste, producao);
* criar uma instancia isolada por teste, sem vazamento de estado;
* evitar imports circulares entre models, services e blueprints.

Ordem de inicializacao (importa: cada etapa depende da anterior)::

    configuracao -> logging -> extensoes -> models -> blueprints
    -> handlers de erro -> hooks de requisicao -> jinja -> CLI

Este arquivo so orquestra. Cada etapa mora no proprio modulo e expoe uma
funcao ``configurar_X(app)``:

===========================  ===========================================
``app/logging_config.py``    log em arquivo rotativo e console
``app/errors.py``            handlers de erro e ``prefere_json()``
``app/hooks.py``             before/after request e cabecalhos de seguranca
``app/jinja_setup.py``       filtros, globais e contexto dos templates
``app/blueprints/``          tupla ``BLUEPRINTS`` e o registro
``app/commands/``            comandos ``flask ...``
===========================  ===========================================
"""

from __future__ import annotations

import os

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app.blueprints import registrar_blueprints
from app.errors import configurar_handlers_erro
from app.extensions import csrf, db, limiter, login_manager, migrate
from app.hooks import configurar_hooks
from app.jinja_setup import configurar_jinja
from app.logging_config import configurar_logging
from app.versao import __version__
from config import BaseConfig, obter_configuracao


def create_app(nome_configuracao: str | None = None) -> Flask:
    """Cria e configura uma instancia da aplicacao SGE."""
    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder="static",
        template_folder="templates",
    )

    # 1. Configuracao ------------------------------------------------------
    classe_config = obter_configuracao(nome_configuracao)
    app.config.from_object(classe_config)
    # Permite sobrescrever qualquer chave via instance/config.py sem tocar
    # no repositorio (util para credenciais especificas do servidor).
    app.config.from_pyfile("config.py", silent=True)
    classe_config.iniciar_app(app)

    _garantir_diretorio_instance(app)

    # 2. Logging -----------------------------------------------------------
    configurar_logging(app)

    # 3. Proxy reverso -----------------------------------------------------
    # Em producao o Flask fica atras do Nginx; sem isso, todo request pareceria
    # vir de 127.0.0.1 e a auditoria de IP e o rate limiting seriam inuteis.
    if not app.debug and not app.testing:
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
        )

    # 4. Extensoes ---------------------------------------------------------
    _registrar_extensoes(app)

    # 5. Models ------------------------------------------------------------
    # O import popula o metadata do SQLAlchemy; sem ele o Alembic nao enxerga
    # as tabelas e o create_all() dos testes nao cria nada.
    from app import models  # noqa: F401

    # 6. Blueprints --------------------------------------------------------
    registrar_blueprints(app)

    # 7. Tratamento de erros ----------------------------------------------
    configurar_handlers_erro(app)

    # 8. Hooks de requisicao ----------------------------------------------
    configurar_hooks(app)

    # 9. Jinja: filtros, globais e contexto -------------------------------
    configurar_jinja(app)

    # 10. Comandos de linha de comando ------------------------------------
    from app.commands import registrar_comandos

    registrar_comandos(app)

    app.logger.info(
        "SGE %s iniciado no ambiente '%s'",
        __version__,
        app.config.get("AMBIENTE", "desconhecido"),
    )
    return app


def _garantir_diretorio_instance(app: Flask) -> None:
    """Cria ``instance/`` antes do SQLite tentar gravar o arquivo la."""
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError as erro:  # pragma: no cover - permissao do sistema
        app.logger.warning("Nao foi possivel criar instance/: %s", erro)


def _registrar_extensoes(app: Flask) -> None:
    """Vincula as extensoes a esta instancia da aplicacao."""
    db.init_app(app)
    migrate.init_app(app, db, directory="migrations", render_as_batch=True)
    login_manager.init_app(app)
    csrf.init_app(app)

    # O rate limiting so e util com armazenamento compartilhado entre
    # processos; em desenvolvimento e teste ele apenas atrapalha.
    if app.config.get("RATELIMIT_ENABLED", True):
        limiter.init_app(app)

    # Cookie de sessao seguro tambem para o token CSRF.
    app.config.setdefault(
        "REMEMBER_COOKIE_SECURE", app.config.get("SESSION_COOKIE_SECURE", False)
    )


__all__ = ["BaseConfig", "__version__", "create_app"]
