"""Rotas de gestao de contas de acesso e do perfil do usuario."""

from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.usuarios import bp
from app.blueprints.usuarios.formularios import (
    FiltroUsuarioForm,
    PerfilForm,
    UsuarioForm,
)
from app.models.usuario import Usuario
from app.services import auditoria_service, usuario_service
from app.services.excecoes import ErroArquivo, ErroDominio, ErroPermissao
from app.utils.arquivos import responder_arquivo, substituir_imagem
from app.utils.decoradores import requer_permissao
from app.utils.paginacao import (
    aplicar_ordenacao,
    filtro_texto,
    paginar,
    parametros_preservados,
)
from app.utils.permissoes import (
    Permissao,
    permissoes_do_papel,
    usuario_tem_permissao,
)

PASTA_FOTOS = "usuarios"

COLUNAS_ORDENAVEIS = {
    "nome": Usuario.nome_normalizado,
    "email": Usuario.email,
    "papel": Usuario.papel,
    "ultimo_login": Usuario.ultimo_login_em,
    "criacao": Usuario.criado_em,
}


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@requer_permissao(Permissao.USUARIO_VISUALIZAR)
def listar():
    """Lista as contas de acesso do sistema."""
    form = FiltroUsuarioForm(request.args, meta={"csrf": False})

    consulta = usuario_service.listar(
        termo=filtro_texto(form.busca.data),
        papel=form.papel.data or None,
        situacao=form.situacao.data or None,
    )
    consulta, coluna, direcao = aplicar_ordenacao(
        consulta, COLUNAS_ORDENAVEIS, coluna_padrao="nome"
    )

    return render_template(
        "usuarios/listar.html",
        form=form,
        pagina=paginar(consulta),
        ordenacao={"coluna": coluna, "direcao": direcao},
        parametros=parametros_preservados("ordenar", "direcao"),
        estatisticas=usuario_service.estatisticas(),
    )


# ---------------------------------------------------------------------------
# Detalhe
# ---------------------------------------------------------------------------
@bp.route("/<int:usuario_id>")
@login_required
@requer_permissao(Permissao.USUARIO_VISUALIZAR)
def detalhe(usuario_id: int):
    """Detalhe de uma conta com as permissoes efetivas do perfil."""
    usuario = usuario_service.buscar(usuario_id)

    return render_template(
        "usuarios/detalhe.html",
        usuario=usuario,
        permissoes=sorted(permissoes_do_papel(usuario.papel)),
        historico=auditoria_service.historico_da_entidade("Usuario", usuario.id, 20),
    )


# ---------------------------------------------------------------------------
# Criacao e edicao
# ---------------------------------------------------------------------------
@bp.route("/novo", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.USUARIO_CRIAR)
def novo():
    """Cria uma conta de acesso com senha temporaria."""
    form = UsuarioForm()

    if form.validate_on_submit():
        try:
            usuario, senha = usuario_service.criar(form.dados_limpos())
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            # A senha aparece uma unica vez. Guardar em texto puro seria uma
            # falha grave; exibir aqui e o que permite a secretaria entregar
            # a credencial ao usuario.
            flash(
                f"Conta criada para {usuario.email}. Senha temporaria: {senha} — "
                "anote agora, ela nao sera exibida novamente.",
                "warning",
            )
            return redirect(url_for("usuarios.detalhe", usuario_id=usuario.id))

    return render_template("usuarios/formulario.html", form=form, usuario=None)


@bp.route("/<int:usuario_id>/editar", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.USUARIO_EDITAR)
def editar(usuario_id: int):
    """Edita uma conta de acesso."""
    usuario = usuario_service.buscar(usuario_id)
    form = UsuarioForm(obj=usuario)

    if not form.is_submitted():
        form.papel.data = usuario.papel.value

    if form.validate_on_submit():
        try:
            usuario_service.atualizar(usuario, form.dados_limpos(), autor=current_user)
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash("Conta atualizada.", "success")
            return redirect(url_for("usuarios.detalhe", usuario_id=usuario.id))

    return render_template("usuarios/formulario.html", form=form, usuario=usuario)


