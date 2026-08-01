"""Rotas de turmas e da grade de disciplinas."""

from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.turmas import bp
from app.blueprints.turmas.formularios import (
    AtribuirDisciplinaForm,
    EditarVinculoForm,
    FiltroTurmaForm,
    TurmaForm,
)
from app.extensions import db
from app.models.estrutura import Sala, Turma, TurmaDisciplina
from app.services import turma_service
from app.services.excecoes import ErroDominio, RegistroNaoEncontrado
from app.utils.decoradores import exigir_acesso_turma, requer_permissao
from app.utils.paginacao import (
    aplicar_ordenacao,
    filtro_texto,
    paginar,
    parametros_preservados,
)
from app.utils.permissoes import Permissao

COLUNAS_ORDENAVEIS = {
    "nome": Turma.nome,
    "turno": Turma.turno,
    "capacidade": Turma.capacidade,
    "criacao": Turma.criado_em,
}


def _opcoes_basicas() -> dict:
    """Listas usadas nos selects de turma."""
    return {
        "anos": turma_service.anos_letivos(),
        "series": turma_service.series_ativas(),
        "salas": db.session.query(Sala)
        .filter(Sala.ativa.is_(True))
        .order_by(Sala.nome)
        .all(),
        "professores": turma_service.professores_ativos(),
    }


def _carregar_opcoes_turma(form: TurmaForm) -> None:
    """Preenche os selects do formulario de turma."""
    opcoes = _opcoes_basicas()

    form.ano_letivo_id.choices = [
        (str(a.id), f"{a.ano}{' (corrente)' if a.corrente else ''}")
        for a in opcoes["anos"]
    ]
    form.serie_id.choices = [
        (str(s.id), s.nome_completo) for s in opcoes["series"]
    ]
    form.sala_id.choices = [("", "Sem sala fixa")] + [
        (str(s.id), s.identificacao) for s in opcoes["salas"]
    ]
    form.professor_regente_id.choices = [("", "Sem regente")] + [
        (str(p.id), p.nome_exibicao) for p in opcoes["professores"]
    ]


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@requer_permissao(Permissao.TURMA_VISUALIZAR)
def listar():
    """Lista as turmas com filtros por ano letivo, serie e turno."""
    form = FiltroTurmaForm(request.args, meta={"csrf": False})

    anos = turma_service.anos_letivos()
    series = turma_service.series_ativas()

    form.ano_letivo_id.choices = [("", "Todos os anos")] + [
        (str(a.id), str(a.ano)) for a in anos
    ]
    form.serie_id.choices = [("", "Todas as series")] + [
        (str(s.id), s.nome) for s in series
    ]

    # Sem filtro explicito, mostra o ano letivo corrente: e o que a
    # secretaria quer ver em 99% dos acessos.
    ano_letivo_id = form.ano_letivo_id.data
    if not ano_letivo_id and getattr(g, "ano_letivo", None):
        ano_letivo_id = str(g.ano_letivo.id)
        form.ano_letivo_id.data = ano_letivo_id

    consulta = turma_service.listar_turmas(
        termo=filtro_texto(form.busca.data),
        ano_letivo_id=int(ano_letivo_id) if (ano_letivo_id or "").isdigit() else None,
        serie_id=int(form.serie_id.data) if (form.serie_id.data or "").isdigit() else None,
        turno=form.turno.data or None,
    )
    consulta, coluna, direcao = aplicar_ordenacao(
        consulta, COLUNAS_ORDENAVEIS, coluna_padrao="nome"
    )

    return render_template(
        "turmas/listar.html",
        form=form,
        pagina=paginar(consulta),
        ordenacao={"coluna": coluna, "direcao": direcao},
        parametros=parametros_preservados("ordenar", "direcao"),
    )


# ---------------------------------------------------------------------------
# Detalhe
# ---------------------------------------------------------------------------
@bp.route("/<int:turma_id>")
@login_required
@requer_permissao(Permissao.TURMA_VISUALIZAR)
@exigir_acesso_turma()
def detalhe(turma_id: int):
    """Ficha da turma: alunos matriculados e grade de disciplinas."""
    turma = turma_service.buscar_turma(turma_id)

    form_disciplina = AtribuirDisciplinaForm()
    form_disciplina.disciplina_id.choices = [
        (str(d.id), f"{d.nome} ({d.codigo})")
        for d in turma_service.disciplinas_disponiveis(turma)
    ]
    form_disciplina.professor_id.choices = [("", "Sem professor")] + [
        (str(p.id), p.nome_exibicao) for p in turma_service.professores_ativos()
    ]

    return render_template(
        "turmas/detalhe.html",
        turma=turma,
        matriculas=turma_service.alunos_da_turma(turma),
        form_disciplina=form_disciplina,
    )


# ---------------------------------------------------------------------------
# Cadastro
# ---------------------------------------------------------------------------
@bp.route("/nova", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.TURMA_CRIAR)
def nova():
    """Cria uma nova turma."""
    form = TurmaForm()
    _carregar_opcoes_turma(form)

    if not form.is_submitted() and getattr(g, "ano_letivo", None):
        form.ano_letivo_id.data = str(g.ano_letivo.id)

    if form.validate_on_submit():
        try:
            turma = turma_service.criar_turma(form.dados_limpos())
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash(f"Turma {turma.nome_completo} criada com sucesso.", "success")
            return redirect(url_for("turmas.detalhe", turma_id=turma.id))

    return render_template("turmas/formulario.html", form=form, turma=None)


