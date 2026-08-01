"""Blueprint de matriculas."""

from flask import Blueprint

bp = Blueprint("matriculas", __name__)

from app.blueprints.matriculas import rotas  # noqa: E402,F401
