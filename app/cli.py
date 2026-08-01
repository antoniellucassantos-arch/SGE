"""Comandos de linha de comando do SGE (``flask <comando>``).

Existem para que tarefas de operacao — criar o primeiro administrador,
preparar o banco, gerar backup, popular dados de demonstracao — sejam
reproduzives e auditaveis, em vez de dependerem de alguem abrindo um console
Python e digitando comandos de memoria.
"""

from __future__ import annotations

import sys
from datetime import date, time

import click
from flask import Flask
from flask.cli import with_appcontext

from app.extensions import db


def registrar_comandos(app: Flask) -> None:
    """Registra todos os comandos na instancia da aplicacao."""
    for comando in (
        criar_tabelas,
        criar_admin,
        criar_estrutura_inicial,
        popular_demonstracao,
        listar_usuarios,
        redefinir_senha,
        executar_backup,
        limpar_auditoria,
        verificar_saude,
    ):
        app.cli.add_command(comando)


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------
@click.command("criar-tabelas")
@with_appcontext
def criar_tabelas():
    """Cria as tabelas direto do metadata (atalho para desenvolvimento).

    Em producao use sempre ``flask db upgrade``: apenas as migrations
    garantem que o banco existente evolua sem perda de dados.
    """
    db.create_all()
    click.secho("Tabelas criadas com sucesso.", fg="green")


@click.command("criar-admin")
@click.option("--nome", prompt="Nome completo", help="Nome do administrador.")
@click.option("--email", prompt="E-mail", help="E-mail de login.")
@click.password_option("--senha", prompt="Senha", confirmation_prompt=True)
@with_appcontext
def criar_admin(nome: str, email: str, senha: str):
    """Cria (ou promove) uma conta de administrador."""
    from app.models.enums import PapelUsuario
    from app.models.usuario import Usuario
    from app.utils.seguranca import avaliar_politica_senha, normalizar_email

    email = normalizar_email(email)

    problemas = avaliar_politica_senha(senha)
    if problemas:
        click.secho("Senha rejeitada pela politica de seguranca:", fg="red")
        for problema in problemas:
            click.echo(f"  - {problema}")
        sys.exit(1)

    existente = db.session.query(Usuario).filter(Usuario.email == email).first()
    if existente:
        if not click.confirm(
            f"Ja existe um usuario com o e-mail {email}. "
            "Deseja promove-lo a administrador e redefinir a senha?"
        ):
            click.secho("Operacao cancelada.", fg="yellow")
            return
        existente.papel = PapelUsuario.ADMINISTRADOR
        existente.ativo = True
        existente.definir_senha(senha)
        db.session.commit()
        click.secho(f"Usuario {email} promovido a administrador.", fg="green")
        return

    usuario = Usuario(
        nome_completo=nome,
        email=email,
        papel=PapelUsuario.ADMINISTRADOR,
        ativo=True,
    )
    usuario.definir_senha(senha)
    db.session.add(usuario)
    db.session.commit()

    click.secho(f"Administrador criado: {email}", fg="green")


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


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
@click.command("listar-usuarios")
@with_appcontext
def listar_usuarios():
    """Lista as contas de acesso cadastradas."""
    from app.models.usuario import Usuario

    usuarios = db.session.query(Usuario).order_by(Usuario.papel, Usuario.nome_completo).all()
    if not usuarios:
        click.secho("Nenhum usuario cadastrado.", fg="yellow")
        return

    click.echo(f"{'ID':>4}  {'PAPEL':<15} {'E-MAIL':<35} {'NOME':<30} SITUACAO")
    click.echo("-" * 100)
    for usuario in usuarios:
        situacao = "ativo" if usuario.ativo else "inativo"
        if usuario.esta_bloqueado:
            situacao = "bloqueado"
        click.echo(
            f"{usuario.id:>4}  {usuario.papel.value:<15} {usuario.email:<35} "
            f"{usuario.nome_completo[:30]:<30} {situacao}"
        )
    click.echo(f"\nTotal: {len(usuarios)} usuario(s).")


@click.command("redefinir-senha")
@click.option("--email", prompt="E-mail do usuario")
@with_appcontext
def redefinir_senha(email: str):
    """Gera uma senha temporaria e exige troca no proximo acesso."""
    from app.models.usuario import Usuario
    from app.utils.seguranca import gerar_senha_temporaria, normalizar_email

    usuario = (
        db.session.query(Usuario)
        .filter(Usuario.email == normalizar_email(email))
        .first()
    )
    if not usuario:
        click.secho(f"Usuario nao encontrado: {email}", fg="red")
        sys.exit(1)

    senha = gerar_senha_temporaria()
    usuario.definir_senha(senha, exigir_troca=True)
    usuario.desbloquear()
    db.session.commit()

    click.secho(f"Senha temporaria de {usuario.email}:", fg="green")
    click.secho(f"  {senha}", fg="yellow", bold=True)
    click.echo("O usuario devera troca-la no proximo acesso.")


