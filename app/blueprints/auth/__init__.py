"""Blueprint de autenticacao: login, logout e gestao de senha."""

from flask import Blueprint

bp = Blueprint("auth", __name__, template_folder="../../templates/auth")

from app.blueprints.auth import rotas  # noqa: E402,F401  (registra as rotas)
