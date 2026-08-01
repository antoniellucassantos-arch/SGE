"""Testes do fluxo de autenticacao e das defesas de login."""

from __future__ import annotations

import pytest

from app.extensions import db
from app.services import auth_service
from app.services.excecoes import ErroAutenticacao, ErroValidacao
from tests.conftest import SENHA_PADRAO, criar_usuario


class TestLoginPelaInterface:
    def test_pagina_de_login_e_publica(self, cliente):
        resposta = cliente.get("/auth/login")
        assert resposta.status_code == 200

    def test_login_com_credenciais_validas(self, cliente, admin):
        resposta = cliente.post(
            "/auth/login",
            data={"email": admin.email, "senha": SENHA_PADRAO},
            follow_redirects=True,
        )
        assert resposta.status_code == 200
        assert b"Painel" in resposta.data

    def test_login_com_senha_errada_e_recusado(self, cliente, admin):
        resposta = cliente.post(
            "/auth/login", data={"email": admin.email, "senha": "ErradaX@1"}
        )
        assert resposta.status_code == 401

    def test_email_normalizado_no_login(self, cliente, admin):
        """Digitar o e-mail com maiusculas nao pode impedir o acesso."""
        resposta = cliente.post(
            "/auth/login",
            data={"email": admin.email.upper(), "senha": SENHA_PADRAO},
            follow_redirects=True,
        )
        assert b"Painel" in resposta.data

    def test_area_restrita_exige_login(self, cliente):
        resposta = cliente.get("/", follow_redirects=False)
        assert resposta.status_code == 302
        assert "/auth/login" in resposta.headers["Location"]

    def test_logout_encerra_a_sessao(self, cliente_admin):
        cliente_admin.get("/auth/logout")
        resposta = cliente_admin.get("/", follow_redirects=False)
        assert resposta.status_code == 302


class TestServicoDeAutenticacao:
    def test_autenticar_com_sucesso(self, app, admin):
        usuario = auth_service.autenticar(admin.email, SENHA_PADRAO)
        assert usuario.id == admin.id
        assert usuario.ultimo_login_em is not None

    def test_usuario_inexistente_gera_mensagem_generica(self, app):
        """Nao revelar quais e-mails existem impede enumerar as contas."""
        with pytest.raises(ErroAutenticacao) as erro:
            auth_service.autenticar("naoexiste@escola.com.br", "QualquerX@1")
        assert erro.value.mensagem == auth_service.MENSAGEM_CREDENCIAL_INVALIDA

    def test_senha_errada_gera_a_mesma_mensagem(self, app, admin):
        with pytest.raises(ErroAutenticacao) as erro:
            auth_service.autenticar(admin.email, "ErradaX@1")
        assert erro.value.mensagem == auth_service.MENSAGEM_CREDENCIAL_INVALIDA

    def test_conta_inativa_nao_autentica(self, app):
        usuario = criar_usuario("inativo@escola.com.br", ativo=False)
        with pytest.raises(ErroAutenticacao) as erro:
            auth_service.autenticar(usuario.email, SENHA_PADRAO)
        assert "desativada" in erro.value.mensagem.lower()

    def test_bloqueio_apos_tentativas_malsucedidas(self, app, admin):
        """Forca bruta e barrada apos o limite configurado."""
        limite = app.config["LOGIN_MAX_TENTATIVAS"]

        for _ in range(limite - 1):
            with pytest.raises(ErroAutenticacao):
                auth_service.autenticar(admin.email, "ErradaX@1")

        # A tentativa que atinge o limite bloqueia a conta.
        with pytest.raises(ErroAutenticacao) as erro:
            auth_service.autenticar(admin.email, "ErradaX@1")
        assert "bloqueada" in erro.value.mensagem.lower()

        db.session.refresh(admin)
        assert admin.esta_bloqueado is True

        # Agora nem a senha correta entra.
        with pytest.raises(ErroAutenticacao):
            auth_service.autenticar(admin.email, SENHA_PADRAO)

    def test_login_bem_sucedido_zera_o_contador(self, app, admin):
        with pytest.raises(ErroAutenticacao):
            auth_service.autenticar(admin.email, "ErradaX@1")

        auth_service.autenticar(admin.email, SENHA_PADRAO)
        db.session.refresh(admin)
        assert admin.tentativas_falhas == 0


