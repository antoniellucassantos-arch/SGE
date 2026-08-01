"""Rotas da grade de horarios."""

from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.horarios import bp
from app.extensions import db
from app.models.estrutura import Sala
from app.models.horario import Horario
from app.services import horario_service, turma_service
from app.services.excecoes import ErroDominio, RegistroNaoEncontrado
from app.utils.decoradores import exigir_acesso_turma, requer_permissao
from app.utils.permissoes import Permissao, usuario_tem_permissao


def _ano_letivo_id() -> int | None:
    ano = getattr(g, "ano_letivo", None)
    return ano.id if ano else None


# ---------------------------------------------------------------------------
# Indice
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@requer_permissao(Permissao.HORARIO_VISUALIZAR)
def index():
    """Lista as turmas para consulta e montagem da grade."""
    if not current_user.e_equipe_interna or current_user.e_professor:
        return redirect(url_for("horarios.meu_horario"))

    turmas = turma_service.listar_turmas(
        ano_letivo_id=_ano_letivo_id(), somente_ativas=True
    ).all()

    return render_template("horarios/index.html", turmas=turmas)


# ---------------------------------------------------------------------------
# Grade da turma
# ---------------------------------------------------------------------------
@bp.route("/turma/<int:turma_id>")
@login_required
@requer_permissao(Permissao.HORARIO_VISUALIZAR)
@exigir_acesso_turma()
def da_turma(turma_id: int):
    """Grade semanal de uma turma."""
    turma = turma_service.buscar_turma(turma_id)

    tempos = horario_service.tempos_do_turno(turma.turno)
    grade = horario_service.montar_grade(
        horario_service.horarios_da_turma(turma.id), tempos
    )

    salas = (
        db.session.query(Sala)
        .filter(Sala.ativa.is_(True))
        .order_by(Sala.nome)
        .all()
    )

    return render_template(
        "horarios/turma.html",
        turma=turma,
        grade=grade,
        salas=salas,
        resumo=horario_service.resumo_carga_horaria(turma),
        livres=horario_service.horarios_livres(turma),
        pode_editar=usuario_tem_permissao(current_user, Permissao.HORARIO_GERENCIAR),
    )


@bp.route("/turma/<int:turma_id>/alocar", methods=["POST"])
@login_required
@requer_permissao(Permissao.HORARIO_GERENCIAR)
def alocar(turma_id: int):
    """Aloca uma disciplina em um espaco da grade."""
    turma = turma_service.buscar_turma(turma_id)

    vinculo_id = request.form.get("turma_disciplina_id", "")
    tempo_id = request.form.get("tempo_aula_id", "")
    dia = request.form.get("dia_semana", "")
    sala_id = request.form.get("sala_id", "")

    if not (vinculo_id.isdigit() and tempo_id.isdigit() and dia):
        flash("Selecione a disciplina, o dia e o tempo de aula.", "danger")
        return redirect(url_for("horarios.da_turma", turma_id=turma_id))

    try:
        horario_service.alocar(
            turma,
            turma_disciplina_id=int(vinculo_id),
            dia_semana=dia,
            tempo_aula_id=int(tempo_id),
            sala_id=int(sala_id) if sala_id.isdigit() else None,
        )
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Disciplina alocada na grade.", "success")

    return redirect(url_for("horarios.da_turma", turma_id=turma_id))


@bp.route("/<int:horario_id>/remover", methods=["POST"])
@login_required
@requer_permissao(Permissao.HORARIO_GERENCIAR)
def remover(horario_id: int):
    """Libera um espaco da grade."""
    horario = db.session.get(Horario, horario_id)
    if horario is None:
        raise RegistroNaoEncontrado("Horario nao encontrado.")

    turma_id = horario.turma_id

    try:
        horario_service.remover(horario)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash("Horario removido da grade.", "success")

    return redirect(url_for("horarios.da_turma", turma_id=turma_id))


@bp.route("/turma/<int:turma_id>/limpar", methods=["POST"])
@login_required
@requer_permissao(Permissao.HORARIO_GERENCIAR)
def limpar(turma_id: int):
    """Remove toda a grade da turma."""
    turma = turma_service.buscar_turma(turma_id)

    try:
        total = horario_service.limpar_grade(turma)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(f"{total} alocacao(oes) removida(s) da grade.", "success")

    return redirect(url_for("horarios.da_turma", turma_id=turma_id))


# ---------------------------------------------------------------------------
# Grade pessoal
# ---------------------------------------------------------------------------
@bp.route("/meu-horario")
@login_required
@requer_permissao(Permissao.HORARIO_VISUALIZAR)
def meu_horario():
    """Grade do professor, do aluno ou dos filhos do responsavel."""
    if current_user.e_professor and current_user.professor:
        horarios = horario_service.horarios_do_professor(
            current_user.professor.id, _ano_letivo_id()
        )
        # O professor pode lecionar em turnos diferentes; usamos todos os
        # tempos presentes na propria grade dele.
        tempos = sorted(
            {h.tempo_aula for h in horarios if h.tempo_aula},
            key=lambda t: (t.turno.value, t.ordem),
        )
        return render_template(
            "horarios/pessoal.html",
            titulo="Meus horarios",
            grade=horario_service.montar_grade(horarios, tempos),
            mostrar_turma=True,
        )

    turma = None
    if current_user.e_aluno and current_user.aluno:
        turma = current_user.aluno.turma_atual
    elif current_user.e_responsavel and current_user.responsavel:
        alunos = current_user.responsavel.alunos
        if len(alunos) == 1:
            turma = alunos[0].turma_atual
        elif alunos:
            return render_template("horarios/escolher_aluno.html", alunos=alunos)

    if turma is None:
        return render_template(
            "horarios/pessoal.html",
            titulo="Meus horarios",
            grade={"tempos": [], "dias": [], "matriz": {}},
            mostrar_turma=False,
        )

    tempos = horario_service.tempos_do_turno(turma.turno)
    return render_template(
        "horarios/pessoal.html",
        titulo=f"Horarios - {turma.identificacao_curta}",
        grade=horario_service.montar_grade(
            horario_service.horarios_da_turma(turma.id), tempos
        ),
        mostrar_turma=False,
        turma=turma,
    )


@bp.route("/aluno/<int:aluno_id>")
@login_required
@requer_permissao(Permissao.HORARIO_VISUALIZAR)
def do_aluno(aluno_id: int):
    """Grade da turma de um aluno especifico."""
    from app.services import aluno_service
    from app.utils.decoradores import pode_acessar_aluno

    if not pode_acessar_aluno(aluno_id):
        from app.services.excecoes import ErroPermissao

        raise ErroPermissao("Voce nao tem acesso aos dados deste aluno.")

    aluno = aluno_service.buscar(aluno_id)
    turma = aluno.turma_atual

    if turma is None:
        return render_template(
            "horarios/pessoal.html",
            titulo=f"Horarios - {aluno.nome_exibicao}",
            grade={"tempos": [], "dias": [], "matriz": {}},
            mostrar_turma=False,
        )

    return redirect(url_for("horarios.da_turma", turma_id=turma.id))
