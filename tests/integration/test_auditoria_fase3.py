"""Testes da Fase 3 da auditoria: robustez e consistencia.

Nenhum destes bugs produz nota errada nem vaza dado. Eles aparecem quando
algo *ja* deu errado: uma consulta que falha, um acesso negado, um lote
pesado no fechamento do periodo. Sao justamente os momentos em que o
sistema precisa se comportar bem.
"""

from __future__ import annotations

import contextlib
from datetime import date

import pytest
from sqlalchemy import event

from app.extensions import db
from app.models.enums import (
    AcaoAuditoria,
    NivelEnsino,
    PapelUsuario,
    SituacaoCadastro,
    SituacaoMatricula,
    TipoAvaliacao,
    Turno,
)
from app.models.estrutura import Serie, Turma, TurmaDisciplina
from app.models.matricula import Matricula
from app.models.pessoas import Aluno
from app.models.sistema import ConfiguracaoEscola, LogAuditoria
from app.services import configuracao_service, nota_service
from tests.conftest import criar_usuario


# ===========================================================================
# Instrumentacao
# ===========================================================================
@contextlib.contextmanager
def contar_commits():
    """Conta os ``commit`` efetivados na sessao dentro do bloco."""
    contagem = {"total": 0}

    def registrar(_sessao):
        contagem["total"] += 1

    event.listen(db.session, "after_commit", registrar)
    try:
        yield contagem
    finally:
        event.remove(db.session, "after_commit", registrar)


@contextlib.contextmanager
def contar_consultas(padrao: str | None = None):
    """Conta as instrucoes SQL executadas, opcionalmente filtrando por texto."""
    contagem = {"total": 0}
    motor = db.session.get_bind()

    def registrar(_conexao, _cursor, instrucao, *_resto):
        if padrao is None or padrao.lower() in instrucao.lower():
            contagem["total"] += 1

    event.listen(motor, "before_cursor_execute", registrar)
    try:
        yield contagem
    finally:
        event.remove(motor, "before_cursor_execute", registrar)


# ===========================================================================
# 3.1 — Sessao suja depois de `except Exception`
# ===========================================================================
class TestSessaoAposFalha:
    def test_falha_ao_carregar_ano_letivo_desfaz_a_transacao(self, app, monkeypatch):
        """Sem ``rollback``, no Postgres a requisicao inteira morre em cascata.

        O ``except Exception`` foi escrito pensando em "banco ainda nao
        migrado", mas ele tambem pega timeout, deadlock e coluna removida.
        Nesses casos a transacao fica abortada e *toda* consulta seguinte
        falha com ``InFailedSqlTransaction``.
        """
        from app.hooks import carregar_ano_letivo_corrente

        desfeita = {"chamado": False}
        rollback_original = db.session.rollback

        def espiao_rollback():
            desfeita["chamado"] = True
            rollback_original()

        def consulta_que_falha(*_args, **_kwargs):
            raise RuntimeError("conexao perdida")

        monkeypatch.setattr(db.session, "rollback", espiao_rollback)
        monkeypatch.setattr(db.session, "query", consulta_que_falha)

        assert carregar_ano_letivo_corrente() is None
        assert desfeita["chamado"], "a transacao ficou suja apos a falha"

    def test_falha_ao_carregar_a_escola_desfaz_a_transacao(self, app, monkeypatch):
        """Mesma armadilha no ``context_processor`` dos templates."""
        desfeita = {"chamado": False}
        rollback_original = db.session.rollback

        def espiao_rollback():
            desfeita["chamado"] = True
            rollback_original()

        @classmethod
        def obter_que_falha(_cls):
            raise RuntimeError("conexao perdida")

        monkeypatch.setattr(db.session, "rollback", espiao_rollback)
        monkeypatch.setattr(ConfiguracaoEscola, "obter", obter_que_falha)

        with app.test_request_context("/"):
            contexto = {}
            for processador in app.template_context_processors[None]:
                contexto.update(processador())

        assert contexto["escola"] is None
        assert desfeita["chamado"], "a transacao ficou suja apos a falha"


# ===========================================================================
# 3.3 — Auditoria de acesso negado pode se perder
# ===========================================================================
@pytest.fixture
def turma_alheia(app, ano_letivo, serie) -> Turma:
    """Turma sem nenhum vinculo com o professor da fixture padrao."""
    outra_serie = Serie(
        nome="7o Ano", nivel_ensino=NivelEnsino.FUNDAMENTAL_II, ordem=2, ativa=True
    )
    db.session.add(outra_serie)
    db.session.flush()

    turma = Turma(
        nome="B",
        ano_letivo_id=ano_letivo.id,
        serie_id=outra_serie.id,
        turno=Turno.VESPERTINO,
        capacidade=30,
        ativa=True,
    )
    db.session.add(turma)
    db.session.commit()
    return turma


def _acessos_negados() -> list[LogAuditoria]:
    return (
        db.session.query(LogAuditoria)
        .filter(LogAuditoria.acao == AcaoAuditoria.ACESSO_NEGADO)
        .all()
    )


