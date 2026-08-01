"""Rotas do painel principal.

O painel e uma unica rota que despacha para o template adequado ao papel do
usuario. Cada perfil enxerga indicadores diferentes, mas a URL e sempre a
mesma (``/``), o que simplifica links, favoritos e o redirecionamento pos-login.
"""

from __future__ import annotations

from flask import g, render_template
from flask_login import current_user, login_required

from app.blueprints.painel import bp
from app.services import dashboard_service


@bp.route("/")
@login_required
def index():
    """Painel principal, adaptado ao papel do usuario autenticado."""
    ano_letivo = getattr(g, "ano_letivo", None)

    if current_user.e_professor:
        return _painel_professor(ano_letivo)
    if current_user.e_aluno:
        return _painel_aluno()
    if current_user.e_responsavel:
        return _painel_responsavel()

    return _painel_administrativo(ano_letivo)


# ---------------------------------------------------------------------------
# Variantes por perfil
# ---------------------------------------------------------------------------
def _painel_administrativo(ano_letivo):
    """Visao da equipe administrativa: numeros gerais e graficos."""
    return render_template(
        "painel/administrativo.html",
        indicadores=dashboard_service.indicadores_gerais(ano_letivo),
        complementares=dashboard_service.indicadores_complementares(ano_letivo),
        grafico_series=dashboard_service.alunos_por_serie(ano_letivo),
        grafico_turnos=dashboard_service.alunos_por_turno(ano_letivo),
        grafico_matriculas=dashboard_service.matriculas_por_mes(ano_letivo),
        grafico_situacoes=dashboard_service.situacao_matriculas(ano_letivo),
        atividades=dashboard_service.atividades_recentes(),
        aniversariantes=dashboard_service.aniversariantes_do_mes(),
    )


def _painel_professor(ano_letivo):
    """Visao do professor: turmas, aulas do dia e pendencias."""
    return render_template(
        "painel/professor.html",
        dados=dashboard_service.painel_professor(current_user.professor, ano_letivo),
    )


def _painel_aluno():
    """Visao do aluno: media, frequencia e ultimas notas."""
    return render_template(
        "painel/aluno.html",
        dados=dashboard_service.painel_aluno(current_user.aluno),
    )


def _painel_responsavel():
    """Visao do responsavel: um resumo por filho."""
    return render_template(
        "painel/responsavel.html",
        filhos=dashboard_service.painel_responsavel(current_user.responsavel),
    )


# ---------------------------------------------------------------------------
# Contexto compartilhado
# ---------------------------------------------------------------------------
@bp.app_context_processor
def injetar_avisos():
    """Disponibiliza os avisos do usuario para o sino da barra superior.

    Registrado como ``app_context_processor`` (e nao ``context_processor``)
    porque a barra superior aparece em todos os templates do sistema, nao
    apenas nos deste blueprint.
    """
    if not current_user.is_authenticated:
        return {}

    try:
        recentes = dashboard_service.avisos_do_usuario(current_user, limite=5)
        nao_lidos = dashboard_service.contar_avisos_nao_lidos(current_user)
    except Exception:  # noqa: BLE001 - banco ainda nao migrado
        return {"avisos_recentes": [], "avisos_nao_lidos": 0}

    return {"avisos_recentes": recentes, "avisos_nao_lidos": nao_lidos}
