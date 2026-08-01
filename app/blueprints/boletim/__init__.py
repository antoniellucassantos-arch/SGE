"""Blueprint de boletins."""

from flask import Blueprint

bp = Blueprint("boletim", __name__)

from app.blueprints.boletim import rotas  # noqa: E402,F401