# ---------------------------------------------------------------------------
# Acoes administrativas
# ---------------------------------------------------------------------------
@bp.route("/<int:usuario_id>/redefinir-senha", methods=["POST"])
@login_required
@requer_permissao(Permissao.USUARIO_REDEFINIR_SENHA)
def redefinir_senha(usuario_id: int):
    """Gera uma senha temporaria para o usuario."""
    usuario = usuario_service.buscar(usuario_id)

    try:
        senha = usuario_service.redefinir_senha(usuario)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(
            f"Senha redefinida para {usuario.email}. Nova senha temporaria: "
            f"{senha} — anote agora, ela nao sera exibida novamente. "
            "A troca sera exigida no proximo acesso.",
            "warning",
        )

    return redirect(url_for("usuarios.detalhe", usuario_id=usuario_id))


@bp.route("/<int:usuario_id>/alternar", methods=["POST"])
@login_required
@requer_permissao(Permissao.USUARIO_EDITAR)
def alternar_ativacao(usuario_id: int):
    """Ativa ou desativa uma conta."""
    usuario = usuario_service.buscar(usuario_id)

    try:
        usuario_service.alternar_ativacao(usuario, autor=current_user)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(
            f"Conta {'ativada' if usuario.ativo else 'desativada'}.", "success"
        )

    return redirect(url_for("usuarios.detalhe", usuario_id=usuario_id))


@bp.route("/<int:usuario_id>/desbloquear", methods=["POST"])
@login_required
@requer_permissao(Permissao.USUARIO_EDITAR)
def desbloquear(usuario_id: int):
    """Remove o bloqueio por excesso de tentativas de login."""
    usuario = usuario_service.buscar(usuario_id)
    usuario_service.desbloquear(usuario)
    flash("Conta desbloqueada.", "success")
    return redirect(url_for("usuarios.detalhe", usuario_id=usuario_id))


@bp.route("/<int:usuario_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.USUARIO_EXCLUIR)
def excluir(usuario_id: int):
    """Exclui logicamente uma conta de acesso."""
    usuario = usuario_service.buscar(usuario_id)
    email = usuario.email

    try:
        usuario_service.excluir(usuario, autor=current_user)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("usuarios.detalhe", usuario_id=usuario_id))

    flash(f"Conta {email} excluida.", "success")
    return redirect(url_for("usuarios.listar"))


# ---------------------------------------------------------------------------
# Perfil do proprio usuario
# ---------------------------------------------------------------------------
@bp.route("/perfil", methods=["GET", "POST"])
@login_required
def perfil():
    """Permite ao usuario editar os proprios dados basicos."""
    form = PerfilForm(obj=current_user)

    if form.validate_on_submit():
        try:
            dados = form.dados_limpos()
            if form.foto.data:
                dados["foto"] = substituir_imagem(
                    form.foto.data,
                    current_user.foto,
                    PASTA_FOTOS,
                    prefixo="user",
                    quadrada=True,
                    largura_maxima=300,
                )
            usuario_service.atualizar_perfil(current_user, dados)
        except ErroArquivo as erro:
            form.foto.errors.append(erro.mensagem)
        except ErroDominio as erro:
            flash(erro.mensagem, "danger")
        else:
            flash("Perfil atualizado.", "success")
            return redirect(url_for("usuarios.perfil"))

    return render_template("usuarios/perfil.html", form=form)


@bp.route("/<int:usuario_id>/foto")
@login_required
def foto(usuario_id: int):
    """Entrega o avatar de um usuario.

    A propria foto e sempre acessivel; a de terceiros exige permissao de
    visualizacao de usuarios. O avatar aparece na barra superior de todas as
    telas, entao a rota precisa ser barata e tolerante.
    """
    if usuario_id != current_user.id and not usuario_tem_permissao(
        current_user, Permissao.USUARIO_VISUALIZAR
    ):
        raise ErroPermissao("Voce nao tem acesso a este arquivo.")

    usuario = usuario_service.buscar(usuario_id)
    return responder_arquivo(PASTA_FOTOS, usuario.foto)
