"""Regras de negocio de turmas, disciplinas e atribuicao de professores."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.enums import SituacaoMatricula
from app.models.estrutura import (
    AnoLetivo,
    Disciplina,
    Serie,
    Turma,
    TurmaDisciplina,
)
from app.models.matricula import Matricula
from app.models.pessoas import Professor
from app.services import auditoria_service
from app.services.excecoes import (
    ErroConflito,
    ErroOperacaoBanco,
    ErroRegraNegocio,
    RegistroNaoEncontrado,
)
from app.utils.seguranca import remover_acentos


# ===========================================================================
# Turmas
# ===========================================================================
def consulta_turmas():
    return db.session.query(Turma).filter(Turma.excluido_em.is_(None))


def buscar_turma(turma_id: int | str | None) -> Turma:
    turma = Turma.buscar_por_id(turma_id)
    if turma is None or turma.esta_excluido:
        raise RegistroNaoEncontrado("Turma nao encontrada.")
    return turma


def listar_turmas(
    termo: str | None = None,
    ano_letivo_id: int | None = None,
    serie_id: int | None = None,
    turno: str | None = None,
    somente_ativas: bool = False,
):
    """Consulta de listagem de turmas com os filtros da tela."""
    consulta = consulta_turmas().join(Serie, Turma.serie_id == Serie.id)

    if termo:
        alvo = f"%{remover_acentos(termo)}%"
        consulta = consulta.filter(
            or_(
                func.lower(Turma.nome).like(f"%{termo.lower()}%"),
                func.lower(Serie.nome).like(alvo),
            )
        )

    if ano_letivo_id:
        consulta = consulta.filter(Turma.ano_letivo_id == ano_letivo_id)
    if serie_id:
        consulta = consulta.filter(Turma.serie_id == serie_id)
    if turno:
        consulta = consulta.filter(Turma.turno == turno)
    if somente_ativas:
        consulta = consulta.filter(Turma.ativa.is_(True))

    return consulta


def criar_turma(dados: dict[str, Any]) -> Turma:
    """Cria uma turma validando a unicidade dentro do ano letivo."""
    _validar_turma_unica(
        dados.get("ano_letivo_id"), dados.get("serie_id"), dados.get("nome")
    )

    turma = Turma()
    turma.atualizar_campos(**dados)

    db.session.add(turma)
    _confirmar("Falha ao criar turma")

    auditoria_service.registrar_criacao(
        "Turma", turma.id, f"Turma criada: {turma.nome_completo}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return turma


def atualizar_turma(turma: Turma, dados: dict[str, Any]) -> Turma:
    """Atualiza a turma verificando o impacto sobre as matriculas ativas."""
    _validar_turma_unica(
        dados.get("ano_letivo_id", turma.ano_letivo_id),
        dados.get("serie_id", turma.serie_id),
        dados.get("nome", turma.nome),
        turma_id=turma.id,
    )

    nova_capacidade = dados.get("capacidade")
    if nova_capacidade:
        matriculados = turma.contar_matriculas_ativas()
        if int(nova_capacidade) < matriculados:
            raise ErroRegraNegocio(
                f"A turma ja possui {matriculados} aluno(s) matriculado(s). "
                f"A capacidade nao pode ser menor que esse numero."
            )

    antes = turma.para_dicionario()
    turma.atualizar_campos(**dados)
    alteracoes = auditoria_service.calcular_alteracoes(
        antes, turma.para_dicionario()
    )
    if not alteracoes:
        return turma

    _confirmar("Falha ao atualizar turma")
    auditoria_service.registrar_atualizacao(
        "Turma", turma.id, f"Turma atualizada: {turma.nome_completo}", alteracoes
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return turma


def excluir_turma(turma: Turma, usuario_id: int | None = None) -> None:
    """Exclui logicamente a turma, desde que nao haja matricula ativa."""
    matriculados = turma.contar_matriculas_ativas()
    if matriculados:
        raise ErroRegraNegocio(
            f"Esta turma possui {matriculados} aluno(s) matriculado(s). "
            "Transfira ou cancele as matriculas antes de excluir a turma."
        )

    turma.excluir(usuario_id)
    turma.ativa = False
    _confirmar("Falha ao excluir turma")

    auditoria_service.registrar_exclusao(
        "Turma", turma.id, f"Turma excluida: {turma.nome_completo}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


def _validar_turma_unica(
    ano_letivo_id: int | None,
    serie_id: int | None,
    nome: str | None,
    turma_id: int | None = None,
) -> None:
    """Impede duas turmas com o mesmo nome, serie e ano letivo."""
    if not (ano_letivo_id and serie_id and nome):
        return

    consulta = consulta_turmas().filter(
        Turma.ano_letivo_id == ano_letivo_id,
        Turma.serie_id == serie_id,
        func.upper(Turma.nome) == str(nome).strip().upper(),
    )
    if turma_id:
        consulta = consulta.filter(Turma.id != turma_id)

    if consulta.first():
        raise ErroConflito(
            f"Ja existe uma turma '{nome}' para esta serie neste ano letivo."
        )


def alunos_da_turma(turma: Turma) -> list[Matricula]:
    """Matriculas ativas da turma, em ordem alfabetica (lista de chamada)."""
    from app.models.pessoas import Aluno

    return (
        db.session.query(Matricula)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .filter(
            Matricula.turma_id == turma.id,
            Matricula.situacao == SituacaoMatricula.ATIVA,
            Matricula.excluido_em.is_(None),
        )
        .order_by(Aluno.nome_normalizado)
        .all()
    )


# ===========================================================================
# Disciplinas
# ===========================================================================
def consulta_disciplinas():
    return db.session.query(Disciplina).filter(Disciplina.excluido_em.is_(None))


def buscar_disciplina(disciplina_id: int | str | None) -> Disciplina:
    disciplina = Disciplina.buscar_por_id(disciplina_id)
    if disciplina is None or disciplina.esta_excluido:
        raise RegistroNaoEncontrado("Disciplina nao encontrada.")
    return disciplina


def listar_disciplinas(termo: str | None = None, somente_ativas: bool = False):
    consulta = consulta_disciplinas()

    if termo:
        alvo = f"%{remover_acentos(termo)}%"
        consulta = consulta.filter(
            or_(
                Disciplina.nome_normalizado.like(alvo),
                func.upper(Disciplina.codigo).like(f"%{termo.upper()}%"),
            )
        )

    if somente_ativas:
        consulta = consulta.filter(Disciplina.ativa.is_(True))

    return consulta


def criar_disciplina(dados: dict[str, Any]) -> Disciplina:
    _validar_codigo_disciplina(dados.get("codigo"))

    disciplina = Disciplina()
    disciplina.atualizar_campos(**dados)

    db.session.add(disciplina)
    _confirmar("Falha ao criar disciplina")

    auditoria_service.registrar_criacao(
        "Disciplina",
        disciplina.id,
        f"Disciplina criada: {disciplina.nome} ({disciplina.codigo})",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return disciplina


def atualizar_disciplina(disciplina: Disciplina, dados: dict[str, Any]) -> Disciplina:
    _validar_codigo_disciplina(dados.get("codigo"), disciplina_id=disciplina.id)

    antes = disciplina.para_dicionario()
    disciplina.atualizar_campos(**dados)
    alteracoes = auditoria_service.calcular_alteracoes(
        antes, disciplina.para_dicionario()
    )
    if not alteracoes:
        return disciplina

    _confirmar("Falha ao atualizar disciplina")
    auditoria_service.registrar_atualizacao(
        "Disciplina", disciplina.id, f"Disciplina atualizada: {disciplina.nome}",
        alteracoes,
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return disciplina


def excluir_disciplina(disciplina: Disciplina, usuario_id: int | None = None) -> None:
    """Exclui a disciplina apenas se ela nao estiver em uso em nenhuma turma."""
    vinculos = (
        db.session.query(func.count(TurmaDisciplina.id))
        .filter(TurmaDisciplina.disciplina_id == disciplina.id)
        .scalar()
        or 0
    )
    if vinculos:
        raise ErroRegraNegocio(
            f"Esta disciplina esta vinculada a {vinculos} turma(s). "
            "Remova os vinculos antes de excluir, ou apenas desative-a."
        )

    disciplina.excluir(usuario_id)
    disciplina.ativa = False
    _confirmar("Falha ao excluir disciplina")

    auditoria_service.registrar_exclusao(
        "Disciplina", disciplina.id, f"Disciplina excluida: {disciplina.nome}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


def _validar_codigo_disciplina(
    codigo: str | None, disciplina_id: int | None = None
) -> None:
    if not codigo:
        return

    consulta = consulta_disciplinas().filter(
        func.upper(Disciplina.codigo) == codigo.strip().upper()
    )
    if disciplina_id:
        consulta = consulta.filter(Disciplina.id != disciplina_id)

    existente = consulta.first()
    if existente:
        raise ErroConflito(
            f"O codigo '{codigo}' ja e usado pela disciplina {existente.nome}."
        )


# ===========================================================================
# Grade: turma x disciplina x professor
# ===========================================================================
def atribuir_disciplina(
    turma: Turma,
    disciplina_id: int,
    professor_id: int | None = None,
    carga_horaria_semanal: int = 2,
) -> TurmaDisciplina:
    """Vincula uma disciplina a turma, opcionalmente com um professor."""
    disciplina = buscar_disciplina(disciplina_id)

    vinculo = (
        db.session.query(TurmaDisciplina)
        .filter(
            TurmaDisciplina.turma_id == turma.id,
            TurmaDisciplina.disciplina_id == disciplina.id,
        )
        .first()
    )
    if vinculo:
        raise ErroConflito(
            f"A disciplina {disciplina.nome} ja esta atribuida a esta turma."
        )

    if professor_id:
        _validar_professor(professor_id)

    vinculo = TurmaDisciplina(
        turma_id=turma.id,
        disciplina_id=disciplina.id,
        professor_id=professor_id or None,
        carga_horaria_semanal=max(1, int(carga_horaria_semanal or 1)),
        ativa=True,
    )
    db.session.add(vinculo)
    _confirmar("Falha ao atribuir disciplina")

    auditoria_service.registrar_criacao(
        "TurmaDisciplina",
        vinculo.id,
        f"Disciplina {disciplina.nome} atribuida a turma {turma.nome_completo}",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return vinculo


def atualizar_vinculo(
    vinculo: TurmaDisciplina,
    professor_id: int | None,
    carga_horaria_semanal: int,
    ativa: bool = True,
) -> TurmaDisciplina:
    """Altera professor, carga horaria ou situacao de um vinculo."""
    if professor_id:
        _validar_professor(professor_id)

    antes = vinculo.para_dicionario()
    vinculo.professor_id = professor_id or None
    vinculo.carga_horaria_semanal = max(1, int(carga_horaria_semanal or 1))
    vinculo.ativa = bool(ativa)

    alteracoes = auditoria_service.calcular_alteracoes(
        antes, vinculo.para_dicionario()
    )
    if not alteracoes:
        return vinculo

    _confirmar("Falha ao atualizar vinculo")
    auditoria_service.registrar_atualizacao(
        "TurmaDisciplina", vinculo.id, f"Vinculo atualizado: {vinculo.descricao}",
        alteracoes,
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return vinculo


def remover_vinculo(vinculo: TurmaDisciplina) -> None:
    """Remove a atribuicao, desde que nao haja aulas ou notas lancadas.

    Remover um vinculo com lancamentos apagaria em cascata o diario de
    classe e as notas da turma inteira — perda irreversivel de dado
    academico.
    """
    from app.models.avaliacao import Avaliacao
    from app.models.frequencia import Aula

    total_aulas = (
        db.session.query(func.count(Aula.id))
        .filter(Aula.turma_disciplina_id == vinculo.id)
        .scalar()
        or 0
    )
    total_avaliacoes = (
        db.session.query(func.count(Avaliacao.id))
        .filter(Avaliacao.turma_disciplina_id == vinculo.id)
        .scalar()
        or 0
    )

    if total_aulas or total_avaliacoes:
        raise ErroRegraNegocio(
            f"Esta disciplina ja possui {total_aulas} aula(s) e "
            f"{total_avaliacoes} avaliacao(oes) registradas. "
            "Desative o vinculo em vez de remove-lo, para preservar o "
            "diario de classe e as notas."
        )

    descricao = vinculo.descricao
    identificador = vinculo.id
    db.session.delete(vinculo)
    _confirmar("Falha ao remover vinculo")

    auditoria_service.registrar_exclusao(
        "TurmaDisciplina", identificador, f"Vinculo removido: {descricao}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


def _validar_professor(professor_id: int) -> Professor:
    professor = db.session.get(Professor, professor_id)
    if professor is None or professor.esta_excluido:
        raise RegistroNaoEncontrado("Professor nao encontrado.")
    return professor


def disciplinas_disponiveis(turma: Turma) -> list[Disciplina]:
    """Disciplinas ativas que ainda nao foram atribuidas a turma."""
    ja_atribuidas = {v.disciplina_id for v in turma.turmas_disciplinas}
    consulta = consulta_disciplinas().filter(Disciplina.ativa.is_(True))
    if ja_atribuidas:
        consulta = consulta.filter(Disciplina.id.notin_(ja_atribuidas))
    return consulta.order_by(Disciplina.nome).all()


# ===========================================================================
# Series e anos letivos (apoio aos formularios)
# ===========================================================================
def series_ativas() -> list[Serie]:
    return (
        db.session.query(Serie)
        .filter(Serie.ativa.is_(True))
        .order_by(Serie.ordem, Serie.nome)
        .all()
    )


def anos_letivos() -> list[AnoLetivo]:
    return db.session.query(AnoLetivo).order_by(AnoLetivo.ano.desc()).all()


def professores_ativos() -> list[Professor]:
    from app.models.enums import SituacaoCadastro

    return (
        db.session.query(Professor)
        .filter(
            Professor.excluido_em.is_(None),
            Professor.situacao == SituacaoCadastro.ATIVO,
        )
        .order_by(Professor.nome_normalizado)
        .all()
    )


# ===========================================================================
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
