"""Rotas de autenticacao.

Controladores finos: validam o formulario, delegam ao ``auth_service`` e
traduzem o resultado em resposta HTTP. Nenhuma regra de seguranca e decidida
aqui — todas vivem no service, onde podem ser testadas isoladamente.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from flask import (
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from app.blueprints.auth import bp
from app.blueprints.auth.formularios import (
    AlterarSenhaForm,
    LoginForm,
    RedefinirSenhaForm,
    SolicitarRecuperacaoForm,
)
from app.extensions import limiter
from app.services import auditoria_service, auth_service
from app.services.excecoes import ErroAutenticacao, ErroValidacao


def _destino_seguro(destino: str | None) -> str:
    """Valida o parametro ``next`` antes de redirecionar.

    Sem esta checagem, ``/auth/login?next=https://site-malicioso`` faria o
    sistema redirecionar o usuario recem-autenticado para fora do dominio
    (*open redirect*), tecnica classica de phishing.
    """
    padrao = url_for("painel.index")
    if not destino:
        return padrao

    referencia = urlparse(request.host_url)
    candidato = urlparse(urljoin(request.host_url, destino))

    mesmo_host = (
        candidato.scheme in ("http", "https")
        and referencia.netloc == candidato.netloc
    )
    if not mesmo_host:
        return padrao

    caminho = candidato.path
    if candidato.query:
        caminho = f"{caminho}?{candidato.query}"

    # Evita devolver o usuario para a propria tela de login.
    if caminho.startswith(url_for("auth.login")):
        return padrao

    return caminho or padrao


def _aplicar_erros(form, erros_por_campo: dict[str, list[str]]) -> None:
    """Transporta erros vindos do service para os campos do formulario."""
    for campo, mensagens in (erros_por_campo or {}).items():
        if hasattr(form, campo):
            getattr(form, campo).errors.extend(mensagens)


# ---------------------------------------------------------------------------
# Login e logout
# ---------------------------------------------------------------------------
@bp.route("/login", methods=["GET", "POST"])
@limiter.limit(
    lambda: current_app.config.get("RATELIMIT_LOGIN", "10 per minute"),
    methods=["POST"],
    error_message="Muitas tentativas de login. Aguarde um minuto.",
)
def login():
    """Autentica o usuario e inicia a sessao."""
    if current_user.is_authenticated:
        return redirect(url_for("painel.index"))

    form = LoginForm()

    if form.validate_on_submit():
        try:
            usuario = auth_service.autenticar(
                email=form.email.data,
                senha=form.senha.data,
                endereco_ip=request.remote_addr,
            )
        except ErroAutenticacao as erro:
            flash(erro.mensagem, "danger")
            return render_template("auth/login.html", form=form), 401

        login_user(usuario, remember=bool(form.lembrar.data))

        if usuario.deve_trocar_senha:
            flash(
                "Bem-vindo! Por seguranca, defina uma nova senha para continuar.",
                "info",
            )
            return redirect(url_for("auth.alterar_senha"))

        flash(f"Bem-vindo(a), {usuario.primeiro_nome}!", "success")
        return redirect(_destino_seguro(request.args.get("next")))

    return render_template("auth/login.html", form=form)


@bp.route("/logout")
@login_required
def logout():
    """Encerra a sessao do usuario."""
    auditoria_service.registrar_logout(current_user)
    try:
        from app.extensions import db

        db.session.commit()
    except Exception:  # noqa: BLE001 - logout nunca pode falhar por auditoria
        from app.extensions import db

        db.session.rollback()

    logout_user()
    flash("Sessao encerrada com sucesso.", "info")
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# Recuperacao de senha
# ---------------------------------------------------------------------------
@bp.route("/recuperar-senha", methods=["GET", "POST"])
@limiter.limit(
    lambda: current_app.config.get("RATELIMIT_RECUPERACAO", "5 per hour"),
    methods=["POST"],
    error_message="Muitas solicitacoes. Tente novamente mais tarde.",
)
def recuperar_senha():
    """Solicita o link de redefinicao de senha."""
    if current_user.is_authenticated:
        return redirect(url_for("painel.index"))

    form = SolicitarRecuperacaoForm()

    if form.validate_on_submit():
        usuario, token = auth_service.solicitar_recuperacao(form.email.data)

        # Resposta identica exista ou nao o e-mail: nao revelamos quais
        # contas estao cadastradas na escola.
        mensagem = (
            "Se este e-mail estiver cadastrado, enviaremos as instrucoes "
            "de redefinicao de senha em instantes."
        )

        if usuario and token:
            link = url_for("auth.redefinir_senha", token=token, _external=True)
            # O envio por e-mail sera plugado ao configurar o SMTP da escola.
            # Ate la, o link vai para o log da aplicacao, permitindo que a
            # secretaria conclua o atendimento sem expor o token na tela.
            current_app.logger.info(
                "Link de recuperacao gerado para %s: %s", usuario.email, link
            )
            if current_app.debug:
                flash(f"[MODO DESENVOLVIMENTO] Link: {link}", "warning")

        flash(mensagem, "info")
        return redirect(url_for("auth.login"))

    return render_template("auth/recuperar_senha.html", form=form)


@bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def redefinir_senha(token: str):
    """Define a nova senha a partir de um token valido."""
    if current_user.is_authenticated:
        return redirect(url_for("painel.index"))

    usuario = auth_service.validar_token_recuperacao(token)
    if usuario is None:
        flash(
            "Link de recuperacao invalido ou expirado. Solicite um novo.",
            "danger",
        )
        return redirect(url_for("auth.recuperar_senha"))

    form = RedefinirSenhaForm()

    if form.validate_on_submit():
        try:
            auth_service.redefinir_senha_por_token(token, form.nova_senha.data)
        except ErroValidacao as erro:
            _aplicar_erros(form, erro.erros_por_campo)
            flash(erro.mensagem, "danger")
            return render_template(
                "auth/redefinir_senha.html", form=form, token=token
            )
        except ErroAutenticacao as erro:
            flash(erro.mensagem, "danger")
            return redirect(url_for("auth.recuperar_senha"))

        flash("Senha redefinida com sucesso. Faca login para continuar.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/redefinir_senha.html", form=form, token=token)


# ---------------------------------------------------------------------------
# Alteracao de senha (usuario autenticado)
# ---------------------------------------------------------------------------
@bp.route("/alterar-senha", methods=["GET", "POST"])
@login_required
def alterar_senha():
    """Permite ao usuario trocar a propria senha."""
    form = AlterarSenhaForm()
    troca_obrigatoria = current_user.deve_trocar_senha

    if form.validate_on_submit():
        try:
            auth_service.alterar_senha(
                usuario=current_user,
                senha_atual=form.senha_atual.data,
                nova_senha=form.nova_senha.data,
            )
        except ErroValidacao as erro:
            _aplicar_erros(form, erro.erros_por_campo)
            flash(erro.mensagem, "danger")
            return render_template(
                "auth/alterar_senha.html",
                form=form,
                troca_obrigatoria=troca_obrigatoria,
            )

        flash("Senha alterada com sucesso.", "success")
        return redirect(url_for("painel.index"))

    return render_template(
        "auth/alterar_senha.html",
        form=form,
        troca_obrigatoria=troca_obrigatoria,
    )
