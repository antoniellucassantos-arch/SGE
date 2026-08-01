"""Blueprint de configuracoes do sistema."""

from flask import Blueprint

bp = Blueprint("configuracoes", __name__)

from app.blueprints.configuracoes import rotas  # noqa: E402,F401
