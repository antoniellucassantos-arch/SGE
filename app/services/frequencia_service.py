"""Regras de negocio do diario de classe e do controle de frequencia.

Fluxo do professor
------------------
1. Registra a aula (data + conteudo ministrado).
2. Faz a chamada: o sistema cria uma linha de frequencia para **cada** aluno
   matriculado, com presenca como padrao.
3. Ao salvar, a aula e marcada como ``chamada_realizada``.

Por que criar linha para todos os alunos, e nao so para os faltosos: sem o
registro explicito de presenca nao ha como distinguir "aluno presente" de
"chamada nunca feita", e o percentual de frequencia do boletim sairia errado.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.enums import SituacaoMatricula, SituacaoPresenca
from app.models.estrutura import Turma, TurmaDisciplina
from app.models.frequencia import Aula, Frequencia
from app.models.matricula import Matricula
from app.models.pessoas import Aluno, Professor
from app.services import auditoria_service
from app.services.excecoes import (
    ErroConflito,
    ErroOperacaoBanco,
    ErroRegraNegocio,
    RegistroNaoEncontrado,
)


# ---------------------------------------------------------------------------
# Consultas de apoio
# ---------------------------------------------------------------------------
def buscar_vinculo(vinculo_id: int | str | None) -> TurmaDisciplina:
    """Recupera um vinculo turma x disciplina."""
    vinculo = TurmaDisciplina.buscar_por_id(vinculo_id)
    if vinculo is None:
        raise RegistroNaoEncontrado("Disciplina da turma nao encontrada.")
    return vinculo


def buscar_aula(aula_id: int | str | None) -> Aula:
    aula = Aula.buscar_por_id(aula_id)
    if aula is None:
        raise RegistroNaoEncontrado("Aula nao encontrada.")
    return aula


def vinculos_do_professor(
    professor: Professor | None, ano_letivo_id: int | None = None
) -> list[TurmaDisciplina]:
    """Disciplinas que o professor leciona no ano letivo."""
    if professor is None:
        return []

    consulta = (
        db.session.query(TurmaDisciplina)
        .join(Turma, TurmaDisciplina.turma_id == Turma.id)
        .filter(
            TurmaDisciplina.professor_id == professor.id,
            TurmaDisciplina.ativa.is_(True),
            Turma.excluido_em.is_(None),
        )
    )
    if ano_letivo_id:
        consulta = consulta.filter(Turma.ano_letivo_id == ano_letivo_id)

    return consulta.all()


def todos_os_vinculos(ano_letivo_id: int | None = None) -> list[TurmaDisciplina]:
    """Todos os vinculos ativos (visao da coordenacao)."""
    consulta = (
        db.session.query(TurmaDisciplina)
        .join(Turma, TurmaDisciplina.turma_id == Turma.id)
        .filter(TurmaDisciplina.ativa.is_(True), Turma.excluido_em.is_(None))
    )
    if ano_letivo_id:
        consulta = consulta.filter(Turma.ano_letivo_id == ano_letivo_id)
    return consulta.all()


def aulas_do_vinculo(vinculo_id: int, limite: int | None = None):
    """Aulas registradas de uma disciplina, da mais recente para a mais antiga."""
    consulta = (
        db.session.query(Aula)
        .filter(Aula.turma_disciplina_id == vinculo_id)
        .order_by(Aula.data_aula.desc(), Aula.ordem_no_dia.desc())
    )
    return consulta.limit(limite).all() if limite else consulta


def aulas_pendentes(ano_letivo_id: int | None = None, dias: int = 30):
    """Aulas ja registradas cujo professor ainda nao lancou a chamada."""
    limite = date.today() - timedelta(days=dias)

    consulta = (
        db.session.query(Aula)
        .join(TurmaDisciplina, Aula.turma_disciplina_id == TurmaDisciplina.id)
        .join(Turma, TurmaDisciplina.turma_id == Turma.id)
        .filter(
            Aula.chamada_realizada.is_(False),
            Aula.data_aula >= limite,
            Aula.data_aula <= date.today(),
        )
    )
    if ano_letivo_id:
        consulta = consulta.filter(Turma.ano_letivo_id == ano_letivo_id)

    return consulta.order_by(Aula.data_aula.desc())


# ---------------------------------------------------------------------------
# Registro de aula
# ---------------------------------------------------------------------------
def registrar_aula(
    vinculo: TurmaDisciplina,
    data_aula: date,
    conteudo: str | None = None,
    quantidade_aulas: int = 1,
    tarefa_casa: str | None = None,
    observacoes: str | None = None,
    usuario_id: int | None = None,
) -> Aula:
    """Registra uma aula no diario de classe.

    A ordem no dia e calculada automaticamente, permitindo aulas geminadas
    (duas aulas da mesma disciplina no mesmo dia).
    """
    _validar_data_aula(vinculo, data_aula)

    ultima_ordem = (
        db.session.query(func.max(Aula.ordem_no_dia))
        .filter(
            Aula.turma_disciplina_id == vinculo.id,
            Aula.data_aula == data_aula,
        )
        .scalar()
        or 0
    )

    aula = Aula(
        turma_disciplina_id=vinculo.id,
        data_aula=data_aula,
        ordem_no_dia=ultima_ordem + 1,
        quantidade_aulas=max(1, int(quantidade_aulas or 1)),
        conteudo=(conteudo or "").strip() or None,
        tarefa_casa=(tarefa_casa or "").strip() or None,
        observacoes=(observacoes or "").strip() or None,
        registrada_por_id=usuario_id,
        chamada_realizada=False,
    )

    db.session.add(aula)
    _confirmar("Falha ao registrar aula")

    auditoria_service.registrar_criacao(
        "Aula",
        aula.id,
        f"Aula registrada em {data_aula:%d/%m/%Y}: {vinculo.descricao}",
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return aula


def atualizar_aula(aula: Aula, dados: dict[str, Any]) -> Aula:
    """Atualiza conteudo, tarefa e observacoes de uma aula."""
    antes = aula.para_dicionario()
    aula.atualizar_campos(**dados)
    alteracoes = auditoria_service.calcular_alteracoes(antes, aula.para_dicionario())
    if not alteracoes:
        return aula

    _confirmar("Falha ao atualizar aula")
    auditoria_service.registrar_atualizacao(
        "Aula", aula.id, f"Aula de {aula.data_aula:%d/%m/%Y} atualizada", alteracoes
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return aula


def excluir_aula(aula: Aula) -> None:
    """Remove a aula e, em cascata, as frequencias associadas."""
    descricao = aula.descricao
    identificador = aula.id

    db.session.delete(aula)
    _confirmar("Falha ao excluir aula")

    auditoria_service.registrar_exclusao(
        "Aula", identificador, f"Aula excluida: {descricao}"
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)


def _validar_data_aula(vinculo: TurmaDisciplina, data_aula: date) -> None:
    """Impede datas futuras ou fora do ano letivo."""
    if data_aula > date.today():
        raise ErroRegraNegocio(
            "Nao e possivel registrar aula com data futura."
        )

    turma = vinculo.turma
    ano_letivo = turma.ano_letivo if turma else None

    if ano_letivo:
        if not ano_letivo.aceita_lancamentos:
            raise ErroRegraNegocio(
                f"O ano letivo de {ano_letivo.ano} nao esta em andamento. "
                "Novos lancamentos estao bloqueados."
            )
        if not ano_letivo.contem_data(data_aula):
            raise ErroRegraNegocio(
                f"A data informada esta fora do ano letivo de {ano_letivo.ano} "
                f"({ano_letivo.data_inicio:%d/%m/%Y} a "
                f"{ano_letivo.data_fim:%d/%m/%Y})."
            )


# ---------------------------------------------------------------------------
# Chamada
# ---------------------------------------------------------------------------
def preparar_chamada(aula: Aula) -> list[dict[str, Any]]:
    """Monta a lista de chamada, criando as linhas ausentes em memoria.

    Retorna, para cada aluno matriculado, o par ``(matricula, frequencia)``.
    Alunos matriculados apos o registro da aula aparecem automaticamente.
    """
    matriculas = _matriculas_da_aula(aula)

    existentes = {
        f.matricula_id: f
        for f in db.session.query(Frequencia).filter(Frequencia.aula_id == aula.id)
    }

    linhas: list[dict[str, Any]] = []
    for matricula in matriculas:
        linhas.append(
            {
                "matricula": matricula,
                "aluno": matricula.aluno,
                "frequencia": existentes.get(matricula.id),
                "situacao": (
                    existentes[matricula.id].situacao.value
                    if matricula.id in existentes
                    else SituacaoPresenca.PRESENTE.value
                ),
                "justificativa": (
                    existentes[matricula.id].justificativa
                    if matricula.id in existentes
                    else ""
                ),
            }
        )

    return linhas


def _matriculas_da_aula(aula: Aula) -> list[Matricula]:
    """Alunos com matricula ativa na turma da aula, em ordem alfabetica."""
    vinculo = aula.turma_disciplina
    if vinculo is None:
        return []

    return (
        db.session.query(Matricula)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .filter(
            Matricula.turma_id == vinculo.turma_id,
            Matricula.situacao == SituacaoMatricula.ATIVA,
            Matricula.excluido_em.is_(None),
        )
        .order_by(Aluno.nome_normalizado)
        .all()
    )


def salvar_chamada(
    aula: Aula,
    situacoes: dict[int, str],
    justificativas: dict[int, str] | None = None,
    usuario_id: int | None = None,
) -> int:
    """Grava a chamada de uma aula.

    Args:
        situacoes: ``{matricula_id: valor_da_situacao}``.
        justificativas: ``{matricula_id: texto}`` para faltas justificadas.

    Returns:
        Quantidade de alunos processados.

    A gravacao usa *upsert* por aluno: refazer a chamada corrige os
    lancamentos anteriores em vez de duplicar linhas.
    """
    justificativas = justificativas or {}
    matriculas = {m.id: m for m in _matriculas_da_aula(aula)}

    if not matriculas:
        raise ErroRegraNegocio(
            "Nao ha alunos com matricula ativa nesta turma."
        )

    existentes = {
        f.matricula_id: f
        for f in db.session.query(Frequencia).filter(Frequencia.aula_id == aula.id)
    }

    processados = 0
    total_faltas = 0

    for matricula_id, valor in situacoes.items():
        # Ignora ids que nao pertencem a turma: protege contra manipulacao
        # do formulario enviado pelo navegador.
        if matricula_id not in matriculas:
            continue

        situacao = SituacaoPresenca.de_valor(valor) or SituacaoPresenca.PRESENTE
        justificativa = (justificativas.get(matricula_id) or "").strip()[:255] or None

        registro = existentes.get(matricula_id)
        if registro is None:
            registro = Frequencia(
                aula_id=aula.id,
                matricula_id=matricula_id,
                registrada_por_id=usuario_id,
            )
            db.session.add(registro)

        registro.situacao = situacao
        registro.justificativa = justificativa
        registro.registrada_por_id = usuario_id

        if situacao is SituacaoPresenca.FALTA:
            total_faltas += 1
        processados += 1

    aula.chamada_realizada = True
    _confirmar("Falha ao salvar chamada")

    auditoria_service.registrar_atualizacao(
        "Aula",
        aula.id,
        f"Chamada registrada em {aula.data_aula:%d/%m/%Y}: "
        f"{processados} aluno(s), {total_faltas} falta(s)",
        {"alunos": processados, "faltas": total_faltas},
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)

    return processados


def justificar_falta(frequencia: Frequencia, motivo: str) -> Frequencia:
    """Converte uma falta em falta justificada."""
    if frequencia.situacao is not SituacaoPresenca.FALTA:
        raise ErroRegraNegocio(
            "Apenas faltas podem ser justificadas."
        )

    frequencia.justificar(motivo)
    _confirmar("Falha ao justificar falta")

    auditoria_service.registrar_atualizacao(
        "Frequencia",
        frequencia.id,
        f"Falta justificada: {frequencia.matricula.nome_aluno if frequencia.matricula else '?'}",
        {"motivo": motivo},
    )
    _confirmar("Falha ao registrar auditoria", propagar=False)
    return frequencia


# ---------------------------------------------------------------------------
# Apuracao
# ---------------------------------------------------------------------------
def apurar_frequencia(
    matricula_id: int, turma_disciplina_id: int | None = None
) -> dict[str, Any]:
    """Calcula a frequencia de um aluno, geral ou em uma disciplina.

    A contagem considera ``quantidade_aulas`` de cada registro: uma aula
    geminada conta como duas para fins de percentual legal.
    """
    consulta = (
        db.session.query(
            func.coalesce(func.sum(Aula.quantidade_aulas), 0).label("total"),
            func.coalesce(
                func.sum(
                    db.case(
                        (
                            Frequencia.situacao == SituacaoPresenca.FALTA,
                            Aula.quantidade_aulas,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("faltas"),
        )
        .select_from(Frequencia)
        .join(Aula, Frequencia.aula_id == Aula.id)
        .filter(Frequencia.matricula_id == matricula_id)
    )

    if turma_disciplina_id:
        consulta = consulta.filter(Aula.turma_disciplina_id == turma_disciplina_id)

    linha = consulta.one()
    return _montar_apuracao(linha.total, linha.faltas)


def _montar_apuracao(total, faltas) -> dict[str, Any]:
    """Formata o resultado da contagem de aulas e faltas.

    Definicao unica do que e "percentual de frequencia": a apuracao
    individual e a em lote precisam produzir exatamente o mesmo numero, sob
    pena de o boletim discordar do fechamento da turma.
    """
    total = int(total or 0)
    faltas = int(faltas or 0)
    presencas = max(0, total - faltas)

    return {
        "total_aulas": total,
        "total_faltas": faltas,
        "total_presencas": presencas,
        "percentual": round(presencas / total * 100, 2) if total else None,
    }


def apurar_frequencia_em_lote(
    matricula_ids: Sequence[int],
) -> dict[tuple[int, int | None], dict[str, Any]]:
    """Frequencia de varios alunos, em uma unica consulta.

    Chave do dicionario: ``(matricula_id, turma_disciplina_id)`` para a
    apuracao por disciplina e ``(matricula_id, None)`` para o total geral do
    aluno.

    Existe por causa do fechamento de periodo: apurando aluno a aluno,
    disciplina a disciplina, uma turma de 40 alunos com 12 disciplinas
    dispara quase 500 consultas. Aqui sai uma so, e o total geral e obtido
    somando as parciais em memoria — nao vale uma segunda ida ao banco.
    """
    identificadores = list(matricula_ids)
    if not identificadores:
        return {}

    linhas = (
        db.session.query(
            Frequencia.matricula_id.label("matricula_id"),
            Aula.turma_disciplina_id.label("vinculo_id"),
            func.coalesce(func.sum(Aula.quantidade_aulas), 0).label("total"),
            func.coalesce(
                func.sum(
                    db.case(
                        (
                            Frequencia.situacao == SituacaoPresenca.FALTA,
                            Aula.quantidade_aulas,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("faltas"),
        )
        .select_from(Frequencia)
        .join(Aula, Frequencia.aula_id == Aula.id)
        .filter(Frequencia.matricula_id.in_(identificadores))
        .group_by(Frequencia.matricula_id, Aula.turma_disciplina_id)
        .all()
    )

    apuracoes: dict[tuple[int, int | None], dict[str, Any]] = {}
    totais_gerais: dict[int, list[int]] = {}

    for linha in linhas:
        apuracoes[(linha.matricula_id, linha.vinculo_id)] = _montar_apuracao(
            linha.total, linha.faltas
        )

        acumulado = totais_gerais.setdefault(linha.matricula_id, [0, 0])
        acumulado[0] += int(linha.total or 0)
        acumulado[1] += int(linha.faltas or 0)

    # Alunos sem nenhuma aula registrada precisam aparecer com zero, e nao
    # sumir do dicionario: quem consulta espera uma apuracao para todos.
    for matricula_id in identificadores:
        total, faltas = totais_gerais.get(matricula_id, (0, 0))
        apuracoes[(matricula_id, None)] = _montar_apuracao(total, faltas)

    return apuracoes


def resumo_por_disciplina(matricula_id: int) -> list[dict[str, Any]]:
    """Frequencia do aluno em cada disciplina que ele cursa."""
    matricula = db.session.get(Matricula, matricula_id)
    if matricula is None:
        return []

    vinculos = (
        db.session.query(TurmaDisciplina)
        .filter(
            TurmaDisciplina.turma_id == matricula.turma_id,
            TurmaDisciplina.ativa.is_(True),
        )
        .all()
    )

    return [
        {
            "vinculo": vinculo,
            "disciplina": vinculo.disciplina,
            **apurar_frequencia(matricula_id, vinculo.id),
        }
        for vinculo in vinculos
    ]


def alunos_em_risco(
    ano_letivo_id: int,
    frequencia_minima: float = 75.0,
    turmas_permitidas: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Alunos abaixo da frequencia minima legal.

    Base do alerta preventivo de evasao exibido no painel e no relatorio de
    frequencia.

    Args:
        turmas_permitidas: quando informado, restringe o resultado a essas
            turmas. O recorte entra na consulta SQL, e nao apos o carregamento
            — do contrario os dados das demais turmas ainda seriam lidos e
            acabariam nas exportacoes.
    """
    linhas = (
        db.session.query(
            Matricula.id.label("matricula_id"),
            func.coalesce(func.sum(Aula.quantidade_aulas), 0).label("total"),
            func.coalesce(
                func.sum(
                    db.case(
                        (
                            Frequencia.situacao == SituacaoPresenca.FALTA,
                            Aula.quantidade_aulas,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("faltas"),
        )
        .select_from(Matricula)
        .join(Frequencia, Frequencia.matricula_id == Matricula.id)
        .join(Aula, Frequencia.aula_id == Aula.id)
        .filter(
            Matricula.ano_letivo_id == ano_letivo_id,
            Matricula.situacao == SituacaoMatricula.ATIVA,
            Matricula.excluido_em.is_(None),
        )
    )

    if turmas_permitidas is not None:
        # Conjunto vazio nunca vira "sem filtro".
        linhas = linhas.filter(Matricula.turma_id.in_(turmas_permitidas or {0}))

    linhas = linhas.group_by(Matricula.id).all()

    em_risco: list[dict[str, Any]] = []
    for linha in linhas:
        total = int(linha.total or 0)
        if total < 10:
            # Poucas aulas ainda nao permitem concluir nada sobre evasao.
            continue

        faltas = int(linha.faltas or 0)
        percentual = round((total - faltas) / total * 100, 2)

        if percentual < frequencia_minima:
            matricula = db.session.get(Matricula, linha.matricula_id)
            em_risco.append(
                {
                    "matricula": matricula,
                    "aluno": matricula.aluno if matricula else None,
                    "turma": matricula.turma if matricula else None,
                    "total_aulas": total,
                    "total_faltas": faltas,
                    "percentual": percentual,
                }
            )

    return sorted(em_risco, key=lambda item: item["percentual"])


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
                "Ja existe um registro de aula ou chamada com estes dados."
            ) from erro
    except Exception as erro:  # noqa: BLE001
        db.session.rollback()
        current_app.logger.error("%s: %s", mensagem, erro)
        if propagar:
            raise ErroOperacaoBanco() from erro
