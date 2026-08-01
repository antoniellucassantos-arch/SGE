"""Rotas de backup do banco de dados."""

from __future__ import annotations

from flask import flash, redirect, render_template, send_file, url_for
from flask_login import current_user, login_required

from app.blueprints.backup import bp
from app.services import backup_service
from app.services.excecoes import ErroDominio
from app.utils.decoradores import requer_permissao
from app.utils.permissoes import Permissao


@bp.route("/")
@login_required
@requer_permissao(Permissao.BACKUP_EXECUTAR)
def index():
    """Historico de backups e acoes disponiveis."""
    return render_template(
        "backup/index.html",
        backups=backup_service.listar(),
        estatisticas=backup_service.estatisticas(),
    )


@bp.route("/gerar", methods=["POST"])
@login_required
@requer_permissao(Permissao.BACKUP_EXECUTAR)
def gerar():
    """Gera um backup manual do banco."""
    registro = backup_service.gerar_backup(
        automatico=False, usuario_id=current_user.id
    )

    if registro.sucesso:
        flash(
            f"Backup gerado com sucesso: {registro.nome_arquivo} "
            f"({registro.tamanho_legivel}).",
            "success",
        )
    else:
        flash(
            f"Falha ao gerar o backup: {registro.mensagem_erro}",
            "danger",
        )

    return redirect(url_for("backup.index"))


@bp.route("/<int:backup_id>/baixar")
@login_required
@requer_permissao(Permissao.BACKUP_EXECUTAR)
def baixar(backup_id: int):
    """Baixa o arquivo de um backup."""
    registro = backup_service.buscar(backup_id)

    try:
        caminho = backup_service.caminho_para_download(registro)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
        return redirect(url_for("backup.index"))

    return send_file(
        caminho,
        as_attachment=True,
        download_name=registro.nome_arquivo,
        mimetype="application/gzip",
    )


@bp.route("/<int:backup_id>/excluir", methods=["POST"])
@login_required
@requer_permissao(Permissao.BACKUP_EXECUTAR)
def excluir(backup_id: int):
    """Remove um backup do disco e do historico."""
    registro = backup_service.buscar(backup_id)
    nome = registro.nome_arquivo

    try:
        backup_service.excluir(registro, usuario_id=current_user.id)
    except ErroDominio as erro:
        flash(erro.mensagem, "danger")
    else:
        flash(f"Backup {nome} removido.", "success")

    return redirect(url_for("backup.index"))


@bp.route("/<int:backup_id>/restaurar")
@login_required
@requer_permissao(Permissao.BACKUP_RESTAURAR)
def restaurar(backup_id: int):
    """Exibe as instrucoes de restauracao.

    A restauracao nao e executada pela interface web: ela sobrescreve o
    banco inteiro e e irreversivel. Exigir execucao no servidor garante que
    uma pessoa tecnica conduza o procedimento.
    """
    registro = backup_service.buscar(backup_id)

    return render_template(
        "backup/restaurar.html",
        backup=registro,
        instrucoes=backup_service.instrucoes_restauracao(registro),
    )
