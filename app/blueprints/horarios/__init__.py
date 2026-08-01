"""Blueprint da grade de horarios."""

from flask import Blueprint

bp = Blueprint("horarios", __name__)

from app.blueprints.horarios import rotas  # noqa: E402,F401
