"""Blueprints do SGE — a camada HTTP da aplicacao.

Organizacao
-----------
Cada modulo funcional e um pacote com, no maximo, tres arquivos::

    app/blueprints/<modulo>/
        __init__.py   -> cria o Blueprint e importa as rotas
        rotas.py      -> controladores (finos): traduzem HTTP <-> service
        formularios.py-> WTForms com validacao de entrada

As rotas nao contem regra de negocio. Elas validam o formulario, delegam ao
service correspondente e traduzem o resultado (ou a excecao de dominio) em
resposta HTTP. Toda a logica reutilizavel vive em ``app/services/``.

Nota sobre a estrutura: o planejamento previa pastas ``routes/`` e
``controllers/`` separadas. Em Flask essa divisao gera indirecao sem ganho —
a funcao de rota **e** o controlador. Optou-se por manter as duas
responsabilidades no mesmo arquivo (``rotas.py``, deliberadamente fino) e
extrair a logica para ``services/``, que e a separacao que de fato produz
codigo testavel e reaproveitavel.
"""

from __future__ import annotations

from importlib import import_module

from flask import Flask

#: Blueprints registrados na aplicacao: (modulo, atributo, prefixo de URL).
#:
#: Manter a lista declarativa torna trivial saber o que existe no sistema e
#: em qual URL, sem cacar ``register_blueprint`` espalhados pelo codigo.
#:
#: Para desativar um modulo temporariamente, comente a linha. Existiu aqui um
#: conjunto ``BLUEPRINTS_ATIVOS`` com essa intencao, mas ele era construido a
#: partir desta mesma tupla — filtrava exatamente nada. Comentar a linha faz
#: o que o mecanismo prometia, e a ausencia fica visivel na revisao.
BLUEPRINTS: tuple[tuple[str, str, str | None], ...] = (
    ("app.blueprints.auth", "bp", "/auth"),
    ("app.blueprints.painel", "bp", "/"),
    ("app.blueprints.alunos", "bp", "/alunos"),
    ("app.blueprints.professores", "bp", "/professores"),
    ("app.blueprints.funcionarios", "bp", "/funcionarios"),
    ("app.blueprints.responsaveis", "bp", "/responsaveis"),
    ("app.blueprints.turmas", "bp", "/turmas"),
    ("app.blueprints.disciplinas", "bp", "/disciplinas"),
    ("app.blueprints.matriculas", "bp", "/matriculas"),
    ("app.blueprints.frequencia", "bp", "/frequencia"),
    ("app.blueprints.notas", "bp", "/notas"),
    ("app.blueprints.boletim", "bp", "/boletim"),
    ("app.blueprints.horarios", "bp", "/horarios"),
    ("app.blueprints.avisos", "bp", "/avisos"),
    ("app.blueprints.relatorios", "bp", "/relatorios"),
    ("app.blueprints.usuarios", "bp", "/usuarios"),
    ("app.blueprints.configuracoes", "bp", "/configuracoes"),
    ("app.blueprints.backup", "bp", "/backup"),
    ("app.blueprints.auditoria", "bp", "/auditoria"),
    ("app.blueprints.api", "bp", "/api/v1"),
)


def registrar_blueprints(app: Flask) -> None:
    """Importa e registra todos os blueprints declarados em ``BLUEPRINTS``."""
    for caminho_modulo, atributo, prefixo in BLUEPRINTS:
        modulo = import_module(caminho_modulo)
        blueprint = getattr(modulo, atributo)
        app.register_blueprint(blueprint, url_prefix=prefixo)
        app.logger.debug("Blueprint registrado: %s -> %s", blueprint.name, prefixo)


__all__ = ["BLUEPRINTS", "registrar_blueprints"]
