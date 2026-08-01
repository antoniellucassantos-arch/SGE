"""Blueprint de avaliacoes e lancamento de notas."""

from flask import Blueprint

bp = Blueprint("notas", __name__)

from app.blueprints.notas import rotas  # noqa: E402,F401
