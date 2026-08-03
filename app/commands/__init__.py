"""Comandos de linha de comando do SGE (``flask <comando>``).

Existem para que tarefas de operacao — criar o primeiro administrador,
preparar o banco, gerar backup, popular dados de demonstracao — sejam
reproduziveis e auditaveis, em vez de dependerem de alguem abrindo um console
Python e digitando comandos de memoria.

Um arquivo por grupo:

===========================  ===========================================
``banco.py``                 estrutura e dados iniciais
``usuarios.py``              contas de acesso
``manutencao.py``            backup, retencao e diagnostico
===========================  ===========================================
"""

from __future__ import annotations

from flask import Flask

from app.commands.banco import (
    criar_estrutura_inicial,
    criar_tabelas,
    popular_demonstracao,
)
from app.commands.manutencao import (
    executar_backup,
    limpar_auditoria,
    verificar_saude,
)
from app.commands.usuarios import criar_admin, listar_usuarios, redefinir_senha

#: Todos os comandos expostos pelo ``flask``.
COMANDOS = (
    criar_tabelas,
    criar_admin,
    criar_estrutura_inicial,
    popular_demonstracao,
    listar_usuarios,
    redefinir_senha,
    executar_backup,
    limpar_auditoria,
    verificar_saude,
)


def registrar_comandos(app: Flask) -> None:
    """Registra todos os comandos na instancia da aplicacao."""
    for comando in COMANDOS:
        app.cli.add_command(comando)


__all__ = ["COMANDOS", "registrar_comandos"]