@bp.route("/<int:turma_id>/editar", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.TURMA_EDITAR)
def editar(turma_id: int):
    """Edita uma turma existente."""
    turma = turma_service.buscar_turma(turma_id)
    form = TurmaForm(obj=turma)
    _carregar_opcoes_turma(form)

    if not form.is_submitted():
        form.ano_letivo_id.data = str(turma.ano_letivo_id)
        form.serie_id.data = str(turma.serie_id)
        form.sala_id.data = str(turma.sala_id or "")
        form.professor_regente_id.data = str(turma.professor_regente_id or "")

    if form.validate_on_submit():
        try:
            turma_service.atualizar_turma(turma, form.dados_limpos())
        except ErroDominio as erro:
            form.aplicar_erros(getattr(erro, "erros_por_campo", None))
            flash(erro.mensagem, "danger")
        else:
            flash("Turma atualizada com sucesso.", "success")
            return redirect(url_for("turmas.detalhe", turma_id=turma.id))

    return render_template("turmas/formulario.html", form=form, turma=turma)


@bp.route("/<int:turma_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.TURMA_EXCLUIR)
def excluir(turma_id: int):
    """Exclui logicamente a turma."""
    turma = turma_service.buscar_turma(turma_id)
    nome = turma.nome_completo

    try:
        turma_service.excluir_turma(turma, usuario_id=current_user.id)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("turmas.detalhe", turma_id=turma_id))

    flash(f"Turma {nome} excluida.", "success")
    return redirect(url_for("turmas.listar"))


# ---------------------------------------------------------------------------
# Grade de disciplinas
# ---------------------------------------------------------------------------
@bp.route("/<int:turma_id>/disciplinas", methods=["POST"])
@login_required
@requer_permissao(Permissao.TURMA_EDITAR)
def atribuir_disciplina(turma_id: int):
    """Atribui uma disciplina (e professor) a turma."""
    turma = turma_service.buscar_turma(turma_id)
    form = AtribuirDisciplinaForm()

    # As choices precisam ser recarregadas para que a validacao aceite o
    # valor submetido — SelectField valida contra a lista de opcoes.
    form.disciplina_id.choices = [
        (str(d.id), d.nome) for d in turma_service.disciplinas_disponiveis(turma)
    ]
    form.professor_id.choices = [("", "Sem professor")] + [
        (str(p.id), p.nome_exibicao) for p in turma_service.professores_ativos()
    ]

    if not form.validate_on_submit():
        primeiro = next(
            (msgs[0] for msgs in form.errors.values() if msgs), "Dados invalidos."
        )
        flash(primeiro, "danger")
        return redirect(url_for("turmas.detalhe", turma_id=turma_id))

    professor_id = form.professor_id.data
    try:
        turma_service.atribuir_disciplina(
            turma,
            disciplina_id=int(form.disciplina_id.data),
            professor_id=int(professor_id) if (professor_id or "").isdigit() else None,
            carga_horaria_semanal=form.carga_horaria_semanal.data or 2,
        )
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Disciplina atribuida a turma.", "success")

    return redirect(url_for("turmas.detalhe", turma_id=turma_id))


@bp.route("/<int:turma_id>/disciplinas/<int:vinculo_id>", methods=["POST"])
@login_required
@requer_permissao(Permissao.TURMA_EDITAR)
def editar_vinculo(turma_id: int, vinculo_id: int):
    """Altera professor, carga horaria ou situacao de um vinculo."""
    turma_service.buscar_turma(turma_id)
    vinculo = _buscar_vinculo(vinculo_id, turma_id)

    form = EditarVinculoForm()
    form.professor_id.choices = [("", "Sem professor")] + [
        (str(p.id), p.nome_exibicao) for p in turma_service.professores_ativos()
    ]

    if not form.validate_on_submit():
        flash("Nao foi possivel salvar as alteracoes do vinculo.", "danger")
        return redirect(url_for("turmas.detalhe", turma_id=turma_id))

    professor_id = form.professor_id.data
    try:
        turma_service.atualizar_vinculo(
            vinculo,
            professor_id=int(professor_id) if (professor_id or "").isdigit() else None,
            carga_horaria_semanal=form.carga_horaria_semanal.data or 2,
            ativa=bool(form.ativa.data),
        )
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Vinculo atualizado.", "success")

    return redirect(url_for("turmas.detalhe", turma_id=turma_id))


@bp.route("/<int:turma_id>/disciplinas/<int:vinculo_id>/remover", methods=["POST"])
@login_required
@requer_permissao(Permissao.TURMA_EDITAR)
def remover_vinculo(turma_id: int, vinculo_id: int):
    """Remove a atribuicao de uma disciplina da turma."""
    turma_service.buscar_turma(turma_id)
    vinculo = _buscar_vinculo(vinculo_id, turma_id)

    try:
        turma_service.remover_vinculo(vinculo)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Disciplina removida da turma.", "success")

    return redirect(url_for("turmas.detalhe", turma_id=turma_id))


def _buscar_vinculo(vinculo_id: int, turma_id: int) -> TurmaDisciplina:
    """Recupera o vinculo garantindo que ele pertence a turma informada.

    Sem esta checagem, trocar o id na URL permitiria alterar a grade de
    outra turma (referencia direta insegura a objeto).
    """
    vinculo = db.session.get(TurmaDisciplina, vinculo_id)
    if vinculo is None or vinculo.turma_id != turma_id:
        raise RegistroNaoEncontrado("Vinculo nao encontrado nesta turma.")
    return vinculo
