"""Rotas de emissao e consulta de boletins."""

from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.blueprints.boletim import bp
from app.services import (
    aluno_service,
    auditoria_service,
    nota_service,
    turma_service,
)
from app.services.excecoes import ErroDominio
from app.utils.decoradores import (
    exigir_acesso_aluno,
    exigir_acesso_turma,
    requer_permissao,
)
from app.utils.permissoes import Permissao


def _ano_letivo_id() -> int | None:
    ano = getattr(g, "ano_letivo", None)
    return ano.id if ano else None


# ---------------------------------------------------------------------------
# Indice
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@requer_permissao(Permissao.BOLETIM_VISUALIZAR)
def index():
    """Lista as turmas para emissao de boletins."""
    if not current_user.e_equipe_interna:
        return redirect(url_for("boletim.meu_boletim"))

    turmas = turma_service.listar_turmas(
        ano_letivo_id=_ano_letivo_id(), somente_ativas=True
    ).all()

    return render_template("boletim/index.html", turmas=turmas)


# ---------------------------------------------------------------------------
# Boletim individual
# ---------------------------------------------------------------------------
@bp.route("/aluno/<int:aluno_id>")
@login_required
@requer_permissao(Permissao.BOLETIM_VISUALIZAR)
@exigir_acesso_aluno()
def do_aluno(aluno_id: int):
    """Boletim de um aluno no ano letivo corrente."""
    aluno = aluno_service.buscar(aluno_id)
    matricula = aluno.matricula_atual

    if matricula is None:
        return render_template("boletim/sem_matricula.html", aluno=aluno)

    return render_template(
        "boletim/boletim.html",
        dados=nota_service.montar_boletim(matricula),
        modo_impressao=request.args.get("impressao") == "1",
    )


@bp.route("/meu-boletim")
@login_required
@requer_permissao(Permissao.BOLETIM_VISUALIZAR)
def meu_boletim():
    """Atalho do aluno ou responsavel para o proprio boletim."""
    if current_user.e_aluno and current_user.aluno:
        return redirect(url_for("boletim.do_aluno", aluno_id=current_user.aluno.id))

    if current_user.e_responsavel and current_user.responsavel:
        alunos = current_user.responsavel.alunos
        if len(alunos) == 1:
            return redirect(url_for("boletim.do_aluno", aluno_id=alunos[0].id))
        return render_template("boletim/escolher_aluno.html", alunos=alunos)

    return redirect(url_for("boletim.index"))


# ---------------------------------------------------------------------------
# Boletim de turma
# ---------------------------------------------------------------------------
@bp.route("/turma/<int:turma_id>")
@login_required
@requer_permissao(Permissao.BOLETIM_VISUALIZAR)
@exigir_acesso_turma()
def da_turma(turma_id: int):
    """Ata de resultados: visao consolidada de toda a turma."""
    turma = turma_service.buscar_turma(turma_id)
    matriculas = turma_service.alunos_da_turma(turma)

    return render_template(
        "boletim/turma.html",
        turma=turma,
        boletins=[nota_service.montar_boletim(m) for m in matriculas],
        periodos=nota_service.periodos_do_ano(turma.ano_letivo_id),
    )


# ---------------------------------------------------------------------------
# Exportacao em PDF
# ---------------------------------------------------------------------------
@bp.route("/aluno/<int:aluno_id>/pdf")
@login_required
@requer_permissao(Permissao.BOLETIM_EMITIR)
@exigir_acesso_aluno()
def pdf_aluno(aluno_id: int):
    """Gera o boletim do aluno em PDF."""
    from app.services import pdf_service

    aluno = aluno_service.buscar(aluno_id)
    matricula = aluno.matricula_atual

    if matricula is None:
        flash("O aluno nao possui matricula ativa para emissao do boletim.", "warning")
        return redirect(url_for("alunos.detalhe", aluno_id=aluno_id))

    try:
        arquivo = pdf_service.gerar_boletim(nota_service.montar_boletim(matricula))
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("boletim.do_aluno", aluno_id=aluno_id))

    auditoria_service.registrar_exportacao("Boletim", "PDF", 1)

    from app.extensions import db

    db.session.commit()

    return pdf_service.responder_pdf(
        arquivo, f"boletim_{aluno.codigo}_{matricula.ano_letivo.ano}.pdf"
    )


@bp.route("/turma/<int:turma_id>/pdf")
@login_required
@requer_permissao(Permissao.BOLETIM_EMITIR)
@exigir_acesso_turma()
def pdf_turma(turma_id: int):
    """Gera os boletins de toda a turma em um unico PDF."""
    from app.services import pdf_service

    turma = turma_service.buscar_turma(turma_id)
    matriculas = turma_service.alunos_da_turma(turma)

    if not matriculas:
        flash("Esta turma nao possui alunos matriculados.", "warning")
        return redirect(url_for("turmas.detalhe", turma_id=turma_id))

    boletins = [nota_service.montar_boletim(m) for m in matriculas]

    try:
        arquivo = pdf_service.gerar_boletins_turma(turma, boletins)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("boletim.da_turma", turma_id=turma_id))

    auditoria_service.registrar_exportacao("Boletins da turma", "PDF", len(boletins))

    from app.extensions import db

    db.session.commit()

    nome = f"boletins_{turma.identificacao_curta.replace(' ', '_')}.pdf"
    return pdf_service.responder_pdf(arquivo, nome)
