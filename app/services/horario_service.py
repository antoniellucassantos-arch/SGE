"""Regras de negocio da grade de horarios.

Deteccao de conflitos
---------------------
Tres conflitos sao verificados antes de gravar qualquer alocacao:

1. **Turma ocupada** — a turma ja tem outra disciplina naquele dia/tempo.
2. **Professor em duas turmas** — o mesmo docente nao pode estar em dois
   lugares ao mesmo tempo.
3. **Sala ocupada** — duas turmas nao cabem na mesma sala no mesmo horario.

O primeiro conflito tem restricao de unicidade no banco; os outros dois
dependem de consulta e sao validados aqui. Detectar na aplicacao permite
devolver uma mensagem util ("Prof. Ana ja leciona para o 9o A neste
horario") em vez de um erro de integridade opaco.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.enums import DiaSemana
from app.models.estrutura import Turma, TurmaDisciplina
from app.models.horario import Horario, TempoAula
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
def tempos_do_turno(turno) -> list[TempoAula]:
    """Tempos de aula ativos de um turno, na ordem da grade."""
    return (
        db.session.query(TempoAula)
        .filter(TempoAula.turno == turno, TempoAula.ativo.is_(True))
        .order_by(TempoAula.ordem)
        .all()
    )


def horarios_da_turma(turma_id: int) -> list[Horario]:
    return (
        db.session.query(Horario)
        .filter(Horario.turma_id == turma_id)
        .order_by(Horario.dia_semana, Horario.tempo_aula_id)
        .all()
    )


def horarios_do_professor(professor_id: int, ano_letivo_id: int | None = None):
    """Grade semanal de um professor, em todas as turmas."""
    consulta = (
        db.session.query(Horario)
        .join(TurmaDisciplina, Horario.turma_disciplina_id == TurmaDisciplina.id)
        .join(Turma, Horario.turma_id == Turma.id)
        .filter(TurmaDisciplina.professor_id == professor_id)
    )
    if ano_letivo_id:
        consulta = consulta.filter(Turma.ano_letivo_id == ano_letivo_id)

    return consulta.order_by(Horario.dia_semana, Horario.tempo_aula_id).all()


def montar_grade(horarios: list[Horario], tempos: list[TempoAula]) -> dict:
    """Organiza os horarios em uma matriz ``[tempo][dia]`` para o template.

    Devolver a matriz pronta evita que o template faca buscas aninhadas
    (``for tempo -> for dia -> for horario``), o que ficaria lento e
    ilegivel.
    """
    matriz: dict[int, dict[str, Horario]] = defaultdict(dict)

    for horario in horarios:
        matriz[horario.tempo_aula_id][horario.dia_semana.value] = horario

    return {
        "tempos": tempos,
        "dias": list(DiaSemana),
        "matriz": matriz,
    }


# ---------------------------------------------------------------------------
# Validacao de conflitos
# ---------------------------------------------------------------------------
def verificar_conflitos(
    turma_id: int,
    turma_disciplina_id: int,
    dia_semana: DiaSemana | str,
    tempo_aula_id: int,
    sala_id: int | None = None,
    horario_id: int | None = None,
) -> list[str]:
    """Retorna a lista de conflitos encontrados; vazia significa livre."""
    dia = dia_semana if isinstance(dia_semana, DiaSemana) else DiaSemana.de_valor(dia_semana)
    if dia is None:
        return ["Dia da semana invalido."]

    conflitos: list[str] = []

    def _base():
        consulta = db.session.query(Horario).filter(
            Horario.dia_semana == dia,
            Horario.tempo_aula_id == tempo_aula_id,
        )
        if horario_id:
            consulta = consulta.filter(Horario.id != horario_id)
        return consulta

    # 1. A turma ja tem aula neste horario?
    ocupacao_turma = _base().filter(Horario.turma_id == turma_id).first()
    if ocupacao_turma:
        conflitos.append(
            f"A turma ja tem {ocupacao_turma.nome_disciplina} neste horario."
        )

    # 2. O professor ja esta em outra turma?
    vinculo = db.session.get(TurmaDisciplina, turma_disciplina_id)
    if vinculo and vinculo.professor_id:
        ocupacao_professor = (
            _base()
            .join(TurmaDisciplina, Horario.turma_disciplina_id == TurmaDisciplina.id)
            .filter(TurmaDisciplina.professor_id == vinculo.professor_id)
            .first()
        )
        if ocupacao_professor:
            turma_conflitante = (
                ocupacao_professor.turma.identificacao_curta
                if ocupacao_professor.turma
                else "outra turma"
            )
            conflitos.append(
                f"{vinculo.professor.nome_exibicao} ja leciona para "
                f"{turma_conflitante} neste horario."
            )

    # 3. A sala ja esta ocupada?
    if sala_id:
        ocupacao_sala = _base().filter(Horario.sala_id == sala_id).first()
        if ocupacao_sala:
            turma_conflitante = (
                ocupacao_sala.turma.identificacao_curta
                if ocupacao_sala.turma
                else "outra turma"
            )
            conflitos.append(
                f"A sala ja esta ocupada por {turma_conflitante} neste horario."
            )

    return conflitos


# ---------------------------------------------------------------------------
# Escrita
# ---------------------------------------------------------------------------
def alocar(
    turma: Turma,
    turma_disciplina_id: int,
    dia_semana: DiaSemana | str,
    tempo_aula_id: int,
    sala_id: int | None = None,
) -> Horario:
    """Aloca uma disciplina na grade da turma."""
    vinculo = db.session.get(TurmaDisciplina, turma_disciplina_id)
    if vinculo is None or vinculo.turma_id != turma.id:
        raise RegistroNaoEncontrado(
            "Disciplina nao encontrada na grade desta turma."
        )

    tempo = db.session.get(TempoAula, tempo_aula_id)
    if tempo is None:
        raise RegistroNaoEncontrado("Tempo de aula nao encontrado.")

    if tempo.e_intervalo:
        raise ErroRegraNegocio(
            "Nao e possivel alocar disciplinas em um intervalo."
        )

    if tempo.turno != turma.turno:
        raise ErroRegraNegocio(
            f"O tempo de aula pertence ao turno {tempo.turno.rotulo}, "
            f"mas a turma e do turno {turma.turno.rotulo}."
        )

    conflitos = verificar_conflitos(
        turma.id, turma_disciplina_id, dia_semana, tempo_aula_id, sala_id
    )
    if conflitos:
        raise ErroConflito(" ".join(conflitos))

    dia = dia_semana if isinstance(dia_semana, DiaSemana) else DiaSemana.de_valor(dia_semana)

    horario = Horario(
        turma_id=turma.id,
        turma_disciplina_id=turma_disciplina_id,
        tempo_aula_id=tempo_aula_id,
        sala_id=sala_id or None,
        dia_semana=dia,
    )
    db.session.add(horario)
    _confirmar("Falha ao alocar horario")

    auditoria_service.registrar_criacao(
        "Horario",
        horario.id,
        f"Horario alocado: {vinculo.descricao} em {dia.rotulo}, {tempo.nome}",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return horario


def remover(horario: Horario) -> None:
    """Libera um espaco da grade."""
    descricao = (
        f"{horario.nome_disciplina} em {horario.dia_semana.rotulo}"
    )
    identificador = horario.id

    db.session.delete(horario)
    _confirmar("Falha ao remover horario")

    auditoria_service.registrar_exclusao(
        "Horario", identificador, f"Horario removido: {descricao}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


def limpar_grade(turma: Turma) -> int:
    """Remove toda a grade de uma turma.

    Util para refazer o horario do zero no inicio do ano letivo.
    """
    total = (
        db.session.query(Horario)
        .filter(Horario.turma_id == turma.id)
        .delete(synchronize_session=False)
    )
    _confirmar("Falha ao limpar a grade")

    auditoria_service.registrar_exclusao(
        "Turma",
        turma.id,
        f"Grade de horarios limpa: {turma.nome_completo} ({total} alocacoes)",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return total


# ---------------------------------------------------------------------------
# Analise
# ---------------------------------------------------------------------------
def resumo_carga_horaria(turma: Turma) -> list[dict[str, Any]]:
    """Compara as aulas alocadas na grade com a carga horaria prevista.

    Ajuda a coordenacao a perceber que uma disciplina de 4 aulas semanais
    foi alocada apenas 3 vezes.
    """
    alocados: dict[int, int] = defaultdict(int)
    for horario in horarios_da_turma(turma.id):
        alocados[horario.turma_disciplina_id] += 1

    resumo = []
    for vinculo in turma.turmas_disciplinas:
        if not vinculo.ativa:
            continue

        quantidade = alocados.get(vinculo.id, 0)
        resumo.append(
            {
                "vinculo": vinculo,
                "disciplina": vinculo.disciplina,
                "previsto": vinculo.carga_horaria_semanal,
                "alocado": quantidade,
                "diferenca": quantidade - vinculo.carga_horaria_semanal,
                "completo": quantidade == vinculo.carga_horaria_semanal,
            }
        )

    return resumo


def horarios_livres(turma: Turma) -> list[dict[str, Any]]:
    """Espacos ainda vagos na grade da turma."""
    tempos = [t for t in tempos_do_turno(turma.turno) if not t.e_intervalo]
    ocupados = {
        (h.dia_semana.value, h.tempo_aula_id) for h in horarios_da_turma(turma.id)
    }

    livres = []
    for dia in DiaSemana:
        for tempo in tempos:
            if (dia.value, tempo.id) not in ocupados:
                livres.append({"dia": dia, "tempo": tempo})

    return livres


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
                "Este espaco da grade ja esta ocupado."
            ) from erro
    except Exception as erro:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error("%s: %s", mensagem, erro)
        if propagar:
            raise ErroOperacaoBanco() from erro
