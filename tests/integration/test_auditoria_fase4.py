"""Testes da Fase 4 da auditoria: correcoes de RBAC.

Dois problemas de natureza oposta. A sentinela ``"*"`` cria uma segunda API
de consulta que responde errado justamente para o papel mais poderoso. E a
permissao de dados sensiveis existe no catalogo, aparece na documentacao e
nao e consultada em lugar nenhum — dado de saude de menor de idade indo
para quem tiver ``aluno.visualizar``.
"""

from __future__ import annotations

import pytest

from app.extensions import db
from app.models.enums import PapelUsuario
from app.services import aluno_service
from app.utils.permissoes import (
    MATRIZ_PERMISSOES,
    PERMISSOES_COMUNS,
    TODAS_PERMISSOES,
    Permissao,
    descrever_matriz,
    papel_tem_permissao,
    permissoes_do_papel,
)


# ===========================================================================
# 4.1 — A sentinela `"*"` cria duas APIs, uma delas armadilha
# ===========================================================================
class TestSentinelaDoAdministrador:
    def test_consulta_direta_ao_conjunto_nao_nega_o_administrador(self):
        """`perm in permissoes_do_papel(...)` tem de funcionar.

        Enquanto a sentinela vazava no retorno, existiam duas formas de
        perguntar a mesma coisa e uma delas mentia: quem escrevesse a
        verificacao mais obvia negava acesso ao administrador, em silencio.
        """
        concedidas = permissoes_do_papel(PapelUsuario.ADMINISTRADOR)

        assert Permissao.ALUNO_CRIAR in concedidas
        assert Permissao.BACKUP_RESTAURAR in concedidas
        assert Permissao.USUARIO_EXCLUIR in concedidas

    def test_sentinela_nao_vaza_para_fora_do_modulo(self):
        assert "*" not in permissoes_do_papel(PapelUsuario.ADMINISTRADOR)

    def test_administrador_recebe_o_catalogo_inteiro(self):
        assert permissoes_do_papel(PapelUsuario.ADMINISTRADOR) == TODAS_PERMISSOES

    def test_catalogo_cobre_todas_as_constantes(self):
        """`TODAS_PERMISSOES` e derivado do catalogo, nao mantido a mao."""
        declaradas = {
            valor
            for nome, valor in vars(Permissao).items()
            if not nome.startswith("_") and isinstance(valor, str)
        }
        assert TODAS_PERMISSOES == declaradas

    def test_matriz_documentada_e_util_para_o_administrador(self):
        """`descrever_matriz()` existe para documentacao e teste.

        Devolver ``["*", "aviso.visualizar"]` no papel mais critico tornava a
        saida inutil exatamente onde ela mais importa.
        """
        documentada = descrever_matriz()["administrador"]

        assert "*" not in documentada
        assert len(documentada) == len(TODAS_PERMISSOES)
        assert Permissao.CONFIGURACAO_EDITAR in documentada

    def test_verificacao_por_papel_continua_valendo(self):
        """Regressao: o caminho antigo nao pode ter mudado de resposta."""
        assert papel_tem_permissao(
            PapelUsuario.ADMINISTRADOR, Permissao.BACKUP_EXECUTAR
        )
        assert not papel_tem_permissao(
            PapelUsuario.PROFESSOR, Permissao.BACKUP_EXECUTAR
        )
        assert not papel_tem_permissao(None, Permissao.ALUNO_VISUALIZAR)


# ===========================================================================
# 4.3 — `ALUNO_VER_DADOS_SENSIVEIS` precisa agir na serializacao
# ===========================================================================
@pytest.fixture
def aluno_com_dados_sensiveis(app, aluno, matricula):
    """Aluno com documentos e ficha de saude preenchidos.

    A ``matricula`` entra porque e ela que autoriza o professor a abrir a
    ficha: sem aluno na turma dele, o teste mediria o escopo, nao a
    permissao.
    """
    aluno.cpf = "39053344705"
    aluno.rg = "123456789"
    aluno.nis = "12345678901"
    aluno.cartao_sus = "123456789012345"
    aluno.certidao_nascimento = "111111 01 55 2012 1 00123 456 7654321-99"
    aluno.tipo_sanguineo = "O+"
    aluno.alergias = "Alergia grave a amendoim"
    aluno.medicamentos_continuos = "Salbutamol inalatorio"
    aluno.condicoes_saude = "Asma"
    aluno.possui_deficiencia = True
    aluno.descricao_deficiencia = "Baixa visao"
    db.session.commit()
    return aluno


#: Trechos que jamais podem chegar a quem nao tem a permissao.
SEGREDOS = (
    "amendoim",
    "Salbutamol",
    "Asma",
    "Baixa visao",
    "12345678901",
    "123456789012345",
)


