"""Teste de fumaca: toda tela do sistema deve renderizar sem erro.

Objetivo
--------
Um erro de template (variavel inexistente, ``url_for`` para endpoint errado,
filtro ausente) so aparece quando a pagina e efetivamente renderizada. Sem
este teste, a falha chegaria ao usuario final como um erro 500.

O teste percorre **todas** as rotas ``GET`` registradas na aplicacao,
preenchendo os parametros de URL com dados reais criados pelas fixtures.
Toda tela nova entra automaticamente na cobertura — nao ha lista para
manter atualizada.
"""

from __future__ import annotations

from datetime import date

import pytest
from flask import url_for

from app.extensions import db
from app.models.avaliacao import Avaliacao
from app.models.comunicacao import Aviso
from app.models.enums import (
    PrioridadeAviso,
    PublicoAviso,
    SituacaoCadastro,
    TipoAvaliacao,
)
from app.models.pessoas import Funcionario
from app.models.sistema import LogAuditoria
from app.services import frequencia_service, matricula_service

#: Rotas que dependem de um recurso externo (arquivo em disco, token
#: assinado) e que por isso sao verificadas em testes proprios.
ROTAS_IGNORADAS = {
    "backup.baixar",       # exige arquivo fisico de backup
    "backup.restaurar",    # exige registro de backup existente
    "auth.redefinir_senha",  # exige token assinado valido
    "static",
}


@pytest.fixture
def base_completa(app, admin, ano_letivo, turma, disciplina, professor,
                  vinculo, aluno, responsavel, tempo_aula):
    """Cria um exemplar de cada entidade para alimentar as rotas com id."""
    matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)

    funcionario = Funcionario(
        nome_completo="Funcionario Teste",
        matricula_funcional="FUNC00001",
        cargo="Secretario escolar",
        situacao=SituacaoCadastro.ATIVO,
    )
    db.session.add(funcionario)

    aviso = Aviso(
        titulo="Aviso de teste",
        mensagem="Conteudo do aviso usado no teste de fumaca.",
        publico=PublicoAviso.TODOS,
        prioridade=PrioridadeAviso.NORMAL,
        publicado=True,
        data_inicio=date.today(),
        autor_id=admin.id,
    )
    db.session.add(aviso)
    db.session.commit()

    aula = frequencia_service.registrar_aula(
        vinculo, date.today(), conteudo="Aula do teste de fumaca"
    )

    avaliacao = Avaliacao(
        turma_disciplina_id=vinculo.id,
        periodo_id=ano_letivo.periodos[0].id,
        nome="Prova de teste",
        tipo=TipoAvaliacao.PROVA,
        peso=1,
        valor_maximo=10,
    )
    db.session.add(avaliacao)
    db.session.commit()

    registro_auditoria = db.session.query(LogAuditoria).first()

    return {
        "aluno_id": aluno.id,
        "turma_id": turma.id,
        "matricula_id": matricula.id,
        "professor_id": professor.id,
        "funcionario_id": funcionario.id,
        "responsavel_id": responsavel.id,
        "disciplina_id": disciplina.id,
        "usuario_id": admin.id,
        "aviso_id": aviso.id,
        "vinculo_id": vinculo.id,
        "aula_id": aula.id,
        "avaliacao_id": avaliacao.id,
        "ano_id": ano_letivo.id,
        "periodo_id": ano_letivo.periodos[0].id,
        "serie_id": turma.serie_id,
        "tempo_id": tempo_aula.id,
        "sala_id": 1,
        "backup_id": 1,
        "log_id": registro_auditoria.id if registro_auditoria else 1,
        "chave": "alunos",
        "frequencia_id": 1,
        "horario_id": 1,
        "token": "token-invalido",
    }


def _rotas_get(app):
    """Todas as rotas GET testaveis, com os parametros ja resolvidos."""
    for regra in sorted(app.url_map.iter_rules(), key=lambda r: str(r)):
        if "GET" not in regra.methods or regra.endpoint in ROTAS_IGNORADAS:
            continue
        yield regra


