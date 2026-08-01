"""Rotas do diario de classe e do controle de frequencia."""

from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.frequencia import bp
from app.blueprints.frequencia.formularios import AulaForm, JustificarFaltaForm
from app.extensions import db
from app.models.frequencia import Frequencia
from app.services import aluno_service, frequencia_service
from app.services.excecoes import ErroDominio, ErroPermissao, RegistroNaoEncontrado
from app.utils.decoradores import (
    exigir_acesso_aluno,
    pode_acessar_turma,
    pode_lancar_em_vinculo,
    requer_permissao,
)
from app.utils.paginacao import paginar
from app.utils.permissoes import Permissao


def _ano_letivo_id() -> int | None:
    ano = getattr(g, "ano_letivo", None)
    return ano.id if ano else None


def _garantir_acesso_vinculo(vinculo) -> None:
    """Valida o escopo: o professor so acessa as proprias turmas."""
    if not pode_acessar_turma(vinculo.turma_id):
        raise ErroPermissao(
            "Voce nao tem acesso ao diario desta turma."
        )


def _garantir_lancamento(vinculo) -> None:
    """Valida quem pode escrever no diario (nao apenas visualizar)."""
    if not pode_lancar_em_vinculo(vinculo):
        raise ErroPermissao(
            "Apenas o professor titular da disciplina (ou a direcao) pode "
            "lancar no diario de classe."
        )


# ---------------------------------------------------------------------------
# Indice: escolha da disciplina
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@requer_permissao(Permissao.FREQUENCIA_VISUALIZAR)
def index():
    """Lista as disciplinas cujo diario o usuario pode acessar."""
    if current_user.e_professor:
        vinculos = frequencia_service.vinculos_do_professor(
            current_user.professor, _ano_letivo_id()
        )
    else:
        vinculos = frequencia_service.todos_os_vinculos(_ano_letivo_id())

    return render_template("frequencia/index.html", vinculos=vinculos)


@bp.route("/pendentes")
@login_required
@requer_permissao(Permissao.FREQUENCIA_VISUALIZAR)
def pendentes():
    """Aulas registradas cuja chamada ainda nao foi lancada."""
    consulta = frequencia_service.aulas_pendentes(_ano_letivo_id())

    # Professor ve apenas as proprias pendencias.
    if current_user.e_professor and current_user.professor:
        ids = [
            v.id
            for v in frequencia_service.vinculos_do_professor(
                current_user.professor, _ano_letivo_id()
            )
        ]
        from app.models.frequencia import Aula

        consulta = consulta.filter(Aula.turma_disciplina_id.in_(ids or [0]))

    return render_template("frequencia/pendentes.html", pagina=paginar(consulta))


# ---------------------------------------------------------------------------
# Diario de uma disciplina
# ---------------------------------------------------------------------------
@bp.route("/diario/<int:vinculo_id>", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.FREQUENCIA_VISUALIZAR)
def diario(vinculo_id: int):
    """Diario de classe: registro de aulas de uma disciplina."""
    vinculo = frequencia_service.buscar_vinculo(vinculo_id)
    _garantir_acesso_vinculo(vinculo)

    form = AulaForm()
    pode_lancar = pode_lancar_em_vinculo(vinculo)

    if pode_lancar and form.validate_on_submit():
        try:
            aula = frequencia_service.registrar_aula(
                vinculo,
                data_aula=form.data_aula.data,
                conteudo=form.conteudo.data,
                quantidade_aulas=form.quantidade_aulas.data or 1,
                tarefa_casa=form.tarefa_casa.data,
                observacoes=form.observacoes.data,
                usuario_id=current_user.id,
            )
        except ErroDominio as erro:
            flash(erro.mensagem, "danger")
        else:
            flash(
                "Aula registrada. Faca a chamada para concluir o lancamento.",
                "success",
            )
            return redirect(url_for("frequencia.chamada", aula_id=aula.id))

    return render_template(
        "frequencia/diario.html",
        vinculo=vinculo,
        form=form,
        pode_lancar=pode_lancar,
        pagina=paginar(frequencia_service.aulas_do_vinculo(vinculo.id)),
    )


