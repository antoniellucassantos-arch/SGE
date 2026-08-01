"""Blueprint de gestao de contas de acesso."""

from flask import Blueprint

bp = Blueprint("usuarios", __name__)

from app.blueprints.usuarios import rotas  # noqa: E402,F401
