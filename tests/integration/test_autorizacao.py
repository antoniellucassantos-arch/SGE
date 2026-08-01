"""Testes de autorizacao e de escopo de acesso (defesa contra IDOR).

Estes sao os testes mais importantes da suite. A falha de controle de acesso
(OWASP A01) e a mais comum e a mais grave em sistemas escolares: trocar o id
na URL e ver o boletim de outro aluno.
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import (
    PapelUsuario,
    Parentesco,
    SituacaoCadastro,
    SituacaoMatricula,
    Turno,
)
from app.models.estrutura import Turma, TurmaDisciplina
from app.models.matricula import Matricula
from app.models.pessoas import Aluno, AlunoResponsavel, Professor
from tests.conftest import SENHA_PADRAO, criar_usuario


# ---------------------------------------------------------------------------
# Rotas restritas por papel
# ---------------------------------------------------------------------------
class TestRestricaoPorPapel:
    @pytest.mark.parametrize(
        "rota",
        [
            "/usuarios/",
            "/configuracoes/",
            "/backup/",
            "/auditoria/",
            "/alunos/",
            "/turmas/",
            "/matriculas/",
        ],
    )
    def test_responsavel_nao_acessa_area_administrativa(
        self, cliente, responsavel, autenticar, rota
    ):
        autenticar(responsavel.usuario)
        resposta = cliente.get(rota)
        assert resposta.status_code == 403, rota

    @pytest.mark.parametrize(
        "rota", ["/usuarios/", "/configuracoes/", "/backup/", "/auditoria/"]
    )
    def test_professor_nao_acessa_administracao_do_sistema(
        self, cliente, professor, autenticar, rota
    ):
        autenticar(professor.usuario)
        assert cliente.get(rota).status_code == 403, rota

    @pytest.mark.parametrize(
        "rota", ["/usuarios/", "/backup/", "/auditoria/"]
    )
    def test_secretaria_nao_gerencia_o_sistema(
        self, cliente, secretaria, autenticar, rota
    ):
        autenticar(secretaria)
        assert cliente.get(rota).status_code == 403, rota

    def test_secretaria_acessa_os_cadastros(self, cliente, secretaria, autenticar):
        autenticar(secretaria)
        for rota in ("/alunos/", "/turmas/", "/matriculas/"):
            assert cliente.get(rota).status_code == 200, rota

    def test_administrador_acessa_tudo(self, cliente_admin):
        for rota in (
            "/alunos/", "/turmas/", "/usuarios/", "/configuracoes/",
            "/backup/", "/auditoria/", "/relatorios/",
        ):
            assert cliente_admin.get(rota).status_code == 200, rota


# ---------------------------------------------------------------------------
# Escopo: responsavel so ve os proprios filhos
# ---------------------------------------------------------------------------
class TestEscopoDoResponsavel:
    @pytest.fixture
    def cenario(self, app, responsavel, turma, ano_letivo):
        """Um aluno vinculado ao responsavel e outro sem vinculo."""
        vinculado = Aluno(
            nome_completo="Filho Vinculado",
            codigo=Aluno.gerar_codigo(),
            situacao=SituacaoCadastro.ATIVO,
        )
        alheio = Aluno(
            nome_completo="Aluno Alheio",
            codigo="99999999",
            situacao=SituacaoCadastro.ATIVO,
        )
        db.session.add_all([vinculado, alheio])
        db.session.flush()

        db.session.add(
            AlunoResponsavel(
                aluno_id=vinculado.id,
                responsavel_id=responsavel.id,
                parentesco=Parentesco.MAE,
                responsavel_legal=True,
            )
        )

        for aluno in (vinculado, alheio):
            db.session.add(
                Matricula(
                    numero=Matricula.gerar_numero(ano_letivo.ano),
                    aluno_id=aluno.id,
                    turma_id=turma.id,
                    ano_letivo_id=ano_letivo.id,
                    situacao=SituacaoMatricula.ATIVA,
                )
            )
        db.session.commit()

        return {"vinculado": vinculado, "alheio": alheio}

    def test_acessa_o_boletim_do_proprio_filho(
        self, cliente, responsavel, autenticar, cenario
    ):
        autenticar(responsavel.usuario)
        resposta = cliente.get(f"/boletim/aluno/{cenario['vinculado'].id}")
        assert resposta.status_code == 200

    def test_nao_acessa_o_boletim_de_outro_aluno(
        self, cliente, responsavel, autenticar, cenario
    ):
        """Trocar o id na URL nao pode expor o dado de outra familia."""
        autenticar(responsavel.usuario)
        resposta = cliente.get(f"/boletim/aluno/{cenario['alheio'].id}")
        assert resposta.status_code == 403

    def test_nao_acessa_a_frequencia_de_outro_aluno(
        self, cliente, responsavel, autenticar, cenario
    ):
        autenticar(responsavel.usuario)
        resposta = cliente.get(f"/frequencia/aluno/{cenario['alheio'].id}")
        assert resposta.status_code == 403

    def test_nao_acessa_a_ficha_de_outro_aluno(
        self, cliente, responsavel, autenticar, cenario
    ):
        autenticar(responsavel.usuario)
        resposta = cliente.get(f"/alunos/{cenario['alheio'].id}")
        # 403 do escopo ou 403 da permissao — em ambos os casos, negado.
        assert resposta.status_code == 403


# ---------------------------------------------------------------------------
# Escopo: professor so acessa as proprias turmas
# ---------------------------------------------------------------------------
class TestEscopoDoProfessor:
    @pytest.fixture
    def outra_turma(self, app, ano_letivo, serie, disciplina):
        """Turma com outro professor titular."""
        outro_usuario = criar_usuario(
            "outro.professor@escola.com.br",
            papel=PapelUsuario.PROFESSOR,
            nome="Outro Professor",
        )
        outro = Professor(
            nome_completo="Outro Professor",
            registro_funcional="PROF00002",
            situacao=SituacaoCadastro.ATIVO,
            usuario_id=outro_usuario.id,
        )
        db.session.add(outro)
        db.session.flush()

        turma = Turma(
            nome="B",
            ano_letivo_id=ano_letivo.id,
            serie_id=serie.id,
            turno=Turno.MATUTINO,
            capacidade=30,
            ativa=True,
        )
        db.session.add(turma)
        db.session.flush()

        vinculo = TurmaDisciplina(
            turma_id=turma.id,
            disciplina_id=disciplina.id,
            professor_id=outro.id,
            ativa=True,
        )
        db.session.add(vinculo)
        db.session.commit()

        return {"turma": turma, "vinculo": vinculo, "professor": outro}

    def test_acessa_o_diario_da_propria_turma(
        self, cliente, professor, autenticar, vinculo
    ):
        autenticar(professor.usuario)
        resposta = cliente.get(f"/frequencia/diario/{vinculo.id}")
        assert resposta.status_code == 200

    def test_nao_acessa_o_diario_de_outra_turma(
        self, cliente, professor, autenticar, vinculo, outra_turma
    ):
        autenticar(professor.usuario)
        resposta = cliente.get(f"/frequencia/diario/{outra_turma['vinculo'].id}")
        assert resposta.status_code == 403

    def test_nao_acessa_as_notas_de_outra_turma(
        self, cliente, professor, autenticar, vinculo, outra_turma
    ):
        autenticar(professor.usuario)
        resposta = cliente.get(f"/notas/lancar/{outra_turma['vinculo'].id}")
        assert resposta.status_code == 403

    def test_nao_lanca_nota_em_turma_alheia(
        self, cliente, professor, autenticar, outra_turma, ano_letivo
    ):
        """Barrar a leitura nao basta: a escrita tambem precisa ser negada."""
        from app.models.avaliacao import Avaliacao
        from app.models.enums import TipoAvaliacao

        avaliacao = Avaliacao(
            turma_disciplina_id=outra_turma["vinculo"].id,
            periodo_id=ano_letivo.periodos[0].id,
            nome="Prova alheia",
            tipo=TipoAvaliacao.PROVA,
            peso=1,
            valor_maximo=10,
        )
        db.session.add(avaliacao)
        db.session.commit()

        autenticar(professor.usuario)
        resposta = cliente.post(f"/notas/avaliacao/{avaliacao.id}/notas", data={})
        assert resposta.status_code == 403


# ---------------------------------------------------------------------------
# Protecao CSRF
# ---------------------------------------------------------------------------
class TestProtecaoCSRF:
    def test_post_sem_token_e_recusado(self, app, admin):
        """Sem CSRF, outro site poderia agir usando a sessao da vitima."""
        app.config["WTF_CSRF_ENABLED"] = True
        cliente = app.test_client()

        cliente.post(
            "/auth/login", data={"email": admin.email, "senha": SENHA_PADRAO}
        )
        resposta = cliente.post(
            "/alunos/novo", data={"nome_completo": "Aluno Sem Token"}
        )
        assert resposta.status_code == 400
