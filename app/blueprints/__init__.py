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
