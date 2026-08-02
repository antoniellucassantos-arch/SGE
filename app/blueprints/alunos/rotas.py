"""Rotas do cadastro de alunos."""

from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.alunos import bp
from app.blueprints.alunos.formularios import (
    AlunoForm,
    FiltroAlunoForm,
    VincularResponsavelForm,
)
from app.extensions import db
from app.models.estrutura import Turma
from app.models.pessoas import Aluno, Responsavel
from app.services import aluno_service
from app.services.excecoes import ErroArquivo, ErroDominio
from app.utils.arquivos import (
    remover_arquivo,
    responder_arquivo,
    substituir_imagem,
)
from app.utils.decoradores import exigir_acesso_aluno, requer_permissao
from app.utils.paginacao import (
    aplicar_ordenacao,
    filtro_texto,
    paginar,
    parametros_preservados,
)
from app.utils.permissoes import Permissao

#: Pasta de uploads das fotos de aluno.
PASTA_FOTOS = "alunos"

#: Colunas pelas quais a listagem pode ser ordenada.
#: Funciona como lista de permissao: nada fora daqui chega ao SQL.
COLUNAS_ORDENAVEIS = {
    "nome": Aluno.nome_normalizado,
    "codigo": Aluno.codigo,
    "nascimento": Aluno.data_nascimento,
    "situacao": Aluno.situacao,
    "cadastro": Aluno.criado_em,
}


def _carregar_opcoes_turma(form: FiltroAlunoForm) -> None:
    """Preenche o filtro de turmas com as turmas do ano letivo corrente."""
    ano_letivo = getattr(g, "ano_letivo", None)
    consulta = db.session.query(Turma).filter(
        Turma.excluido_em.is_(None), Turma.ativa.is_(True)
    )
    if ano_letivo:
        consulta = consulta.filter(Turma.ano_letivo_id == ano_letivo.id)

    turmas = consulta.join(Turma.serie).order_by(Turma.nome).all()
    form.turma_id.choices = [("", "Todas as turmas")] + [
        (str(turma.id), turma.nome_completo) for turma in turmas
    ]


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@requer_permissao(Permissao.ALUNO_VISUALIZAR)
def listar():
    """Lista os alunos com busca, filtros, ordenacao e paginacao."""
    form = FiltroAlunoForm(request.args, meta={"csrf": False})
    _carregar_opcoes_turma(form)

    consulta = aluno_service.listar(
        termo=filtro_texto(form.busca.data),
        situacao=form.situacao.data or None,
        turma_id=int(form.turma_id.data) if (form.turma_id.data or "").isdigit() else None,
        ano_letivo_id=getattr(g.ano_letivo, "id", None) if getattr(g, "ano_letivo", None) else None,
        somente_sem_turma=bool(form.sem_turma.data),
    )

    consulta, coluna, direcao = aplicar_ordenacao(
        consulta, COLUNAS_ORDENAVEIS, coluna_padrao="nome"
    )

    return render_template(
        "alunos/listar.html",
        form=form,
        pagina=paginar(consulta),
        ordenacao={"coluna": coluna, "direcao": direcao},
        parametros=parametros_preservados("ordenar", "direcao"),
    )


# ---------------------------------------------------------------------------
# Ficha do aluno
# ---------------------------------------------------------------------------
@bp.route("/<int:aluno_id>")
@login_required
@requer_permissao(Permissao.ALUNO_VISUALIZAR)
@exigir_acesso_aluno()
def detalhe(aluno_id: int):
    """Ficha completa do aluno."""
    aluno = aluno_service.buscar(aluno_id)

    return render_template(
        "alunos/detalhe.html",
        aluno=aluno,
        resumo=aluno_service.resumo_academico(aluno),
        pode_ver_saude=current_user.tem_papel(
            "administrador", "direcao", "secretaria"
        ),
        form_responsavel=_montar_form_responsavel(),
    )


def _montar_form_responsavel() -> VincularResponsavelForm:
    """Formulario de vinculo com a lista de responsaveis disponiveis."""
    form = VincularResponsavelForm()
    responsaveis = (
        db.session.query(Responsavel)
        .filter(Responsavel.excluido_em.is_(None))
        .order_by(Responsavel.nome_normalizado)
        .all()
    )
    form.responsavel_id.choices = [("", "Selecione um responsavel")] + [
        (str(r.id), f"{r.nome_completo} ({r.cpf_formatado or 'sem CPF'})")
        for r in responsaveis
    ]
    return form


# ---------------------------------------------------------------------------
# Cadastro
# ---------------------------------------------------------------------------
@bp.route("/novo", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.ALUNO_CRIAR)
def novo():
    """Cadastra um novo aluno."""
    form = AlunoForm()

    if form.validate_on_submit():
        try:
            dados = form.dados_limpos()
            dados["foto"] = _processar_foto(form, None)
            aluno = aluno_service.criar(dados, usuario_id=current_user.id)
        except ErroArquivo as erro:
            form.foto.errors.append(erro.mensagem)
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash(
                f"Aluno {aluno.nome_exibicao} cadastrado com sucesso "
                f"(codigo {aluno.codigo}).",
                "success",
            )
            return redirect(url_for("alunos.detalhe", aluno_id=aluno.id))

    return render_template("alunos/formulario.html", form=form, aluno=None)


