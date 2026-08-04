"""Rotas do modulo de matriculas."""

from __future__ import annotations

from datetime import date

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import login_required

from app.blueprints.matriculas import bp
from app.blueprints.matriculas.formularios import (
    EncerrarMatriculaForm,
    FiltroMatriculaForm,
    MatriculaForm,
    TransferirEscolaForm,
    TransferirTurmaForm,
)
from app.models.matricula import Matricula
from app.models.pessoas import Aluno
from app.services import matricula_service, turma_service
from app.services.excecoes import ErroDominio, ErroPermissao
from app.utils.decoradores import pode_acessar_aluno, requer_permissao
from app.utils.paginacao import (
    aplicar_ordenacao,
    filtro_texto,
    paginar,
    parametros_preservados,
)
from app.utils.permissoes import Permissao

COLUNAS_ORDENAVEIS = {
    "numero": Matricula.numero,
    "aluno": Aluno.nome_normalizado,
    "data": Matricula.data_matricula,
    "situacao": Matricula.situacao,
}


def _ano_letivo_padrao() -> int | None:
    ano = getattr(g, "ano_letivo", None)
    return ano.id if ano else None


# ---------------------------------------------------------------------------
# Listagem
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@requer_permissao(Permissao.MATRICULA_VISUALIZAR)
def listar():
    """Lista as matriculas com filtros por ano letivo, turma e situacao."""
    form = FiltroMatriculaForm(request.args, meta={"csrf": False})

    anos = turma_service.anos_letivos()
    form.ano_letivo_id.choices = [("", "Todos os anos")] + [
        (str(a.id), str(a.ano)) for a in anos
    ]

    # Sem filtro explicito, mostra o ano corrente.
    ano_letivo_id = form.ano_letivo_id.data
    if not ano_letivo_id and _ano_letivo_padrao():
        ano_letivo_id = str(_ano_letivo_padrao())
        form.ano_letivo_id.data = ano_letivo_id

    id_ano = int(ano_letivo_id) if (ano_letivo_id or "").isdigit() else None
    turmas = matricula_service.turmas_com_vaga(id_ano) if id_ano else []
    form.turma_id.choices = [("", "Todas as turmas")] + [
        (str(t.id), t.identificacao_curta) for t in turmas
    ]

    consulta = matricula_service.listar(
        termo=filtro_texto(form.busca.data),
        ano_letivo_id=id_ano,
        turma_id=int(form.turma_id.data) if (form.turma_id.data or "").isdigit() else None,
        situacao=form.situacao.data or None,
    )
    consulta, coluna, direcao = aplicar_ordenacao(
        consulta, COLUNAS_ORDENAVEIS, coluna_padrao="aluno"
    )

    return render_template(
        "matriculas/listar.html",
        form=form,
        pagina=paginar(consulta),
        ordenacao={"coluna": coluna, "direcao": direcao},
        parametros=parametros_preservados("ordenar", "direcao"),
        estatisticas=matricula_service.estatisticas(id_ano),
    )


# ---------------------------------------------------------------------------
# Detalhe
# ---------------------------------------------------------------------------
@bp.route("/<int:matricula_id>")
@login_required
@requer_permissao(Permissao.MATRICULA_VISUALIZAR)
def detalhe(matricula_id: int):
    """Detalhe da matricula com as acoes disponiveis."""
    matricula = matricula_service.buscar(matricula_id)

    # O id da URL e o da matricula, nao o do aluno — `exigir_acesso_aluno()`
    # le de `kwargs` e nao teria o que conferir aqui. Sem esta linha, um
    # professor com MATRICULA_VISUALIZAR percorria /matriculas/1,
    # /matriculas/2... e lia a ficha de qualquer aluno da escola.
    if not pode_acessar_aluno(matricula.aluno_id):
        raise ErroPermissao("Voce nao tem acesso aos dados deste aluno.")

    form_turma = TransferirTurmaForm()
    turmas = matricula_service.turmas_com_vaga(matricula.ano_letivo_id)
    form_turma.nova_turma_id.choices = [
        (str(t.id), f"{t.identificacao_curta} ({t.vagas_disponiveis} vagas)")
        for t in turmas
        if t.id != matricula.turma_id
    ]

    return render_template(
        "matriculas/detalhe.html",
        matricula=matricula,
        form_turma=form_turma,
        form_escola=TransferirEscolaForm(),
        form_encerrar=EncerrarMatriculaForm(),
    )