# ---------------------------------------------------------------------------
# Chamada
# ---------------------------------------------------------------------------
@bp.route("/chamada/<int:aula_id>", methods=["GET", "POST"])
@login_required
@requer_permissao(Permissao.FREQUENCIA_VISUALIZAR)
def chamada(aula_id: int):
    """Registro de presenca dos alunos em uma aula."""
    aula = frequencia_service.buscar_aula(aula_id)
    vinculo = aula.turma_disciplina
    _garantir_acesso_vinculo(vinculo)

    pode_lancar = pode_lancar_em_vinculo(vinculo)

    if request.method == "POST":
        _garantir_lancamento(vinculo)

        situacoes, justificativas = _extrair_chamada(request.form)

        try:
            total = frequencia_service.salvar_chamada(
                aula,
                situacoes=situacoes,
                justificativas=justificativas,
                usuario_id=current_user.id,
            )
        except ErroDominio as erro:
            flash(erro.mensagem, "danger")
        else:
            flash(f"Chamada registrada para {total} aluno(s).", "success")
            return redirect(url_for("frequencia.diario", vinculo_id=vinculo.id))

    return render_template(
        "frequencia/chamada.html",
        aula=aula,
        vinculo=vinculo,
        linhas=frequencia_service.preparar_chamada(aula),
        pode_lancar=pode_lancar,
    )


def _extrair_chamada(dados) -> tuple[dict[int, str], dict[int, str]]:
    """Le os campos ``situacao_<id>`` e ``justificativa_<id>`` do formulario.

    Ids invalidos sao descartados aqui; o service ainda revalida contra a
    lista real de matriculas da turma, garantindo que um POST manipulado
    nao altere a frequencia de outra turma.
    """
    situacoes: dict[int, str] = {}
    justificativas: dict[int, str] = {}

    for chave, valor in dados.items():
        if chave.startswith("situacao_"):
            sufixo = chave.removeprefix("situacao_")
            if sufixo.isdigit():
                situacoes[int(sufixo)] = valor
        elif chave.startswith("justificativa_"):
            sufixo = chave.removeprefix("justificativa_")
            if sufixo.isdigit():
                justificativas[int(sufixo)] = valor

    return situacoes, justificativas


@bp.route("/aula/<int:aula_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.FREQUENCIA_LANCAR)
def excluir_aula(aula_id: int):
    """Exclui uma aula e as frequencias associadas."""
    aula = frequencia_service.buscar_aula(aula_id)
    vinculo = aula.turma_disciplina
    _garantir_lancamento(vinculo)

    try:
        frequencia_service.excluir_aula(aula)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Aula excluida do diario.", "success")

    return redirect(url_for("frequencia.diario", vinculo_id=vinculo.id))


# ---------------------------------------------------------------------------
# Justificativa de falta
# ---------------------------------------------------------------------------
@bp.route("/falta/<int:frequencia_id>/justificar", methods=["POST"])
@login_required
@requer_permissao(Permissao.FREQUENCIA_JUSTIFICAR)
def justificar(frequencia_id: int):
    """Converte uma falta em falta justificada."""
    registro = db.session.get(Frequencia, frequencia_id)
    if registro is None:
        raise RegistroNaoEncontrado("Registro de frequencia nao encontrado.")

    form = JustificarFaltaForm()
    if not form.validate_on_submit():
        flash("Informe o motivo da justificativa.", "danger")
        return redirect(request.referrer or url_for("frequencia.index"))

    try:
        frequencia_service.justificar_falta(registro, form.motivo.data)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Falta justificada.", "success")

    return redirect(request.referrer or url_for("frequencia.index"))


# ---------------------------------------------------------------------------
# Consulta por aluno
# ---------------------------------------------------------------------------
@bp.route("/aluno/<int:aluno_id>")
@login_required
@requer_permissao(Permissao.FREQUENCIA_VISUALIZAR)
@exigir_acesso_aluno()
def do_aluno(aluno_id: int):
    """Frequencia de um aluno, consolidada e por disciplina."""
    aluno = aluno_service.buscar(aluno_id)
    matricula = aluno.matricula_atual

    if matricula is None:
        return render_template(
            "frequencia/aluno.html", aluno=aluno, matricula=None,
            resumo=None, disciplinas=[],
        )

    return render_template(
        "frequencia/aluno.html",
        aluno=aluno,
        matricula=matricula,
        resumo=frequencia_service.apurar_frequencia(matricula.id),
        disciplinas=frequencia_service.resumo_por_disciplina(matricula.id),
        form_justificativa=JustificarFaltaForm(),
    )


@bp.route("/minha-frequencia")
@login_required
@requer_permissao(Permissao.FREQUENCIA_VISUALIZAR)
def minha_frequencia():
    """Atalho do aluno ou responsavel para a propria frequencia."""
    if current_user.e_aluno and current_user.aluno:
        return redirect(url_for("frequencia.do_aluno", aluno_id=current_user.aluno.id))

    if current_user.e_responsavel and current_user.responsavel:
        alunos = current_user.responsavel.alunos
        if len(alunos) == 1:
            return redirect(url_for("frequencia.do_aluno", aluno_id=alunos[0].id))
        return render_template("frequencia/escolher_aluno.html", alunos=alunos)

    return redirect(url_for("frequencia.index"))
