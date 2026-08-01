"""Regras de negocio das configuracoes do sistema.

Reune a manutencao dos dados institucionais e da estrutura de apoio (anos
letivos, periodos, series, salas e tempos de aula) — tudo aquilo que a
escola precisa configurar uma vez e revisar a cada ano.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.enums import SituacaoAnoLetivo
from app.models.estrutura import AnoLetivo, PeriodoLetivo, Sala, Serie, Turma
from app.models.horario import TempoAula
from app.models.sistema import ConfiguracaoEscola
from app.services import auditoria_service
from app.services.excecoes import (
    ErroConflito,
    ErroOperacaoBanco,
    ErroRegraNegocio,
    RegistroNaoEncontrado,
)


# ---------------------------------------------------------------------------
# Dados da escola
# ---------------------------------------------------------------------------
def obter_escola() -> ConfiguracaoEscola:
    return ConfiguracaoEscola.obter()


def atualizar_escola(dados: dict[str, Any]) -> ConfiguracaoEscola:
    """Atualiza os dados institucionais."""
    escola = obter_escola()

    antes = escola.para_dicionario()
    escola.atualizar_campos(**dados)
    alteracoes = auditoria_service.calcular_alteracoes(antes, escola.para_dicionario())
    if not alteracoes:
        return escola

    _confirmar("Falha ao salvar dados da escola")
    auditoria_service.registrar_atualizacao(
        "ConfiguracaoEscola", escola.id, "Dados da escola atualizados", alteracoes
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return escola


# ---------------------------------------------------------------------------
# Ano letivo
# ---------------------------------------------------------------------------
def listar_anos() -> list[AnoLetivo]:
    return db.session.query(AnoLetivo).order_by(AnoLetivo.ano.desc()).all()


def buscar_ano(ano_id: int | str | None) -> AnoLetivo:
    ano = AnoLetivo.buscar_por_id(ano_id)
    if ano is None:
        raise RegistroNaoEncontrado("Ano letivo nao encontrado.")
    return ano


def criar_ano_letivo(dados: dict[str, Any], criar_periodos: bool = True) -> AnoLetivo:
    """Cria um ano letivo e, opcionalmente, os periodos padrao."""
    ano_numero = dados.get("ano")
    if db.session.query(AnoLetivo).filter(AnoLetivo.ano == ano_numero).first():
        raise ErroConflito(f"O ano letivo de {ano_numero} ja esta cadastrado.")

    ano = AnoLetivo()
    ano.atualizar_campos(**dados)

    db.session.add(ano)
    db.session.flush()

    if criar_periodos:
        _criar_periodos_padrao(ano)

    if ano.corrente:
        _definir_corrente(ano)

    _confirmar("Falha ao criar ano letivo")

    auditoria_service.registrar_criacao(
        "AnoLetivo", ano.id, f"Ano letivo criado: {ano.ano}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return ano


def _criar_periodos_padrao(ano: AnoLetivo) -> None:
    """Divide o ano letivo em periodos conforme a configuracao da escola."""
    quantidade = obter_escola().quantidade_periodos or 4
    rotulo = {4: "Bimestre", 3: "Trimestre", 2: "Semestre"}.get(quantidade, "Periodo")

    total_dias = (ano.data_fim - ano.data_inicio).days
    duracao = max(1, total_dias // quantidade)

    for ordem in range(1, quantidade + 1):
        inicio = ano.data_inicio + timedelta(days=duracao * (ordem - 1))
        # O ultimo periodo vai ate o fim do ano letivo, absorvendo o resto da
        # divisao — assim nenhum dia letivo fica fora de um periodo.
        fim = (
            ano.data_fim
            if ordem == quantidade
            else ano.data_inicio + timedelta(days=duracao * ordem - 1)
        )

        db.session.add(
            PeriodoLetivo(
                ano_letivo_id=ano.id,
                nome=f"{ordem}o {rotulo}",
                ordem=ordem,
                data_inicio=inicio,
                data_fim=fim,
            )
        )


def atualizar_ano_letivo(ano: AnoLetivo, dados: dict[str, Any]) -> AnoLetivo:
    """Atualiza um ano letivo existente."""
    novo_numero = dados.get("ano")
    if novo_numero and novo_numero != ano.ano:
        existente = (
            db.session.query(AnoLetivo)
            .filter(AnoLetivo.ano == novo_numero, AnoLetivo.id != ano.id)
            .first()
        )
        if existente:
            raise ErroConflito(f"O ano letivo de {novo_numero} ja esta cadastrado.")

    antes = ano.para_dicionario()
    ano.atualizar_campos(**dados)

    if ano.corrente:
        _definir_corrente(ano)

    alteracoes = auditoria_service.calcular_alteracoes(antes, ano.para_dicionario())
    if not alteracoes:
        return ano

    _confirmar("Falha ao atualizar ano letivo")
    auditoria_service.registrar_atualizacao(
        "AnoLetivo", ano.id, f"Ano letivo atualizado: {ano.ano}", alteracoes
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return ano


def definir_como_corrente(ano: AnoLetivo) -> AnoLetivo:
    """Marca o ano como corrente, desmarcando os demais."""
    _definir_corrente(ano)
    ano.corrente = True
    if ano.situacao is SituacaoAnoLetivo.PLANEJAMENTO:
        ano.situacao = SituacaoAnoLetivo.EM_ANDAMENTO

    _confirmar("Falha ao definir ano corrente")

    auditoria_service.registrar_atualizacao(
        "AnoLetivo", ano.id, f"Ano letivo {ano.ano} definido como corrente"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return ano


def _definir_corrente(ano: AnoLetivo) -> None:
    """Garante que apenas um ano letivo esteja marcado como corrente."""
    db.session.query(AnoLetivo).filter(AnoLetivo.id != ano.id).update(
        {"corrente": False}, synchronize_session=False
    )


def encerrar_ano_letivo(ano: AnoLetivo) -> AnoLetivo:
    """Encerra o ano letivo, bloqueando novos lancamentos.

    Depois disso, notas e frequencia daquele ano tornam-se somente leitura —
    o que protege o historico escolar ja emitido.
    """
    if ano.situacao is SituacaoAnoLetivo.ENCERRADO:
        raise ErroRegraNegocio("Este ano letivo ja esta encerrado.")

    ano.situacao = SituacaoAnoLetivo.ENCERRADO
    ano.corrente = False
    for periodo in ano.periodos:
        periodo.encerrado = True

    _confirmar("Falha ao encerrar ano letivo")

    auditoria_service.registrar_atualizacao(
        "AnoLetivo",
        ano.id,
        f"Ano letivo {ano.ano} encerrado. Lancamentos bloqueados.",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return ano


def excluir_ano_letivo(ano: AnoLetivo) -> None:
    """Exclui um ano letivo sem turmas vinculadas."""
    turmas = (
        db.session.query(Turma).filter(Turma.ano_letivo_id == ano.id).count()
    )
    if turmas:
        raise ErroRegraNegocio(
            f"Este ano letivo possui {turmas} turma(s) vinculada(s) e nao "
            "pode ser excluido."
        )

    numero = ano.ano
    identificador = ano.id
    db.session.delete(ano)
    _confirmar("Falha ao excluir ano letivo")

    auditoria_service.registrar_exclusao(
        "AnoLetivo", identificador, f"Ano letivo excluido: {numero}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


# ---------------------------------------------------------------------------
# Periodos
# ---------------------------------------------------------------------------
def alternar_periodo(periodo: PeriodoLetivo) -> PeriodoLetivo:
    """Abre ou encerra um periodo para lancamento de notas."""
    periodo.encerrado = not periodo.encerrado
    _confirmar("Falha ao alterar o periodo")

    auditoria_service.registrar_atualizacao(
        "PeriodoLetivo",
        periodo.id,
        f"Periodo {periodo.nome} {'encerrado' if periodo.encerrado else 'reaberto'}",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return periodo


# ---------------------------------------------------------------------------
# Series
# ---------------------------------------------------------------------------
def listar_series() -> list[Serie]:
    return db.session.query(Serie).order_by(Serie.ordem, Serie.nome).all()


def salvar_serie(dados: dict[str, Any], serie: Serie | None = None) -> Serie:
    """Cria ou atualiza uma serie."""
    novo = serie is None
    serie = serie or Serie()
    serie.atualizar_campos(**dados)

    if novo:
        db.session.add(serie)

    _confirmar("Falha ao salvar serie")

    if novo:
        auditoria_service.registrar_criacao(
            "Serie", serie.id, f"Serie criada: {serie.nome}"
        )
    else:
        auditoria_service.registrar_atualizacao(
            "Serie", serie.id, f"Serie atualizada: {serie.nome}"
        )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return serie


def excluir_serie(serie: Serie) -> None:
    """Exclui uma serie sem turmas vinculadas."""
    turmas = db.session.query(Turma).filter(Turma.serie_id == serie.id).count()
    if turmas:
        raise ErroRegraNegocio(
            f"Esta serie possui {turmas} turma(s) vinculada(s). "
            "Desative-a em vez de excluir."
        )

    nome = serie.nome
    identificador = serie.id
    db.session.delete(serie)
    _confirmar("Falha ao excluir serie")

    auditoria_service.registrar_exclusao(
        "Serie", identificador, f"Serie excluida: {nome}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


# ---------------------------------------------------------------------------
# Salas
# ---------------------------------------------------------------------------
def listar_salas() -> list[Sala]:
    return db.session.query(Sala).order_by(Sala.nome).all()


def salvar_sala(dados: dict[str, Any], sala: Sala | None = None) -> Sala:
    novo = sala is None
    sala = sala or Sala()
    sala.atualizar_campos(**dados)

    if novo:
        db.session.add(sala)

    _confirmar("Falha ao salvar sala")

    if novo:
        auditoria_service.registrar_criacao("Sala", sala.id, f"Sala criada: {sala.nome}")
    else:
        auditoria_service.registrar_atualizacao(
            "Sala", sala.id, f"Sala atualizada: {sala.nome}"
        )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return sala


def excluir_sala(sala: Sala) -> None:
    turmas = db.session.query(Turma).filter(Turma.sala_id == sala.id).count()
    if turmas:
        raise ErroRegraNegocio(
            f"Esta sala esta alocada em {turmas} turma(s). Desative-a em vez "
            "de excluir."
        )

    nome = sala.nome
    identificador = sala.id
    db.session.delete(sala)
    _confirmar("Falha ao excluir sala")

    auditoria_service.registrar_exclusao(
        "Sala", identificador, f"Sala excluida: {nome}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


# ---------------------------------------------------------------------------
# Tempos de aula
# ---------------------------------------------------------------------------
def listar_tempos() -> list[TempoAula]:
    return (
        db.session.query(TempoAula)
        .order_by(TempoAula.turno, TempoAula.ordem)
        .all()
    )


def salvar_tempo(dados: dict[str, Any], tempo: TempoAula | None = None) -> TempoAula:
    """Cria ou atualiza um tempo de aula."""
    dados = dict(dados)
    dados["hora_inicio"] = _para_hora(dados.get("hora_inicio"))
    dados["hora_fim"] = _para_hora(dados.get("hora_fim"))

    if dados["hora_fim"] <= dados["hora_inicio"]:
        raise ErroRegraNegocio("O termino deve ser posterior ao inicio.")

    novo = tempo is None
    tempo = tempo or TempoAula()
    tempo.atualizar_campos(**dados)

    if novo:
        db.session.add(tempo)

    _confirmar("Falha ao salvar tempo de aula")

    if novo:
        auditoria_service.registrar_criacao(
            "TempoAula", tempo.id, f"Tempo de aula criado: {tempo}"
        )
    else:
        auditoria_service.registrar_atualizacao(
            "TempoAula", tempo.id, f"Tempo de aula atualizado: {tempo}"
        )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return tempo


def _para_hora(valor) -> time:
    """Converte ``"07:30"`` em :class:`datetime.time`."""
    if isinstance(valor, time):
        return valor
    if not valor:
        raise ErroRegraNegocio("Informe o horario no formato HH:MM.")
    try:
        return datetime.strptime(str(valor)[:5], "%H:%M").time()
    except ValueError as erro:
        raise ErroRegraNegocio(
            f"Horario invalido: '{valor}'. Use o formato HH:MM."
        ) from erro


def excluir_tempo(tempo: TempoAula) -> None:
    """Exclui um tempo de aula sem horarios alocados."""
    from app.models.horario import Horario

    alocados = (
        db.session.query(Horario).filter(Horario.tempo_aula_id == tempo.id).count()
    )
    if alocados:
        raise ErroRegraNegocio(
            f"Este tempo de aula possui {alocados} alocacao(oes) na grade. "
            "Desative-o em vez de excluir."
        )

    descricao = str(tempo)
    identificador = tempo.id
    db.session.delete(tempo)
    _confirmar("Falha ao excluir tempo de aula")

    auditoria_service.registrar_exclusao(
        "TempoAula", identificador, f"Tempo de aula excluido: {descricao}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


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
                "Ja existe um registro com estes dados."
            ) from erro
    except Exception as erro:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error("%s: %s", mensagem, erro)
        if propagar:
            raise ErroOperacaoBanco() from erro
