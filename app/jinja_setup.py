"""Filtros, funcoes globais e contexto dos templates.

Tudo o que os templates enxergam alem das variaveis passadas no
``render_template`` e registrado aqui — um lugar so para responder "de onde
vem esse filtro".
"""

from __future__ import annotations

from datetime import date

from flask import Flask, g

from app.extensions import db
from app.versao import __version__


def configurar_jinja(app: Flask) -> None:
    """Registra filtros, funcoes globais e variaveis de contexto do Jinja2."""
    from app.utils import formatadores

    # -- Filtros -----------------------------------------------------------
    app.jinja_env.filters.update(
        {
            "data": formatadores.formatar_data,
            "data_hora": formatadores.formatar_data_hora,
            "hora": formatadores.formatar_hora,
            "data_extenso": formatadores.formatar_data_extenso,
            "moeda": formatadores.formatar_moeda,
            "nota": formatadores.formatar_nota,
            "quantidade": formatadores.formatar_quantidade,
            "percentual": formatadores.formatar_percentual,
            "cpf": formatadores.formatar_cpf_seguro,
            "telefone": formatadores.formatar_telefone_seguro,
            "cep": formatadores.formatar_cep_seguro,
            "tempo_relativo": formatadores.tempo_relativo,
            "truncar": formatadores.truncar,
            "primeiro_nome": formatadores.primeiro_nome,
            "sim_nao": formatadores.sim_nao,
            "quebra_linha": formatadores.quebra_linha,
        }
    )

    # -- Funcoes globais ---------------------------------------------------
    from app.utils.permissoes import Permissao, usuario_tem_permissao

    def tem_permissao(permissao: str) -> bool:
        """Usado nos templates para esconder acoes indisponiveis.

        Esconder o botao e apenas usabilidade; a rota continua protegida
        pelo decorador. Nunca confiar somente nisto.
        """
        from flask_login import current_user as usuario

        return usuario_tem_permissao(usuario, permissao)

    app.jinja_env.globals.update(
        {
            "tem_permissao": tem_permissao,
            "Permissao": Permissao,
            "APP_NOME": app.config["APP_NOME"],
            "APP_VERSAO": __version__,
        }
    )

    # -- Contexto disponivel em todos os templates -------------------------
    @app.context_processor
    def injetar_contexto():
        from app.models.sistema import ConfiguracaoEscola

        try:
            # Copia em cache: este bloco roda a cada renderizacao de
            # template e os dados institucionais mudam uma vez por semestre.
            escola = ConfiguracaoEscola.obter_para_leitura()
        except Exception:  # noqa: BLE001 - banco ainda nao migrado
            # Mesma armadilha de `carregar_ano_letivo_corrente`: sem o
            # rollback a transacao fica abortada e derruba o restante da
            # requisicao. Aqui e ainda mais silencioso, porque o
            # context_processor roda durante a renderizacao do template.
            db.session.rollback()
            escola = None

        return {
            "escola": escola,
            "ano_letivo_atual": getattr(g, "ano_letivo", None),
            "hoje": date.today(),
        }


__all__ = ["configurar_jinja"]
