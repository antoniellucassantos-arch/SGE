"""Blueprint de consulta a trilha de auditoria."""

from flask import Blueprint

bp = Blueprint("auditoria", __name__)

from app.blueprints.auditoria import rotas  # noqa: E402,F401
