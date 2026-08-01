"""Regras de negocio de avisos e comunicados."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.base import agora_utc
from app.models.comunicacao import Aviso, AvisoLeitura
from app.models.enums import PublicoAviso
from app.services import auditoria_service
from app.services.excecoes import (
    ErroConflito,
    ErroOperacaoBanco,
    ErroPermissao,
    ErroValidacao,
    RegistroNaoEncontrado,
)


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------
def consulta_base():
    return db.session.query(Aviso).filter(Aviso.excluido_em.is_(None))


def buscar(aviso_id: int | str | None) -> Aviso:
    aviso = Aviso.buscar_por_id(aviso_id)
    if aviso is None or aviso.esta_excluido:
        raise RegistroNaoEncontrado("Aviso nao encontrado.")
    return aviso


def listar(
    termo: str | None = None,
    publico: str | None = None,
    somente_vigentes: bool = False,
):
    """Consulta de listagem administrativa de avisos."""
    consulta = consulta_base()

    if termo:
        alvo = f"%{termo.lower()}%"
        consulta = consulta.filter(
            or_(
                db.func.lower(Aviso.titulo).like(alvo),
                db.func.lower(Aviso.mensagem).like(alvo),
            )
        )

    if publico:
        consulta = consulta.filter(Aviso.publico == publico)

    if somente_vigentes:
        hoje = date.today()
        consulta = consulta.filter(
            Aviso.publicado.is_(True),
            Aviso.data_inicio <= hoje,
            or_(Aviso.data_fim.is_(None), Aviso.data_fim >= hoje),
        )

    return consulta.order_by(Aviso.fixado.desc(), Aviso.criado_em.desc())


def listar_para_usuario(usuario, limite: int | None = None) -> list[Aviso]:
    """Avisos vigentes destinados a um usuario especifico.

    A segmentacao final (turma do aluno, filhos do responsavel) e feita em
    Python porque depende de vinculos que nao cabem em uma unica clausula
    SQL portavel entre SQLite e PostgreSQL. O conjunto candidato ja vem
    filtrado e ordenado pelo banco.
    """
    candidatos = listar(somente_vigentes=True).limit((limite or 50) * 4).all()
    destinados = [aviso for aviso in candidatos if aviso.destinado_a(usuario)]
    return destinados[:limite] if limite else destinados


def nao_lidos_do_usuario(usuario) -> set[int]:
    """Ids de avisos destinados ao usuario que ele ainda nao leu."""
    lidos = {
        linha[0]
        for linha in db.session.query(AvisoLeitura.aviso_id)
        .filter(
            AvisoLeitura.usuario_id == usuario.id,
            AvisoLeitura.lido_em.isnot(None),
        )
        .all()
    }
    return {a.id for a in listar_para_usuario(usuario) if a.id not in lidos}


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------
def criar(dados: dict[str, Any], autor_id: int | None = None) -> Aviso:
    """Publica um novo aviso."""
    _validar(dados)

    aviso = Aviso()
    aviso.atualizar_campos(**dados)
    aviso.autor_id = autor_id

    db.session.add(aviso)
    _confirmar("Falha ao criar aviso")

    auditoria_service.registrar_criacao(
        "Aviso", aviso.id, f"Aviso publicado: {aviso.titulo}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return aviso


def atualizar(aviso: Aviso, dados: dict[str, Any]) -> Aviso:
    """Atualiza um aviso existente."""
    _validar(dados)

    antes = aviso.para_dicionario()
    aviso.atualizar_campos(**dados)
    alteracoes = auditoria_service.calcular_alteracoes(antes, aviso.para_dicionario())
    if not alteracoes:
        return aviso

    _confirmar("Falha ao atualizar aviso")
    auditoria_service.registrar_atualizacao(
        "Aviso", aviso.id, f"Aviso atualizado: {aviso.titulo}", alteracoes
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return aviso


def excluir(aviso: Aviso, usuario_id: int | None = None) -> None:
    """Exclui logicamente o aviso, preservando o registro de leituras."""
    aviso.excluir(usuario_id)
    aviso.publicado = False
    _confirmar("Falha ao excluir aviso")

    auditoria_service.registrar_exclusao(
        "Aviso", aviso.id, f"Aviso excluido: {aviso.titulo}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


def _validar(dados: dict[str, Any]) -> None:
    """Valida coerencia entre publico-alvo e vigencia."""
    publico = dados.get("publico")
    if publico == PublicoAviso.TURMA.value and not dados.get("turma_id"):
        raise ErroValidacao(
            "Selecione a turma de destino.",
            erros_por_campo={"turma_id": ["Obrigatorio para avisos de turma."]},
        )

    inicio = dados.get("data_inicio")
    fim = dados.get("data_fim")
    if inicio and fim and fim < inicio:
        raise ErroValidacao(
            "A data final nao pode ser anterior a data inicial.",
            erros_por_campo={"data_fim": ["Data final invalida."]},
        )

    # Turma so faz sentido quando o publico e uma turma especifica.
    if publico != PublicoAviso.TURMA.value:
        dados["turma_id"] = None


def marcar_como_lido(aviso: Aviso, usuario) -> AvisoLeitura:
    """Registra a leitura do aviso por um usuario.

    Idempotente: reabrir o aviso nao cria linhas duplicadas nem altera o
    carimbo da primeira leitura.
    """
    if not aviso.destinado_a(usuario):
        raise ErroPermissao("Este aviso nao e destinado a voce.")

    leitura = (
        db.session.query(AvisoLeitura)
        .filter(
            AvisoLeitura.aviso_id == aviso.id,
            AvisoLeitura.usuario_id == usuario.id,
        )
        .first()
    )

    if leitura is None:
        leitura = AvisoLeitura(
            aviso_id=aviso.id, usuario_id=usuario.id, lido_em=agora_utc()
        )
        db.session.add(leitura)
        _confirmar("Falha ao registrar leitura", propagar=False)
    elif leitura.lido_em is None:
        leitura.lido_em = agora_utc()
        _confirmar("Falha ao registrar leitura", propagar=False)

    return leitura


def leitores(aviso: Aviso) -> list[AvisoLeitura]:
    """Quem leu o aviso, do mais recente para o mais antigo."""
    return (
        db.session.query(AvisoLeitura)
        .filter(
            AvisoLeitura.aviso_id == aviso.id,
            AvisoLeitura.lido_em.isnot(None),
        )
        .order_by(AvisoLeitura.lido_em.desc())
        .all()
    )


# ---------------------------------------------------------------------------
def _confirmar(mensagem: str, propagar: bool = True) -> None:
    from flask import current_app

    try:
        db.session.commit()
    except IntegrityError as erro:
        db.session.rollback()
        current_app.logger.warning("%s (integridade): %s", mensagem, erro)
        if propagar:
            raise ErroConflito("Registro duplicado.") from erro
    except Exception as erro:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error("%s: %s", mensagem, erro)
        if propagar:
            raise ErroOperacaoBanco() from erro
