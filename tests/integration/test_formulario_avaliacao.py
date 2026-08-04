"""O formulario de nova avaliacao, do jeito que chega ao navegador.

Reclamacao do professor: "peso na media e nota maxima ficam sempre em
numeros quebrados". Nao era impressao — era o `<input type="number">`
recusando todo numero redondo.

Num campo numerico do HTML os valores validos sao ``min + n*step``. Com
``min=0.1`` e ``step=0.5``, a escada era 0,1 / 0,6 / 1,1 / 1,6... As setinhas
partiam de 1 e paravam em 1,1; quem insistisse chegava a 10,1 — que foi
exatamente o que apareceu no banco de desenvolvimento.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from app.blueprints.notas.formularios import PASSO, AvaliacaoForm

VALOR = re.compile(r'value="([^"]*)"')


def _atributo(html: str, nome: str) -> str:
    achado = re.search(rf'{nome}="([^"]*)"', html)
    return achado.group(1) if achado else ""


@pytest.fixture
def campos(app):
    with app.test_request_context("/"):
        form = AvaliacaoForm()
        return {
            "peso": str(form.peso()),
            "valor_maximo": str(form.valor_maximo()),
        }


class TestEscadaDeValores:
    @pytest.mark.parametrize("campo", ["peso", "valor_maximo"])
    def test_numero_redondo_esta_na_escada(self, campos, campo):
        """`min` alinhado ao `step`: 1, 2, 3... sao valores validos.

        Sem isso o navegador marca o campo como invalido e a setinha pula
        para o proximo valor da escada — que nunca e inteiro.
        """
        minimo = float(_atributo(campos[campo], "min"))
        passo = float(_atributo(campos[campo], "step"))

        for inteiro in (1, 2, 5, 10):
            distancia = (inteiro - minimo) / passo
            assert distancia == int(distancia), (
                f"{campo}: {inteiro} nao e alcancavel com min={minimo} "
                f"e step={passo}"
            )

    @pytest.mark.parametrize("campo", ["peso", "valor_maximo"])
    def test_meio_ponto_continua_valendo(self, campos, campo):
        """A escola usa 0,5 — o conserto nao pode proibir o decimal legitimo."""
        assert float(_atributo(campos[campo], "step")) == PASSO


class TestValoresIniciais:
    def test_peso_comeca_em_um_inteiro(self, campos):
        assert VALOR.search(campos["peso"]).group(1) == "1"

    def test_nota_maxima_comeca_em_dez_inteiro(self, campos):
        assert VALOR.search(campos["valor_maximo"]).group(1) == "10"

    def test_valor_vindo_do_banco_perde_o_zero(self, app):
        """`Numeric(4, 2)` entrega Decimal('3.00'); o campo mostra 3."""
        with app.test_request_context("/"):
            form = AvaliacaoForm(
                data={"peso": Decimal("3.00"), "valor_maximo": Decimal("20.00")}
            )
            assert VALOR.search(str(form.peso())).group(1) == "3"
            assert VALOR.search(str(form.valor_maximo())).group(1) == "20"

    def test_decimal_de_verdade_sobrevive(self, app):
        with app.test_request_context("/"):
            form = AvaliacaoForm(data={"peso": Decimal("2.50")})
            assert VALOR.search(str(form.peso())).group(1) == "2.5"


class TestTelaDeLancamento:
    def test_explicacao_do_peso_aparece(self, app, cliente, admin, autenticar, vinculo):
        """Rotulo sozinho nao ensina o que e peso; o exemplo numerico ensina."""
        autenticar(admin)
        corpo = cliente.get(f"/notas/lancar/{vinculo.id}").get_data(as_text=True)

        assert "Como o peso muda a media" in corpo
        assert "Quantas vezes ela conta na media" in corpo
        assert "Quanto vale a prova inteira" in corpo