# ---------------------------------------------------------------------------
# Operacao
# ---------------------------------------------------------------------------
@click.command("backup")
@click.option("--automatico", is_flag=True, help="Marca como backup automatico.")
@with_appcontext
def executar_backup(automatico: bool):
    """Gera um backup do banco de dados."""
    from app.services.backup_service import gerar_backup

    registro = gerar_backup(automatico=automatico)
    if registro.sucesso:
        click.secho(
            f"Backup gerado: {registro.nome_arquivo} ({registro.tamanho_legivel})",
            fg="green",
        )
    else:
        click.secho(f"Falha no backup: {registro.mensagem_erro}", fg="red")
        sys.exit(1)


@click.command("limpar-auditoria")
@click.option("--dias", default=365, help="Retencao em dias.")
@click.confirmation_option(prompt="Remover registros de auditoria antigos?")
@with_appcontext
def limpar_auditoria(dias: int):
    """Remove registros de auditoria fora do periodo de retencao."""
    from app.services.auditoria_service import limpar_antigos

    removidos = limpar_antigos(dias=dias)
    click.secho(f"{removidos} registro(s) removido(s).", fg="green")


@click.command("verificar-saude")
@with_appcontext
def verificar_saude():
    """Diagnostico rapido da instalacao (banco, pastas, dados essenciais)."""
    from flask import current_app
    from sqlalchemy import inspect, text

    from app.models.estrutura import AnoLetivo
    from app.models.usuario import Usuario

    problemas: list[str] = []
    click.secho("Diagnostico do SGE", fg="cyan", bold=True)
    click.echo("-" * 50)

    # Banco
    try:
        db.session.execute(text("SELECT 1"))
        click.secho("[ok] Conexao com o banco de dados", fg="green")
    except Exception as erro:  # noqa: BLE001
        click.secho(f"[falha] Banco de dados: {erro}", fg="red")
        problemas.append("banco")

    # Tabelas
    try:
        tabelas = inspect(db.engine).get_table_names()
        click.secho(f"[ok] {len(tabelas)} tabelas encontradas", fg="green")
        if "usuarios" not in tabelas:
            click.secho("[aviso] Tabela 'usuarios' ausente: rode flask db upgrade", fg="yellow")
            problemas.append("migrations")
    except Exception as erro:  # noqa: BLE001
        click.secho(f"[falha] Inspecao de tabelas: {erro}", fg="red")
        problemas.append("tabelas")

    # Diretorios
    for rotulo, caminho in (
        ("uploads", current_app.config["PASTA_UPLOADS"]),
        ("backups", current_app.config["PASTA_BACKUPS"]),
        ("logs", current_app.config["PASTA_LOGS"]),
    ):
        if caminho.exists():
            click.secho(f"[ok] Pasta {rotulo}: {caminho}", fg="green")
        else:
            click.secho(f"[aviso] Pasta {rotulo} ausente: {caminho}", fg="yellow")

    # Dados essenciais
    try:
        total_admins = (
            db.session.query(Usuario)
            .filter(Usuario.papel == "administrador", Usuario.ativo.is_(True))
            .count()
        )
        if total_admins:
            click.secho(f"[ok] {total_admins} administrador(es) ativo(s)", fg="green")
        else:
            click.secho("[aviso] Nenhum administrador ativo: rode flask criar-admin", fg="yellow")
            problemas.append("admin")

        corrente = db.session.query(AnoLetivo).filter(AnoLetivo.corrente.is_(True)).first()
        if corrente:
            click.secho(f"[ok] Ano letivo corrente: {corrente.ano}", fg="green")
        else:
            click.secho("[aviso] Nenhum ano letivo corrente definido", fg="yellow")
            problemas.append("ano_letivo")
    except Exception as erro:  # noqa: BLE001
        click.secho(f"[falha] Consulta de dados essenciais: {erro}", fg="red")

    # Seguranca
    if current_app.config["SECRET_KEY"] == "sge-chave-insegura-apenas-para-dev":
        click.secho("[aviso] SECRET_KEY de desenvolvimento em uso", fg="yellow")

    click.echo("-" * 50)
    if problemas:
        click.secho(f"Pendencias: {', '.join(problemas)}", fg="yellow", bold=True)
    else:
        click.secho("Sistema saudavel.", fg="green", bold=True)
