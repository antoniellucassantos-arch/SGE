"""Blueprint de turmas e da grade de disciplinas."""

from flask import Blueprint

bp = Blueprint("turmas", __name__)

from app.blueprints.turmas import rotas  # noqa: E402,F401
