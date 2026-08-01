"""Rotas do cadastro de disciplinas.

As disciplinas sao componentes curriculares reutilizados por varias turmas e
varios anos letivos. A atribuicao concreta (qual professor leciona a
disciplina em qual turma) e feita na tela da turma.
"""

from __future__ import annotations

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.disciplinas import bp
from app.blueprints.turmas.formularios import DisciplinaForm, FiltroDisciplinaForm
from app.models.estrutura import Disciplina
from app.services import turma_service
from app.services.excecoes import ErroDominio
from app.utils.decoradores import requer_permissao
from app.utils.paginacao import (
    aplicar_ordenacao,
    filtro_texto,
    paginar,
    parametros_preservados,
)
from app.utils.permissoes import Permissao

COLUNAS_ORDENAVEIS = {
    "nome": Disciplina.nome_normalizado,
    "codigo": Disciplina.codigo,
    "carga": Disciplina.carga_horaria,
}


@bp.route("/")
@login_required
@requer_permissao(Permissao.DISCIPLINA_VISUALIZAR)
def listar():
    """Lista as disciplinas cadastradas."""
    form = FiltroDisciplinaForm(request.args, meta={"csrf": False})

    consulta = turma_service.listar_disciplinas(termo=filtro_texto(form.busca.data))

    if form.ativa.data == "1":
        consulta = consulta.filter(Disciplina.ativa.is_(True))
    elif form.ativa.data == "0":
        consulta = consulta.filter(Disciplina.ativa.is_(False))

    consulta, coluna, direcao = aplicar_ordenacao(
        consulta, COLUNAS_ORDENAVEIS, coluna_padrao="nome"
    )

    return render_template(
        "disciplinas/listar.html",
        form=form,
        pagina=paginar(consulta),
        ordenacao={"coluna": coluna, "direcao": direcao},
        parametros=parametros_preservados("ordenar", "direcao"),
    )


@bp.route("/nova", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.DISCIPLINA_CRIAR)
def nova():
    """Cadastra uma nova disciplina."""
    form = DisciplinaForm()

    if form.validate_on_submit():
        try:
            disciplina = turma_service.criar_disciplina(form.dados_limpos())
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash(f"Disciplina {disciplina.nome} cadastrada.", "success")
            return redirect(url_for("disciplinas.listar"))

    return render_template("disciplinas/formulario.html", form=form, disciplina=None)


@bp.route("/<int:disciplina_id>/editar", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.DISCIPLINA_EDITAR)
def editar(disciplina_id: int):
    """Edita uma disciplina existente."""
    disciplina = turma_service.buscar_disciplina(disciplina_id)
    form = DisciplinaForm(obj=disciplina)

    if form.validate_on_submit():
        try:
            turma_service.atualizar_disciplina(disciplina, form.dados_limpos())
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash("Disciplina atualizada.", "success")
            return redirect(url_for("disciplinas.listar"))

    return render_template(
        "disciplinas/formulario.html", form=form, disciplina=disciplina
    )


@bp.route("/<int:disciplina_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.DISCIPLINA_EXCLUIR)
def excluir(disciplina_id: int):
    """Exclui logicamente a disciplina, se ela nao estiver em uso."""
    disciplina = turma_service.buscar_disciplina(disciplina_id)
    nome = disciplina.nome

    try:
        turma_service.excluir_disciplina(disciplina, usuario_id=current_user.id)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(f"Disciplina {nome} excluida.", "success")

    return redirect(url_for("disciplinas.listar"))
