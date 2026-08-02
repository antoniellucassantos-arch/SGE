"""Servico de auditoria: registra quem fez o que, quando e de onde.

Decisoes de projeto
-------------------
**Falha silenciosa proposital.** Se a gravacao do log falhar, a operacao
principal do usuario nao pode ser abortada — a escola nao pode ficar sem
lancar notas porque a auditoria teve um problema. A falha e enviada ao log
da aplicacao para investigacao.

**Sessao separada para eventos negativos.** Eventos como falha de login e
acesso negado sao gravados em uma sessao propria (``commit`` imediato), pois
a transacao principal costuma sofrer ``rollback`` logo em seguida — e o
registro do incidente seria perdido junto.

**Copia do nome do usuario.** ``LogAuditoria.usuario_nome`` guarda o nome no
momento do evento, de modo que a trilha permaneca legivel mesmo apos a
exclusao ou renomeacao da conta.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from flask import current_app, has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models.base import agora_utc
from app.models.enums import AcaoAuditoria
from app.models.sistema import LogAuditoria

#: Campos que jamais podem aparecer no detalhamento da auditoria.
CAMPOS_SENSIVEIS: frozenset[str] = frozenset(
    {
        "senha",
        "senha_hash",
        "confirmar_senha",
        "senha_atual",
        "nova_senha",
        "token",
        "csrf_token",
        "secret_key",
    }
)

#: Tamanho maximo do JSON de detalhes, para nao inflar o banco.
LIMITE_DETALHES = 4000


def _contexto_requisicao() -> dict[str, str | None]:
    """Extrai IP, navegador e rota da requisicao corrente, se houver."""
    if not has_request_context():
        return {"endereco_ip": None, "navegador": None, "rota": None}

    # X-Forwarded-For so e confiavel atras de um proxy reverso configurado;
    # o ProxyFix aplicado na factory ja normaliza remote_addr nesse caso.
    return {
        "endereco_ip": (request.remote_addr or "")[:45] or None,
        "navegador": (request.user_agent.string or "")[:255] or None,
        "rota": f"{request.method} {request.path}"[:255],
    }


def _identificar_usuario() -> tuple[int | None, str | None]:
    """Descobre o usuario responsavel pelo evento em curso."""
    try:
        if current_user and getattr(current_user, "is_authenticated", False):
            return current_user.id, current_user.nome_completo
    except Exception:  # noqa: BLE001 - fora de contexto de requisicao
        pass
    return None, None


def _sanitizar(valor: Any) -> Any:
    """Remove campos sensiveis e trunca valores longos recursivamente."""
    if isinstance(valor, dict):
        # A chave nem sempre e string: detalhes indexados por id de matricula
        # chegam como int. Converter antes de comparar evita quebrar a
        # auditoria com AttributeError justamente no evento que ela deveria
        # registrar.
        return {
            str(chave): (
                "***"
                if str(chave).lower() in CAMPOS_SENSIVEIS
                else _sanitizar(item)
            )
            for chave, item in valor.items()
        }
    if isinstance(valor, (list, tuple)):
        return [_sanitizar(item) for item in valor][:50]
    if isinstance(valor, datetime):
        return valor.isoformat()
    if hasattr(valor, "value"):  # enums de dominio
        return valor.value
    if isinstance(valor, str) and len(valor) > 500:
        return valor[:500] + "..."
    return valor


def _serializar_detalhes(detalhes: dict[str, Any] | None) -> str | None:
    if not detalhes:
        return None
    try:
        texto = json.dumps(
            _sanitizar(detalhes), ensure_ascii=False, default=str, sort_keys=True
        )
    except (TypeError, ValueError):
        return None
    return texto[:LIMITE_DETALHES]


def registrar(
    acao: AcaoAuditoria,
    entidade: str | None = None,
    entidade_id: int | None = None,
    descricao: str | None = None,
    detalhes: dict[str, Any] | None = None,
    usuario_id: int | None = None,
    usuario_nome: str | None = None,
    commit_imediato: bool = False,
) -> LogAuditoria | None:
    """Grava um evento na trilha de auditoria.

    Args:
        acao: Tipo do evento.
        entidade: Nome do model afetado (ex.: ``"Aluno"``).
        entidade_id: Chave primaria do registro afetado.
        descricao: Frase curta legivel exibida na listagem.
        detalhes: Dados adicionais; campos sensiveis sao mascarados.
        usuario_id/usuario_nome: Informe explicitamente quando o evento
            ocorre fora de uma sessao autenticada (ex.: falha de login).
        commit_imediato: Grava em sessao propria, sobrevivendo a um
            ``rollback`` da transacao principal.

    Returns:
        O registro criado, ou ``None`` se a gravacao falhou.
    """
    try:
        contexto = _contexto_requisicao()

        if usuario_id is None and usuario_nome is None:
            usuario_id, usuario_nome = _identificar_usuario()

        registro = LogAuditoria(
            usuario_id=usuario_id,
            usuario_nome=(usuario_nome or "")[:150] or None,
            acao=acao,
            entidade=(entidade or "")[:60] or None,
            entidade_id=entidade_id,
            descricao=(descricao or "")[:255] or None,
            detalhes=_serializar_detalhes(detalhes),
            criado_em=agora_utc(),
            **contexto,
        )

        if commit_imediato:
            # Sessao independente: o evento sobrevive ao rollback do fluxo
            # principal, que e exatamente o caso de falha de login.
            with db.engine.connect() as conexao:
                conexao.execute(
                    LogAuditoria.__table__.insert().values(
                        usuario_id=registro.usuario_id,
                        usuario_nome=registro.usuario_nome,
                        acao=registro.acao.value,
                        entidade=registro.entidade,
                        entidade_id=registro.entidade_id,
                        descricao=registro.descricao,
                        detalhes=registro.detalhes,
                        endereco_ip=registro.endereco_ip,
                        navegador=registro.navegador,
                        rota=registro.rota,
                        criado_em=registro.criado_em,
                    )
                )
                conexao.commit()
            return registro

        db.session.add(registro)
        return registro

    except Exception as erro:  # noqa: BLE001 - auditoria nunca quebra o fluxo
        try:
            current_app.logger.error("Falha ao registrar auditoria: %s", erro)
        except Exception:  # noqa: BLE001 - sem contexto de aplicacao
            pass
        return None


# ---------------------------------------------------------------------------
# Atalhos por tipo de evento
# ---------------------------------------------------------------------------
def registrar_criacao(entidade: str, entidade_id: int, descricao: str, **detalhes):
    return registrar(
        AcaoAuditoria.CRIACAO, entidade, entidade_id, descricao, detalhes or None
    )


def registrar_atualizacao(
    entidade: str,
    entidade_id: int,
    descricao: str,
    alteracoes: dict[str, Any] | None = None,
):
    return registrar(
        AcaoAuditoria.ATUALIZACAO, entidade, entidade_id, descricao, alteracoes
    )


def registrar_exclusao(entidade: str, entidade_id: int, descricao: str, **detalhes):
    return registrar(
        AcaoAuditoria.EXCLUSAO, entidade, entidade_id, descricao, detalhes or None
    )


def registrar_login(usuario) -> None:
    registrar(
        AcaoAuditoria.LOGIN,
        entidade="Usuario",
        entidade_id=usuario.id,
        descricao=f"Login realizado por {usuario.email}",
        usuario_id=usuario.id,
        usuario_nome=usuario.nome_completo,
    )


def registrar_logout(usuario) -> None:
    registrar(
        AcaoAuditoria.LOGOUT,
        entidade="Usuario",
        entidade_id=usuario.id,
        descricao=f"Logout de {usuario.email}",
        usuario_id=usuario.id,
        usuario_nome=usuario.nome_completo,
    )


def registrar_falha_login(email: str, motivo: str, usuario_id: int | None = None):
    """Registra tentativa malsucedida em sessao propria.

    Commit imediato porque o fluxo de login normalmente termina em rollback
    ou redirect sem commit — sem isso, o incidente sumiria.
    """
    return registrar(
        AcaoAuditoria.LOGIN_FALHOU,
        entidade="Usuario",
        entidade_id=usuario_id,
        descricao=f"Falha de login para {email}: {motivo}",
        detalhes={"email": email, "motivo": motivo},
        commit_imediato=True,
    )


def registrar_acesso_negado(motivo: str):
    """Registra tentativa de acesso a recurso sem autorizacao."""
    usuario_id, usuario_nome = _identificar_usuario()
    return registrar(
        AcaoAuditoria.ACESSO_NEGADO,
        descricao=motivo[:255],
        usuario_id=usuario_id,
        usuario_nome=usuario_nome,
        commit_imediato=True,
    )


def registrar_alteracao_senha(usuario, por_recuperacao: bool = False):
    acao = (
        AcaoAuditoria.SENHA_RECUPERADA
        if por_recuperacao
        else AcaoAuditoria.SENHA_ALTERADA
    )
    return registrar(
        acao,
        entidade="Usuario",
        entidade_id=usuario.id,
        descricao=f"Senha alterada para {usuario.email}",
        usuario_id=usuario.id,
        usuario_nome=usuario.nome_completo,
    )


def registrar_exportacao(tipo: str, formato: str, quantidade: int | None = None):
    return registrar(
        AcaoAuditoria.EXPORTACAO,
        descricao=f"Exportacao de {tipo} em {formato}",
        detalhes={"tipo": tipo, "formato": formato, "quantidade": quantidade},
    )


# ---------------------------------------------------------------------------
# Comparacao de estado para o detalhamento
# ---------------------------------------------------------------------------
def calcular_alteracoes(
    antes: dict[str, Any], depois: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Compara dois snapshots e devolve apenas os campos alterados.

    Registrar o objeto inteiro a cada edicao inflaria o banco sem ganho: o
    que interessa em uma auditoria e o *delta*.
    """
    alteracoes: dict[str, dict[str, Any]] = {}

    for campo, valor_novo in depois.items():
        if campo in CAMPOS_SENSIVEIS or campo in {"atualizado_em", "criado_em"}:
            continue
        valor_antigo = antes.get(campo)
        if valor_antigo != valor_novo:
            alteracoes[campo] = {
                "de": _sanitizar(valor_antigo),
                "para": _sanitizar(valor_novo),
            }

    return alteracoes