# ---------------------------------------------------------------------------
# Nova matricula
# ---------------------------------------------------------------------------
@bp.route("/nova", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.MATRICULA_CRIAR)
def nova():
    """Efetiva uma nova matricula.

    Aceita ``?aluno_id=`` e ``?turma_id=`` para pre-selecionar os campos
    quando o usuario chega pela ficha do aluno ou pela tela da turma.
    """
    form = MatriculaForm()

    anos = turma_service.anos_letivos()
    form.ano_letivo_id.choices = [
        (str(a.id), f"{a.ano}{' (corrente)' if a.corrente else ''}") for a in anos
    ]

    # O ano determina quais turmas e quais alunos estao disponiveis.
    ano_selecionado = form.ano_letivo_id.data or str(_ano_letivo_padrao() or "")
    id_ano = int(ano_selecionado) if (ano_selecionado or "").isdigit() else None

    turmas = matricula_service.turmas_com_vaga(id_ano) if id_ano else []
    form.turma_id.choices = [
        (
            str(t.id),
            f"{t.identificacao_curta} - {t.turno.rotulo} "
            f"({t.vagas_disponiveis} vaga(s))"
            + (" [LOTADA]" if t.esta_lotada else ""),
        )
        for t in turmas
    ]

    disponiveis = matricula_service.alunos_sem_matricula(id_ano) if id_ano else []
    form.aluno_id.choices = [
        (str(a.id), f"{a.nome_exibicao} ({a.codigo})") for a in disponiveis
    ]

    if not form.is_submitted():
        form.ano_letivo_id.data = ano_selecionado
        form.data_matricula.data = date.today()
        if request.args.get("aluno_id"):
            form.aluno_id.data = request.args["aluno_id"]
        if request.args.get("turma_id"):
            form.turma_id.data = request.args["turma_id"]

    if form.validate_on_submit():
        try:
            matricula = matricula_service.matricular(
                aluno_id=int(form.aluno_id.data),
                turma_id=int(form.turma_id.data),
                ano_letivo_id=int(form.ano_letivo_id.data),
                data_matricula=form.data_matricula.data,
                escola_origem=form.escola_origem.data,
                observacoes=form.observacoes.data,
            )
        except ErroDominio as erro:
            flash(erro.mensagem, "danger")
        else:
            flash(
                f"Matricula {matricula.numero} efetivada para "
                f"{matricula.nome_aluno}.",
                "success",
            )
            return redirect(url_for("matriculas.detalhe", matricula_id=matricula.id))

    return render_template(
        "matriculas/formulario.html",
        form=form,
        sem_alunos=not disponiveis,
        sem_turmas=not turmas,
    )


# ---------------------------------------------------------------------------
# Acoes sobre a matricula
# ---------------------------------------------------------------------------
@bp.route("/<int:matricula_id>/transferir-turma", methods=["POST"])
@login_required
@requer_permissao(Permissao.MATRICULA_TRANSFERIR)
def transferir_turma(matricula_id: int):
    """Move o aluno para outra turma preservando notas e frequencia."""
    matricula = matricula_service.buscar(matricula_id)

    form = TransferirTurmaForm()
    turmas = matricula_service.turmas_com_vaga(matricula.ano_letivo_id)
    form.nova_turma_id.choices = [
        (str(t.id), t.identificacao_curta)
        for t in turmas
        if t.id != matricula.turma_id
    ]

    if not form.validate_on_submit():
        flash("Selecione a turma de destino.", "danger")
        return redirect(url_for("matriculas.detalhe", matricula_id=matricula_id))

    try:
        matricula_service.transferir_turma(
            matricula,
            nova_turma_id=int(form.nova_turma_id.data),
            motivo=form.motivo.data,
        )
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(
            "Aluno transferido de turma. Notas e frequencia lancadas foram "
            "preservadas.",
            "success",
        )

    return redirect(url_for("matriculas.detalhe", matricula_id=matricula_id))


@bp.route("/<int:matricula_id>/transferir-escola", methods=["POST"])
@login_required
@requer_permissao(Permissao.MATRICULA_TRANSFERIR)
def transferir_escola(matricula_id: int):
    """Encerra a matricula por transferencia para outra escola."""
    matricula = matricula_service.buscar(matricula_id)
    form = TransferirEscolaForm()

    if not form.validate_on_submit():
        flash("Informe a escola de destino.", "danger")
        return redirect(url_for("matriculas.detalhe", matricula_id=matricula_id))

    try:
        matricula_service.transferir_escola(
            matricula,
            escola_destino=form.escola_destino.data,
            motivo=form.motivo.data,
        )
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(
            "Transferencia registrada. O historico escolar do aluno "
            "permanece disponivel para emissao de documentos.",
            "success",
        )

    return redirect(url_for("matriculas.detalhe", matricula_id=matricula_id))


@bp.route("/<int:matricula_id>/cancelar", methods=["POST"])
@login_required
@requer_permissao(Permissao.MATRICULA_CANCELAR)
def cancelar(matricula_id: int):
    """Cancela a matricula (desistencia ou evasao)."""
    matricula = matricula_service.buscar(matricula_id)
    form = EncerrarMatriculaForm()

    if not form.validate_on_submit():
        flash("Informe o motivo do cancelamento.", "danger")
        return redirect(url_for("matriculas.detalhe", matricula_id=matricula_id))

    try:
        matricula_service.cancelar(matricula, motivo=form.motivo.data)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Matricula cancelada.", "success")

    return redirect(url_for("matriculas.detalhe", matricula_id=matricula_id))


@bp.route("/<int:matricula_id>/trancar", methods=["POST"])
@login_required
@requer_permissao(Permissao.MATRICULA_EDITAR)
def trancar(matricula_id: int):
    """Tranca temporariamente a matricula, mantendo a vaga."""
    matricula = matricula_service.buscar(matricula_id)
    form = EncerrarMatriculaForm()

    if not form.validate_on_submit():
        flash("Informe o motivo do trancamento.", "danger")
        return redirect(url_for("matriculas.detalhe", matricula_id=matricula_id))

    try:
        matricula_service.trancar(matricula, motivo=form.motivo.data)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Matricula trancada. A vaga do aluno foi mantida.", "success")

    return redirect(url_for("matriculas.detalhe", matricula_id=matricula_id))


@bp.route("/<int:matricula_id>/reativar", methods=["POST"])
@login_required
@requer_permissao(Permissao.MATRICULA_EDITAR)
def reativar(matricula_id: int):
    """Reativa uma matricula trancada ou cancelada."""
    matricula = matricula_service.buscar(matricula_id)

    try:
        matricula_service.reativar(matricula)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Matricula reativada.", "success")

    return redirect(url_for("matriculas.detalhe", matricula_id=matricula_id))
