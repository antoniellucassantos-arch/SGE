"""Blueprint do cadastro de alunos."""

from flask import Blueprint

bp = Blueprint("alunos", __name__)

from app.blueprints.alunos import rotas  # noqa: E402,F401
