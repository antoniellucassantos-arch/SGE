"""Regras de negocio de matriculas.

A matricula e o ato que liga o aluno a uma turma em um ano letivo. Todas as
regras criticas da escola passam por aqui: capacidade da turma, duplicidade
no ano, transferencia entre turmas e preservacao do historico.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.enums import (
    ResultadoFinal,
    SituacaoAnoLetivo,
    SituacaoCadastro,
    SituacaoMatricula,
)
from app.models.estrutura import AnoLetivo, Turma
from app.models.matricula import Matricula
from app.models.pessoas import Aluno
from app.services import auditoria_service
from app.services.excecoes import (
    ErroConflito,
    ErroOperacaoBanco,
    ErroRegraNegocio,
    RegistroNaoEncontrado,
)


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------
def consulta_base():
    return db.session.query(Matricula).filter(Matricula.excluido_em.is_(None))


def buscar(matricula_id: int | str | None) -> Matricula:
    matricula = Matricula.buscar_por_id(matricula_id)
    if matricula is None or matricula.esta_excluido:
        raise RegistroNaoEncontrado("Matricula nao encontrada.")
    return matricula


def listar(
    termo: str | None = None,
    ano_letivo_id: int | None = None,
    turma_id: int | None = None,
    situacao: str | None = None,
):
    """Consulta de listagem de matriculas com os filtros da tela."""
    consulta = consulta_base().join(Aluno, Matricula.aluno_id == Aluno.id)

    if termo:
        from app.utils.seguranca import remover_acentos

        alvo = f"%{remover_acentos(termo)}%"
        consulta = consulta.filter(
            db.or_(
                Aluno.nome_normalizado.like(alvo),
                Aluno.codigo.like(f"%{termo}%"),
                Matricula.numero.like(f"%{termo}%"),
            )
        )

    if ano_letivo_id:
        consulta = consulta.filter(Matricula.ano_letivo_id == ano_letivo_id)
    if turma_id:
        consulta = consulta.filter(Matricula.turma_id == turma_id)
    if situacao:
        consulta = consulta.filter(Matricula.situacao == situacao)

    return consulta


def matricula_ativa_do_aluno(
    aluno_id: int, ano_letivo_id: int
) -> Matricula | None:
    """Matricula ativa do aluno em um ano letivo especifico."""
    return (
        consulta_base()
        .filter(
            Matricula.aluno_id == aluno_id,
            Matricula.ano_letivo_id == ano_letivo_id,
            Matricula.situacao.in_(
                [SituacaoMatricula.ATIVA, SituacaoMatricula.TRANCADA]
            ),
        )
        .first()
    )


# ---------------------------------------------------------------------------
# Validacoes
# ---------------------------------------------------------------------------
def _validar_ano_letivo(ano_letivo: AnoLetivo) -> None:
    """Impede lancamentos em ano letivo encerrado."""
    if ano_letivo.situacao is SituacaoAnoLetivo.ENCERRADO:
        raise ErroRegraNegocio(
            f"O ano letivo de {ano_letivo.ano} esta encerrado e nao aceita "
            "novas matriculas."
        )


def _validar_aluno(aluno: Aluno) -> None:
    if aluno.esta_excluido:
        raise RegistroNaoEncontrado("Aluno nao encontrado.")

    if aluno.situacao in (
        SituacaoCadastro.TRANSFERIDO,
        SituacaoCadastro.DESLIGADO,
    ):
        raise ErroRegraNegocio(
            f"O aluno esta com situacao '{aluno.situacao.rotulo}'. "
            "Reative o cadastro antes de matricular."
        )


def _validar_turma(turma: Turma, ano_letivo_id: int) -> None:
    """Valida turma ativa, do ano correto e com vaga disponivel."""
    if turma.esta_excluido or not turma.ativa:
        raise ErroRegraNegocio("Esta turma esta inativa e nao aceita matriculas.")

    if turma.ano_letivo_id != ano_letivo_id:
        raise ErroRegraNegocio(
            "A turma selecionada pertence a outro ano letivo."
        )

    if turma.esta_lotada:
        raise ErroRegraNegocio(
            f"A turma {turma.nome_completo} atingiu a capacidade maxima "
            f"({turma.capacidade} alunos). Escolha outra turma ou amplie a "
            "capacidade."
        )


def _validar_duplicidade(aluno_id: int, ano_letivo_id: int) -> None:
    """Impede duas matriculas simultaneas do mesmo aluno no mesmo ano."""
    existente = matricula_ativa_do_aluno(aluno_id, ano_letivo_id)
    if existente:
        turma = existente.turma.nome_completo if existente.turma else "?"
        raise ErroConflito(
            f"Este aluno ja possui matricula {existente.situacao.rotulo.lower()} "
            f"neste ano letivo (turma {turma}, matricula {existente.numero}). "
            "Use a transferencia para move-lo de turma."
        )


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------
def matricular(
    aluno_id: int,
    turma_id: int,
    ano_letivo_id: int,
    data_matricula: date | None = None,
    escola_origem: str | None = None,
    observacoes: str | None = None,
) -> Matricula:
    """Matricula um aluno em uma turma.

    Todas as validacoes acontecem antes de qualquer escrita, para que uma
    tentativa invalida nunca deixe registro parcial no banco.
    """
    aluno = db.session.get(Aluno, aluno_id)
    if aluno is None:
        raise RegistroNaoEncontrado("Aluno nao encontrado.")

    turma = db.session.get(Turma, turma_id)
    if turma is None:
        raise RegistroNaoEncontrado("Turma nao encontrada.")

    ano_letivo = db.session.get(AnoLetivo, ano_letivo_id)
    if ano_letivo is None:
        raise RegistroNaoEncontrado("Ano letivo nao encontrado.")

    _validar_aluno(aluno)
    _validar_ano_letivo(ano_letivo)
    _validar_turma(turma, ano_letivo_id)
    _validar_duplicidade(aluno_id, ano_letivo_id)

    matricula = Matricula(
        numero=Matricula.gerar_numero(ano_letivo.ano),
        aluno_id=aluno.id,
        turma_id=turma.id,
        ano_letivo_id=ano_letivo.id,
        data_matricula=data_matricula or date.today(),
        situacao=SituacaoMatricula.ATIVA,
        resultado_final=ResultadoFinal.CURSANDO,
        escola_origem=escola_origem or None,
        observacoes=observacoes or None,
    )

    db.session.add(matricula)

    # Aluno matriculado volta a situacao ativa automaticamente: e o efeito
    # que a secretaria espera ao rematricular um aluno transferido.
    if aluno.situacao is not SituacaoCadastro.ATIVO:
        aluno.situacao = SituacaoCadastro.ATIVO

    _confirmar("Falha ao registrar matricula")

    auditoria_service.registrar_criacao(
        "Matricula",
        matricula.id,
        f"Matricula {matricula.numero}: {aluno.nome_completo} em "
        f"{turma.nome_completo}",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return matricula


def transferir_turma(
    matricula: Matricula, nova_turma_id: int, motivo: str | None = None
) -> Matricula:
    """Move o aluno para outra turma preservando notas e frequencia.

    A mesma matricula e mantida (e nao encerrada e recriada), de modo que o
    historico de lancamentos do ano acompanha o aluno na nova turma.
    """
    if matricula.situacao is not SituacaoMatricula.ATIVA:
        raise ErroRegraNegocio(
            "Somente matriculas ativas podem ser transferidas de turma."
        )

    nova_turma = db.session.get(Turma, nova_turma_id)
    if nova_turma is None:
        raise RegistroNaoEncontrado("Turma de destino nao encontrada.")

    if nova_turma.id == matricula.turma_id:
        raise ErroRegraNegocio("O aluno ja esta matriculado nesta turma.")

    _validar_turma(nova_turma, matricula.ano_letivo_id)

    turma_anterior = (
        matricula.turma.nome_completo if matricula.turma else "?"
    )
    matricula.turma_id = nova_turma.id
    if motivo:
        matricula.observacoes = (
            f"{matricula.observacoes or ''}\n"
            f"[{date.today():%d/%m/%Y}] Transferido de {turma_anterior} "
            f"para {nova_turma.nome_completo}: {motivo}"
        ).strip()

    _confirmar("Falha ao transferir turma")

    auditoria_service.registrar_atualizacao(
        "Matricula",
        matricula.id,
        f"Matricula {matricula.numero} transferida de {turma_anterior} "
        f"para {nova_turma.nome_completo}",
        {"turma": {"de": turma_anterior, "para": nova_turma.nome_completo}},
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return matricula


def transferir_escola(
    matricula: Matricula, escola_destino: str, motivo: str | None = None
) -> Matricula:
    """Encerra a matricula por transferencia para outra escola."""
    if matricula.situacao.e_encerrada:
        raise ErroRegraNegocio(
            f"Esta matricula ja esta {matricula.situacao.rotulo.lower()}."
        )

    matricula.transferir(escola_destino, motivo)

    # O aluno sai do quadro ativo, mas o cadastro e todo o historico
    # permanecem para emissao de documentos.
    if matricula.aluno:
        matricula.aluno.situacao = SituacaoCadastro.TRANSFERIDO

    _confirmar("Falha ao transferir aluno")

    auditoria_service.registrar_atualizacao(
        "Matricula",
        matricula.id,
        f"Matricula {matricula.numero} transferida para {escola_destino}",
        {"escola_destino": escola_destino, "motivo": motivo},
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return matricula


def cancelar(matricula: Matricula, motivo: str | None = None) -> Matricula:
    """Cancela a matricula (desistencia, evasao, cancelamento)."""
    if matricula.situacao.e_encerrada:
        raise ErroRegraNegocio(
            f"Esta matricula ja esta {matricula.situacao.rotulo.lower()}."
        )

    matricula.cancelar(motivo)
    if matricula.aluno:
        matricula.aluno.situacao = SituacaoCadastro.INATIVO

    _confirmar("Falha ao cancelar matricula")

    auditoria_service.registrar_atualizacao(
        "Matricula",
        matricula.id,
        f"Matricula {matricula.numero} cancelada",
        {"motivo": motivo},
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return matricula


def trancar(matricula: Matricula, motivo: str | None = None) -> Matricula:
    """Tranca temporariamente a matricula, mantendo a vaga do aluno."""
    if matricula.situacao is not SituacaoMatricula.ATIVA:
        raise ErroRegraNegocio("Somente matriculas ativas podem ser trancadas.")

    matricula.trancar(motivo)
    _confirmar("Falha ao trancar matricula")

    auditoria_service.registrar_atualizacao(
        "Matricula", matricula.id, f"Matricula {matricula.numero} trancada",
        {"motivo": motivo},
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return matricula


def reativar(matricula: Matricula) -> Matricula:
    """Reativa uma matricula trancada ou cancelada."""
    if matricula.situacao is SituacaoMatricula.ATIVA:
        raise ErroRegraNegocio("Esta matricula ja esta ativa.")

    if matricula.turma:
        _validar_turma(matricula.turma, matricula.ano_letivo_id)

    matricula.reativar()
    if matricula.aluno:
        matricula.aluno.situacao = SituacaoCadastro.ATIVO

    _confirmar("Falha ao reativar matricula")

    auditoria_service.registrar_atualizacao(
        "Matricula", matricula.id, f"Matricula {matricula.numero} reativada"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return matricula


def atualizar(matricula: Matricula, dados: dict[str, Any]) -> Matricula:
    """Atualiza campos editaveis da matricula (datas, observacoes)."""
    antes = matricula.para_dicionario()
    matricula.atualizar_campos(**dados)
    alteracoes = auditoria_service.calcular_alteracoes(
        antes, matricula.para_dicionario()
    )
    if not alteracoes:
        return matricula

    _confirmar("Falha ao atualizar matricula")
    auditoria_service.registrar_atualizacao(
        "Matricula", matricula.id,
        f"Matricula {matricula.numero} atualizada", alteracoes,
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return matricula


# ---------------------------------------------------------------------------
# Apoio as telas
# ---------------------------------------------------------------------------
def alunos_sem_matricula(ano_letivo_id: int) -> list[Aluno]:
    """Alunos aptos a matricula no ano letivo informado."""
    ja_matriculados = db.session.query(Matricula.aluno_id).filter(
        Matricula.ano_letivo_id == ano_letivo_id,
        Matricula.situacao.in_(
            [SituacaoMatricula.ATIVA, SituacaoMatricula.TRANCADA]
        ),
        Matricula.excluido_em.is_(None),
    )

    return (
        db.session.query(Aluno)
        .filter(
            Aluno.excluido_em.is_(None),
            Aluno.situacao != SituacaoCadastro.DESLIGADO,
            Aluno.id.notin_(ja_matriculados),
        )
        .order_by(Aluno.nome_normalizado)
        .all()
    )


def turmas_com_vaga(ano_letivo_id: int) -> list[Turma]:
    """Turmas ativas do ano letivo, com indicacao de lotacao.

    Turmas lotadas continuam na lista (marcadas na interface) para que a
    secretaria saiba que elas existem e possa ampliar a capacidade.
    """
    return (
        db.session.query(Turma)
        .filter(
            Turma.ano_letivo_id == ano_letivo_id,
            Turma.ativa.is_(True),
            Turma.excluido_em.is_(None),
        )
        .join(Turma.serie)
        .order_by(Turma.nome)
        .all()
    )


def estatisticas(ano_letivo_id: int | None = None) -> dict[str, int]:
    """Contagem de matriculas por situacao, para os cartoes da listagem."""
    consulta = db.session.query(
        Matricula.situacao, func.count(Matricula.id)
    ).filter(Matricula.excluido_em.is_(None))

    if ano_letivo_id:
        consulta = consulta.filter(Matricula.ano_letivo_id == ano_letivo_id)

    resultado = {situacao.value: 0 for situacao in SituacaoMatricula}
    for situacao, total in consulta.group_by(Matricula.situacao).all():
        chave = situacao.value if hasattr(situacao, "value") else str(situacao)
        resultado[chave] = total

    resultado["total"] = sum(resultado.values())
    return resultado


# ---------------------------------------------------------------------------
def _confirmar(mensagem: str, propagar: bool = True) -> None:
    from flask import current_app

    try:
        db.session.commit()
    except IntegrityError as erro:
        db.session.rollback()
        current_app.logger.warning("%s (integridade): %s", mensagem, erro)
        if propagar:
            raise ErroConflito(
                "Ja existe uma matricula com estes dados."
            ) from erro
    except Exception as erro:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error("%s: %s", mensagem, erro)
        if propagar:
            raise ErroOperacaoBanco() from erro
