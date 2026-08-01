"""Rotas de avisos e comunicados."""

from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.avisos import bp
from app.blueprints.avisos.formularios import AvisoForm, FiltroAvisoForm
from app.models.comunicacao import Aviso
from app.services import aviso_service, turma_service
from app.services.excecoes import ErroDominio, ErroPermissao
from app.utils.decoradores import requer_permissao
from app.utils.paginacao import filtro_texto, paginar, parametros_preservados
from app.utils.permissoes import Permissao, usuario_tem_permissao


def _carregar_turmas(form: AvisoForm) -> None:
    """Preenche o select de turmas do ano letivo corrente."""
    ano = getattr(g, "ano_letivo", None)
    turmas = turma_service.listar_turmas(
        ano_letivo_id=ano.id if ano else None, somente_ativas=True
    ).all()

    form.turma_id.choices = [("", "Selecione a turma")] + [
        (str(t.id), t.identificacao_curta) for t in turmas
    ]


def _pode_editar(aviso: Aviso) -> bool:
    """Autor edita o proprio aviso; a direcao edita qualquer um."""
    if usuario_tem_permissao(current_user, Permissao.AVISO_EDITAR_QUALQUER):
        return True
    return aviso.autor_id == current_user.id


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@requer_permissao(Permissao.AVISO_VISUALIZAR)
def listar():
    """Lista os avisos.

    Equipe interna ve todos (inclusive rascunhos); aluno e responsavel veem
    apenas os avisos vigentes destinados a eles.
    """
    if not current_user.e_equipe_interna:
        avisos = aviso_service.listar_para_usuario(current_user)
        nao_lidos = aviso_service.nao_lidos_do_usuario(current_user)
        return render_template(
            "avisos/mural.html", avisos=avisos, nao_lidos=nao_lidos
        )

    form = FiltroAvisoForm(request.args, meta={"csrf": False})
    consulta = aviso_service.listar(
        termo=filtro_texto(form.busca.data),
        publico=form.publico.data or None,
    )

    return render_template(
        "avisos/listar.html",
        form=form,
        pagina=paginar(consulta),
        parametros=parametros_preservados(),
    )


# ---------------------------------------------------------------------------
# Detalhe
# ---------------------------------------------------------------------------
@bp.route("/<int:aviso_id>")
@login_required
@requer_permissao(Permissao.AVISO_VISUALIZAR)
def detalhe(aviso_id: int):
    """Exibe um aviso e registra a leitura."""
    aviso = aviso_service.buscar(aviso_id)

    # Alunos e responsaveis so acessam avisos destinados a eles.
    if not current_user.e_equipe_interna and not aviso.destinado_a(current_user):
        raise ErroPermissao("Este aviso nao e destinado a voce.")

    try:
        aviso_service.marcar_como_lido(aviso, current_user)
    except ErroDominio:
        pass  # a leitura e acessoria: nunca impede a exibicao

    return render_template(
        "avisos/detalhe.html",
        aviso=aviso,
        pode_editar=_pode_editar(aviso),
        leitores=(
            aviso_service.leitores(aviso) if current_user.e_equipe_interna else []
        ),
    )


# ---------------------------------------------------------------------------
# Criacao e edicao
# ---------------------------------------------------------------------------
@bp.route("/novo", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.AVISO_CRIAR)
def novo():
    """Publica um novo aviso."""
    form = AvisoForm()
    _carregar_turmas(form)

    if form.validate_on_submit():
        try:
            aviso = aviso_service.criar(form.dados_limpos(), autor_id=current_user.id)
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash(f"Aviso '{aviso.titulo}' publicado.", "success")
            return redirect(url_for("avisos.detalhe", aviso_id=aviso.id))

    return render_template("avisos/formulario.html", form=form, aviso=None)


@bp.route("/<int:aviso_id>/editar", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.AVISO_CRIAR)
def editar(aviso_id: int):
    """Edita um aviso existente."""
    aviso = aviso_service.buscar(aviso_id)

    if not _pode_editar(aviso):
        raise ErroPermissao("Voce so pode editar avisos que voce mesmo publicou.")

    form = AvisoForm(obj=aviso)
    _carregar_turmas(form)

    if not form.is_submitted():
        form.turma_id.data = str(aviso.turma_id or "")

    if form.validate_on_submit():
        try:
            aviso_service.atualizar(aviso, form.dados_limpos())
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash("Aviso atualizado.", "success")
            return redirect(url_for("avisos.detalhe", aviso_id=aviso.id))

    return render_template("avisos/formulario.html", form=form, aviso=aviso)


@bp.route("/<int:aviso_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.AVISO_EXCLUIR)
def excluir(aviso_id: int):
    """Exclui logicamente um aviso."""
    aviso = aviso_service.buscar(aviso_id)
    titulo = aviso.titulo

    try:
        aviso_service.excluir(aviso, usuario_id=current_user.id)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("avisos.detalhe", aviso_id=aviso_id))

    flash(f"Aviso '{titulo}' excluido.", "success")
    return redirect(url_for("avisos.listar"))