class TestAlteracaoDeSenha:
    def test_alterar_senha_com_sucesso(self, app, admin):
        auth_service.alterar_senha(admin, SENHA_PADRAO, "NovaSenha@2026")

        assert admin.conferir_senha("NovaSenha@2026") is True
        assert admin.deve_trocar_senha is False

    def test_senha_atual_incorreta_e_recusada(self, app, admin):
        with pytest.raises(ErroValidacao):
            auth_service.alterar_senha(admin, "ErradaX@1", "NovaSenha@2026")

    def test_nova_senha_igual_a_atual_e_recusada(self, app, admin):
        with pytest.raises(ErroValidacao) as erro:
            auth_service.alterar_senha(admin, SENHA_PADRAO, SENHA_PADRAO)
        assert "diferente" in erro.value.mensagem.lower()

    def test_senha_fraca_e_recusada(self, app, admin):
        with pytest.raises(ErroValidacao):
            auth_service.alterar_senha(admin, SENHA_PADRAO, "123")

    def test_troca_obrigatoria_redireciona(self, cliente, app):
        """Primeiro acesso deve levar direto a troca de senha."""
        usuario = criar_usuario("novo@escola.com.br", deve_trocar_senha=True)

        cliente.post(
            "/auth/login", data={"email": usuario.email, "senha": SENHA_PADRAO}
        )
        resposta = cliente.get("/", follow_redirects=False)

        assert resposta.status_code == 302
        assert "alterar-senha" in resposta.headers["Location"]


class TestRecuperacaoDeSenha:
    def test_token_valido_permite_redefinir(self, app, admin):
        _, token = auth_service.solicitar_recuperacao(admin.email)
        assert token is not None

        auth_service.redefinir_senha_por_token(token, "Recuperada@2026")
        assert admin.conferir_senha("Recuperada@2026") is True

    def test_token_e_de_uso_unico(self, app, admin):
        """Trocar a senha invalida os tokens emitidos antes."""
        _, token = auth_service.solicitar_recuperacao(admin.email)
        auth_service.redefinir_senha_por_token(token, "Primeira@2026")

        with pytest.raises(ErroAutenticacao):
            auth_service.redefinir_senha_por_token(token, "Segunda@2026")

    def test_token_invalido_e_recusado(self, app):
        with pytest.raises(ErroAutenticacao):
            auth_service.redefinir_senha_por_token("token-falso", "Nova@2026")

    def test_email_inexistente_nao_revela_nada(self, app):
        usuario, token = auth_service.solicitar_recuperacao("naoexiste@escola.com.br")
        assert usuario is None and token is None

    def test_resposta_identica_para_email_existente_ou_nao(self, cliente, admin):
        """A tela precisa responder igual nos dois casos."""
        primeira = cliente.post(
            "/auth/recuperar-senha", data={"email": admin.email},
            follow_redirects=True,
        )
        segunda = cliente.post(
            "/auth/recuperar-senha", data={"email": "naoexiste@escola.com.br"},
            follow_redirects=True,
        )
        assert primeira.status_code == segunda.status_code == 200


class TestProtecaoDeRedirecionamento:
    def test_next_externo_e_ignorado(self, cliente, admin):
        """Open redirect e vetor classico de phishing."""
        resposta = cliente.post(
            "/auth/login?next=https://site-malicioso.example",
            data={"email": admin.email, "senha": SENHA_PADRAO},
            follow_redirects=False,
        )
        assert "site-malicioso" not in resposta.headers.get("Location", "")

    def test_next_interno_e_respeitado(self, cliente, admin):
        resposta = cliente.post(
            "/auth/login?next=/alunos/",
            data={"email": admin.email, "senha": SENHA_PADRAO},
            follow_redirects=False,
        )
        assert "/alunos/" in resposta.headers.get("Location", "")


class TestCabecalhosDeSeguranca:
    def test_cabecalhos_presentes(self, cliente):
        resposta = cliente.get("/auth/login")

        assert resposta.headers["X-Content-Type-Options"] == "nosniff"
        assert resposta.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert "Content-Security-Policy" in resposta.headers
        assert "Referrer-Policy" in resposta.headers

    def test_csp_nao_permite_script_inline(self, cliente):
        """Bloquear inline e o que impede XSS por interpolacao em <script>."""
        csp = cliente.get("/auth/login").headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp
        assert "unsafe-inline" not in csp.split("style-src")[0]
