"""Rotas de relatorios e exportacoes."""

from __future__ import annotations

from flask import flash, g, redirect, render_template, request, url_for
from flask_login import login_required

from app.blueprints.relatorios import bp
from app.services import (
    auditoria_service,
    pdf_service,
    relatorio_service,
    turma_service,
)
from app.services.excecoes import ErroDominio
from app.utils.decoradores import requer_permissao
from app.utils.permissoes import Permissao, usuario_tem_permissao


def _ano_letivo_id() -> int | None:
    ano = getattr(g, "ano_letivo", None)
    return ano.id if ano else None


def _filtros_da_url() -> dict:
    """Le os filtros aceitos pelos relatorios a partir da querystring."""
    ano = request.args.get("ano_letivo_id", "")
    turma = request.args.get("turma_id", "")

    return {
        "ano_letivo_id": int(ano) if ano.isdigit() else _ano_letivo_id(),
        "turma_id": int(turma) if turma.isdigit() else None,
        "situacao": request.args.get("situacao") or None,
    }


@bp.route("/")
@login_required
@requer_permissao(
    Permissao.RELATORIO_ACADEMICO, Permissao.RELATORIO_ADMINISTRATIVO
)
def index():
    """Catalogo de relatorios disponiveis ao usuario."""
    from flask_login import current_user

    disponiveis = {
        chave: dados
        for chave, dados in relatorio_service.RELATORIOS.items()
        if usuario_tem_permissao(current_user, dados["permissao"])
    }

    return render_template("relatorios/index.html", relatorios=disponiveis)


@bp.route("/<chave>")
@login_required
@requer_permissao(
    Permissao.RELATORIO_ACADEMICO, Permissao.RELATORIO_ADMINISTRATIVO
)
def visualizar(chave: str):
    """Exibe um relatorio em tela."""
    from flask_login import current_user

    definicao = relatorio_service.RELATORIOS.get(chave)
    if definicao is None:
        flash("Relatorio nao encontrado.", "danger")
        return redirect(url_for("relatorios.index"))

    if not usuario_tem_permissao(current_user, definicao["permissao"]):
        flash("Voce nao tem permissao para acessar este relatorio.", "danger")
        return redirect(url_for("relatorios.index"))

    filtros = _filtros_da_url()

    try:
        dados = relatorio_service.gerar_dados(chave, **filtros)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("relatorios.index"))

    return render_template(
        "relatorios/visualizar.html",
        chave=chave,
        definicao=definicao,
        dados=dados,
        filtros=filtros,
        anos=turma_service.anos_letivos(),
        turmas=turma_service.listar_turmas(
            ano_letivo_id=filtros["ano_letivo_id"], somente_ativas=True
        ).all(),
    )


@bp.route("/<chave>/excel")
@login_required
@requer_permissao(Permissao.RELATORIO_EXPORTAR)
def exportar_excel(chave: str):
    """Exporta o relatorio em planilha Excel."""
    dados = relatorio_service.gerar_dados(chave, **_filtros_da_url())

    auditoria_service.registrar_exportacao(
        dados["titulo"], "Excel", len(dados["linhas"])
    )
    from app.extensions import db

    db.session.commit()

    buffer = relatorio_service.gerar_excel(dados)
    return relatorio_service.responder_excel(buffer, f"relatorio_{chave}.xlsx")


@bp.route("/<chave>/pdf")
@login_required
@requer_permissao(Permissao.RELATORIO_EXPORTAR)
def exportar_pdf(chave: str):
    """Exporta o relatorio em PDF."""
    dados = relatorio_service.gerar_dados(chave, **_filtros_da_url())

    try:
        buffer = pdf_service.gerar_listagem(
            titulo=dados["titulo"],
            cabecalhos=dados["cabecalhos"],
            linhas=dados["linhas"],
            orientacao_paisagem=dados.get("paisagem", False),
            observacao=dados.get("observacao"),
        )
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("relatorios.visualizar", chave=chave))

    auditoria_service.registrar_exportacao(
        dados["titulo"], "PDF", len(dados["linhas"])
    )
    from app.extensions import db

    db.session.commit()

    return pdf_service.responder_pdf(buffer, f"relatorio_{chave}.pdf")


# ---------------------------------------------------------------------------
# Atalhos usados por outras telas
# ---------------------------------------------------------------------------
@bp.route("/exportar/alunos")
@login_required
@requer_permissao(Permissao.RELATORIO_EXPORTAR)
def exportar_alunos():
    """Exporta a listagem de alunos com os filtros da tela de alunos."""
    return redirect(url_for("relatorios.exportar_excel", chave="alunos", **request.args))


@bp.route("/frequencia")
@login_required
@requer_permissao(Permissao.RELATORIO_ACADEMICO)
def frequencia():
    """Atalho para o relatorio de frequencia em risco."""
    return redirect(url_for("relatorios.visualizar", chave="frequencia"))
