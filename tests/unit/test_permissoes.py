"""Testes da matriz de permissoes (RBAC).

Esta e a camada que decide o que cada perfil pode fazer. Um erro aqui abre o
sistema inteiro, entao a matriz e verificada explicitamente — inclusive as
negacoes, que sao o que realmente protege os dados.
"""

from __future__ import annotations

import pytest

from app.models.enums import PapelUsuario
from app.utils.permissoes import (
    Permissao,
    descrever_matriz,
    papel_tem_permissao,
    permissoes_do_papel,
    usuario_tem_alguma_permissao,
    usuario_tem_permissao,
    usuario_tem_todas_permissoes,
)


class UsuarioFalso:
    """Dublê minimo de usuario, suficiente para exercitar a matriz."""

    def __init__(self, papel, ativo=True, autenticado=True):
        self.papel = papel
        self.is_active = ativo
        self.is_authenticated = autenticado


class TestMatrizPorPapel:
    def test_administrador_tem_acesso_irrestrito(self):
        assert papel_tem_permissao(
            PapelUsuario.ADMINISTRADOR, Permissao.BACKUP_RESTAURAR
        )
        assert papel_tem_permissao(
            PapelUsuario.ADMINISTRADOR, Permissao.CONFIGURACAO_EDITAR
        )

    def test_permissao_inexistente_e_negada_mesmo_ao_administrador(self):
        """Mudanca deliberada da Fase 4 da auditoria.

        Enquanto a sentinela ``"*"`` era comparada na hora da verificacao,
        *qualquer* string passava para o administrador — inclusive um erro de
        digitacao. O bug ficava invisivel: a tela funcionava para quem
        testava (o admin) e negava acesso a todos os outros papeis, sem que
        nada apontasse para a permissao inexistente.

        Agora o conjunto do administrador e o catalogo real, entao um nome
        errado e negado para todo mundo, do mesmo jeito.
        """
        assert not papel_tem_permissao(
            PapelUsuario.ADMINISTRADOR, "permissao.que.nem.existe"
        )

    def test_secretaria_nao_lanca_notas(self):
        """Lancamento e ato pedagogico, exclusivo do professor."""
        assert papel_tem_permissao(PapelUsuario.SECRETARIA, Permissao.NOTA_VISUALIZAR)
        assert not papel_tem_permissao(PapelUsuario.SECRETARIA, Permissao.NOTA_LANCAR)

    def test_secretaria_nao_gerencia_usuarios(self):
        assert not papel_tem_permissao(
            PapelUsuario.SECRETARIA, Permissao.USUARIO_CRIAR
        )

    def test_professor_lanca_nota_e_frequencia(self):
        assert papel_tem_permissao(PapelUsuario.PROFESSOR, Permissao.NOTA_LANCAR)
        assert papel_tem_permissao(
            PapelUsuario.PROFESSOR, Permissao.FREQUENCIA_LANCAR
        )

    def test_professor_nao_cria_alunos_nem_matriculas(self):
        assert not papel_tem_permissao(PapelUsuario.PROFESSOR, Permissao.ALUNO_CRIAR)
        assert not papel_tem_permissao(
            PapelUsuario.PROFESSOR, Permissao.MATRICULA_CRIAR
        )

    def test_professor_nao_ve_dados_sensiveis_de_saude(self):
        assert not papel_tem_permissao(
            PapelUsuario.PROFESSOR, Permissao.ALUNO_VER_DADOS_SENSIVEIS
        )

    @pytest.mark.parametrize(
        "papel", [PapelUsuario.ALUNO, PapelUsuario.RESPONSAVEL]
    )
    def test_aluno_e_responsavel_sao_somente_leitura(self, papel):
        for permissao in (
            Permissao.ALUNO_CRIAR,
            Permissao.ALUNO_EDITAR,
            Permissao.NOTA_LANCAR,
            Permissao.FREQUENCIA_LANCAR,
            Permissao.MATRICULA_CRIAR,
            Permissao.TURMA_CRIAR,
            Permissao.USUARIO_VISUALIZAR,
            Permissao.AUDITORIA_VISUALIZAR,
            Permissao.BACKUP_EXECUTAR,
            Permissao.CONFIGURACAO_EDITAR,
        ):
            assert not papel_tem_permissao(papel, permissao), permissao

    @pytest.mark.parametrize(
        "papel", [PapelUsuario.ALUNO, PapelUsuario.RESPONSAVEL]
    )
    def test_aluno_e_responsavel_consultam_o_proprio_desempenho(self, papel):
        assert papel_tem_permissao(papel, Permissao.BOLETIM_VISUALIZAR)
        assert papel_tem_permissao(papel, Permissao.FREQUENCIA_VISUALIZAR)
        assert papel_tem_permissao(papel, Permissao.AVISO_VISUALIZAR)

    def test_apenas_administrador_restaura_backup(self):
        for papel in PapelUsuario:
            esperado = papel is PapelUsuario.ADMINISTRADOR
            assert papel_tem_permissao(papel, Permissao.BACKUP_RESTAURAR) is esperado

    def test_apenas_admin_e_direcao_veem_auditoria(self):
        permitidos = {PapelUsuario.ADMINISTRADOR, PapelUsuario.DIRECAO}
        for papel in PapelUsuario:
            esperado = papel in permitidos
            assert (
                papel_tem_permissao(papel, Permissao.AUDITORIA_VISUALIZAR) is esperado
            )

    def test_todo_papel_visualiza_avisos(self):
        for papel in PapelUsuario:
            assert papel_tem_permissao(papel, Permissao.AVISO_VISUALIZAR)


