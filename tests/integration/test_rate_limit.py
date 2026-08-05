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
    """Aplicacao de teste com o limitador ligado e limite curto.

    A limpeza no fim nao e zelo: sem ela, este arquivo derruba o resto da
    suite. O ``limiter`` e um objeto de modulo, compartilhado por todas as
    aplicacoes criadas no processo. Ligado aqui, ele **continua ligado**
    depois — a factory so chama ``init_app`` quando ``RATELIMIT_ENABLED`` e
    verdadeiro, entao nada o desliga de volta.

    O efeito e traicoeiro: os logins de todos os testes seguintes contam
    contra a mesma cota de 127.0.0.1. Passada a cota, ``autenticar()`` recebe
    429 em silencio, o cliente segue anonimo, e os testes quebram com 302
    onde esperavam 200 ou 403 — longe daqui, sem nada apontando para ca.
    Foi o que aconteceu: apareceu so quando a suite passou de 370 testes.
    """
    monkeypatch.setattr(TestingConfig, "RATELIMIT_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "RATELIMIT_LOGIN", "3 per minute")

    aplicacao = create_app("testing")

    with aplicacao.app_context():
        _db.create_all()
        limiter.reset()  # comeca com a cota inteira, venha de onde vier
        yield aplicacao

        # `reset()` precisa do contexto da aplicacao para achar o
        # armazenamento — fora do `with` ele nao limpa nada.
        limiter.reset()
        _db.session.remove()
        _db.drop_all()

    # Desligar explicitamente, e nao "restaurar o valor anterior": o
    # `Limiter` nasce com `enabled=True`, entao restaurar deixaria ligado.
    #
    # O que mantinha o limitador inerte na suite nao era essa bandeira, e sim
    # o `init_app` nunca ter sido chamado. Depois da primeira chamada — que
    # este teste faz de proposito — o objeto fica armado para o processo
    # inteiro, e so um `enabled = False` o desarma.
    limiter.enabled = False


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


class TestLimitadorNaoVazaParaOResto:
    """A fixture acima liga um objeto de modulo. Ela precisa desliga-lo.

    Este teste roda **depois** de `TestForcaBrutaNoLogin` (ordem de
    declaracao no arquivo) e confere que a limpeza aconteceu. Sem ele, o
    vazamento so apareceria daqui a alguns meses, como um 302 inexplicavel
    em outro arquivo — que foi exatamente como apareceu da primeira vez.
    """

    def test_limitador_ficou_desarmado(self):
        assert limiter.enabled is False

    def test_logins_repetidos_nao_tomam_429(self, app, cliente, admin):
        """O padrao da suite: varios testes autenticando em sequencia."""
        for _ in range(8):
            resposta = cliente.post(
                "/auth/login",
                data={"email": admin.email, "senha": SENHA_PADRAO},
            )
            assert resposta.status_code != 429, (
                "o limitador ficou ligado e vai derrubar o resto da suite"
            )