# ---------------------------------------------------------------------------
# Consulta e manutencao
# ---------------------------------------------------------------------------
def listar(
    pagina: int = 1,
    por_pagina: int = 50,
    usuario_id: int | None = None,
    acao: AcaoAuditoria | str | None = None,
    entidade: str | None = None,
    data_inicio: datetime | None = None,
    data_fim: datetime | None = None,
):
    """Lista eventos com filtros, do mais recente para o mais antigo."""
    consulta = db.session.query(LogAuditoria)

    if usuario_id:
        consulta = consulta.filter(LogAuditoria.usuario_id == usuario_id)
    if acao:
        valor = acao.value if isinstance(acao, AcaoAuditoria) else acao
        consulta = consulta.filter(LogAuditoria.acao == valor)
    if entidade:
        consulta = consulta.filter(LogAuditoria.entidade == entidade)
    if data_inicio:
        consulta = consulta.filter(LogAuditoria.criado_em >= data_inicio)
    if data_fim:
        consulta = consulta.filter(LogAuditoria.criado_em <= data_fim)

    return consulta.order_by(LogAuditoria.criado_em.desc()).paginate(
        page=pagina, per_page=por_pagina, error_out=False
    )


def historico_da_entidade(entidade: str, entidade_id: int, limite: int = 50):
    """Linha do tempo de alteracoes de um registro especifico."""
    return (
        db.session.query(LogAuditoria)
        .filter(
            LogAuditoria.entidade == entidade,
            LogAuditoria.entidade_id == entidade_id,
        )
        .order_by(LogAuditoria.criado_em.desc())
        .limit(limite)
        .all()
    )


def limpar_antigos(dias: int = 365) -> int:
    """Remove eventos anteriores ao periodo de retencao.

    Executado apenas por rotina administrativa explicita. Retorna a
    quantidade de registros removidos.
    """
    limite = agora_utc() - timedelta(days=dias)
    removidos = (
        db.session.query(LogAuditoria)
        .filter(LogAuditoria.criado_em < limite)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    return removidos
