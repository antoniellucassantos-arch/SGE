"""Registro de consentimento e base legal (LGPD).

O cadastro tinha dois booleanos — uso de imagem e saida desacompanhada. Um
booleano responde "pode?", que e a pergunta operacional, e nenhuma das que a
lei faz quando a familia reclama: quem autorizou, quando, sob qual base
legal, e desde quando deixou de valer.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.extensions import db
from app.models.enums import (
    AcaoAuditoria,
    BaseLegalLGPD,
    FinalidadeTratamento,
    Parentesco,
)
from app.models.lgpd import ConsentimentoLGPD
from app.models.pessoas import AlunoResponsavel
from app.models.sistema import LogAuditoria
from app.services import consentimento_service
from app.services.excecoes import ErroRegraNegocio, ErroValidacao


@pytest.fixture
def responsavel_do_aluno(app, aluno, responsavel):
    """Vincula o responsavel da fixture padrao ao aluno."""
    db.session.add(
        AlunoResponsavel(
            aluno_id=aluno.id,
            responsavel_id=responsavel.id,
            parentesco=Parentesco.MAE,
            ordem_contato=1,
        )
    )
    db.session.commit()
    db.session.refresh(responsavel)
    return responsavel


# ===========================================================================
# Base legal
# ===========================================================================
class TestBaseLegal:
    def test_nem_toda_finalidade_depende_de_consentimento(self):
        """Pedir consentimento para o historico escolar seria enganoso.

        A escola nao pode parar de emitir historico se a familia disser nao;
        oferecer a escolha daria a impressao de uma decisao que nao existe.
        """
        assert not FinalidadeTratamento.REGISTRO_OBRIGATORIO.exige_consentimento
        assert not FinalidadeTratamento.VIDA_ESCOLAR.exige_consentimento
        assert not FinalidadeTratamento.SAUDE_E_EMERGENCIA.exige_consentimento

        assert FinalidadeTratamento.USO_DE_IMAGEM.exige_consentimento
        assert FinalidadeTratamento.COMUNICACAO_INSTITUCIONAL.exige_consentimento

    def test_saude_se_apoia_na_tutela_da_saude(self):
        """Art. 11, II, "f": socorrer uma crianca nao espera assinatura."""
        finalidade = FinalidadeTratamento.SAUDE_E_EMERGENCIA
        assert finalidade.base_legal is BaseLegalLGPD.TUTELA_DA_SAUDE

    def test_so_o_que_se_apoia_em_consentimento_e_revogavel(self):
        for finalidade in FinalidadeTratamento:
            assert finalidade.revogavel == finalidade.exige_consentimento


# ===========================================================================
# pode_tratar
# ===========================================================================
class TestPodeTratar:
    def test_obrigacao_legal_dispensa_registro(self, app, aluno):
        """Sem registro nenhum, o historico escolar continua saindo."""
        assert consentimento_service.pode_tratar(
            aluno.id, FinalidadeTratamento.REGISTRO_OBRIGATORIO
        )

    def test_consentimento_ausente_bloqueia(self, app, aluno):
        """Silencio nao e autorizacao."""
        assert not consentimento_service.pode_tratar(
            aluno.id, FinalidadeTratamento.USO_DE_IMAGEM
        )

    def test_consentimento_concedido_autoriza(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=True,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
        )
        assert consentimento_service.pode_tratar(
            aluno.id, FinalidadeTratamento.USO_DE_IMAGEM
        )

    def test_negativa_registrada_bloqueia(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        """Um "nao" tambem e uma decisao, e precisa constar."""
        consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=False,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
        )
        assert not consentimento_service.pode_tratar(
            aluno.id, FinalidadeTratamento.USO_DE_IMAGEM
        )


# ===========================================================================
# Historico
# ===========================================================================
class TestHistorico:
    def test_nova_decisao_nao_apaga_a_anterior(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        """A LGPD poe sobre a escola o onus de provar o consentimento.

        Um registro sobrescrito prova o presente e destroi a evidencia do
        passado — que e exatamente o que se pede quando a familia contesta
        uma foto publicada ano passado.
        """
        consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=True,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
            data_decisao=date(2026, 2, 1),
        )
        consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=False,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
            data_decisao=date(2026, 8, 1),
        )

        registros = (
            db.session.query(ConsentimentoLGPD)
            .filter(
                ConsentimentoLGPD.aluno_id == aluno.id,
                ConsentimentoLGPD.finalidade
                == FinalidadeTratamento.USO_DE_IMAGEM,
            )
            .all()
        )

        assert len(registros) == 2
        assert not consentimento_service.pode_tratar(
            aluno.id, FinalidadeTratamento.USO_DE_IMAGEM
        )

    def test_registro_guarda_quem_e_quando(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        registro = consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=True,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
            documento="Termo 2026/0042",
        )

        assert registro.responsavel_id == responsavel_do_aluno.id
        assert registro.registrado_por_id == secretaria.id
        assert registro.documento == "Termo 2026/0042"
        assert registro.base_legal is BaseLegalLGPD.CONSENTIMENTO

    def test_nome_de_quem_decidiu_sobrevive_a_exclusao(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        """A trilha precisa continuar legivel depois da limpeza do cadastro."""
        registro = consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=True,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
        )
        nome = responsavel_do_aluno.nome_completo

        registro.responsavel_id = None
        registro.responsavel = None
        db.session.commit()

        assert registro.nome_de_quem_decidiu == nome


# ===========================================================================
# Revogacao
# ===========================================================================
class TestRevogacao:
    def test_revogar_encerra_a_autorizacao(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        registro = consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=True,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
        )

        consentimento_service.revogar(registro, autor=secretaria)

        assert registro.revogado_em is not None
        assert not registro.vigente
        assert not consentimento_service.pode_tratar(
            aluno.id, FinalidadeTratamento.USO_DE_IMAGEM
        )

    def test_revogar_nao_apaga_o_registro(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        """A prova de que houve consentimento continua existindo."""
        registro = consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=True,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
        )
        identificador = registro.id

        consentimento_service.revogar(registro, autor=secretaria)

        assert db.session.get(ConsentimentoLGPD, identificador) is not None

    def test_nao_se_revoga_o_que_nao_depende_de_consentimento(
        self, app, aluno, secretaria
    ):
        """Revogar obrigacao legal daria a impressao falsa de que parou."""
        registro = consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.REGISTRO_OBRIGATORIO,
            concedido=True,
            autor=secretaria,
        )

        with pytest.raises(ErroRegraNegocio):
            consentimento_service.revogar(registro, autor=secretaria)

    def test_revogar_duas_vezes_e_recusado(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        registro = consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=True,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
        )
        consentimento_service.revogar(registro, autor=secretaria)

        with pytest.raises(ErroRegraNegocio):
            consentimento_service.revogar(registro, autor=secretaria)


# ===========================================================================
# Integridade do registro
# ===========================================================================
class TestIntegridade:
    def test_consentimento_exige_responsavel_identificado(
        self, app, aluno, secretaria
    ):
        """"Alguem autorizou" nao prova nada."""
        with pytest.raises(ErroValidacao):
            consentimento_service.registrar(
                aluno,
                FinalidadeTratamento.USO_DE_IMAGEM,
                concedido=True,
                autor=secretaria,
            )

    def test_responsavel_de_outro_aluno_e_recusado(
        self, app, aluno, responsavel, secretaria
    ):
        """Sem o vinculo, qualquer adulto assinaria pela crianca de outro."""
        with pytest.raises(ErroRegraNegocio):
            consentimento_service.registrar(
                aluno,
                FinalidadeTratamento.USO_DE_IMAGEM,
                concedido=True,
                responsavel=responsavel,
                autor=secretaria,
            )

    def test_finalidade_desconhecida_e_recusada(self, app, aluno, secretaria):
        with pytest.raises(ErroValidacao):
            consentimento_service.registrar(
                aluno, "finalidade_inventada", concedido=True, autor=secretaria
            )


# ===========================================================================
# Sincronia com o cadastro
# ===========================================================================
class TestEspelhoNoCadastro:
    def test_registro_atualiza_o_booleano_do_cadastro(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        """Os campos antigos alimentam a tela de cadastro e os filtros.

        Duas fontes de verdade divergem — foi o que a auditoria encontrou em
        outros pontos. Aqui nao divergem porque so o service escreve nas
        duas, e quem decide e sempre `pode_tratar()`.
        """
        assert aluno.autoriza_uso_imagem is False

        consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=True,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
        )
        assert aluno.autoriza_uso_imagem is True

    def test_revogacao_atualiza_o_booleano(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        registro = consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.SAIDA_DESACOMPANHADA,
            concedido=True,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
        )
        assert aluno.autorizado_sair_sozinho is True

        consentimento_service.revogar(registro, autor=secretaria)
        assert aluno.autorizado_sair_sozinho is False


# ===========================================================================
# Painel e pendencias
# ===========================================================================
class TestPainel:
    def test_pendencias_listam_o_que_falta_perguntar(self, app, aluno):
        pendentes = consentimento_service.pendencias(aluno.id)

        assert FinalidadeTratamento.USO_DE_IMAGEM in pendentes
        # Obrigacao legal nunca e pendencia: nao ha o que perguntar.
        assert FinalidadeTratamento.REGISTRO_OBRIGATORIO not in pendentes

    def test_negativa_registrada_deixa_de_ser_pendencia(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        """Um "nao" e uma decisao tomada, nao uma pergunta em aberto."""
        consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=False,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
        )

        pendentes = consentimento_service.pendencias(aluno.id)
        assert FinalidadeTratamento.USO_DE_IMAGEM not in pendentes

    def test_painel_cobre_todas_as_finalidades(self, app, aluno):
        painel = consentimento_service.painel(aluno.id)
        assert len(painel) == len(list(FinalidadeTratamento))


# ===========================================================================
# Telas
# ===========================================================================
class TestTelaDoConsentimento:
    def test_ficha_mostra_o_painel(
        self, app, cliente, secretaria, autenticar, aluno, responsavel_do_aluno
    ):
        autenticar(secretaria)
        corpo = cliente.get(f"/alunos/{aluno.id}").get_data(as_text=True)

        assert "Consentimentos" in corpo
        assert FinalidadeTratamento.USO_DE_IMAGEM.rotulo in corpo
        # Finalidade dispensada aparece, mas sem oferecer escolha.
        assert "Dispensa consentimento" in corpo

    def test_registrar_pela_tela(
        self, app, cliente, secretaria, autenticar, aluno, responsavel_do_aluno
    ):
        autenticar(secretaria)
        resposta = cliente.post(
            f"/alunos/{aluno.id}/consentimentos",
            data={
                "finalidade": FinalidadeTratamento.USO_DE_IMAGEM.value,
                "concedido": "1",
                "responsavel_id": str(responsavel_do_aluno.id),
                "documento": "Termo 2026/0001",
            },
            follow_redirects=True,
        )

        assert resposta.status_code == 200
        assert consentimento_service.pode_tratar(
            aluno.id, FinalidadeTratamento.USO_DE_IMAGEM
        )

    def test_professor_nao_registra(
        self, app, cliente_professor, vinculo, matricula, aluno, responsavel_do_aluno
    ):
        """Registrar consentimento e ato da secretaria, nao do professor."""
        resposta = cliente_professor.post(
            f"/alunos/{aluno.id}/consentimentos",
            data={
                "finalidade": FinalidadeTratamento.USO_DE_IMAGEM.value,
                "concedido": "1",
                "responsavel_id": str(responsavel_do_aluno.id),
            },
        )

        assert resposta.status_code in (302, 403)
        assert not consentimento_service.pode_tratar(
            aluno.id, FinalidadeTratamento.USO_DE_IMAGEM
        )

    def test_revogacao_de_outro_aluno_e_recusada(
        self, app, cliente, secretaria, autenticar, aluno, responsavel_do_aluno
    ):
        """O id do consentimento vem da URL.

        O decorador de escopo valida o `aluno_id`, nao o registro pendurado
        nele: sem a conferencia na rota, trocar o numero revogaria o
        consentimento de outra crianca.
        """
        from app.models.pessoas import Aluno as ModeloAluno

        registro = consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=True,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
        )

        outro = ModeloAluno(
            nome_completo="Outro Aluno",
            codigo=ModeloAluno.gerar_codigo(),
            data_nascimento=date(2012, 1, 1),
        )
        db.session.add(outro)
        db.session.commit()

        autenticar(secretaria)
        cliente.post(
            f"/alunos/{outro.id}/consentimentos/{registro.id}/revogar",
            follow_redirects=True,
        )

        db.session.refresh(registro)
        assert registro.revogado_em is None


# ===========================================================================
# Auditoria
# ===========================================================================
class TestAuditoriaDoConsentimento:
    def test_decisao_vai_para_a_trilha(
        self, app, aluno, responsavel_do_aluno, secretaria
    ):
        consentimento_service.registrar(
            aluno,
            FinalidadeTratamento.USO_DE_IMAGEM,
            concedido=True,
            responsavel=responsavel_do_aluno,
            autor=secretaria,
        )

        registros = (
            db.session.query(LogAuditoria)
            .filter(LogAuditoria.acao == AcaoAuditoria.CONSENTIMENTO)
            .all()
        )

        assert len(registros) == 1
        assert registros[0].entidade_id == aluno.id
        assert registros[0].usuario_id == secretaria.id
