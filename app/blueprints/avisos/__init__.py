"""Blueprint de avisos e comunicados."""

from flask import Blueprint

bp = Blueprint("avisos", __name__)

from app.blueprints.avisos import rotas  # noqa: E402,F401
