"""Comandos de manutencao das contas de acesso."""

from __future__ import annotations

import sys

import click
from flask.cli import with_appcontext

from app.extensions import db


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


@click.command("listar-usuarios")
@with_appcontext
def listar_usuarios():
    """Lista as contas de acesso cadastradas."""
    from app.models.usuario import Usuario

    usuarios = (
        db.session.query(Usuario)
        .order_by(Usuario.papel, Usuario.nome_completo)
        .all()
    )
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


__all__ = ["criar_admin", "listar_usuarios", "redefinir_senha"]
