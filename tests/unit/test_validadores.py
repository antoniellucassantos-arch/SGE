"""Testes dos validadores de documentos e datas brasileiras."""

from __future__ import annotations

from datetime import date

import pytest

from app.utils.validadores import (
    calcular_idade,
    cep_valido,
    cnpj_valido,
    cpf_valido,
    data_nascimento_plausivel,
    formatar_cep,
    formatar_cnpj,
    formatar_cpf,
    formatar_telefone,
    telefone_valido,
    uf_valida,
)


class TestCPF:
    @pytest.mark.parametrize(
        "cpf",
        ["52998224725", "529.982.247-25", "16899535009", "168.995.350-09"],
    )
    def test_cpf_valido(self, cpf):
        assert cpf_valido(cpf) is True

    @pytest.mark.parametrize(
        "cpf",
        [
            "11111111111",   # sequencia repetida
            "00000000000",
            "52998224724",   # digito verificador errado
            "1234567890",    # curto demais
            "123456789012",  # longo demais
            "",
            None,
            "abcdefghijk",
        ],
    )
    def test_cpf_invalido(self, cpf):
        assert cpf_valido(cpf) is False

    def test_formatacao(self):
        assert formatar_cpf("52998224725") == "529.982.247-25"
        # Entrada incompleta e devolvida como veio, sem quebrar a tela.
        assert formatar_cpf("123") == "123"


class TestCNPJ:
    @pytest.mark.parametrize("cnpj", ["11222333000181", "11.222.333/0001-81"])
    def test_cnpj_valido(self, cnpj):
        assert cnpj_valido(cnpj) is True

    @pytest.mark.parametrize(
        "cnpj", ["11111111111111", "11222333000182", "1122233300018", "", None]
    )
    def test_cnpj_invalido(self, cnpj):
        assert cnpj_valido(cnpj) is False

    def test_formatacao(self):
        assert formatar_cnpj("11222333000181") == "11.222.333/0001-81"


class TestTelefone:
    @pytest.mark.parametrize(
        "telefone",
        ["11987654321", "(11) 98765-4321", "1132165498", "(11) 3216-5498"],
    )
    def test_telefone_valido(self, telefone):
        assert telefone_valido(telefone) is True

    @pytest.mark.parametrize(
        "telefone",
        [
            "119876543",     # curto
            "119876543210",  # longo
            "11887654321",   # celular sem o 9
            "01987654321",   # DDD invalido
            "",
            None,
        ],
    )
    def test_telefone_invalido(self, telefone):
        assert telefone_valido(telefone) is False

    def test_formatacao(self):
        assert formatar_telefone("11987654321") == "(11) 98765-4321"
        assert formatar_telefone("1132165498") == "(11) 3216-5498"


class TestCEP:
    def test_cep_valido(self):
        assert cep_valido("01310100") is True
        assert cep_valido("01310-100") is True

    @pytest.mark.parametrize("cep", ["0131010", "00000000", "", None])
    def test_cep_invalido(self, cep):
        assert cep_valido(cep) is False

    def test_formatacao(self):
        assert formatar_cep("01310100") == "01310-100"


class TestUF:
    def test_uf_valida(self):
        assert uf_valida("SP") is True
        assert uf_valida("sp") is True
        assert uf_valida(" RJ ") is True

    @pytest.mark.parametrize("uf", ["XX", "", None, "SPP"])
    def test_uf_invalida(self, uf):
        assert uf_valida(uf) is False


class TestDatas:
    def test_calcular_idade(self):
        referencia = date(2026, 7, 31)
        assert calcular_idade(date(2000, 7, 31), referencia) == 26
        assert calcular_idade(date(2000, 8, 1), referencia) == 25  # antes do aniversario
        assert calcular_idade(None) is None

    def test_data_futura_e_implausivel(self):
        futuro = date(date.today().year + 1, 1, 1)
        assert data_nascimento_plausivel(futuro) is False

    def test_idade_absurda_e_implausivel(self):
        assert data_nascimento_plausivel(date(1800, 1, 1)) is False

    def test_data_normal_e_plausivel(self):
        assert data_nascimento_plausivel(date(2010, 3, 15)) is True

    def test_data_ausente_e_implausivel(self):
        assert data_nascimento_plausivel(None) is False