class TestFumacaDeTodasAsTelas:
    def test_toda_rota_get_renderiza(self, app, cliente_admin, base_completa):
        """Nenhuma tela do sistema pode responder com erro 4xx ou 5xx."""
        falhas: list[str] = []

        for regra in _rotas_get(app):
            try:
                parametros = {arg: base_completa[arg] for arg in regra.arguments}
            except KeyError as erro:
                pytest.fail(
                    f"A rota {regra.endpoint} usa o parametro {erro} que a "
                    "fixture 'base_completa' nao conhece. Acrescente-o la."
                )

            with app.test_request_context():
                url = url_for(regra.endpoint, **parametros)

            resposta = cliente_admin.get(url, follow_redirects=True)
            if resposta.status_code >= 400:
                falhas.append(f"{resposta.status_code} {url} ({regra.endpoint})")

        assert not falhas, "Telas com erro:\n" + "\n".join(falhas)

    def test_quantidade_minima_de_rotas(self, app):
        """Protege contra uma regressao que remova blueprints do registro."""
        assert len(list(app.url_map.iter_rules())) > 100


class TestGeracaoDeDocumentos:
    def test_boletim_em_pdf(self, cliente_admin, base_completa):
        resposta = cliente_admin.get(
            f"/boletim/aluno/{base_completa['aluno_id']}/pdf"
        )

        assert resposta.status_code == 200
        assert resposta.mimetype == "application/pdf"
        assert resposta.data[:4] == b"%PDF"

    def test_boletins_da_turma_em_pdf(self, cliente_admin, base_completa):
        resposta = cliente_admin.get(
            f"/boletim/turma/{base_completa['turma_id']}/pdf"
        )

        assert resposta.status_code == 200
        assert resposta.data[:4] == b"%PDF"

    def test_relatorio_em_excel(self, cliente_admin, base_completa):
        resposta = cliente_admin.get("/relatorios/alunos/excel")

        assert resposta.status_code == 200
        # Arquivos .xlsx sao ZIP: comecam com a assinatura "PK".
        assert resposta.data[:2] == b"PK"

    def test_relatorio_em_pdf(self, cliente_admin, base_completa):
        resposta = cliente_admin.get("/relatorios/turmas/pdf")

        assert resposta.status_code == 200
        assert resposta.data[:4] == b"%PDF"

    def test_documento_nao_fica_em_cache(self, cliente_admin, base_completa):
        """Boletim tem dado de aluno: nao pode ficar em cache de proxy."""
        resposta = cliente_admin.get(
            f"/boletim/aluno/{base_completa['aluno_id']}/pdf"
        )
        assert "no-store" in resposta.headers.get("Cache-Control", "")


class TestApiJson:
    def test_status_e_publico(self, cliente):
        """O health check precisa funcionar sem autenticacao."""
        resposta = cliente.get("/api/v1/status")

        assert resposta.status_code == 200
        assert resposta.json["dados"]["estado"] == "online"

    def test_sessao_exige_autenticacao(self, cliente):
        resposta = cliente.get("/api/v1/sessao")
        assert resposta.status_code in (302, 401)

    def test_sessao_devolve_o_usuario(self, cliente_admin, admin):
        resposta = cliente_admin.get("/api/v1/sessao")

        assert resposta.status_code == 200
        assert resposta.json["dados"]["email"] == admin.email

    def test_envelope_de_resposta(self, cliente_admin, base_completa):
        resposta = cliente_admin.get("/api/v1/turmas")

        assert resposta.json["sucesso"] is True
        assert isinstance(resposta.json["dados"], list)

    def test_erro_de_escopo_devolve_json(self, cliente, responsavel, autenticar,
                                         base_completa):
        """A API nao pode responder HTML a um cliente que pediu JSON."""
        autenticar(responsavel.usuario)
        resposta = cliente.get(
            f"/api/v1/turmas/{base_completa['turma_id']}/alunos"
        )

        assert resposta.status_code == 403
        assert resposta.is_json
