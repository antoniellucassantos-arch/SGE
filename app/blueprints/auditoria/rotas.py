"""Rotas de consulta a trilha de auditoria.

Somente leitura por definicao: uma trilha que pode ser alterada nao serve
como evidencia. Nao existe rota de edicao nem de exclusao individual.
"""

from __future__ import annotations

from datetime import datetime

from flask import render_template, request

from app.blueprints.auditoria import bp
from app.extensions import db
from app.models.enums import AcaoAuditoria
from app.models.sistema import LogAuditoria
from app.models.usuario import Usuario
from app.services import auditoria_service
from app.utils.decoradores import requer_permissao
from app.utils.paginacao import obter_pagina, obter_por_pagina, parametros_preservados
from app.utils.permissoes import Permissao


def _para_data(valor: str | None) -> datetime | None:
    """Converte ``YYYY-MM-DD`` da querystring em ``datetime``."""
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d")
    except ValueError:
        return None


@bp.route("/")
@requer_permissao(Permissao.AUDITORIA_VISUALIZAR)
def listar():
    """Lista os eventos registrados, com filtros por usuario, acao e periodo."""
    usuario_id = request.args.get("usuario_id", "")
    acao = request.args.get("acao", "")
    entidade = request.args.get("entidade", "")

    data_inicio = _para_data(request.args.get("data_inicio"))
    data_fim = _para_data(request.args.get("data_fim"))
    if data_fim:
        # Inclui o dia inteiro escolhido pelo usuario, nao apenas 00:00.
        data_fim = data_fim.replace(hour=23, minute=59, second=59)

    pagina = auditoria_service.listar(
        pagina=obter_pagina(),
        por_pagina=obter_por_pagina(50),
        usuario_id=int(usuario_id) if usuario_id.isdigit() else None,
        acao=acao or None,
        entidade=entidade or None,
        data_inicio=data_inicio,
        data_fim=data_fim,
    )

    # Entidades presentes na trilha, para alimentar o filtro sem hardcode.
    entidades = [
        linha[0]
        for linha in db.session.query(LogAuditoria.entidade)
        .filter(LogAuditoria.entidade.isnot(None))
        .distinct()
        .order_by(LogAuditoria.entidade)
        .all()
    ]

    usuarios = (
        db.session.query(Usuario)
        .filter(Usuario.excluido_em.is_(None))
        .order_by(Usuario.nome_normalizado)
        .all()
    )

    return render_template(
        "auditoria/listar.html",
        pagina=pagina,
        acoes=list(AcaoAuditoria),
        entidades=entidades,
        usuarios=usuarios,
        filtros={
            "usuario_id": usuario_id,
            "acao": acao,
            "entidade": entidade,
            "data_inicio": request.args.get("data_inicio", ""),
            "data_fim": request.args.get("data_fim", ""),
        },
        parametros=parametros_preservados(),
    )


@bp.route("/<int:log_id>")
@requer_permissao(Permissao.AUDITORIA_VISUALIZAR)
def detalhe(log_id: int):
    """Detalhe de um evento, com o JSON de alteracoes formatado."""
    from app.services.excecoes import RegistroNaoEncontrado

    registro = db.session.get(LogAuditoria, log_id)
    if registro is None:
        raise RegistroNaoEncontrado("Registro de auditoria nao encontrado.")

    detalhes = None
    if registro.detalhes:
        import json

        try:
            detalhes = json.loads(registro.detalhes)
        except (ValueError, TypeError):
            detalhes = {"conteudo": registro.detalhes}

    return render_template(
        "auditoria/detalhe.html", registro=registro, detalhes=detalhes
    )
