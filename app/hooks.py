"""Hooks executados a cada requisicao.

Tres responsabilidades, todas transversais demais para viver em um blueprint:
preparar o contexto da requisicao, aplicar os cabecalhos de seguranca na
resposta e devolver a conexao do banco ao pool no fim.
"""

from __future__ import annotations

from flask import Flask, flash, g, redirect, request, session, url_for
from flask_login import current_user

from app.errors import prefere_json
from app.extensions import db

#: Rotas acessiveis mesmo com troca de senha pendente.
#:
#: A comparacao e por ``request.endpoint``, e nao por caminho: o endpoint ja
#: foi resolvido pelo roteador, entao nao ha como um prefixo parecido
#: (``/staticos/…``) passar por engano.
ROTAS_LIVRES: frozenset[str] = frozenset(
    {
        "auth.login",
        "auth.logout",
        "auth.alterar_senha",
        "auth.recuperar_senha",
        "auth.redefinir_senha",
        "static",
    }
)

#: Cabecalhos de defesa aplicados a todas as respostas.
#:
#: Escritos a mao em vez de via Flask-Talisman para manter a lista explicita
#: e auditavel, e uma dependencia a menos.
#:
#: Sobre a CSP: todo CSS/JS e servido localmente, entao nao ha necessidade de
#: liberar CDN nenhuma. O ``'unsafe-inline'`` em ``style-src`` e concessao
#: pontual ao Bootstrap e aos estilos inline dos graficos — **nao** existe em
#: ``script-src``, e nao deve passar a existir: os dados dos graficos vao por
#: atributos ``data-*``, lidos por um arquivo servido.
CABECALHOS_SEGURANCA: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


def configurar_hooks(app: Flask) -> None:
    """Registra os hooks de requisicao na aplicacao."""

    @app.before_request
    def preparar_requisicao():
        # Sessao permanente com expiracao deslizante por inatividade.
        session.permanent = True

        if not current_user.is_authenticated:
            return None

        # Troca de senha obrigatoria (primeiro acesso ou reset administrativo).
        if current_user.deve_trocar_senha and request.endpoint not in ROTAS_LIVRES:
            if prefere_json():
                # Um cliente JSON — o JavaScript da tela, amanha o aplicativo
                # Android — nao tem o que fazer com um 302 para uma pagina
                # HTML: ele so enxerga uma resposta de sucesso com conteudo
                # incompreensivel. O status precisa dizer o que houve.
                return (
                    {
                        "sucesso": False,
                        "erro": "Defina uma nova senha antes de usar o sistema.",
                    },
                    403,
                )

            flash(
                "Por seguranca, defina uma nova senha antes de continuar.",
                "warning",
            )
            return redirect(url_for("auth.alterar_senha"))

        # Ano letivo corrente disponivel em toda a requisicao (evita repetir
        # a mesma consulta em dezenas de rotas e templates).
        g.ano_letivo = carregar_ano_letivo_corrente()
        return None

    @app.after_request
    def aplicar_cabecalhos_seguranca(resposta):
        for cabecalho, valor in CABECALHOS_SEGURANCA.items():
            resposta.headers.setdefault(cabecalho, valor)

        if app.config.get("SESSION_COOKIE_SECURE"):
            resposta.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )

        return resposta

    @app.teardown_appcontext
    def encerrar_sessao(excecao=None):
        """Devolve a conexao ao pool ao final de cada contexto."""
        if excecao:
            db.session.rollback()
        db.session.remove()


def carregar_ano_letivo_corrente():
    """Busca o ano letivo marcado como corrente.

    Tolerante a falhas de proposito: antes da primeira migration a tabela
    ainda nao existe, e a aplicacao precisa subir mesmo assim.
    """
    try:
        from app.models.estrutura import AnoLetivo

        return (
            db.session.query(AnoLetivo)
            .filter(AnoLetivo.corrente.is_(True))
            .first()
        )
    except Exception:  # noqa: BLE001 - banco ainda nao migrado
        # O `rollback` nao e cosmetico. O `except` acima foi escrito para o
        # caso "tabela ainda nao existe", mas ele tambem pega timeout,
        # deadlock e coluna removida. No PostgreSQL, uma consulta que falha
        # deixa a transacao abortada: sem desfaze-la aqui, *toda* consulta
        # seguinte da requisicao morre com InFailedSqlTransaction — e a
        # causa aparente fica sendo a proxima query, nao esta.
        db.session.rollback()
        return None


__all__ = [
    "CABECALHOS_SEGURANCA",
    "ROTAS_LIVRES",
    "carregar_ano_letivo_corrente",
    "configurar_hooks",
]