@bp.route("/<int:aluno_id>/editar", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.ALUNO_EDITAR)
@exigir_acesso_aluno()
def editar(aluno_id: int):
    """Edita um aluno existente."""
    aluno = aluno_service.buscar(aluno_id)
    form = AlunoForm(obj=aluno)

    if form.validate_on_submit():
        try:
            dados = form.dados_limpos()
            dados["foto"] = _processar_foto(form, aluno.foto)
            aluno_service.atualizar(aluno, dados, usuario_id=current_user.id)
        except ErroArquivo as erro:
            form.foto.errors.append(erro.mensagem)
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash("Cadastro atualizado com sucesso.", "success")
            return redirect(url_for("alunos.detalhe", aluno_id=aluno.id))

    return render_template("alunos/formulario.html", form=form, aluno=aluno)


def _processar_foto(form: AlunoForm, foto_atual: str | None) -> str | None:
    """Grava a nova foto (se enviada) mantendo a anterior caso contrario."""
    if not form.foto.data:
        return foto_atual
    return substituir_imagem(
        form.foto.data,
        foto_atual,
        PASTA_FOTOS,
        prefixo="aluno",
        quadrada=True,
        largura_maxima=400,
    )


# ---------------------------------------------------------------------------
# Exclusao
# ---------------------------------------------------------------------------
@bp.route("/<int:aluno_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.ALUNO_EXCLUIR)
def excluir(aluno_id: int):
    """Exclui logicamente o aluno preservando o historico escolar."""
    aluno = aluno_service.buscar(aluno_id)
    nome = aluno.nome_exibicao

    try:
        aluno_service.excluir(aluno, usuario_id=current_user.id)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("alunos.detalhe", aluno_id=aluno_id))

    flash(
        f"Aluno {nome} excluido. O historico escolar foi preservado e o "
        "cadastro pode ser restaurado pela direcao.",
        "success",
    )
    return redirect(url_for("alunos.listar"))


@bp.route("/<int:aluno_id>/foto/remover", methods=["POST"])
@login_required
@requer_permissao(Permissao.ALUNO_EDITAR)
def remover_foto(aluno_id: int):
    """Remove a foto do aluno."""
    aluno = aluno_service.buscar(aluno_id)

    if aluno.foto:
        remover_arquivo(aluno.foto, PASTA_FOTOS)
        aluno_service.atualizar(aluno, {"foto": None}, usuario_id=current_user.id)
        flash("Foto removida.", "success")

    return redirect(url_for("alunos.editar", aluno_id=aluno_id))


# ---------------------------------------------------------------------------
# Responsaveis
# ---------------------------------------------------------------------------
@bp.route("/<int:aluno_id>/responsaveis/vincular", methods=["POST"])
@login_required
@requer_permissao(Permissao.ALUNO_EDITAR)
def vincular_responsavel(aluno_id: int):
    """Vincula um responsavel ao aluno."""
    aluno = aluno_service.buscar(aluno_id)
    form = _montar_form_responsavel()

    if not form.validate_on_submit():
        primeiro_erro = next(
            (msgs[0] for msgs in form.errors.values() if msgs), "Dados invalidos."
        )
        flash(primeiro_erro, "danger")
        return redirect(url_for("alunos.detalhe", aluno_id=aluno_id))

    try:
        aluno_service.vincular_responsavel(
            aluno,
            responsavel_id=int(form.responsavel_id.data),
            parentesco=form.parentesco.data,
            responsavel_legal=bool(form.responsavel_legal.data),
            responsavel_financeiro=bool(form.responsavel_financeiro.data),
            autorizado_buscar=bool(form.autorizado_buscar.data),
            ordem_contato=form.ordem_contato.data or 1,
        )
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Responsavel vinculado com sucesso.", "success")

    return redirect(url_for("alunos.detalhe", aluno_id=aluno_id))


@bp.route("/<int:aluno_id>/responsaveis/<int:responsavel_id>/remover", methods=["POST"])
@login_required
@requer_permissao(Permissao.ALUNO_EDITAR)
def desvincular_responsavel(aluno_id: int, responsavel_id: int):
    """Remove o vinculo entre o aluno e um responsavel."""
    aluno = aluno_service.buscar(aluno_id)

    try:
        aluno_service.desvincular_responsavel(aluno, responsavel_id)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Vinculo removido.", "success")

    return redirect(url_for("alunos.detalhe", aluno_id=aluno_id))


# ---------------------------------------------------------------------------
# Foto (servida por rota autenticada, nunca por static/)
# ---------------------------------------------------------------------------
@bp.route("/<int:aluno_id>/foto")
@login_required
@exigir_acesso_aluno()
def foto(aluno_id: int):
    """Entrega a foto do aluno apenas a quem tem escopo sobre ele.

    Uploads ficam fora de ``static/`` justamente para passarem por aqui:
    sao imagens de menores de idade e nao podem ser acessiveis por URL
    direta, sem login.
    """
    aluno = aluno_service.buscar(aluno_id)
    return responder_arquivo(PASTA_FOTOS, aluno.foto)
