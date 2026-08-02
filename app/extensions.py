"""Instancias unicas das extensoes Flask usadas pelo SGE.

As extensoes sao criadas aqui **sem** vinculo com nenhuma aplicacao. O
vinculo acontece em :func:`app.create_app` atraves de ``init_app()``.

Motivo: isso evita import circular entre a Application Factory, os models e
os blueprints, e permite instanciar varias aplicacoes (ex.: uma por teste)
sem estado compartilhado indevido.
"""

from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import MetaData

# ---------------------------------------------------------------------------
# Convencao de nomes para constraints
# ---------------------------------------------------------------------------
# Sem isso, o SQLite gera constraints anonimas e o Alembic nao consegue
# aplicar ALTER/DROP em migrations futuras (o famoso erro
# "Constraint must have a name"). Definir a convencao desde o inicio evita
# uma dor de cabeca enorme na primeira alteracao de schema em producao.
CONVENCAO_NOMES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=CONVENCAO_NOMES)

# ---------------------------------------------------------------------------
# Extensoes
# ---------------------------------------------------------------------------
db = SQLAlchemy(metadata=metadata)
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
    strategy="fixed-window",
)

# ---------------------------------------------------------------------------
# Configuracao do Flask-Login
# ---------------------------------------------------------------------------
login_manager.login_view = "auth.login"
login_manager.login_message = "Faca login para acessar esta pagina."
login_manager.login_message_category = "warning"
login_manager.session_protection = "strong"
login_manager.refresh_view = "auth.login"
login_manager.needs_refresh_message = (
    "Sua sessao expirou por inatividade. Faca login novamente."
)
login_manager.needs_refresh_message_category = "warning"


@login_manager.user_loader
def carregar_usuario(usuario_id: str):
    """Recupera o usuario da sessao a cada requisicao autenticada.

    Contas inativas ou excluidas sao recusadas **aqui**, e nao apenas no
    login. Motivo: o Flask-Login consulta ``is_active`` somente em
    ``login_user()``. Sem esta checagem, quem ja estava autenticado quando a
    conta foi desativada continuaria navegando ate a sessao expirar — o que
    torna inutil desligar o acesso de um funcionario demitido.

    Recusar no ``user_loader`` faz o corte valer para **toda** rota, inclusive
    as protegidas apenas por ``login_required``.

    Import local proposital: ``app.models`` depende de ``db``, definido neste
    modulo. Importar no topo criaria um ciclo.
    """
    from app.models.usuario import Usuario

    try:
        chave = int(usuario_id)
    except (TypeError, ValueError):
        return None

    usuario = db.session.get(Usuario, chave)

    if usuario is None or not usuario.ativo or usuario.excluido_em is not None:
        return None

    return usuario


@login_manager.unauthorized_handler
def nao_autorizado():
    """Redireciona visitantes anonimos para o login preservando o destino."""
    from flask import flash, redirect, request, url_for

    flash("Faca login para acessar esta pagina.", "warning")
    return redirect(url_for("auth.login", next=request.full_path))
