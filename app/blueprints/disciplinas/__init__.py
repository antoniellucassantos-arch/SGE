"""Blueprint do cadastro de disciplinas."""

from flask import Blueprint

bp = Blueprint("disciplinas", __name__)

from app.blueprints.disciplinas import rotas  # noqa: E402,F401