class TestUsuarioTemPermissao:
    def test_usuario_ativo_recebe_as_permissoes_do_papel(self):
        usuario = UsuarioFalso(PapelUsuario.PROFESSOR)
        assert usuario_tem_permissao(usuario, Permissao.NOTA_LANCAR) is True

    def test_conta_inativa_perde_todas_as_permissoes(self):
        """Desativar um funcionario desligado precisa ter efeito imediato."""
        usuario = UsuarioFalso(PapelUsuario.ADMINISTRADOR, ativo=False)
        assert usuario_tem_permissao(usuario, Permissao.ALUNO_VISUALIZAR) is False

    def test_usuario_nao_autenticado_nao_tem_permissao(self):
        usuario = UsuarioFalso(PapelUsuario.ADMINISTRADOR, autenticado=False)
        assert usuario_tem_permissao(usuario, Permissao.ALUNO_VISUALIZAR) is False

    def test_usuario_nulo_nao_tem_permissao(self):
        assert usuario_tem_permissao(None, Permissao.ALUNO_VISUALIZAR) is False

    def test_alguma_e_todas(self):
        usuario = UsuarioFalso(PapelUsuario.PROFESSOR)

        assert usuario_tem_alguma_permissao(
            usuario, Permissao.NOTA_LANCAR, Permissao.BACKUP_EXECUTAR
        )
        assert not usuario_tem_todas_permissoes(
            usuario, Permissao.NOTA_LANCAR, Permissao.BACKUP_EXECUTAR
        )
        assert usuario_tem_todas_permissoes(
            usuario, Permissao.NOTA_LANCAR, Permissao.NOTA_VISUALIZAR
        )


class TestIntegridadeDaMatriz:
    def test_todo_papel_tem_entrada_na_matriz(self):
        matriz = descrever_matriz()
        for papel in PapelUsuario:
            assert papel.value in matriz

    def test_papel_invalido_nao_recebe_permissao(self):
        assert permissoes_do_papel("papel_inexistente") == frozenset()
        assert permissoes_do_papel(None) == frozenset()

    def test_permissoes_declaradas_seguem_o_padrao_recurso_acao(self):
        """Nomes fora do padrao denunciam erro de digitacao na matriz."""
        for nome in dir(Permissao):
            if nome.startswith("_"):
                continue
            valor = getattr(Permissao, nome)
            if isinstance(valor, str):
                assert "." in valor, f"{nome} fora do padrao recurso.acao"
