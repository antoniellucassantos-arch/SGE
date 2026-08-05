"""O atalho de frequencia redirecionava para si mesmo.

Encontrado pelo ensaio de um dia letivo
(``scripts/ensaio_dia_letivo.py``), nao pela suite: nenhum teste abria essa
tela, e as duas rotas isoladamente pareciam corretas.

``relatorios.frequencia`` responde em ``/relatorios/frequencia`` e redireciona
para ``url_for("relatorios.visualizar", chave="frequencia")`` — que constroi
exatamente ``/relatorios/frequencia``. Como o Werkzeug prefere a regra
estatica a regra com variavel, o caminho volta para o proprio atalho.

No navegador isso e ERR_TOO_MANY_REDIRECTS: o relatorio de alunos em risco
de reprovar por falta simplesmente nao abria.
"""

from __future__ import annotations

import pytest


class TestAtalhoDeFrequencia:
    def test_nao_redireciona_para_si_mesmo(self, app):
        """A causa, verificada no roteador em vez de na resposta.

        Checar so o HTTP esconderia o motivo: 302 e uma resposta legitima
        em varias telas. O que nao pode e o destino ser a origem.
        """
        with app.test_request_context("/"):
            from flask import url_for

            destino = url_for("relatorios.visualizar", chave="frequencia")

        endpoint, _ = app.url_map.bind("localhost").match(destino)
        assert endpoint != "relatorios.frequencia", (
            f"{destino} volta para o proprio atalho — laco de redirecionamento"
        )

    def test_tela_abre_para_quem_tem_permissao(self, app, cliente_admin):
        """Sem `follow_redirects` o laco estoura; com ele, a tela responde."""
        resposta = cliente_admin.get("/relatorios/frequencia", follow_redirects=True)

        assert resposta.status_code == 200
        assert "Frequencia" in resposta.get_data(as_text=True)

    @pytest.mark.parametrize(
        "caminho",
        ["/relatorios/frequencia", "/relatorios/frequencia/excel"],
    )
    def test_exportacao_continua_funcionando(self, app, cliente_admin, caminho):
        """Regressao: o conserto do atalho nao pode quebrar o relatorio."""
        resposta = cliente_admin.get(caminho, follow_redirects=True)
        assert resposta.status_code == 200
