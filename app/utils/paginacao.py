"""Apoio a listagens paginadas, filtradas e ordenadas.

Toda listagem do sistema usa estes helpers. Isso garante que o comportamento
(limite de itens por pagina, colunas ordenaveis permitidas, preservacao dos
filtros na URL) seja identico em alunos, professores, turmas e relatorios —
e, principalmente, que nenhuma tela carregue milhares de linhas de uma vez.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from flask import current_app, request
from sqlalchemy import asc, desc


def obter_pagina() -> int:
    """Le o numero da pagina da querystring, com validacao."""
    try:
        pagina = int(request.args.get("pagina", 1))
    except (TypeError, ValueError):
        return 1
    return max(1, pagina)


def obter_por_pagina(padrao: int | None = None) -> int:
    """Le a quantidade de itens por pagina, limitada pelo teto configurado.

    O teto existe para impedir que ``?por_pagina=100000`` derrube o servidor —
    uma negacao de servico trivial se o valor viesse direto do usuario.
    """
    padrao = padrao or current_app.config.get("ITENS_POR_PAGINA", 20)
    teto = current_app.config.get("ITENS_POR_PAGINA_MAXIMO", 100)

    try:
        valor = int(request.args.get("por_pagina", padrao))
    except (TypeError, ValueError):
        return padrao

    return max(5, min(valor, teto))


def paginar(consulta, pagina: int | None = None, por_pagina: int | None = None):
    """Aplica paginacao a uma query do SQLAlchemy.

    ``error_out=False`` faz uma pagina inexistente devolver lista vazia em vez
    de 404: o usuario que estava na pagina 5 e apagou registros nao deve
    receber um erro.
    """
    return consulta.paginate(
        page=pagina or obter_pagina(),
        per_page=por_pagina or obter_por_pagina(),
        error_out=False,
    )


def aplicar_ordenacao(
    consulta,
    colunas_permitidas: dict[str, Any],
    coluna_padrao: str,
    direcao_padrao: str = "asc",
):
    """Ordena a consulta apenas por colunas explicitamente permitidas.

    O dicionario ``colunas_permitidas`` funciona como lista de permissao: o
    nome vindo da URL nunca chega ao SQL. Sem isso, ``?ordenar=<expressao>``
    seria um vetor de injecao e de vazamento de estrutura interna.

    Args:
        colunas_permitidas: ``{"nome": Model.nome_normalizado, ...}``
        coluna_padrao: chave usada quando o parametro esta ausente ou invalido.
    """
    chave = request.args.get("ordenar", coluna_padrao)
    if chave not in colunas_permitidas:
        chave = coluna_padrao

    direcao = request.args.get("direcao", direcao_padrao).lower()
    if direcao not in ("asc", "desc"):
        direcao = direcao_padrao

    coluna = colunas_permitidas[chave]
    ordenador = desc if direcao == "desc" else asc

    return consulta.order_by(ordenador(coluna)), chave, direcao


def parametros_preservados(*excluir: str) -> dict[str, str]:
    """Devolve os parametros atuais da URL, exceto os informados.

    Usado para manter filtros e busca ao trocar de pagina ou de ordenacao —
    perder o filtro ao paginar e um dos defeitos mais irritantes em sistemas
    administrativos.
    """
    remover = set(excluir) | {"pagina"}
    return {
        chave: valor
        for chave, valor in request.args.items()
        if chave not in remover and valor not in (None, "")
    }


def alternar_direcao(coluna_atual: str, coluna: str, direcao_atual: str) -> str:
    """Direcao do proximo clique no cabecalho de uma coluna ordenavel."""
    if coluna_atual != coluna:
        return "asc"
    return "desc" if direcao_atual == "asc" else "asc"


def filtro_texto(valor: str | None) -> str | None:
    """Normaliza o termo de busca; devolve ``None`` quando irrelevante.

    Termos com um unico caractere sao descartados: eles casariam com quase
    toda a base e produziriam uma varredura completa da tabela.
    """
    termo = (valor or "").strip()
    return termo if len(termo) >= 2 else None


def extrair_filtros(nomes: Iterable[str]) -> dict[str, str]:
    """Coleta os filtros presentes na querystring, ignorando os vazios."""
    filtros: dict[str, str] = {}
    for nome in nomes:
        valor = (request.args.get(nome) or "").strip()
        if valor:
            filtros[nome] = valor
    return filtros
