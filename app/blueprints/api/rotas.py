"""Rotas da API JSON (v1).

Todas as respostas seguem o mesmo envelope::

    {"sucesso": true, "dados": ...}
    {"sucesso": false, "erro": "mensagem"}

Um formato de resposta unico simplifica o tratamento no cliente — hoje o
JavaScript do proprio sistema, amanha o aplicativo Android.
"""

from __future__ import annotations

from flask import g, jsonify, request
from flask_login import current_user, login_required

from app.blueprints.api import bp
from app.services import dashboard_service, turma_service
from app.services.excecoes import ErroDominio
from app.utils.decoradores import pode_acessar_turma, requer_permissao
from app.utils.permissoes import Permissao


def _ok(dados) -> tuple:
    return jsonify({"sucesso": True, "dados": dados}), 200


def _erro(mensagem: str, codigo: int = 400) -> tuple:
    return jsonify({"sucesso": False, "erro": mensagem}), codigo


def _ano_letivo_id() -> int | None:
    ano = getattr(g, "ano_letivo", None)
    return ano.id if ano else None


@bp.errorhandler(ErroDominio)
def tratar_erro_dominio(erro: ErroDominio):
    """Converte excecoes de dominio em resposta JSON coerente."""
    return _erro(erro.mensagem, erro.codigo_http)


# ---------------------------------------------------------------------------
# Estado do sistema
# ---------------------------------------------------------------------------
@bp.route("/status")
def status():
    """Verificacao de disponibilidade (health check).

    Publica de proposito: e usada por monitoramento externo, que nao tem
    como autenticar. Nao expoe nenhum dado sensivel.
    """
    from app import __version__

    return _ok({"aplicacao": "SGE", "versao": __version__, "estado": "online"})


@bp.route("/sessao")
@login_required
def sessao():
    """Dados do usuario autenticado, para o cliente montar a interface."""
    return _ok(
        {
            "id": current_user.id,
            "nome": current_user.nome_completo,
            "primeiro_nome": current_user.primeiro_nome,
            "email": current_user.email,
            "papel": current_user.papel.value,
            "papel_rotulo": current_user.papel.rotulo,
            "equipe_interna": current_user.e_equipe_interna,
            "ano_letivo": getattr(g.ano_letivo, "ano", None)
            if getattr(g, "ano_letivo", None)
            else None,
        }
    )


# ---------------------------------------------------------------------------
# Dados para graficos do painel
# ---------------------------------------------------------------------------
@bp.route("/painel/indicadores")
@login_required
@requer_permissao(Permissao.DASHBOARD_ADMINISTRATIVO)
def painel_indicadores():
    """Contadores principais do painel administrativo."""
    ano = getattr(g, "ano_letivo", None)
    return _ok(
        {
            "gerais": dashboard_service.indicadores_gerais(ano),
            "complementares": dashboard_service.indicadores_complementares(ano),
        }
    )


@bp.route("/painel/graficos")
@login_required
@requer_permissao(Permissao.DASHBOARD_ADMINISTRATIVO)
def painel_graficos():
    """Series de dados dos graficos do painel."""
    ano = getattr(g, "ano_letivo", None)
    return _ok(
        {
            "alunos_por_serie": dashboard_service.alunos_por_serie(ano),
            "alunos_por_turno": dashboard_service.alunos_por_turno(ano),
            "matriculas_por_mes": dashboard_service.matriculas_por_mes(ano),
            "situacao_matriculas": dashboard_service.situacao_matriculas(ano),
        }
    )


# ---------------------------------------------------------------------------
# Consultas auxiliares usadas pelos formularios
# ---------------------------------------------------------------------------
@bp.route("/turmas")
@login_required
@requer_permissao(Permissao.TURMA_VISUALIZAR)
def turmas():
    """Turmas do ano letivo, para preencher selects dinamicamente."""
    ano_id = request.args.get("ano_letivo_id", "")
    ano_letivo_id = int(ano_id) if ano_id.isdigit() else _ano_letivo_id()

    consulta = turma_service.listar_turmas(
        ano_letivo_id=ano_letivo_id, somente_ativas=True
    )

    return _ok(
        [
            {
                "id": turma.id,
                "nome": turma.identificacao_curta,
                "nome_completo": turma.nome_completo,
                "turno": turma.turno.value,
                "vagas": turma.vagas_disponiveis,
                "lotada": turma.esta_lotada,
            }
            for turma in consulta.all()
        ]
    )


@bp.route("/turmas/<int:turma_id>/alunos")
@login_required
@requer_permissao(Permissao.ALUNO_VISUALIZAR)
def alunos_da_turma(turma_id: int):
    """Alunos matriculados em uma turma."""
    if not pode_acessar_turma(turma_id):
        return _erro("Voce nao tem acesso a esta turma.", 403)

    turma = turma_service.buscar_turma(turma_id)

    return _ok(
        [
            {
                "matricula_id": matricula.id,
                "aluno_id": matricula.aluno_id,
                "nome": matricula.nome_aluno,
                "codigo": matricula.aluno.codigo if matricula.aluno else None,
            }
            for matricula in turma_service.alunos_da_turma(turma)
        ]
    )


@bp.route("/disciplinas")
@login_required
@requer_permissao(Permissao.DISCIPLINA_VISUALIZAR)
def disciplinas():
    """Disciplinas ativas."""
    return _ok(
        [
            {
                "id": disciplina.id,
                "nome": disciplina.nome,
                "codigo": disciplina.codigo,
                "cor": disciplina.cor,
            }
            for disciplina in turma_service.listar_disciplinas(
                somente_ativas=True
            ).all()
        ]
    )


# ---------------------------------------------------------------------------
# Avisos
# ---------------------------------------------------------------------------
@bp.route("/avisos")
@login_required
def avisos():
    """Avisos vigentes destinados ao usuario autenticado."""
    from app.services import aviso_service

    itens = aviso_service.listar_para_usuario(current_user, limite=20)
    nao_lidos = aviso_service.nao_lidos_do_usuario(current_user)

    return _ok(
        {
            "nao_lidos": len(nao_lidos),
            "itens": [
                {
                    "id": aviso.id,
                    "titulo": aviso.titulo,
                    "resumo": aviso.texto_resumido,
                    "prioridade": aviso.prioridade.value,
                    "autor": aviso.nome_autor,
                    "criado_em": aviso.criado_em.isoformat(),
                    "lido": aviso.id not in nao_lidos,
                }
                for aviso in itens
            ],
        }
    )


# ---------------------------------------------------------------------------
# Nota sobre CSRF
# ---------------------------------------------------------------------------
# A protecao CSRF **permanece ativa** neste blueprint. Como todas as rotas
# atuais sao ``GET``, o Flask-WTF nao as intercepta de qualquer forma; ja
# rotas de escrita adicionadas no futuro estarao protegidas por padrao.
#
# O JavaScript do sistema envia o token em ``X-CSRFToken``
# (ver ``SGE.requisitar`` em ``static/js/sge.js``). Quando o aplicativo
# Android for construido, ele autenticara por JWT — e requisicoes com
# ``Authorization: Bearer`` nao carregam cookie, logo nao sofrem CSRF.
#
# Isentar o blueprint inteiro (``csrf.exempt(bp)``) seria mais simples,
# porem abriria as futuras rotas de escrita a requisicoes forjadas a partir
# de outro site usando a sessao da vitima.