class TestDadosSensiveisDoAluno:
    def test_professor_nao_recebe_saude_nem_documentos(
        self, app, cliente_professor, vinculo, aluno_com_dados_sensiveis
    ):
        """Esconder o `<td>` no template nao resolve: o dado ja foi enviado.

        O professor precisa da ficha do aluno para dar aula. Nao precisa do
        CPF, do NIS nem do laudo de saude — que sao dado sensivel de menor
        de idade sob a LGPD.
        """
        resposta = cliente_professor.get(f"/alunos/{aluno_com_dados_sensiveis.id}")
        assert resposta.status_code == 200

        corpo = resposta.get_data(as_text=True)
        for segredo in SEGREDOS:
            assert segredo not in corpo, f"vazou '{segredo}' para o professor"

        # O CPF sai formatado pelo filtro do Jinja; procura pelos dois jeitos.
        assert "39053344705" not in corpo
        assert "390.533.447-05" not in corpo

    def test_professor_nao_ve_nem_o_indicio_de_saude_na_listagem(
        self, app, cliente_professor, vinculo, aluno_com_dados_sensiveis
    ):
        """"Este aluno tem uma condicao de saude" ja e informacao de saude."""
        corpo = cliente_professor.get("/alunos/").get_data(as_text=True)
        assert "informacoes de saude relevantes" not in corpo

    def test_secretaria_continua_vendo_tudo(
        self, app, cliente, secretaria, autenticar, aluno_com_dados_sensiveis
    ):
        """A permissao serve para restringir, nao para esconder de todos."""
        autenticar(secretaria)
        corpo = cliente.get(f"/alunos/{aluno_com_dados_sensiveis.id}").get_data(
            as_text=True
        )

        assert "amendoim" in corpo
        assert "390.533.447-05" in corpo

    def test_serializacao_filtra_por_permissao(
        self, app, aluno_com_dados_sensiveis, professor, secretaria
    ):
        """A regra vive no service — a API e a CLI nao passam por template."""
        restrito = aluno_service.serializar(
            aluno_com_dados_sensiveis, professor.usuario
        )
        completo = aluno_service.serializar(aluno_com_dados_sensiveis, secretaria)

        for campo in ("cpf", "alergias", "condicoes_saude", "nis"):
            assert campo not in restrito, f"'{campo}' vazou na serializacao"
            assert campo in completo

        # O que nao e sensivel continua saindo para os dois.
        assert restrito["nome_completo"] == completo["nome_completo"]
        assert restrito["codigo"] == completo["codigo"]

    def test_ficha_devolve_none_no_lugar_do_dado(
        self, app, aluno_com_dados_sensiveis, professor
    ):
        """A ficha entregue ao template ja vem filtrada.

        Assim um `{% if %}` esquecido em um template futuro nao vaza nada:
        nao ha o que exibir.
        """
        ficha = aluno_service.montar_ficha(
            aluno_com_dados_sensiveis, professor.usuario
        )

        assert ficha.alergias is None
        assert ficha.cpf is None
        assert ficha.tem_alerta_saude is False
        # O resto da ficha continua utilizavel.
        assert ficha.nome_completo == aluno_com_dados_sensiveis.nome_completo
        assert ficha.id == aluno_com_dados_sensiveis.id

    def test_relatorio_administrativo_mascara_o_cpf(
        self, app, aluno_com_dados_sensiveis, vinculo, professor, secretaria
    ):
        """Exportacao tambem e serializacao.

        Hoje so tem `relatorio.administrativo` quem tambem tem
        `aluno.ver_dados_sensiveis`. A mascara existe para o dia em que a
        escola conceder o relatorio ao coordenador — sem ela a planilha
        entrega o CPF de todos os alunos junto.
        """
        from flask_login import login_user

        from app.services import relatorio_service

        with app.test_request_context("/"):
            login_user(professor.usuario)
            restrito = relatorio_service.relatorio_alunos()

        with app.test_request_context("/"):
            login_user(secretaria)
            completo = relatorio_service.relatorio_alunos()

        coluna = completo["cabecalhos"].index("CPF")

        # O professor precisa enxergar a linha — senao o teste passaria por
        # falta de dado, e nao pela mascara.
        assert restrito["linhas"], "escopo vazio: o teste nao exercitou a mascara"
        assert completo["linhas"][0][coluna] == "390.533.447-05"
        assert all(linha[coluna] == "—" for linha in restrito["linhas"])

    def test_permissao_e_a_fonte_da_verdade(self):
        """Quem decide e a matriz, nao uma lista de papeis repetida na rota."""
        for papel in (
            PapelUsuario.ADMINISTRADOR,
            PapelUsuario.DIRECAO,
            PapelUsuario.SECRETARIA,
        ):
            assert papel_tem_permissao(papel, Permissao.ALUNO_VER_DADOS_SENSIVEIS)

        for papel in (
            PapelUsuario.PROFESSOR,
            PapelUsuario.ALUNO,
            PapelUsuario.RESPONSAVEL,
        ):
            assert not papel_tem_permissao(
                papel, Permissao.ALUNO_VER_DADOS_SENSIVEIS
            )


# ===========================================================================
# 4.4 — Limpezas
# ===========================================================================
class TestHigieneDaMatriz:
    def test_permissao_comum_nao_e_repetida_nos_papeis(self):
        """Repetida em cinco lugares, um dia sai de quatro e fica em um."""
        for papel, concedidas in MATRIZ_PERMISSOES.items():
            repetidas = concedidas & PERMISSOES_COMUNS
            assert not repetidas, (
                f"{papel.value} repete permissao comum: {sorted(repetidas)}"
            )

    def test_permissao_comum_continua_valendo_para_todos(self):
        """Regressao da limpeza acima: ninguem pode ter perdido o aviso."""
        for papel in PapelUsuario:
            assert papel_tem_permissao(papel, Permissao.AVISO_VISUALIZAR)
