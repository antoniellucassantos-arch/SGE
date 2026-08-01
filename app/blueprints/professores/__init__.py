"""Blueprint do cadastro de professores."""

from flask import Blueprint

bp = Blueprint("professores", __name__)

from app.blueprints.professores import rotas  # noqa: E402,F401
