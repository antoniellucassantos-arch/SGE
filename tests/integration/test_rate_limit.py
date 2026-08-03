"""Testes da protecao contra forca bruta no login.

Por que este arquivo existe separado: o ambiente de teste desliga o rate
limiting (``RATELIMIT_ENABLED = False``), senao dezenas de testes que fazem
login em sequencia comecariam a receber 429 e falhariam por motivo errado.

O efeito colateral era que a protecao de forca bruta — uma das defesas mais
importantes do sistema, e a unica que depende de configuracao de infra —
nunca era exercitada. Aqui ela e ligada de proposito, em uma aplicacao
propria, com limite baixo para o teste ser rapido.
"""

from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db as _db
from app.extensions import limiter
from config.settings import TestingConfig
from tests.conftest import SENHA_PADRAO, criar_usuario


@pytest.fixture
def app_com_limite(monkeypatch):
    """Aplicacao de teste com o limitador ligado e limite curto."""
    monkeypatch.setattr(TestingConfig, "RATELIMIT_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "RATELIMIT_LOGIN", "3 per minute")

    aplicacao = create_app("testing")

    with aplicacao.app_context():
        _db.create_all()
        yield aplicacao
        _db.session.remove()
        _db.drop_all()

    # O armazenamento e do processo, nao da aplicacao: sem esta limpeza, o
    # proximo teste comecaria com a cota ja gasta.
    limiter.reset()


@pytest.fixture
def cliente_limitado(app_com_limite):
    return app_com_limite.test_client()


def _tentar_login(cliente, senha: str = "SenhaErrada@1"):
    return cliente.post(
        "/auth/login",
        data={"email": "vitima@escola.com.br", "senha": senha},
    )


class TestForcaBrutaNoLogin:
    def test_tentativas_repetidas_recebem_429(
        self, app_com_limite, cliente_limitado
    ):
        """Sem isto, um script tenta senhas a noite inteira sem obstaculo."""
        criar_usuario("vitima@escola.com.br")

        for tentativa in range(3):
            resposta = _tentar_login(cliente_limitado)
            assert resposta.status_code != 429, (
                f"bloqueou cedo demais, na tentativa {tentativa + 1}"
            )

        bloqueada = _tentar_login(cliente_limitado)
        assert bloqueada.status_code == 429

    def test_bloqueio_alcanca_a_senha_correta(
        self, app_com_limite, cliente_limitado
    ):
        """O limite vale por origem, nao por resultado da tentativa.

        Se a senha certa passasse durante o bloqueio, o atacante teria como
        confirmar o acerto — e o limitador viraria um oraculo.
        """
        criar_usuario("vitima@escola.com.br")

        for _ in range(4):
            _tentar_login(cliente_limitado)

        resposta = _tentar_login(cliente_limitado, senha=SENHA_PADRAO)
        assert resposta.status_code == 429

    def test_pagina_de_login_continua_acessivel(
        self, app_com_limite, cliente_limitado
    ):
        """O limite e sobre POST: bloquear o GET tiraria o sistema do ar."""
        for _ in range(5):
            _tentar_login(cliente_limitado)

        assert cliente_limitado.get("/auth/login").status_code == 200

    def test_ambiente_de_teste_mantem_o_limitador_desligado(self, app):
        """Regressao da propria fixture.

        Se o padrao voltasse a ser "ligado", dezenas de testes que fazem
        login em sequencia passariam a falhar com 429 — e a causa levaria
        horas para ser encontrada.
        """
        assert app.config["RATELIMIT_ENABLED"] is False
