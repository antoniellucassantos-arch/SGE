"""Comandos de estrutura e dados iniciais do banco."""

from __future__ import annotations

from datetime import date, time

import click
from flask.cli import with_appcontext

from app.extensions import db


@click.command("criar-tabelas")
@with_appcontext
def criar_tabelas():
    """Cria as tabelas direto do metadata (atalho para desenvolvimento).

    Em producao use sempre ``flask db upgrade``: apenas as migrations
    garantem que o banco existente evolua sem perda de dados.
    """
    db.create_all()
    click.secho("Tabelas criadas com sucesso.", fg="green")


@click.command("criar-estrutura-inicial")
@click.option("--ano", default=None, type=int, help="Ano letivo a criar.")
@with_appcontext
def criar_estrutura_inicial(ano: int | None):
    """Cria configuracao da escola, ano letivo, series e tempos de aula.

    Ponto de partida minimo para a escola comecar a usar o sistema sem
    precisar cadastrar a estrutura basica manualmente.
    """
    from app.models.enums import NivelEnsino, SituacaoAnoLetivo, Turno
    from app.models.estrutura import AnoLetivo, PeriodoLetivo, Serie
    from app.models.horario import TempoAula
    from app.models.sistema import ConfiguracaoEscola

    ano = ano or date.today().year

    config = ConfiguracaoEscola.obter()
    click.echo(f"Configuracao da escola: {config.nome}")

    # -- Ano letivo e periodos ---------------------------------------------
    ano_letivo = db.session.query(AnoLetivo).filter(AnoLetivo.ano == ano).first()
    if ano_letivo:
        click.secho(f"Ano letivo {ano} ja existe.", fg="yellow")
    else:
        ano_letivo = AnoLetivo(
            ano=ano,
            descricao=f"Ano Letivo {ano}",
            data_inicio=date(ano, 2, 1),
            data_fim=date(ano, 12, 20),
            situacao=SituacaoAnoLetivo.EM_ANDAMENTO,
            corrente=True,
        )
        db.session.add(ano_letivo)
        db.session.flush()

        bimestres = (
            ("1o Bimestre", date(ano, 2, 1), date(ano, 4, 30)),
            ("2o Bimestre", date(ano, 5, 1), date(ano, 7, 15)),
            ("3o Bimestre", date(ano, 8, 1), date(ano, 9, 30)),
            ("4o Bimestre", date(ano, 10, 1), date(ano, 12, 20)),
        )
        for ordem, (nome, inicio, fim) in enumerate(bimestres, start=1):
            db.session.add(
                PeriodoLetivo(
                    ano_letivo_id=ano_letivo.id,
                    nome=nome,
                    ordem=ordem,
                    data_inicio=inicio,
                    data_fim=fim,
                )
            )
        click.secho(f"Ano letivo {ano} criado com 4 bimestres.", fg="green")

    # -- Series -------------------------------------------------------------
    series_padrao = [
        ("Infantil I", NivelEnsino.INFANTIL, 1, 3),
        ("Infantil II", NivelEnsino.INFANTIL, 2, 4),
        ("Infantil III", NivelEnsino.INFANTIL, 3, 5),
        ("1o Ano", NivelEnsino.FUNDAMENTAL_I, 4, 6),
        ("2o Ano", NivelEnsino.FUNDAMENTAL_I, 5, 7),
        ("3o Ano", NivelEnsino.FUNDAMENTAL_I, 6, 8),
        ("4o Ano", NivelEnsino.FUNDAMENTAL_I, 7, 9),
        ("5o Ano", NivelEnsino.FUNDAMENTAL_I, 8, 10),
        ("6o Ano", NivelEnsino.FUNDAMENTAL_II, 9, 11),
        ("7o Ano", NivelEnsino.FUNDAMENTAL_II, 10, 12),
        ("8o Ano", NivelEnsino.FUNDAMENTAL_II, 11, 13),
        ("9o Ano", NivelEnsino.FUNDAMENTAL_II, 12, 14),
        ("1a Serie", NivelEnsino.MEDIO, 13, 15),
        ("2a Serie", NivelEnsino.MEDIO, 14, 16),
        ("3a Serie", NivelEnsino.MEDIO, 15, 17),
    ]
    criadas = 0
    for nome, nivel, ordem, idade in series_padrao:
        existe = (
            db.session.query(Serie)
            .filter(Serie.nome == nome, Serie.nivel_ensino == nivel)
            .first()
        )
        if not existe:
            db.session.add(
                Serie(
                    nome=nome,
                    nivel_ensino=nivel,
                    ordem=ordem,
                    idade_recomendada=idade,
                )
            )
            criadas += 1
    if criadas:
        click.secho(f"{criadas} series criadas.", fg="green")

    # -- Tempos de aula -----------------------------------------------------
    grade_matutino = [
        (1, "1o tempo", time(7, 0), time(7, 50), False),
        (2, "2o tempo", time(7, 50), time(8, 40), False),
        (3, "Intervalo", time(8, 40), time(9, 0), True),
        (4, "3o tempo", time(9, 0), time(9, 50), False),
        (5, "4o tempo", time(9, 50), time(10, 40), False),
        (6, "5o tempo", time(10, 40), time(11, 30), False),
    ]
    grade_vespertino = [
        (1, "1o tempo", time(13, 0), time(13, 50), False),
        (2, "2o tempo", time(13, 50), time(14, 40), False),
        (3, "Intervalo", time(14, 40), time(15, 0), True),
        (4, "3o tempo", time(15, 0), time(15, 50), False),
        (5, "4o tempo", time(15, 50), time(16, 40), False),
        (6, "5o tempo", time(16, 40), time(17, 30), False),
    ]

    tempos_criados = 0
    for turno, grade in (
        (Turno.MATUTINO, grade_matutino),
        (Turno.VESPERTINO, grade_vespertino),
    ):
        for ordem, nome, inicio, fim, intervalo in grade:
            existe = (
                db.session.query(TempoAula)
                .filter(TempoAula.turno == turno, TempoAula.ordem == ordem)
                .first()
            )
            if not existe:
                db.session.add(
                    TempoAula(
                        turno=turno,
                        ordem=ordem,
                        nome=nome,
                        hora_inicio=inicio,
                        hora_fim=fim,
                        e_intervalo=intervalo,
                    )
                )
                tempos_criados += 1
    if tempos_criados:
        click.secho(f"{tempos_criados} tempos de aula criados.", fg="green")

    db.session.commit()
    click.secho("Estrutura inicial pronta.", fg="green", bold=True)


@click.command("popular-demonstracao")
@click.option("--alunos", default=60, help="Quantidade de alunos ficticios.")
@click.confirmation_option(
    prompt="Isso cria dados FICTICIOS. Nunca execute em producao. Continuar?"
)
@with_appcontext
def popular_demonstracao(alunos: int):
    """Popula o banco com dados ficticios para testes e demonstracao."""
    from scripts.seed_dados import popular

    resumo = popular(quantidade_alunos=alunos)
    click.secho("Dados de demonstracao criados:", fg="green", bold=True)
    for chave, valor in resumo.items():
        click.echo(f"  {chave}: {valor}")


__all__ = ["criar_estrutura_inicial", "criar_tabelas", "popular_demonstracao"]
