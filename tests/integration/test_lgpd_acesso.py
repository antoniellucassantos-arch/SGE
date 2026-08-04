"""Registro de acesso a dado pessoal (LGPD).

A trilha de auditoria sabia dizer quem *alterou* a ficha de um aluno. Nao
sabia dizer quem a *leu* — e e a leitura que a LGPD exige rastrear quando o
dado e de saude de menor de idade (art. 11 e art. 37).

Sem isso, um vazamento nao tem como ser investigado: a escola sabe que a
ficha saiu, mas nao sabe por qual conta.
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import AcaoAuditoria
from app.models.sistema import LogAuditoria
from app.services import aluno_service


@pytest.fixture
def aluno_com_saude(app, aluno, matricula):
    aluno.cpf = "39053344705"
    aluno.alergias = "Alergia grave a amendoim"
    aluno.condicoes_saude = "Asma"
    db.session.commit()
    return aluno


def _acessos() -> list[LogAuditoria]:
    return (
        db.session.query(LogAuditoria)
        .filter(LogAuditoria.acao == AcaoAuditoria.ACESSO_DADO_PESSOAL)
        .order_by(LogAuditoria.id)
        .all()
    )


class TestRegistroDeAcesso:
    def test_abrir_ficha_completa_deixa_rastro(
        self, app, cliente, secretaria, autenticar, aluno_com_saude
    ):
        autenticar(secretaria)
        resposta = cliente.get(f"/alunos/{aluno_com_saude.id}")
        assert resposta.status_code == 200

        db.session.remove()
        registros = _acessos()

        assert len(registros) == 1
        registro = registros[0]
        assert registro.entidade == "Aluno"
        assert registro.entidade_id == aluno_com_saude.id
        assert registro.usuario_id == secretaria.id

    def test_registro_sobrevive_a_requisicao_sem_escrita(
        self, app, cliente, secretaria, autenticar, aluno_com_saude
    ):
        """Abrir uma ficha e um GET: nada mais na requisicao faz commit.

        Sem gravacao em sessao propria, o `db.session.remove()` do teardown
        levaria o registro junto — a mesma armadilha do item 3.3 da
        auditoria, e aqui ela apagaria justamente a trilha exigida por lei.
        """
        autenticar(secretaria)
        cliente.get(f"/alunos/{aluno_com_saude.id}")

        # Sessao nova, sem nada pendente: so ve o que foi realmente gravado.
        db.session.remove()
        assert _acessos()

    def test_registro_diz_quais_campos_sairam(
        self, app, cliente, secretaria, autenticar, aluno_com_saude
    ):
        """"Acessou a ficha" nao basta para responder o que vazou."""
        autenticar(secretaria)
        cliente.get(f"/alunos/{aluno_com_saude.id}")

        db.session.remove()
        detalhes = _acessos()[0].detalhes or ""

        assert "alergias" in detalhes
        assert "cpf" in detalhes
        # O valor jamais entra no log: a trilha registra o que saiu, nao
        # duplica o dado sensivel em outra tabela.
        assert "amendoim" not in detalhes

    def test_professor_nao_gera_registro(
        self, app, cliente_professor, vinculo, aluno_com_saude
    ):
        """O professor recebe a ficha filtrada — nao ha acesso a registrar.

        Registrar aqui encheria a trilha de eventos vazios e afogaria os que
        importam. O que se rastreia e a entrega efetiva do dado sensivel.
        """
        resposta = cliente_professor.get(f"/alunos/{aluno_com_saude.id}")
        assert resposta.status_code == 200

        db.session.remove()
        assert _acessos() == []

    def test_listagem_nao_gera_registro_por_aluno(
        self, app, cliente, secretaria, autenticar, aluno_com_saude
    ):
        """A listagem mostra nome, codigo e turma — nao documento nem saude.

        Uma linha de log por aluno por pagina aberta tornaria a trilha
        inutil: o evento que interessa desapareceria no meio do ruido.
        """
        autenticar(secretaria)
        cliente.get("/alunos/")

        db.session.remove()
        assert _acessos() == []

    def test_serializacao_completa_tambem_registra(
        self, app, aluno_com_saude, secretaria
    ):
        """A API e a exportacao entregam os mesmos campos que a tela."""
        dados = aluno_service.serializar(aluno_com_saude, secretaria)
        assert "cpf" in dados

        db.session.remove()
        assert _acessos()

    def test_serializacao_filtrada_nao_registra(
        self, app, aluno_com_saude, professor
    ):
        aluno_service.serializar(aluno_com_saude, professor.usuario)

        db.session.remove()
        assert _acessos() == []


class TestConsultaDaTrilha:
    def test_acao_aparece_no_filtro_da_auditoria(self, app, cliente_admin):
        """Trilha que nao da para consultar nao serve para prestar contas."""
        corpo = cliente_admin.get("/auditoria/").get_data(as_text=True)
        assert AcaoAuditoria.ACESSO_DADO_PESSOAL.rotulo in corpo

    def test_historico_do_aluno_reune_leitura_e_alteracao(
        self, app, cliente, secretaria, autenticar, aluno_com_saude
    ):
        """Quem investiga um vazamento pergunta pelo aluno, nao pela acao."""
        from app.services import auditoria_service

        autenticar(secretaria)
        cliente.get(f"/alunos/{aluno_com_saude.id}")

        db.session.remove()
        historico = auditoria_service.historico_da_entidade(
            "Aluno", aluno_com_saude.id
        )
        assert any(
            registro.acao is AcaoAuditoria.ACESSO_DADO_PESSOAL
            for registro in historico
        )