class TestAuditoriaDeAcessoNegado:
    def test_decorador_persiste_o_registro(
        self, app, cliente_professor, turma_alheia
    ):
        """`abort(403)` derruba a sessao logo depois — o log precisa sobreviver."""
        resposta = cliente_professor.get(f"/turmas/{turma_alheia.id}")
        assert resposta.status_code == 403

        db.session.remove()
        assert _acessos_negados(), "o registro de acesso negado se perdeu"

    def test_erro_permissao_do_service_tambem_e_auditado(
        self, app, cliente_professor, turma_alheia
    ):
        """Escopo negado na querystring nao passa por decorador nenhum.

        A Fase 1 fechou o buraco levantando ``ErroPermissao`` no proprio
        blueprint. Mas quem levanta a excecao nao registra nada: a tentativa
        de ler as notas de outra turma — exatamente o sinal que interessa —
        nao aparecia na trilha.
        """
        resposta = cliente_professor.get(
            f"/relatorios/desempenho?turma_id={turma_alheia.id}"
        )
        assert resposta.status_code == 403

        db.session.remove()
        registros = _acessos_negados()
        assert registros, "ErroPermissao do service nao foi auditado"
        assert any("desempenho" in (r.rota or "") for r in registros)

    def test_acesso_permitido_nao_gera_registro(
        self, app, cliente_professor, vinculo, turma
    ):
        """A trilha so vale se o ruido ficar de fora.

        O ``vinculo`` e o que torna esta turma legitimamente do professor.
        """
        cliente_professor.get(f"/turmas/{turma.id}")

        db.session.remove()
        assert _acessos_negados() == []


# ===========================================================================
# 3.7 — Performance da consolidacao
# ===========================================================================
@pytest.fixture
def turma_cheia(app, ano_letivo, turma, professor, disciplina):
    """Turma com varios alunos e varias disciplinas.

    O tamanho e modesto de proposito: o objetivo e medir a *ordem de
    grandeza* do numero de commits e consultas, nao cronometrar.
    """
    from app.models.estrutura import Disciplina

    vinculos = []
    for indice in range(3):
        outra = Disciplina(
            nome=f"Disciplina {indice}",
            codigo=f"D{indice:02d}",
            carga_horaria=100,
            ativa=True,
        )
        db.session.add(outra)
        db.session.flush()

        vinculo = TurmaDisciplina(
            turma_id=turma.id,
            disciplina_id=outra.id,
            professor_id=professor.id,
            carga_horaria_semanal=2,
            ativa=True,
        )
        db.session.add(vinculo)
        vinculos.append(vinculo)

    matriculas = []
    for indice in range(5):
        aluno = Aluno(
            nome_completo=f"Aluno {indice:02d}",
            codigo=Aluno.gerar_codigo(),
            data_nascimento=date(2012, 5, 10),
            situacao=SituacaoCadastro.ATIVO,
        )
        db.session.add(aluno)
        db.session.flush()

        matricula = Matricula(
            numero=Matricula.gerar_numero(ano_letivo.ano),
            aluno_id=aluno.id,
            turma_id=turma.id,
            ano_letivo_id=ano_letivo.id,
            data_matricula=date.today(),
            situacao=SituacaoMatricula.ATIVA,
        )
        db.session.add(matricula)
        matriculas.append(matricula)

    db.session.commit()

    periodo = ano_letivo.periodos[0]
    for vinculo in vinculos:
        avaliacao = nota_service.criar_avaliacao(
            vinculo, periodo.id, "Prova", TipoAvaliacao.PROVA
        )
        nota_service.salvar_notas(
            avaliacao, {m.id: "7" for m in matriculas}
        )

    return {"turma": turma, "matriculas": matriculas, "vinculos": vinculos}


class TestPerformanceDaConsolidacao:
    def test_consolidar_turma_usa_poucos_commits(self, app, turma_cheia):
        """Um commit por aluno **por disciplina** nao escala.

        5 alunos x 3 disciplinas ja produziam 20 commits. Numa turma real
        (40 alunos, 12 disciplinas) sao quase 500 — cada um com o custo de
        um fsync.
        """
        with contar_commits() as commits:
            nota_service.consolidar_turma(turma_cheia["turma"])

        assert commits["total"] <= 2, (
            f"{commits['total']} commits para consolidar uma turma"
        )

    def test_consolidar_turma_carrega_notas_em_lote(self, app, turma_cheia):
        """Notas e frequencia vem por turma, nao por aluno por disciplina."""
        with contar_consultas("from notas") as consultas:
            nota_service.consolidar_turma(turma_cheia["turma"])

        assert consultas["total"] <= 3, (
            f"{consultas['total']} consultas a notas para uma unica turma"
        )

    def test_consolidacao_em_lote_produz_o_mesmo_resultado(self, app, turma_cheia):
        """Otimizar nao pode mudar nota: os valores tem de bater com o
        calculo individual, aluno a aluno."""
        matricula = turma_cheia["matriculas"][0]
        vinculo = turma_cheia["vinculos"][0]

        individual = nota_service.calcular_resultado_disciplina(matricula, vinculo)
        esperado = (
            individual.media_final,
            individual.media_anual,
            individual.total_aulas,
            individual.resultado,
        )

        nota_service.consolidar_turma(turma_cheia["turma"])
        db.session.refresh(individual)

        assert (
            individual.media_final,
            individual.media_anual,
            individual.total_aulas,
            individual.resultado,
        ) == esperado


