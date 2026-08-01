"""Servico do painel: indicadores, graficos e atividades recentes.

Estrategia de desempenho
------------------------
Todos os numeros sao apurados com ``COUNT``/``GROUP BY`` no proprio banco.
Nenhuma consulta carrega colecoes para contar em Python — com alguns milhares
de alunos, ``len(turma.matriculas)`` transferiria milhares de linhas apenas
para produzir um numero na tela.

Cada perfil recebe apenas os dados que lhe dizem respeito: o professor ve as
proprias turmas, o responsavel ve apenas os filhos.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import case, func

from app.extensions import db
from app.models.avaliacao import Nota
from app.models.comunicacao import Aviso, AvisoLeitura
from app.models.enums import (
    SituacaoCadastro,
    SituacaoMatricula,
    SituacaoPresenca,
)
from app.models.estrutura import AnoLetivo, Serie, Turma, TurmaDisciplina
from app.models.frequencia import Aula, Frequencia
from app.models.matricula import Matricula
from app.models.pessoas import Aluno, Funcionario, Professor, Responsavel
from app.models.sistema import LogAuditoria
from app.models.usuario import Usuario


# ---------------------------------------------------------------------------
# Indicadores gerais (equipe administrativa)
# ---------------------------------------------------------------------------
def indicadores_gerais(ano_letivo: AnoLetivo | None = None) -> dict:
    """Contadores principais exibidos nos cartoes do painel."""
    total_alunos = (
        db.session.query(func.count(Aluno.id))
        .filter(
            Aluno.excluido_em.is_(None),
            Aluno.situacao == SituacaoCadastro.ATIVO,
        )
        .scalar()
        or 0
    )

    total_professores = (
        db.session.query(func.count(Professor.id))
        .filter(
            Professor.excluido_em.is_(None),
            Professor.situacao == SituacaoCadastro.ATIVO,
        )
        .scalar()
        or 0
    )

    total_funcionarios = (
        db.session.query(func.count(Funcionario.id))
        .filter(
            Funcionario.excluido_em.is_(None),
            Funcionario.situacao == SituacaoCadastro.ATIVO,
        )
        .scalar()
        or 0
    )

    total_responsaveis = (
        db.session.query(func.count(Responsavel.id))
        .filter(Responsavel.excluido_em.is_(None))
        .scalar()
        or 0
    )

    consulta_turmas = db.session.query(func.count(Turma.id)).filter(
        Turma.excluido_em.is_(None), Turma.ativa.is_(True)
    )
    consulta_matriculas = db.session.query(func.count(Matricula.id)).filter(
        Matricula.excluido_em.is_(None),
        Matricula.situacao == SituacaoMatricula.ATIVA,
    )
    if ano_letivo:
        consulta_turmas = consulta_turmas.filter(
            Turma.ano_letivo_id == ano_letivo.id
        )
        consulta_matriculas = consulta_matriculas.filter(
            Matricula.ano_letivo_id == ano_letivo.id
        )

    total_usuarios = (
        db.session.query(func.count(Usuario.id))
        .filter(Usuario.excluido_em.is_(None), Usuario.ativo.is_(True))
        .scalar()
        or 0
    )

    return {
        "alunos": total_alunos,
        "professores": total_professores,
        "funcionarios": total_funcionarios,
        "responsaveis": total_responsaveis,
        "turmas": consulta_turmas.scalar() or 0,
        "matriculas": consulta_matriculas.scalar() or 0,
        "usuarios": total_usuarios,
    }


def indicadores_complementares(ano_letivo: AnoLetivo | None = None) -> dict:
    """Metricas de apoio: ocupacao, pendencias e alertas de frequencia."""
    if ano_letivo is None:
        return {
            "taxa_ocupacao": 0.0,
            "vagas_disponiveis": 0,
            "chamadas_pendentes": 0,
            "alunos_risco_frequencia": 0,
        }

    # Ocupacao agregada: soma das capacidades x matriculas ativas.
    capacidade_total = (
        db.session.query(func.coalesce(func.sum(Turma.capacidade), 0))
        .filter(
            Turma.ano_letivo_id == ano_letivo.id,
            Turma.ativa.is_(True),
            Turma.excluido_em.is_(None),
        )
        .scalar()
        or 0
    )

    matriculados = (
        db.session.query(func.count(Matricula.id))
        .filter(
            Matricula.ano_letivo_id == ano_letivo.id,
            Matricula.situacao == SituacaoMatricula.ATIVA,
            Matricula.excluido_em.is_(None),
        )
        .scalar()
        or 0
    )

    taxa = round(matriculados / capacidade_total * 100, 1) if capacidade_total else 0.0

    # Aulas registradas nos ultimos 30 dias ainda sem chamada lancada.
    limite = date.today() - timedelta(days=30)
    chamadas_pendentes = (
        db.session.query(func.count(Aula.id))
        .join(TurmaDisciplina, Aula.turma_disciplina_id == TurmaDisciplina.id)
        .join(Turma, TurmaDisciplina.turma_id == Turma.id)
        .filter(
            Turma.ano_letivo_id == ano_letivo.id,
            Aula.chamada_realizada.is_(False),
            Aula.data_aula >= limite,
            Aula.data_aula <= date.today(),
        )
        .scalar()
        or 0
    )

    return {
        "taxa_ocupacao": taxa,
        "vagas_disponiveis": max(0, capacidade_total - matriculados),
        "capacidade_total": capacidade_total,
        "chamadas_pendentes": chamadas_pendentes,
        "alunos_risco_frequencia": _contar_alunos_em_risco(ano_letivo),
    }


def _contar_alunos_em_risco(ano_letivo: AnoLetivo, limite_faltas: int = 10) -> int:
    """Conta alunos com muitas faltas no ano — alerta preventivo de evasao."""
    subconsulta = (
        db.session.query(
            Frequencia.matricula_id.label("matricula_id"),
            func.count(Frequencia.id).label("faltas"),
        )
        .join(Matricula, Frequencia.matricula_id == Matricula.id)
        .filter(
            Matricula.ano_letivo_id == ano_letivo.id,
            Matricula.situacao == SituacaoMatricula.ATIVA,
            Frequencia.situacao == SituacaoPresenca.FALTA,
        )
        .group_by(Frequencia.matricula_id)
        .having(func.count(Frequencia.id) >= limite_faltas)
        .subquery()
    )

    return db.session.query(func.count()).select_from(subconsulta).scalar() or 0


# ---------------------------------------------------------------------------
# Dados para graficos
# ---------------------------------------------------------------------------
def alunos_por_serie(ano_letivo: AnoLetivo | None) -> dict:
    """Distribuicao de matriculas ativas por serie (grafico de barras)."""
    if ano_letivo is None:
        return {"rotulos": [], "valores": []}

    linhas = (
        db.session.query(Serie.nome, func.count(Matricula.id))
        .join(Turma, Turma.serie_id == Serie.id)
        .join(Matricula, Matricula.turma_id == Turma.id)
        .filter(
            Matricula.ano_letivo_id == ano_letivo.id,
            Matricula.situacao == SituacaoMatricula.ATIVA,
            Matricula.excluido_em.is_(None),
        )
        .group_by(Serie.id, Serie.nome, Serie.ordem)
        .order_by(Serie.ordem)
        .all()
    )

    return {
        "rotulos": [linha[0] for linha in linhas],
        "valores": [linha[1] for linha in linhas],
    }


def alunos_por_turno(ano_letivo: AnoLetivo | None) -> dict:
    """Distribuicao de matriculas por turno (grafico de rosca)."""
    if ano_letivo is None:
        return {"rotulos": [], "valores": []}

    linhas = (
        db.session.query(Turma.turno, func.count(Matricula.id))
        .join(Matricula, Matricula.turma_id == Turma.id)
        .filter(
            Matricula.ano_letivo_id == ano_letivo.id,
            Matricula.situacao == SituacaoMatricula.ATIVA,
            Matricula.excluido_em.is_(None),
        )
        .group_by(Turma.turno)
        .all()
    )

    return {
        "rotulos": [
            turno.rotulo if hasattr(turno, "rotulo") else str(turno)
            for turno, _ in linhas
        ],
        "valores": [total for _, total in linhas],
    }


def matriculas_por_mes(ano_letivo: AnoLetivo | None) -> dict:
    """Evolucao mensal das matriculas (grafico de linha).

    A extracao do mes usa ``strftime`` no SQLite e ``to_char`` no PostgreSQL;
    aqui agrupamos em Python sobre um conjunto ja reduzido (apenas as datas),
    o que mantem o codigo portavel entre os dois bancos sem custo relevante.
    """
    if ano_letivo is None:
        return {"rotulos": [], "valores": []}

    datas = (
        db.session.query(Matricula.data_matricula)
        .filter(
            Matricula.ano_letivo_id == ano_letivo.id,
            Matricula.excluido_em.is_(None),
        )
        .all()
    )

    contagem: dict[int, int] = dict.fromkeys(range(1, 13), 0)
    for (data_matricula,) in datas:
        if data_matricula:
            contagem[data_matricula.month] += 1

    nomes = ("Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
             "Jul", "Ago", "Set", "Out", "Nov", "Dez")

    return {
        "rotulos": list(nomes),
        "valores": [contagem[mes] for mes in range(1, 13)],
    }


def situacao_matriculas(ano_letivo: AnoLetivo | None) -> dict:
    """Quantidade de matriculas por situacao (ativa, trancada, etc.)."""
    if ano_letivo is None:
        return {"rotulos": [], "valores": [], "cores": []}

    linhas = (
        db.session.query(Matricula.situacao, func.count(Matricula.id))
        .filter(
            Matricula.ano_letivo_id == ano_letivo.id,
            Matricula.excluido_em.is_(None),
        )
        .group_by(Matricula.situacao)
        .all()
    )

    mapa_cores = {
        "success": "#057a55",
        "warning": "#c27803",
        "info": "#1c64f2",
        "danger": "#e02424",
        "primary": "#1a56db",
        "secondary": "#6b7280",
    }

    rotulos, valores, cores = [], [], []
    for situacao, total in linhas:
        rotulos.append(getattr(situacao, "rotulo", str(situacao)))
        valores.append(total)
        cores.append(mapa_cores.get(getattr(situacao, "cor", "secondary"), "#6b7280"))

    return {"rotulos": rotulos, "valores": valores, "cores": cores}


def desempenho_por_disciplina(ano_letivo: AnoLetivo | None, limite: int = 8) -> dict:
    """Media geral por disciplina, para o grafico comparativo da direcao."""
    if ano_letivo is None:
        return {"rotulos": [], "valores": []}

    from app.models.avaliacao import Avaliacao
    from app.models.estrutura import Disciplina

    linhas = (
        db.session.query(
            Disciplina.nome,
            func.avg(
                case((Nota.ausente.is_(True), 0.0), else_=Nota.valor)
            ).label("media"),
        )
        .join(TurmaDisciplina, TurmaDisciplina.disciplina_id == Disciplina.id)
        .join(Avaliacao, Avaliacao.turma_disciplina_id == TurmaDisciplina.id)
        .join(Nota, Nota.avaliacao_id == Avaliacao.id)
        .join(Turma, TurmaDisciplina.turma_id == Turma.id)
        .filter(
            Turma.ano_letivo_id == ano_letivo.id,
            db.or_(Nota.valor.isnot(None), Nota.ausente.is_(True)),
        )
        .group_by(Disciplina.id, Disciplina.nome)
        .order_by(func.avg(Nota.valor).desc())
        .limit(limite)
        .all()
    )

    return {
        "rotulos": [linha[0] for linha in linhas],
        "valores": [round(float(linha[1] or 0), 2) for linha in linhas],
    }


# ---------------------------------------------------------------------------
# Painel do professor
# ---------------------------------------------------------------------------
def painel_professor(professor: Professor, ano_letivo: AnoLetivo | None) -> dict:
    """Dados do painel de um professor: turmas, aulas do dia e pendencias."""
    if professor is None:
        return {
            "vinculos": [],
            "total_turmas": 0,
            "total_alunos": 0,
            "aulas_hoje": [],
            "chamadas_pendentes": [],
            "notas_pendentes": 0,
        }

    consulta = (
        db.session.query(TurmaDisciplina)
        .join(Turma, TurmaDisciplina.turma_id == Turma.id)
        .filter(
            TurmaDisciplina.professor_id == professor.id,
            TurmaDisciplina.ativa.is_(True),
            Turma.excluido_em.is_(None),
        )
    )
    if ano_letivo:
        consulta = consulta.filter(Turma.ano_letivo_id == ano_letivo.id)

    vinculos = consulta.all()
    ids_turmas = {v.turma_id for v in vinculos}

    total_alunos = 0
    if ids_turmas:
        total_alunos = (
            db.session.query(func.count(func.distinct(Matricula.aluno_id)))
            .filter(
                Matricula.turma_id.in_(ids_turmas),
                Matricula.situacao == SituacaoMatricula.ATIVA,
                Matricula.excluido_em.is_(None),
            )
            .scalar()
            or 0
        )

    ids_vinculos = [v.id for v in vinculos]

    aulas_hoje = []
    chamadas_pendentes = []
    if ids_vinculos:
        aulas_hoje = (
            db.session.query(Aula)
            .filter(
                Aula.turma_disciplina_id.in_(ids_vinculos),
                Aula.data_aula == date.today(),
            )
            .order_by(Aula.ordem_no_dia)
            .all()
        )

        chamadas_pendentes = (
            db.session.query(Aula)
            .filter(
                Aula.turma_disciplina_id.in_(ids_vinculos),
                Aula.chamada_realizada.is_(False),
                Aula.data_aula <= date.today(),
                Aula.data_aula >= date.today() - timedelta(days=30),
            )
            .order_by(Aula.data_aula.desc())
            .limit(10)
            .all()
        )

    return {
        "vinculos": vinculos,
        "total_turmas": len(ids_turmas),
        "total_alunos": total_alunos,
        "aulas_hoje": aulas_hoje,
        "chamadas_pendentes": chamadas_pendentes,
        "notas_pendentes": _contar_notas_pendentes(ids_vinculos),
    }


def _contar_notas_pendentes(ids_vinculos: list[int]) -> int:
    """Notas ainda nao lancadas em avaliacoes ja aplicadas."""
    if not ids_vinculos:
        return 0

    from app.models.avaliacao import Avaliacao

    return (
        db.session.query(func.count(Nota.id))
        .join(Avaliacao, Nota.avaliacao_id == Avaliacao.id)
        .filter(
            Avaliacao.turma_disciplina_id.in_(ids_vinculos),
            Avaliacao.data_aplicacao.isnot(None),
            Avaliacao.data_aplicacao <= date.today(),
            Nota.valor.is_(None),
            Nota.ausente.is_(False),
        )
        .scalar()
        or 0
    )


# ---------------------------------------------------------------------------
# Painel do aluno e do responsavel
# ---------------------------------------------------------------------------
def painel_aluno(aluno: Aluno) -> dict:
    """Resumo academico de um aluno: media, frequencia e ultimas notas."""
    if aluno is None:
        return {"matricula": None}

    matricula = aluno.matricula_atual
    if matricula is None:
        return {"matricula": None}

    total_aulas = (
        db.session.query(func.count(Frequencia.id))
        .filter(Frequencia.matricula_id == matricula.id)
        .scalar()
        or 0
    )
    total_faltas = (
        db.session.query(func.count(Frequencia.id))
        .filter(
            Frequencia.matricula_id == matricula.id,
            Frequencia.situacao == SituacaoPresenca.FALTA,
        )
        .scalar()
        or 0
    )
    percentual = (
        round((total_aulas - total_faltas) / total_aulas * 100, 1)
        if total_aulas
        else None
    )

    media = (
        db.session.query(
            func.avg(case((Nota.ausente.is_(True), 0.0), else_=Nota.valor))
        )
        .filter(
            Nota.matricula_id == matricula.id,
            db.or_(Nota.valor.isnot(None), Nota.ausente.is_(True)),
        )
        .scalar()
    )

    ultimas_notas = (
        db.session.query(Nota)
        .filter(
            Nota.matricula_id == matricula.id,
            db.or_(Nota.valor.isnot(None), Nota.ausente.is_(True)),
        )
        .order_by(Nota.atualizado_em.desc())
        .limit(6)
        .all()
    )

    return {
        "matricula": matricula,
        "turma": matricula.turma,
        "total_aulas": total_aulas,
        "total_faltas": total_faltas,
        "percentual_frequencia": percentual,
        "media_geral": round(float(media), 2) if media is not None else None,
        "ultimas_notas": ultimas_notas,
    }


def painel_responsavel(responsavel: Responsavel) -> list[dict]:
    """Resumo de cada aluno sob responsabilidade do usuario."""
    if responsavel is None:
        return []
    return [
        {"aluno": aluno, **painel_aluno(aluno)}
        for aluno in responsavel.alunos
    ]


# ---------------------------------------------------------------------------
# Avisos e atividades
# ---------------------------------------------------------------------------
def avisos_do_usuario(usuario, limite: int = 5) -> list[Aviso]:
    """Avisos vigentes destinados ao usuario, priorizando os fixados."""
    hoje = date.today()

    candidatos = (
        db.session.query(Aviso)
        .filter(
            Aviso.publicado.is_(True),
            Aviso.excluido_em.is_(None),
            Aviso.data_inicio <= hoje,
            db.or_(Aviso.data_fim.is_(None), Aviso.data_fim >= hoje),
        )
        .order_by(Aviso.fixado.desc(), Aviso.criado_em.desc())
        .limit(limite * 4)  # margem para o filtro de segmentacao
        .all()
    )

    # A segmentacao depende de vinculos (turma do aluno, filhos do
    # responsavel) que nao cabem em uma unica clausula SQL portavel.
    # Filtramos em Python sobre um conjunto pequeno e ja ordenado.
    return [aviso for aviso in candidatos if aviso.destinado_a(usuario)][:limite]


def contar_avisos_nao_lidos(usuario) -> int:
    """Quantos avisos destinados ao usuario ainda nao foram lidos."""
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return 0

    lidos = {
        linha[0]
        for linha in db.session.query(AvisoLeitura.aviso_id)
        .filter(
            AvisoLeitura.usuario_id == usuario.id,
            AvisoLeitura.lido_em.isnot(None),
        )
        .all()
    }

    return sum(1 for aviso in avisos_do_usuario(usuario, limite=50)
               if aviso.id not in lidos)


def atividades_recentes(limite: int = 8) -> list[LogAuditoria]:
    """Ultimas acoes relevantes registradas na auditoria.

    Eventos de login e logout sao omitidos: eles dominariam a lista e nao
    representam atividade academica.
    """
    from app.models.enums import AcaoAuditoria

    return (
        db.session.query(LogAuditoria)
        .filter(
            LogAuditoria.acao.notin_(
                [
                    AcaoAuditoria.LOGIN.value,
                    AcaoAuditoria.LOGOUT.value,
                    AcaoAuditoria.LOGIN_FALHOU.value,
                ]
            )
        )
        .order_by(LogAuditoria.criado_em.desc())
        .limit(limite)
        .all()
    )


def aniversariantes_do_mes(limite: int = 10) -> list[Aluno]:
    """Alunos aniversariantes do mes corrente.

    Recurso pequeno, porem muito valorizado no dia a dia da escola.
    ``extract('month')`` funciona tanto no SQLite quanto no PostgreSQL.
    """
    mes = date.today().month
    return (
        db.session.query(Aluno)
        .filter(
            Aluno.excluido_em.is_(None),
            Aluno.situacao == SituacaoCadastro.ATIVO,
            Aluno.data_nascimento.isnot(None),
            func.extract("month", Aluno.data_nascimento) == mes,
        )
        .order_by(func.extract("day", Aluno.data_nascimento))
        .limit(limite)
        .all()
    )
