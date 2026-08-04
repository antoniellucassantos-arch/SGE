"""Varredura de escopo: nenhuma rota com id fica so com permissao funcional.

A auditoria encontrou a mesma falha tres vezes — rota que recebe um id,
confere se o papel *pode fazer a acao* e nao confere se pode fazer **sobre
aquele registro**. E o OWASP A01, e o jeito mais barato de ler o dado de
outra crianca: trocar um numero na barra de enderecos.

CLAUDE.md registra a regra. Este arquivo a torna verificavel: percorre o
``url_map``, e para cada rota que recebe id **e que um papel de escopo
restrito alcanca**, exige uma das duas provas de que o escopo foi validado.

Por que a condicao "papel de escopo restrito alcanca": administrador,
direcao e secretaria enxergam a escola inteira. Uma rota que so eles
alcancam — editar sala, restaurar backup, excluir disciplina — nao tem
escopo a validar, e exigir decorador ali seria cerimonia sem defesa. O teste
calcula isso a partir da propria matriz de permissoes, em vez de depender de
uma lista escrita a mao que envelhece.
"""

from __future__ import annotations

import re

import pytest

from app.models.enums import PapelUsuario
from app.utils.decoradores import ATRIBUTO_ESCOPO, ATRIBUTO_PERMISSOES
from app.utils.permissoes import papel_tem_permissao

#: Papeis cujo alcance depende do registro, e nao apenas do papel.
PAPEIS_RESTRITOS = (
    PapelUsuario.PROFESSOR,
    PapelUsuario.ALUNO,
    PapelUsuario.RESPONSAVEL,
)

PADRAO_ID = re.compile(r"<(?:int:)?(\w*_?id)>")

#: Rotas que validam o escopo **dentro do corpo**, e nao por decorador.
#:
#: Sao legitimas: em varias delas o id da URL nao e o do recurso protegido
#: (uma aula aponta para um vinculo, um vinculo para uma turma), e o
#: decorador so sabe ler `kwargs`. O que nao pode e a validacao sumir sem
#: ninguem notar — por isso cada entrada diz onde ela esta.
#:
#: Entrada nova aqui exige leitura do codigo. Se voce esta acrescentando uma
#: linha para o teste passar, provavelmente o certo era o decorador.
VALIDAM_NO_CORPO: dict[str, str] = {
    "avisos.detalhe": "aviso.destinado_a(current_user) para quem nao e equipe",
    "avisos.editar": "_pode_editar(aviso): autor ou AVISO_EDITAR_QUALQUER",
    "avisos.excluir": "_pode_editar(aviso)",
    "frequencia.chamada": "_garantir_acesso_vinculo(aula.turma_disciplina)",
    "frequencia.diario": "_garantir_acesso_vinculo(vinculo)",
    "frequencia.excluir_aula": "_garantir_lancamento(aula.turma_disciplina)",
    "frequencia.justificar": "_garantir_lancamento(vinculo da frequencia)",
    "matriculas.detalhe": "pode_acessar_aluno(matricula.aluno_id)",
    "notas.criar_avaliacao": "_garantir_lancamento(vinculo)",
    "notas.excluir_avaliacao": "_garantir_lancamento(avaliacao.turma_disciplina)",
    "notas.lancar": "_garantir_acesso(vinculo)",
    "notas.publicar_avaliacao": "_garantir_lancamento(avaliacao.turma_disciplina)",
    "notas.salvar_notas": (
        "_garantir_lancamento na rota e pode_lancar_em_vinculo dentro do "
        "service (API e CLI nao passam por rota)"
    ),
    "usuarios.foto": "propria foto ou USUARIO_VISUALIZAR",
}


def _rotas_com_id(app):
    for regra in app.url_map.iter_rules():
        ids = PADRAO_ID.findall(str(regra))
        if ids:
            yield regra, ids


def _alcancavel_por_papel_restrito(permissoes: tuple[str, ...]) -> bool:
    """Se professor, aluno ou responsavel consegue chegar a rota.

    Sem permissao declarada, basta estar autenticado — o que inclui os tres.
    """
    if not permissoes:
        return True

    return any(
        papel_tem_permissao(papel, permissao)
        for papel in PAPEIS_RESTRITOS
        for permissao in permissoes
    )


def _coletar(app) -> dict[str, dict]:
    dados = {}
    for regra, ids in _rotas_com_id(app):
        view = app.view_functions[regra.endpoint]
        dados[regra.endpoint] = {
            "regra": str(regra),
            "ids": ids,
            "escopos": tuple(getattr(view, ATRIBUTO_ESCOPO, ())),
            "permissoes": tuple(getattr(view, ATRIBUTO_PERMISSOES, ())),
        }
    return dados