# ===========================================================================
# 3.8 — `ConfiguracaoEscola.obter()` a cada requisicao
# ===========================================================================
class TestCacheDaConfiguracao:
    def test_varias_requisicoes_consultam_a_escola_uma_vez(
        self, app, cliente_admin, escola
    ):
        """Dentro de uma requisicao a identity map ja evitava a repeticao.

        O desperdicio esta *entre* requisicoes: o ``context_processor`` roda
        a cada renderizacao e a sessao e descartada no fim de cada uma, entao
        o cabecalho da escola — que muda uma vez por semestre — ia ao banco
        em toda tela aberta por todo mundo, o dia inteiro.
        """
        cliente_admin.get("/painel/")  # aquece

        with contar_consultas("from configuracoes_escola") as consultas:
            for _ in range(5):
                cliente_admin.get("/painel/")

        assert consultas["total"] == 0, (
            f"{consultas['total']} consultas para um dado que muda por semestre"
        )

    def test_alteracao_invalida_o_cache(self, app, escola):
        """Cache que nao invalida e pior que cache nenhum."""
        ConfiguracaoEscola.obter()

        configuracao_service.atualizar_escola({"nome": "Escola Renomeada"})

        assert ConfiguracaoEscola.obter().nome == "Escola Renomeada"

    def test_objeto_devolvido_pertence_a_sessao_corrente(self, app, escola):
        """Guardar a *instancia* entre requisicoes vazaria um objeto de uma
        sessao ja encerrada — o erro classico de cache de ORM.

        Alterar o registro devolvido tem de continuar funcionando.
        """
        atual = ConfiguracaoEscola.obter()
        atual.nome = "Escola A"
        db.session.commit()

        assert ConfiguracaoEscola.obter().nome == "Escola A"
        assert ConfiguracaoEscola.obter() in db.session


# ===========================================================================
# 3.9 — CSP e os graficos
# ===========================================================================
class TestPoliticaDeScripts:
    def test_cabecalho_proibe_script_inline(self, app, cliente_admin):
        resposta = cliente_admin.get("/painel/")
        politica = resposta.headers.get("Content-Security-Policy", "")

        assert "script-src 'self'" in politica
        assert "unsafe-inline" not in politica.split("style-src")[0]

    def test_paginas_nao_trazem_script_executavel_inline(
        self, app, cliente_admin, matricula
    ):
        """A CSP so protege se ninguem depender de script inline.

        Um `<script>` inline em qualquer tela quebraria silenciosamente em
        producao: a pagina carrega, o grafico some, e nada aparece no log do
        servidor.
        """
        import re

        for rota in ("/painel/", "/alunos/", "/turmas/", "/relatorios/"):
            corpo = cliente_admin.get(rota).get_data(as_text=True)

            for tag in re.findall(r"<script\b[^>]*>", corpo):
                assert "src=" in tag or 'type="application/json"' in tag, (
                    f"script inline executavel em {rota}: {tag}"
                )


# ===========================================================================
# 3.10 — Requisicoes `/api/v1` recebem 302 HTML
# ===========================================================================
class TestApiComSenhaPendente:
    @pytest.fixture
    def cliente_com_senha_pendente(self, app, cliente, autenticar):
        usuario = criar_usuario(
            "pendente@escola.com.br",
            PapelUsuario.SECRETARIA,
            "Usuario Pendente",
            deve_trocar_senha=True,
        )
        autenticar(usuario)
        return cliente

    def test_api_devolve_403_json(self, app, cliente_com_senha_pendente):
        """Cliente JSON nao sabe o que fazer com uma tela de login em HTML."""
        resposta = cliente_com_senha_pendente.get("/api/v1/sessao")

        assert resposta.status_code == 403
        assert resposta.is_json
        assert "senha" in resposta.get_json()["erro"].lower()

    def test_navegacao_continua_redirecionando(self, app, cliente_com_senha_pendente):
        """A tela normal precisa seguir levando a pessoa para a troca."""
        resposta = cliente_com_senha_pendente.get("/painel/")

        assert resposta.status_code == 302
        assert "/auth/alterar-senha" in resposta.headers["Location"]


# ===========================================================================
# Regressao das fases anteriores
# ===========================================================================
def test_professor_continua_sem_ver_turma_alheia(
    app, cliente_professor, turma_alheia
):
    """Guarda a correcao 1.1 enquanto a Fase 3 mexe no tratamento de erro."""
    resposta = cliente_professor.get(
        f"/relatorios/desempenho?turma_id={turma_alheia.id}"
    )
    assert resposta.status_code == 403
