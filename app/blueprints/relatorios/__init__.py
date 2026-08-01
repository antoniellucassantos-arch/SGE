"""Blueprint de relatorios e exportacoes."""

from flask import Blueprint

bp = Blueprint("relatorios", __name__)

from app.blueprints.relatorios import rotas  # noqa: E402,F401
