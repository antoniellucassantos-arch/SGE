"""Blueprint do cadastro de responsaveis."""

from flask import Blueprint

bp = Blueprint("responsaveis", __name__)

from app.blueprints.responsaveis import rotas  # noqa: E402,F401
