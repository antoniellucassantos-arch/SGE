"""Blueprint de backup do banco de dados."""

from flask import Blueprint

bp = Blueprint("backup", __name__)

from app.blueprints.backup import rotas  # noqa: E402,F401
