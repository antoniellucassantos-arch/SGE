"""Blueprint do painel principal (dashboard)."""

from flask import Blueprint

bp = Blueprint("painel", __name__)

from app.blueprints.painel import rotas  # noqa: E402,F401
