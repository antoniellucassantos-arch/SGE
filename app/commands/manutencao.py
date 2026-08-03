"""Comandos de operacao: backup, retencao e diagnostico."""

from __future__ import annotations

import sys

import click
from flask.cli import with_appcontext

from app.extensions import db


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
            click.secho(
                "[aviso] Tabela 'usuarios' ausente: rode flask db upgrade",
                fg="yellow",
            )
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
            click.secho(
                f"[ok] {total_admins} administrador(es) ativo(s)", fg="green"
            )
        else:
            click.secho(
                "[aviso] Nenhum administrador ativo: rode flask criar-admin",
                fg="yellow",
            )
            problemas.append("admin")

        corrente = (
            db.session.query(AnoLetivo)
            .filter(AnoLetivo.corrente.is_(True))
            .first()
        )
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


__all__ = ["executar_backup", "limpar_auditoria", "verificar_saude"]
