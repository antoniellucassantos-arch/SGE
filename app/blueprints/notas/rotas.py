"""Rotas de avaliacoes e lancamento de notas."""

from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.notas import bp
from app.blueprints.notas.formularios import AvaliacaoForm
from app.services import frequencia_service, nota_service, turma_service
from app.services.excecoes import ErroDominio, ErroPermissao
from app.utils.decoradores import (
    pode_acessar_turma,
    pode_lancar_em_vinculo,
    requer_permissao,
)
from app.utils.permissoes import Permissao


def _ano_letivo_id() -> int | None:
    ano = getattr(g, "ano_letivo", None)
    return ano.id if ano else None


def _garantir_acesso(vinculo) -> None:
    if not pode_acessar_turma(vinculo.turma_id):
        raise ErroPermissao("Voce nao tem acesso as notas desta turma.")


def _garantir_lancamento(vinculo) -> None:
    if not pode_lancar_em_vinculo(vinculo):
        raise ErroPermissao(
            "Apenas o professor titular da disciplina (ou a direcao) pode "
            "lancar notas."
        )


def _periodo_selecionado(vinculo) -> int | None:
    """Resolve o periodo ativo da tela.

    Ordem: parametro da URL -> periodo vigente hoje -> primeiro do ano.
    """
    turma = vinculo.turma
    if turma is None:
        return None

    periodos = nota_service.periodos_do_ano(turma.ano_letivo_id)
    if not periodos:
        return None

    informado = request.args.get("periodo_id")
    if informado and informado.isdigit():
        if any(p.id == int(informado) for p in periodos):
            return int(informado)

    for periodo in periodos:
        if periodo.esta_vigente:
            return periodo.id

    return periodos[0].id


# ---------------------------------------------------------------------------
# Indice
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@requer_permissao(Permissao.NOTA_VISUALIZAR)
def index():
    """Lista as disciplinas cujas notas o usuario pode acessar."""
    if current_user.e_professor:
        vinculos = frequencia_service.vinculos_do_professor(
            current_user.professor, _ano_letivo_id()
        )
    else:
        vinculos = frequencia_service.todos_os_vinculos(_ano_letivo_id())

    return render_template("notas/index.html", vinculos=vinculos)


# ---------------------------------------------------------------------------
# Grade de lancamento
# ---------------------------------------------------------------------------
@bp.route("/lancar/<int:vinculo_id>")
@login_required
@requer_permissao(Permissao.NOTA_VISUALIZAR)
def lancar(vinculo_id: int):
    """Grade de notas: alunos nas linhas, avaliacoes nas colunas."""
    vinculo = frequencia_service.buscar_vinculo(vinculo_id)
    _garantir_acesso(vinculo)

    periodo_id = _periodo_selecionado(vinculo)
    turma = vinculo.turma
    periodos = (
        nota_service.periodos_do_ano(turma.ano_letivo_id) if turma else []
    )

    grade = (
        nota_service.preparar_grade(vinculo, periodo_id)
        if periodo_id
        else {"avaliacoes": [], "linhas": []}
    )

    return render_template(
        "notas/lancar.html",
        vinculo=vinculo,
        periodos=periodos,
        periodo_id=periodo_id,
        grade=grade,
        pode_lancar=pode_lancar_em_vinculo(vinculo),
        form=_montar_form_avaliacao(periodos, periodo_id),
    )


def _montar_form_avaliacao(periodos, periodo_id) -> AvaliacaoForm:
    form = AvaliacaoForm()
    form.periodo_id.choices = [(str(p.id), p.nome) for p in periodos]
    if periodo_id and not form.is_submitted():
        form.periodo_id.data = str(periodo_id)
    return form


# ---------------------------------------------------------------------------
# Avaliacoes
# ---------------------------------------------------------------------------
@bp.route("/vinculo/<int:vinculo_id>/avaliacoes/nova", methods=["POST"])
@login_required
@requer_permissao(Permissao.AVALIACAO_GERENCIAR)
def criar_avaliacao(vinculo_id: int):
    """Cria uma avaliacao e prepara as linhas de nota da turma."""
    vinculo = frequencia_service.buscar_vinculo(vinculo_id)
    _garantir_lancamento(vinculo)

    turma = vinculo.turma
    periodos = nota_service.periodos_do_ano(turma.ano_letivo_id) if turma else []

    form = AvaliacaoForm()
    form.periodo_id.choices = [(str(p.id), p.nome) for p in periodos]

    if not form.validate_on_submit():
        primeiro = next(
            (msgs[0] for msgs in form.errors.values() if msgs), "Dados invalidos."
        )
        flash(primeiro, "danger")
        return redirect(url_for("notas.lancar", vinculo_id=vinculo_id))

    try:
        avaliacao = nota_service.criar_avaliacao(
            vinculo,
            periodo_id=int(form.periodo_id.data),
            nome=form.nome.data,
            tipo=form.tipo.data,
            peso=form.peso.data,
            valor_maximo=form.valor_maximo.data,
            data_aplicacao=form.data_aplicacao.data,
            descricao=form.descricao.data,
            usuario_id=current_user.id,
        )
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("notas.lancar", vinculo_id=vinculo_id))

    flash(f"Avaliacao '{avaliacao.nome}' criada.", "success")
    return redirect(
        url_for("notas.lancar", vinculo_id=vinculo_id, periodo_id=avaliacao.periodo_id)
    )


