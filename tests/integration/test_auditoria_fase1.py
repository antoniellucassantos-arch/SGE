"""Testes da Fase 1 da auditoria de seguranca.

Cada teste aqui corresponde a uma vulnerabilidade encontrada na revisao. Todos
falhavam antes da correcao — foram escritos primeiro, justamente para provar
que o problema existia.

Referencia dos itens: ``docs/auditoria-fase1.md``.
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import (
    PapelUsuario,
    SituacaoCadastro,
    TipoAvaliacao,
    Turno,
)
from app.models.estrutura import Turma, TurmaDisciplina
from app.models.pessoas import Aluno, Professor
from app.services import nota_service
from app.services.excecoes import ErroPermissao, ErroRegraNegocio
from app.utils import permissoes as modulo_permissoes
from tests.conftest import SENHA_PADRAO, criar_usuario


# ===========================================================================
# Cenario compartilhado: duas turmas, dois professores
# ===========================================================================
@pytest.fixture
def turma_alheia(app, ano_letivo, serie, disciplina):
    """Turma de outro professor, que o professor da fixture nao leciona."""
    usuario = criar_usuario(
        "outro.prof@escola.com.br", PapelUsuario.PROFESSOR, "Outro Professor"
    )
    outro = Professor(
        nome_completo="Outro Professor",
        registro_funcional="PROF09999",
        situacao=SituacaoCadastro.ATIVO,
        usuario_id=usuario.id,
    )
    db.session.add(outro)
    db.session.flush()

    turma = Turma(
        nome="Z",
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


# ===========================================================================
# 1.1 — Broken Access Control nos relatorios (escopo por querystring)
# ===========================================================================
class TestEscopoPorQuerystring:
    """`?turma_id=` nao passa por decorador de rota — precisa de guarda propria.

    Os relatorios academicos (`frequencia`, `desempenho`) sao os acessiveis ao
    professor; os administrativos ja sao barrados pela permissao.
    """

    def test_professor_nao_acessa_turma_alheia_via_querystring(
        self, cliente, professor, autenticar, vinculo, turma_alheia
    ):
        autenticar(professor.usuario)

        resposta = cliente.get(
            f"/relatorios/desempenho?turma_id={turma_alheia['turma'].id}"
        )

        assert resposta.status_code == 403

    def test_professor_acessa_a_propria_turma_via_querystring(
        self, cliente, professor, autenticar, vinculo, turma
    ):
        autenticar(professor.usuario)

        resposta = cliente.get(f"/relatorios/desempenho?turma_id={turma.id}")

        assert resposta.status_code == 200

    def test_sem_turma_id_o_escopo_limita_a_consulta(
        self, app, professor, vinculo, turma, turma_alheia, aluno, ano_letivo
    ):
        """`turma_id` ausente nao pode significar "escola inteira".

        A verificacao e feita no proprio service, onde o recorte acontece —
        conferir no HTML mascararia um filtro aplicado apenas no template.
        """
        from flask_login import login_user

        from app.services import matricula_service, relatorio_service

        matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)

        alheio = Aluno(
            nome_completo="Aluno De Outra Turma",
            codigo="90000001",
            situacao=SituacaoCadastro.ATIVO,
        )
        db.session.add(alheio)
        db.session.commit()
        matricula_service.matricular(
            alheio.id, turma_alheia["turma"].id, ano_letivo.id
        )

        with app.test_request_context("/relatorios/turmas"):
            login_user(professor.usuario)
            dados = relatorio_service.relatorio_turmas(ano_letivo.id)

        turmas_no_relatorio = {linha[0] for linha in dados["linhas"]}
        assert turma.identificacao_curta in turmas_no_relatorio
        assert turma_alheia["turma"].identificacao_curta not in turmas_no_relatorio

    def test_select_de_turmas_nao_vaza_turmas_alheias(
        self, cliente, professor, autenticar, vinculo, turma, turma_alheia
    ):
        """O <select> entrega os ids validos para o ataque — precisa ser filtrado."""
        autenticar(professor.usuario)

        corpo = cliente.get("/relatorios/desempenho").data.decode()

        assert f'value="{turma.id}"' in corpo
        assert f'value="{turma_alheia["turma"].id}"' not in corpo

    def test_equipe_administrativa_continua_vendo_a_escola_inteira(
        self, cliente, secretaria, autenticar, turma, turma_alheia
    ):
        autenticar(secretaria)

        corpo = cliente.get("/relatorios/alunos").data.decode()

        assert f'value="{turma.id}"' in corpo
        assert f'value="{turma_alheia["turma"].id}"' in corpo


# ===========================================================================
# 1.2 — Exportacao ignora a permissao do relatorio
# ===========================================================================
class TestPermissaoNaExportacao:
    @pytest.fixture
    def professor_com_export(self, monkeypatch):
        """Concede RELATORIO_EXPORTAR ao professor, sem mexer na matriz real.

        Simula o cenario descrito na auditoria: no dia em que o professor
        ganhar exportacao, ele nao pode levar junto os relatorios
        administrativos.
        """
        matriz = dict(modulo_permissoes.MATRIZ_PERMISSOES)
        matriz[PapelUsuario.PROFESSOR] = (
            matriz[PapelUsuario.PROFESSOR]
            | {modulo_permissoes.Permissao.RELATORIO_EXPORTAR}
        )
        monkeypatch.setattr(modulo_permissoes, "MATRIZ_PERMISSOES", matriz)

    def test_professor_nao_exporta_relatorio_administrativo(
        self, cliente, professor, autenticar, professor_com_export
    ):
        autenticar(professor.usuario)

        assert cliente.get("/relatorios/professores/excel").status_code == 403
        assert cliente.get("/relatorios/professores/pdf").status_code == 403

    def test_professor_exporta_relatorio_academico(
        self, cliente, professor, autenticar, professor_com_export, ano_letivo
    ):
        autenticar(professor.usuario)

        resposta = cliente.get("/relatorios/frequencia/excel")
        assert resposta.status_code == 200

    def test_chave_inexistente_nao_gera_500(self, cliente_admin):
        """Chave desconhecida deve virar 404, nunca KeyError cru."""
        assert cliente_admin.get("/relatorios/inexistente/excel").status_code == 404
        assert cliente_admin.get("/relatorios/inexistente/pdf").status_code == 404


# ===========================================================================
# 1.3 — Nota alteravel com o periodo encerrado
# ===========================================================================
class TestPeriodoEncerrado:
    @pytest.fixture
    def cenario(self, app, vinculo, aluno, turma, ano_letivo):
        from app.services import matricula_service

        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        periodo = ano_letivo.periodos[0]

        avaliacao = nota_service.criar_avaliacao(
            vinculo, periodo.id, "Prova 1", TipoAvaliacao.PROVA
        )
        nota_service.salvar_notas(avaliacao, {matricula.id: "4"})

        # Fecha o periodo depois do lancamento, como acontece no fim do bimestre.
        periodo.encerrado = True
        db.session.commit()

        return {
            "matricula": matricula,
            "periodo": periodo,
            "avaliacao": avaliacao,
            "vinculo": vinculo,
        }

    def test_nota_nao_altera_com_periodo_encerrado(self, app, cenario):
        with pytest.raises(ErroRegraNegocio) as erro:
            nota_service.salvar_notas(
                cenario["avaliacao"], {cenario["matricula"].id: "10"}
            )
        assert "encerrado" in erro.value.mensagem.lower()

    def test_avaliacao_nao_e_editada_com_periodo_encerrado(self, app, cenario):
        with pytest.raises(ErroRegraNegocio):
            nota_service.atualizar_avaliacao(
                cenario["avaliacao"], {"nome": "Prova alterada"}
            )

    def test_avaliacao_nao_e_excluida_com_periodo_encerrado(self, app, cenario):
        with pytest.raises(ErroRegraNegocio):
            nota_service.excluir_avaliacao(cenario["avaliacao"])

    def test_avaliacao_nao_e_publicada_com_periodo_encerrado(self, app, cenario):
        with pytest.raises(ErroRegraNegocio):
            nota_service.publicar_avaliacao(cenario["avaliacao"], True)

    def test_ano_encerrado_tambem_bloqueia(self, app, cenario, ano_letivo):
        from app.models.enums import SituacaoAnoLetivo

        cenario["periodo"].encerrado = False
        ano_letivo.situacao = SituacaoAnoLetivo.ENCERRADO
        db.session.commit()

        with pytest.raises(ErroRegraNegocio):
            nota_service.salvar_notas(
                cenario["avaliacao"], {cenario["matricula"].id: "10"}
            )

    def test_direcao_reabre_com_auditoria_obrigatoria(self, app, cenario, admin):
        """A excecao existe, mas toda alteracao pos-fechamento fica registrada."""
        from app.models.enums import AcaoAuditoria
        from app.models.sistema import LogAuditoria

        nota_service.salvar_notas(
            cenario["avaliacao"],
            {cenario["matricula"].id: "10"},
            usuario_id=admin.id,
            permitir_periodo_encerrado=True,
        )

        registro = (
            db.session.query(LogAuditoria)
            .filter(LogAuditoria.acao == AcaoAuditoria.ATUALIZACAO)
            .order_by(LogAuditoria.id.desc())
            .first()
        )
        assert registro is not None
        assert "periodo encerrado" in (registro.descricao or "").lower()
        # O valor anterior precisa constar para permitir reconstituir o boletim.
        assert "4" in (registro.detalhes or "")


# ===========================================================================
# 1.4 — salvar_notas() nao verifica autorizacao
# ===========================================================================
class TestAutorizacaoNoService:
    def test_service_recusa_lancamento_de_professor_alheio(
        self, app, professor, turma_alheia, ano_letivo, aluno
    ):
        """A API e a CLI nao passam por decorador — a guarda vive no service."""
        from flask_login import login_user

        from app.services import matricula_service

        matricula = matricula_service.matricular(
            aluno.id, turma_alheia["turma"].id, ano_letivo.id
        )
        avaliacao = nota_service.criar_avaliacao(
            turma_alheia["vinculo"],
            ano_letivo.periodos[0].id,
            "Prova alheia",
            TipoAvaliacao.PROVA,
        )

        with app.test_request_context():
            login_user(professor.usuario)

            with pytest.raises(ErroPermissao):
                nota_service.salvar_notas(avaliacao, {matricula.id: "10"})

    def test_professor_titular_lanca_normalmente(
        self, app, professor, vinculo, ano_letivo, aluno, turma
    ):
        from flask_login import login_user

        from app.services import matricula_service

        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        avaliacao = nota_service.criar_avaliacao(
            vinculo, ano_letivo.periodos[0].id, "Prova", TipoAvaliacao.PROVA
        )

        with app.test_request_context():
            login_user(professor.usuario)
            alteradas = nota_service.salvar_notas(avaliacao, {matricula.id: "8"})

        assert alteradas == 1


# ===========================================================================
# 1.5 — Uploads servidos sem autenticacao
# ===========================================================================
class TestUploadsProtegidos:
    def test_foto_de_aluno_exige_autenticacao(self, cliente, aluno):
        resposta = cliente.get(f"/alunos/{aluno.id}/foto", follow_redirects=False)
        assert resposta.status_code in (302, 401, 403)

    def test_responsavel_nao_ve_foto_de_aluno_alheio(
        self, cliente, responsavel, autenticar, aluno
    ):
        autenticar(responsavel.usuario)
        resposta = cliente.get(f"/alunos/{aluno.id}/foto")
        assert resposta.status_code == 403

    def test_pasta_de_uploads_fora_de_static(self, app):
        """Nada em static/ passa por autenticacao — uploads nao podem morar la."""
        pasta = str(app.config["PASTA_UPLOADS"]).replace("\\", "/")
        assert "/static/" not in pasta

    def test_nome_de_arquivo_e_uuid(self, app):
        """Nome previsivel permite adivinhar a URL da foto de um aluno."""
        import re

        from app.utils.arquivos import gerar_nome_arquivo

        nome = gerar_nome_arquivo("jpg")
        assert re.fullmatch(r"[0-9a-f]{32}\.jpg", nome), nome


# ===========================================================================
# 1.6 — Open redirect
# ===========================================================================
class TestOpenRedirect:
    def test_next_externo_e_ignorado_no_login(self, cliente, admin):
        resposta = cliente.post(
            "/auth/login?next=https://site-malicioso.example/fake",
            data={"email": admin.email, "senha": SENHA_PADRAO},
            follow_redirects=False,
        )
        assert "site-malicioso" not in resposta.headers.get("Location", "")

    def test_referer_externo_nao_e_usado_no_erro_de_dominio(
        self, cliente, secretaria, autenticar, aluno, turma, ano_letivo
    ):
        """Um erro previsivel com Referer externo jogaria o usuario para fora."""
        from app.services import matricula_service

        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        matricula_service.cancelar(matricula, "Desistencia")

        autenticar(secretaria)
        resposta = cliente.post(
            f"/matriculas/{matricula.id}/cancelar",
            data={"motivo": "Tentativa duplicada"},
            headers={"Referer": "https://site-malicioso.example/login"},
            follow_redirects=False,
        )

        assert "site-malicioso" not in resposta.headers.get("Location", "")

    @pytest.mark.parametrize(
        "destino",
        [
            "https://externo.example/x",
            "//externo.example/x",
            "http://externo.example",
        ],
    )
    def test_helper_recusa_destinos_externos(self, app, destino):
        from app.utils.navegacao import destino_seguro

        with app.test_request_context("/"):
            assert "externo.example" not in destino_seguro(destino)

    @pytest.mark.parametrize("destino", ["/alunos/", "/turmas/?pagina=2"])
    def test_helper_aceita_destinos_internos(self, app, destino):
        from app.utils.navegacao import destino_seguro

        with app.test_request_context("/"):
            assert destino_seguro(destino) == destino


# ===========================================================================
# 1.7 — Usuario desativado mantinha a sessao
# ===========================================================================
class TestSessaoDeUsuarioDesativado:
    def test_usuario_desativado_perde_sessao_imediatamente(
        self, cliente, admin, autenticar
    ):
        autenticar(admin)
        assert cliente.get("/alunos/").status_code == 200

        admin.ativo = False
        db.session.commit()

        resposta = cliente.get("/alunos/", follow_redirects=False)
        assert resposta.status_code == 302
        assert "/auth/login" in resposta.headers["Location"]

    def test_usuario_excluido_perde_sessao_imediatamente(
        self, cliente, admin, autenticar
    ):
        autenticar(admin)

        admin.excluir()
        db.session.commit()

        resposta = cliente.get("/alunos/", follow_redirects=False)
        assert resposta.status_code == 302

    def test_is_active_reflete_a_situacao_da_conta(self, app, admin):
        assert admin.is_active is True

        admin.ativo = False
        assert admin.is_active is False


# ===========================================================================
# Varredura paramétrica: nenhuma rota responde 200 sem a permissao
# ===========================================================================
class TestVarreduraDePermissoes:
    """Percorre todas as rotas GET com cada papel de baixo privilegio.

    Objetivo: nenhuma rota administrativa pode responder 200 para aluno ou
    responsavel. Rotas novas entram na varredura automaticamente.
    """

    #: Rotas legitimamente acessiveis a qualquer usuario autenticado.
    ROTAS_PERMITIDAS = {
        "painel.index",
        "auth.logout",
        "auth.alterar_senha",
        "usuarios.perfil",
        "avisos.listar",
        "avisos.detalhe",
        "boletim.meu_boletim",
        "boletim.index",
        "boletim.do_aluno",
        "frequencia.minha_frequencia",
        "frequencia.do_aluno",
        "horarios.meu_horario",
        "horarios.index",
        "horarios.do_aluno",
        "api.status",
        "api.sessao",
        "api.avisos",
        "alunos.foto",
        "static",
    }

    def _rotas_sem_parametro(self, app):
        for regra in app.url_map.iter_rules():
            if "GET" not in regra.methods or regra.arguments:
                continue
            if regra.endpoint in self.ROTAS_PERMITIDAS:
                continue
            yield regra

    def test_responsavel_nao_recebe_200_em_rota_administrativa(
        self, app, cliente, responsavel, autenticar
    ):
        autenticar(responsavel.usuario)

        vazamentos = [
            str(regra)
            for regra in self._rotas_sem_parametro(app)
            if cliente.get(str(regra)).status_code == 200
        ]
        assert not vazamentos, "Rotas acessiveis ao responsavel:\n" + "\n".join(
            vazamentos
        )

    def test_professor_nao_recebe_200_em_rota_de_sistema(
        self, app, cliente, professor, autenticar
    ):
        autenticar(professor.usuario)

        restritas = [
            "/usuarios/", "/configuracoes/", "/backup/", "/auditoria/",
            "/configuracoes/parametros", "/configuracoes/anos-letivos",
            "/configuracoes/estrutura",
        ]
        vazamentos = [
            rota for rota in restritas if cliente.get(rota).status_code == 200
        ]
        assert not vazamentos, f"Rotas acessiveis ao professor: {vazamentos}"
