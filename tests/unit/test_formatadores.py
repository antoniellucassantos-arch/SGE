"""Formatacao de numeros para a tela.

Nota e quantidade parecem a mesma coisa e nao sao. Nota "8,0" comunica
precisao e faz sentido num boletim. Peso "1,0" e nota maxima "10,0" nao —
sao quantidades, e o zero a direita faz o professor procurar um decimal que
nao existe. Foi a primeira coisa que ele estranhou na tela de avaliacoes.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.utils.formatadores import formatar_nota, formatar_quantidade


class TestFormatarQuantidade:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            (Decimal("1.00"), "1"),
            (Decimal("10.00"), "10"),
            (Decimal("100.00"), "100"),
            (1, "1"),
            (10, "10"),
        ],
    )
    def test_inteiro_sai_sem_casa_decimal(self, valor, esperado):
        """`Numeric(4, 2)` devolve Decimal('1.00'); a tela mostra 1."""
        assert formatar_quantidade(valor) == esperado

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            (Decimal("2.50"), "2,5"),
            (Decimal("0.50"), "0,5"),
            (Decimal("3.25"), "3,25"),
        ],
    )
    def test_decimal_de_verdade_e_preservado(self, valor, esperado):
        """Meio ponto existe e a escola usa — o que some e so o zero inutil."""
        assert formatar_quantidade(valor) == esperado

    def test_vazio_tem_marcador(self):
        assert formatar_quantidade(None) == "—"
        assert formatar_quantidade("nao e numero") == "—"

    def test_nota_continua_com_uma_casa(self):
        """Regressao: o filtro novo nao pode ter mudado o antigo.

        No boletim, "8" e "8,0" nao sao equivalentes: a casa decimal diz que
        a nota foi apurada, nao arredondada de olho.
        """
        assert formatar_nota(Decimal("8.00")) == "8,0"
        assert formatar_nota(Decimal("10.00")) == "10,0"