@bp.route("/avaliacao/<int:avaliacao_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.AVALIACAO_GERENCIAR)
def excluir_avaliacao(avaliacao_id: int):
    """Exclui uma avaliacao sem notas lancadas."""
    avaliacao = nota_service.buscar_avaliacao(avaliacao_id)
    vinculo = avaliacao.turma_disciplina
    _garantir_lancamento(vinculo)

    try:
        nota_service.excluir_avaliacao(avaliacao)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Avaliacao excluida.", "success")

    return redirect(url_for("notas.lancar", vinculo_id=vinculo.id))


@bp.route("/avaliacao/<int:avaliacao_id>/publicar", methods=["POST"])
@login_required
@requer_permissao(Permissao.AVALIACAO_GERENCIAR)
def publicar_avaliacao(avaliacao_id: int):
    """Libera ou oculta as notas para alunos e responsaveis."""
    avaliacao = nota_service.buscar_avaliacao(avaliacao_id)
    vinculo = avaliacao.turma_disciplina
    _garantir_lancamento(vinculo)

    publicar = request.form.get("publicar") == "1"
    nota_service.publicar_avaliacao(avaliacao, publicar)

    flash(
        "Notas liberadas para alunos e responsaveis."
        if publicar
        else "Notas ocultadas. Apenas voce e a coordenacao as visualizam.",
        "success",
    )
    return redirect(
        url_for("notas.lancar", vinculo_id=vinculo.id, periodo_id=avaliacao.periodo_id)
    )


# ---------------------------------------------------------------------------
# Lancamento de notas
# ---------------------------------------------------------------------------
@bp.route("/avaliacao/<int:avaliacao_id>/notas", methods=["POST"])
@login_required
@requer_permissao(Permissao.NOTA_LANCAR)
def salvar_notas(avaliacao_id: int):
    """Grava as notas de uma avaliacao."""
    avaliacao = nota_service.buscar_avaliacao(avaliacao_id)
    vinculo = avaliacao.turma_disciplina
    _garantir_lancamento(vinculo)

    valores, ausencias = _extrair_notas(request.form)

    try:
        alteradas = nota_service.salvar_notas(
            avaliacao,
            valores=valores,
            ausencias=ausencias,
            usuario_id=current_user.id,
        )
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(
            f"{alteradas} nota(s) gravada(s)." if alteradas
            else "Nenhuma alteracao a gravar.",
            "success" if alteradas else "info",
        )

    return redirect(
        url_for("notas.lancar", vinculo_id=vinculo.id, periodo_id=avaliacao.periodo_id)
    )


def _extrair_notas(dados) -> tuple[dict[int, str], set[int]]:
    """Le os campos ``nota_<id>`` e ``ausente_<id>`` do formulario."""
    valores: dict[int, str] = {}
    ausencias: set[int] = set()

    for chave, valor in dados.items():
        if chave.startswith("nota_"):
            sufixo = chave.removeprefix("nota_")
            if sufixo.isdigit():
                valores[int(sufixo)] = valor
        elif chave.startswith("ausente_"):
            sufixo = chave.removeprefix("ausente_")
            if sufixo.isdigit():
                ausencias.add(int(sufixo))

    return valores, ausencias


# ---------------------------------------------------------------------------
# Consolidacao
# ---------------------------------------------------------------------------
@bp.route("/turma/<int:turma_id>/consolidar", methods=["POST"])
@login_required
@requer_permissao(Permissao.NOTA_EDITAR_QUALQUER)
def consolidar(turma_id: int):
    """Recalcula medias, frequencia e resultado de toda a turma."""
    turma = turma_service.buscar_turma(turma_id)

    try:
        total = nota_service.consolidar_turma(turma)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(
            f"Resultados consolidados para {total} aluno(s) da turma "
            f"{turma.identificacao_curta}.",
            "success",
        )

    return redirect(request.referrer or url_for("turmas.detalhe", turma_id=turma_id))
