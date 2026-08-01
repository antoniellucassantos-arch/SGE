"""Blueprint da API JSON (versao 1).

Base para o futuro aplicativo Android: as rotas aqui reutilizam exatamente
os mesmos services da interface web, sem duplicar regra de negocio.

Autenticacao: por enquanto, sessao (o mesmo cookie da interface web), o que
ja atende as chamadas AJAX do proprio sistema. Ao construir o aplicativo,
acrescenta-se JWT nesta mesma camada — os services nao precisam mudar.
"""

from flask import Blueprint

bp = Blueprint("api", __name__)

from app.blueprints.api import rotas  # noqa: E402,F401
