"""Blueprint do diario de classe e da frequencia."""

from flask import Blueprint

bp = Blueprint("frequencia", __name__)

from app.blueprints.frequencia import rotas  # noqa: E402,F401