class TestVarreduraDeEscopo:
    def test_a_varredura_encontra_rotas(self, app):
        """Guarda do proprio teste.

        Se o padrao de id parar de casar — porque alguem passou a usar
        ``<uuid:...>``, por exemplo — a varredura passaria a examinar zero
        rotas e ficaria verde para sempre, sem proteger nada.
        """
        assert len(_coletar(app)) > 50

    def test_toda_rota_com_id_valida_escopo(self, app):
        """A regra da camada 2, verificada rota a rota."""
        desprotegidas = []

        for endpoint, info in sorted(_coletar(app).items()):
            if info["escopos"] or endpoint in VALIDAM_NO_CORPO:
                continue
            if not _alcancavel_por_papel_restrito(info["permissoes"]):
                continue

            desprotegidas.append(
                f"{endpoint} ({info['regra']}) "
                f"perm={','.join(info['permissoes']) or '(nenhuma)'}"
            )

        assert not desprotegidas, (
            "Rota que recebe id sem validacao de escopo — trocar o numero na "
            "URL alcanca o registro de outra pessoa:\n  "
            + "\n  ".join(desprotegidas)
        )

    def test_lista_de_excecoes_nao_tem_entrada_morta(self, app):
        """Excecao que sobra vira permissao esquecida.

        Se uma rota ganhou decorador ou deixou de existir, a entrada aqui
        precisa sair — senao a lista cresce e para de significar alguma
        coisa.
        """
        coletadas = _coletar(app)
        obsoletas = [
            endpoint
            for endpoint in VALIDAM_NO_CORPO
            if endpoint not in coletadas or coletadas[endpoint]["escopos"]
        ]

        assert not obsoletas, (
            "Entradas de VALIDAM_NO_CORPO que nao sao mais necessarias: "
            f"{obsoletas}"
        )

    def test_rotas_de_aluno_e_turma_usam_decorador(self, app):
        """Quando o id da URL **e** o do recurso, o decorador e obrigatorio.

        Validar no corpo funciona, mas depende de alguem lembrar. Nestes
        casos nao ha desculpa: `aluno_id` e `turma_id` na assinatura sao
        exatamente o que `exigir_acesso_aluno()` e `exigir_acesso_turma()`
        leem.
        """
        sem_decorador = []

        for endpoint, info in sorted(_coletar(app).items()):
            if not _alcancavel_por_papel_restrito(info["permissoes"]):
                continue
            for parametro in ("aluno_id", "turma_id"):
                if parametro in info["ids"] and parametro not in info["escopos"]:
                    sem_decorador.append(f"{endpoint} ({parametro})")

        assert not sem_decorador, (
            "Rota com id de aluno ou turma na URL deveria usar o decorador "
            f"de escopo: {sem_decorador}"
        )


# ===========================================================================
# O caso concreto que a varredura encontrou
# ===========================================================================
class TestMatriculaDeOutraTurma:
    @pytest.fixture
    def matricula_alheia(self, app, ano_letivo, serie):
        """Matricula de um aluno em turma sem vinculo com o professor."""
        from datetime import date

        from app.extensions import db
        from app.models.enums import SituacaoCadastro, SituacaoMatricula, Turno
        from app.models.estrutura import Turma
        from app.models.matricula import Matricula
        from app.models.pessoas import Aluno

        turma = Turma(
            nome="Z",
            ano_letivo_id=ano_letivo.id,
            serie_id=serie.id,
            turno=Turno.NOTURNO,
            capacidade=30,
            ativa=True,
        )
        db.session.add(turma)
        db.session.flush()

        aluno = Aluno(
            nome_completo="Aluno de Outra Turma",
            codigo=Aluno.gerar_codigo(),
            data_nascimento=date(2011, 3, 3),
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
        db.session.commit()
        return matricula

    def test_professor_nao_abre_matricula_de_turma_alheia(
        self, app, cliente_professor, vinculo, matricula_alheia
    ):
        """`MATRICULA_VISUALIZAR` esta na matriz do professor.

        Sem escopo, ele percorria `/matriculas/1`, `/matriculas/2`... e lia
        a ficha de matricula de qualquer aluno da escola.
        """
        resposta = cliente_professor.get(f"/matriculas/{matricula_alheia.id}")
        assert resposta.status_code == 403

    def test_professor_abre_matricula_da_propria_turma(
        self, app, cliente_professor, vinculo, matricula
    ):
        """Regressao: a correcao nao pode fechar o acesso legitimo."""
        resposta = cliente_professor.get(f"/matriculas/{matricula.id}")
        assert resposta.status_code == 200

    def test_secretaria_continua_vendo_qualquer_matricula(
        self, app, cliente, secretaria, autenticar, matricula_alheia
    ):
        autenticar(secretaria)
        resposta = cliente.get(f"/matriculas/{matricula_alheia.id}")
        assert resposta.status_code == 200
