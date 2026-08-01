"""Testes das primitivas de seguranca: hash, politica de senha e tokens."""

from __future__ import annotations

import pytest

from app.utils.seguranca import (
    apenas_digitos,
    avaliar_politica_senha,
    comparar_seguro,
    gerar_hash_senha,
    gerar_senha_temporaria,
    gerar_token,
    normalizar_email,
    precisa_reidratar_hash,
    remover_acentos,
    validar_token,
    verificar_senha,
)

CHAVE = "chave-secreta-de-teste"


class TestHashSenha:
    def test_hash_e_verificacao(self):
        hash_gerado = gerar_hash_senha("MinhaSenha@123")

        assert hash_gerado.startswith("$argon2")
        assert verificar_senha(hash_gerado, "MinhaSenha@123") is True
        assert verificar_senha(hash_gerado, "SenhaErrada") is False

    def test_hashes_diferentes_para_mesma_senha(self):
        """O sal aleatorio impede identificar senhas iguais pelo hash."""
        assert gerar_hash_senha("Senha@123") != gerar_hash_senha("Senha@123")

    def test_senha_vazia_e_rejeitada(self):
        with pytest.raises(ValueError):
            gerar_hash_senha("")

    @pytest.mark.parametrize(
        "hash_armazenado, senha",
        [(None, "x"), ("", "x"), ("lixo", "x"), ("$argon2id$invalido", "x")],
    )
    def test_entrada_invalida_nao_propaga_excecao(self, hash_armazenado, senha):
        """A rota de login nunca pode vazar detalhe interno por excecao."""
        assert verificar_senha(hash_armazenado, senha) is False

    def test_hash_legado_do_werkzeug_continua_valido(self):
        from werkzeug.security import generate_password_hash

        legado = generate_password_hash("Senha@123", method="pbkdf2:sha256:1000")

        assert verificar_senha(legado, "Senha@123") is True
        # E sinalizado para migracao no proximo login bem-sucedido.
        assert precisa_reidratar_hash(legado) is True

    def test_hash_argon2_atual_nao_precisa_migracao(self):
        assert precisa_reidratar_hash(gerar_hash_senha("Senha@123")) is False


class TestPoliticaSenha:
    def test_senha_forte_e_aceita(self):
        assert avaliar_politica_senha("Escola@2026Seg") == []

    @pytest.mark.parametrize(
        "senha, trecho_esperado",
        [
            ("Ab1", "minimo"),
            ("senhaminuscula1", "maiuscula"),
            ("SENHAMAIUSCULA1", "minuscula"),
            ("SenhaSemNumero", "numero"),
            ("aaaaaaaaA1", "repetir"),
            ("Senha1234", "sequencias"),
        ],
    )
    def test_senhas_fracas_sao_rejeitadas(self, senha, trecho_esperado):
        problemas = avaliar_politica_senha(senha)
        assert any(trecho_esperado in p.lower() for p in problemas), problemas

    def test_senha_comum_e_rejeitada(self):
        problemas = avaliar_politica_senha("senha123")
        assert any("comum" in p.lower() for p in problemas)

    def test_todos_os_problemas_sao_reportados_de_uma_vez(self):
        """Devolver tudo junto evita o antipadrao de descobrir regra a regra."""
        assert len(avaliar_politica_senha("abc")) >= 3

    def test_simbolo_exigido_quando_configurado(self):
        assert avaliar_politica_senha("Escola2026x", exige_simbolo=True)
        assert avaliar_politica_senha("Escola@2026x", exige_simbolo=True) == []


class TestSenhaTemporaria:
    def test_senha_gerada_passa_na_propria_politica(self):
        """Uma senha sorteada que o sistema recusaria seria um bug grave."""
        for _ in range(50):
            assert avaliar_politica_senha(gerar_senha_temporaria()) == []

    def test_respeita_o_tamanho_minimo(self):
        assert len(gerar_senha_temporaria(16)) == 16
        assert len(gerar_senha_temporaria(4)) == 8  # piso de seguranca

    def test_senhas_sao_diferentes_entre_si(self):
        geradas = {gerar_senha_temporaria() for _ in range(50)}
        assert len(geradas) == 50


class TestTokens:
    def test_token_valido_devolve_o_conteudo(self):
        token = gerar_token({"usuario_id": 7}, CHAVE)
        assert validar_token(token, CHAVE) == {"usuario_id": 7}

    def test_token_expirado_e_recusado(self):
        token = gerar_token({"usuario_id": 7}, CHAVE)
        assert validar_token(token, CHAVE, validade_segundos=-1) is None

    def test_token_adulterado_e_recusado(self):
        token = gerar_token({"usuario_id": 7}, CHAVE)
        assert validar_token(token + "x", CHAVE) is None

    def test_chave_diferente_invalida_o_token(self):
        token = gerar_token({"usuario_id": 7}, CHAVE)
        assert validar_token(token, "outra-chave") is None

    def test_sal_diferente_invalida_o_token(self):
        """Um token de outra finalidade nao pode ser aceito aqui."""
        token = gerar_token({"usuario_id": 7}, CHAVE, sal="recuperacao")
        assert validar_token(token, CHAVE, sal="confirmacao") is None

    def test_token_vazio_e_recusado(self):
        assert validar_token("", CHAVE) is None


class TestNormalizacao:
    @pytest.mark.parametrize(
        "entrada, esperado",
        [
            ("  ADMIN@Escola.COM.BR ", "admin@escola.com.br"),
            (None, ""),
            ("", ""),
        ],
    )
    def test_normalizar_email(self, entrada, esperado):
        assert normalizar_email(entrada) == esperado

    @pytest.mark.parametrize(
        "entrada, esperado",
        [
            ("José da Silva", "jose da silva"),
            ("ÁÉÍÓÚ Ção", "aeiou cao"),
            (None, ""),
        ],
    )
    def test_remover_acentos(self, entrada, esperado):
        assert remover_acentos(entrada) == esperado

    def test_apenas_digitos(self):
        assert apenas_digitos("123.456.789-00") == "12345678900"
        assert apenas_digitos("(11) 98765-4321") == "11987654321"
        assert apenas_digitos(None) == ""

    def test_comparacao_segura(self):
        assert comparar_seguro("abc", "abc") is True
        assert comparar_seguro("abc", "abd") is False
        assert comparar_seguro(None, None) is True
