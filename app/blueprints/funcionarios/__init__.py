"""Blueprint do cadastro de funcionarios."""

from flask import Blueprint

bp = Blueprint("funcionarios", __name__)

from app.blueprints.funcionarios import rotas  # noqa: E402,F401
