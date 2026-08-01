"""Testes das regras de negocio criticas da escola.

Sao as regras que, se falharem, produzem dano real: aluno matriculado duas
vezes, turma acima da capacidade, nota fora da escala, boletim com media
errada, historico apagado.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.avaliacao import Nota
from app.models.enums import (
    ResultadoFinal,
    SituacaoAnoLetivo,
    SituacaoCadastro,
    SituacaoMatricula,
    SituacaoPresenca,
    TipoAvaliacao,
)
from app.models.frequencia import Frequencia
from app.models.pessoas import Aluno
from app.services import (
    aluno_service,
    frequencia_service,
    matricula_service,
    nota_service,
    turma_service,
)
from app.services.excecoes import (
    ErroConflito,
    ErroRegraNegocio,
    ErroValidacao,
    RegistroNaoEncontrado,
)


# ---------------------------------------------------------------------------
# Matriculas
# ---------------------------------------------------------------------------
class TestMatricula:
    def test_matricula_gera_numero_sequencial(self, app, aluno, turma, ano_letivo):
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)

        assert matricula.numero.startswith(f"{ano_letivo.ano}-")
        assert matricula.situacao is SituacaoMatricula.ATIVA

    def test_aluno_nao_pode_ter_duas_matriculas_no_mesmo_ano(
        self, app, aluno, turma, ano_letivo
    ):
        """Matricula duplicada corromperia notas e frequencia do aluno."""
        matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)

        with pytest.raises(ErroConflito) as erro:
            matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        assert "ja possui matricula" in erro.value.mensagem.lower()

    def test_turma_lotada_recusa_nova_matricula(self, app, turma, ano_letivo):
        turma.capacidade = 2
        db.session.commit()

        for indice in range(2):
            novo = Aluno(
                nome_completo=f"Aluno {indice}",
                codigo=f"TESTE{indice:04d}",
                situacao=SituacaoCadastro.ATIVO,
            )
            db.session.add(novo)
            db.session.commit()
            matricula_service.matricular(novo.id, turma.id, ano_letivo.id)

        excedente = Aluno(
            nome_completo="Aluno Excedente",
            codigo="TESTE9999",
            situacao=SituacaoCadastro.ATIVO,
        )
        db.session.add(excedente)
        db.session.commit()

        with pytest.raises(ErroRegraNegocio) as erro:
            matricula_service.matricular(excedente.id, turma.id, ano_letivo.id)
        assert "capacidade" in erro.value.mensagem.lower()

    def test_ano_letivo_encerrado_recusa_matricula(
        self, app, aluno, turma, ano_letivo
    ):
        ano_letivo.situacao = SituacaoAnoLetivo.ENCERRADO
        db.session.commit()

        with pytest.raises(ErroRegraNegocio) as erro:
            matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        assert "encerrado" in erro.value.mensagem.lower()

    def test_transferencia_de_turma_preserva_a_matricula(
        self, app, aluno, turma, ano_letivo, serie
    ):
        """Notas e frequencia acompanham o aluno na nova turma."""
        from app.models.enums import Turno
        from app.models.estrutura import Turma

        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        numero_original = matricula.numero

        destino = Turma(
            nome="B",
            ano_letivo_id=ano_letivo.id,
            serie_id=serie.id,
            turno=Turno.MATUTINO,
            capacidade=30,
            ativa=True,
        )
        db.session.add(destino)
        db.session.commit()

        matricula_service.transferir_turma(matricula, destino.id, "Ajuste de turno")

        assert matricula.turma_id == destino.id
        assert matricula.numero == numero_original  # mesma matricula
        assert matricula.situacao is SituacaoMatricula.ATIVA

    def test_transferencia_para_a_mesma_turma_e_recusada(
        self, app, aluno, turma, ano_letivo
    ):
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)

        with pytest.raises(ErroRegraNegocio):
            matricula_service.transferir_turma(matricula, turma.id)

    def test_cancelamento_libera_vaga_na_turma(self, app, aluno, turma, ano_letivo):
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        assert turma.contar_matriculas_ativas() == 1

        matricula_service.cancelar(matricula, "Desistencia")

        assert turma.contar_matriculas_ativas() == 0
        assert matricula.situacao is SituacaoMatricula.CANCELADA

    def test_transferencia_de_escola_preserva_o_historico(
        self, app, aluno, turma, ano_letivo
    ):
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        matricula_service.transferir_escola(matricula, "Escola Municipal X")

        assert matricula.situacao is SituacaoMatricula.TRANSFERIDA
        assert matricula.escola_destino == "Escola Municipal X"
        # O registro continua no banco para emissao de documentos.
        assert matricula_service.buscar(matricula.id) is not None

    def test_matricula_encerrada_nao_aceita_nova_acao(
        self, app, aluno, turma, ano_letivo
    ):
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        matricula_service.cancelar(matricula, "Desistencia")

        with pytest.raises(ErroRegraNegocio):
            matricula_service.cancelar(matricula, "Outra vez")


# ---------------------------------------------------------------------------
# Alunos
# ---------------------------------------------------------------------------
class TestAluno:
    def test_codigo_gerado_automaticamente(self, app):
        aluno = aluno_service.criar({"nome_completo": "Novo Aluno Teste"})

        assert aluno.codigo
        assert aluno.codigo.startswith(str(date.today().year))

    def test_cpf_duplicado_e_recusado(self, app):
        aluno_service.criar(
            {"nome_completo": "Primeiro Aluno", "cpf": "52998224725"}
        )

        with pytest.raises(ErroConflito):
            aluno_service.criar(
                {"nome_completo": "Segundo Aluno", "cpf": "52998224725"}
            )

    def test_cpf_invalido_e_recusado(self, app):
        with pytest.raises(ErroValidacao):
            aluno_service.criar(
                {"nome_completo": "Aluno Teste", "cpf": "11111111111"}
            )

    def test_aluno_com_matricula_ativa_nao_pode_ser_excluido(
        self, app, aluno, turma, ano_letivo
    ):
        """Excluir aluno matriculado apagaria o vinculo academico do ano."""
        matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)

        with pytest.raises(ErroRegraNegocio) as erro:
            aluno_service.excluir(aluno)
        assert "matricula ativa" in erro.value.mensagem.lower()

    def test_exclusao_e_logica(self, app, aluno):
        """O historico escolar precisa sobreviver a exclusao do cadastro."""
        identificador = aluno.id
        aluno_service.excluir(aluno)

        assert aluno.esta_excluido is True
        # A linha continua no banco.
        assert db.session.get(Aluno, identificador) is not None
        # Mas some das consultas do sistema.
        with pytest.raises(RegistroNaoEncontrado):
            aluno_service.buscar(identificador)

    def test_busca_ignora_acentos(self, app):
        aluno_service.criar({"nome_completo": "Jose da Silva"})

        encontrados = aluno_service.listar(termo="jose").all()
        assert len(encontrados) == 1


# ---------------------------------------------------------------------------
# Turmas e disciplinas
# ---------------------------------------------------------------------------
class TestTurma:
    def test_turma_duplicada_no_mesmo_ano_e_recusada(
        self, app, turma, ano_letivo, serie
    ):
        from app.models.enums import Turno

        with pytest.raises(ErroConflito):
            turma_service.criar_turma(
                {
                    "nome": turma.nome,
                    "ano_letivo_id": ano_letivo.id,
                    "serie_id": serie.id,
                    "turno": Turno.MATUTINO,
                    "capacidade": 30,
                }
            )

    def test_capacidade_menor_que_matriculados_e_recusada(
        self, app, aluno, turma, ano_letivo
    ):
        """Reduzir a capacidade nao pode deixar alunos "fora" da propria turma."""
        matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)

        segundo = Aluno(
            nome_completo="Segundo Aluno",
            codigo="TESTE0002",
            situacao=SituacaoCadastro.ATIVO,
        )
        db.session.add(segundo)
        db.session.commit()
        matricula_service.matricular(segundo.id, turma.id, ano_letivo.id)

        with pytest.raises(ErroRegraNegocio) as erro:
            turma_service.atualizar_turma(turma, {"capacidade": 1})
        assert "matriculado" in erro.value.mensagem.lower()

    def test_turma_com_alunos_nao_pode_ser_excluida(
        self, app, aluno, turma, ano_letivo
    ):
        matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)

        with pytest.raises(ErroRegraNegocio):
            turma_service.excluir_turma(turma)

    def test_disciplina_duplicada_na_turma_e_recusada(
        self, app, turma, disciplina, vinculo
    ):
        with pytest.raises(ErroConflito):
            turma_service.atribuir_disciplina(turma, disciplina.id)

    def test_vinculo_com_aulas_nao_pode_ser_removido(self, app, vinculo):
        """Remover apagaria o diario de classe e as notas da turma."""
        frequencia_service.registrar_aula(
            vinculo, date.today(), conteudo="Aula de teste"
        )

        with pytest.raises(ErroRegraNegocio) as erro:
            turma_service.remover_vinculo(vinculo)
        assert "aula" in erro.value.mensagem.lower()


# ---------------------------------------------------------------------------
# Frequencia
# ---------------------------------------------------------------------------
class TestFrequencia:
    def test_aula_com_data_futura_e_recusada(self, app, vinculo):
        with pytest.raises(ErroRegraNegocio) as erro:
            frequencia_service.registrar_aula(
                vinculo, date.today() + timedelta(days=1), conteudo="Futura"
            )
        assert "futura" in erro.value.mensagem.lower()

    def test_aula_fora_do_ano_letivo_e_recusada(self, app, vinculo, ano_letivo):
        with pytest.raises(ErroRegraNegocio) as erro:
            frequencia_service.registrar_aula(
                vinculo,
                ano_letivo.data_inicio - timedelta(days=10),
                conteudo="Antes do ano",
            )
        assert "fora do ano letivo" in erro.value.mensagem.lower()

    def test_aulas_geminadas_recebem_ordem_distinta(self, app, vinculo):
        primeira = frequencia_service.registrar_aula(
            vinculo, date.today(), conteudo="Primeira"
        )
        segunda = frequencia_service.registrar_aula(
            vinculo, date.today(), conteudo="Segunda"
        )

        assert primeira.ordem_no_dia == 1
        assert segunda.ordem_no_dia == 2

    def test_chamada_marca_a_aula_como_realizada(
        self, app, vinculo, aluno, turma, ano_letivo
    ):
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        aula = frequencia_service.registrar_aula(
            vinculo, date.today(), conteudo="Aula"
        )
        assert aula.chamada_realizada is False

        total = frequencia_service.salvar_chamada(
            aula, {matricula.id: SituacaoPresenca.FALTA.value}
        )

        assert total == 1
        assert aula.chamada_realizada is True

    def test_chamada_ignora_aluno_de_outra_turma(
        self, app, vinculo, aluno, turma, ano_letivo
    ):
        """Protege contra POST manipulado com id de outra turma."""
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        aula = frequencia_service.registrar_aula(
            vinculo, date.today(), conteudo="Aula"
        )

        total = frequencia_service.salvar_chamada(
            aula,
            {
                matricula.id: SituacaoPresenca.PRESENTE.value,
                99999: SituacaoPresenca.FALTA.value,  # id inexistente
            },
        )

        assert total == 1

    def test_refazer_chamada_nao_duplica_registros(
        self, app, vinculo, aluno, turma, ano_letivo
    ):
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        aula = frequencia_service.registrar_aula(
            vinculo, date.today(), conteudo="Aula"
        )

        frequencia_service.salvar_chamada(
            aula, {matricula.id: SituacaoPresenca.FALTA.value}
        )
        frequencia_service.salvar_chamada(
            aula, {matricula.id: SituacaoPresenca.PRESENTE.value}
        )

        registros = (
            db.session.query(Frequencia)
            .filter(Frequencia.aula_id == aula.id)
            .all()
        )
        assert len(registros) == 1
        assert registros[0].situacao is SituacaoPresenca.PRESENTE

    def test_percentual_de_frequencia(self, app, vinculo, aluno, turma, ano_letivo):
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)

        # 4 aulas, 1 falta -> 75%
        for indice in range(4):
            aula = frequencia_service.registrar_aula(
                vinculo, date.today() - timedelta(days=indice), conteudo=f"Aula {indice}"
            )
            situacao = (
                SituacaoPresenca.FALTA if indice == 0 else SituacaoPresenca.PRESENTE
            )
            frequencia_service.salvar_chamada(aula, {matricula.id: situacao.value})

        apuracao = frequencia_service.apurar_frequencia(matricula.id, vinculo.id)

        assert apuracao["total_aulas"] == 4
        assert apuracao["total_faltas"] == 1
        assert apuracao["percentual"] == 75.0

    def test_falta_justificada_conta_como_presenca(
        self, app, vinculo, aluno, turma, ano_letivo
    ):
        """Regra legal: a justificativa abona a falta para fins de frequencia."""
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        aula = frequencia_service.registrar_aula(
            vinculo, date.today(), conteudo="Aula"
        )

        frequencia_service.salvar_chamada(
            aula,
            {matricula.id: SituacaoPresenca.FALTA_JUSTIFICADA.value},
            {matricula.id: "Atestado medico"},
        )

        apuracao = frequencia_service.apurar_frequencia(matricula.id, vinculo.id)
        assert apuracao["total_faltas"] == 0
        assert apuracao["percentual"] == 100.0


# ---------------------------------------------------------------------------
# Notas e apuracao de resultado
# ---------------------------------------------------------------------------
class TestNotas:
    @pytest.fixture
    def cenario(self, app, vinculo, aluno, turma, ano_letivo):
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        periodo = ano_letivo.periodos[0]
        return {"matricula": matricula, "periodo": periodo, "vinculo": vinculo}

    def test_avaliacao_cria_linhas_de_nota_para_a_turma(self, app, cenario):
        """Linha vazia distingue 'nao lancado' de 'tirou zero'."""
        avaliacao = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Prova 1", TipoAvaliacao.PROVA
        )

        notas = db.session.query(Nota).filter(Nota.avaliacao_id == avaliacao.id).all()
        assert len(notas) == 1
        assert notas[0].valor is None
        assert notas[0].foi_lancada is False

    def test_periodo_encerrado_recusa_nova_avaliacao(self, app, cenario):
        cenario["periodo"].encerrado = True
        db.session.commit()

        with pytest.raises(ErroRegraNegocio) as erro:
            nota_service.criar_avaliacao(
                cenario["vinculo"], cenario["periodo"].id, "Prova", TipoAvaliacao.PROVA
            )
        assert "encerrado" in erro.value.mensagem.lower()

    def test_peso_zero_e_recusado(self, app, cenario):
        with pytest.raises(ErroValidacao):
            nota_service.criar_avaliacao(
                cenario["vinculo"], cenario["periodo"].id, "Prova",
                TipoAvaliacao.PROVA, peso=0,
            )

    def test_nota_acima_do_maximo_e_recusada(self, app, cenario):
        avaliacao = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Prova",
            TipoAvaliacao.PROVA, valor_maximo=10,
        )

        with pytest.raises(ErroValidacao) as erro:
            nota_service.salvar_notas(avaliacao, {cenario["matricula"].id: "11"})
        assert "intervalo" in erro.value.mensagem.lower()

    def test_nota_negativa_e_recusada(self, app, cenario):
        avaliacao = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Prova", TipoAvaliacao.PROVA
        )

        with pytest.raises(ErroValidacao):
            nota_service.salvar_notas(avaliacao, {cenario["matricula"].id: "-1"})

    def test_nota_aceita_virgula_decimal(self, app, cenario):
        """A secretaria digita '8,5', nao '8.5'."""
        avaliacao = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Prova", TipoAvaliacao.PROVA
        )

        nota_service.salvar_notas(avaliacao, {cenario["matricula"].id: "8,5"})

        nota = (
            db.session.query(Nota)
            .filter(Nota.avaliacao_id == avaliacao.id)
            .first()
        )
        assert nota.valor == Decimal("8.50")

    def test_media_ponderada(self, app, cenario):
        """Prova peso 3 (nota 6) + trabalho peso 1 (nota 10) = 7,0."""
        prova = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Prova",
            TipoAvaliacao.PROVA, peso=3,
        )
        trabalho = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Trabalho",
            TipoAvaliacao.TRABALHO, peso=1,
        )

        nota_service.salvar_notas(prova, {cenario["matricula"].id: "6"})
        nota_service.salvar_notas(trabalho, {cenario["matricula"].id: "10"})

        media = nota_service.calcular_media_periodo(
            cenario["matricula"].id, cenario["vinculo"].id, cenario["periodo"].id
        )
        assert media == Decimal("7.00")

    def test_media_nula_sem_lancamento(self, app, cenario):
        """Sem nota lancada a media e None, nunca zero."""
        nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Prova", TipoAvaliacao.PROVA
        )

        media = nota_service.calcular_media_periodo(
            cenario["matricula"].id, cenario["vinculo"].id, cenario["periodo"].id
        )
        assert media is None

    def test_ausencia_conta_como_zero(self, app, cenario):
        avaliacao = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Prova", TipoAvaliacao.PROVA
        )

        nota_service.salvar_notas(
            avaliacao, {}, ausencias={cenario["matricula"].id}
        )

        media = nota_service.calcular_media_periodo(
            cenario["matricula"].id, cenario["vinculo"].id, cenario["periodo"].id
        )
        assert media == Decimal("0.00")

    def test_escala_diferente_e_normalizada(self, app, cenario):
        """Um trabalho de 20 pontos precisa entrar na media em escala 0-10."""
        avaliacao = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Trabalho",
            TipoAvaliacao.TRABALHO, valor_maximo=20,
        )

        nota_service.salvar_notas(avaliacao, {cenario["matricula"].id: "16"})

        media = nota_service.calcular_media_periodo(
            cenario["matricula"].id, cenario["vinculo"].id, cenario["periodo"].id
        )
        assert media == Decimal("8.00")

    def test_recuperacao_substitui_a_media_quando_maior(self, app, cenario):
        prova = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Prova", TipoAvaliacao.PROVA
        )
        nota_service.salvar_notas(prova, {cenario["matricula"].id: "4"})

        recuperacao = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Recuperacao",
            TipoAvaliacao.RECUPERACAO,
        )
        nota_service.salvar_notas(recuperacao, {cenario["matricula"].id: "7"})

        media = nota_service.calcular_media_periodo(
            cenario["matricula"].id, cenario["vinculo"].id, cenario["periodo"].id
        )
        assert media == Decimal("7.00")

    def test_recuperacao_nao_reduz_a_media(self, app, cenario):
        prova = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Prova", TipoAvaliacao.PROVA
        )
        nota_service.salvar_notas(prova, {cenario["matricula"].id: "9"})

        recuperacao = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Recuperacao",
            TipoAvaliacao.RECUPERACAO,
        )
        nota_service.salvar_notas(recuperacao, {cenario["matricula"].id: "5"})

        media = nota_service.calcular_media_periodo(
            cenario["matricula"].id, cenario["vinculo"].id, cenario["periodo"].id
        )
        assert media == Decimal("9.00")

    def test_avaliacao_com_notas_nao_pode_ser_excluida(self, app, cenario):
        avaliacao = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Prova", TipoAvaliacao.PROVA
        )
        nota_service.salvar_notas(avaliacao, {cenario["matricula"].id: "8"})

        with pytest.raises(ErroRegraNegocio):
            nota_service.excluir_avaliacao(avaliacao)


class TestApuracaoDeResultado:
    @pytest.fixture
    def cenario(self, app, vinculo, aluno, turma, ano_letivo):
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)
        return {
            "matricula": matricula,
            "periodo": ano_letivo.periodos[0],
            "vinculo": vinculo,
            "ano": ano_letivo,
        }

    def _lancar(self, cenario, valor: str) -> None:
        avaliacao = nota_service.criar_avaliacao(
            cenario["vinculo"], cenario["periodo"].id, "Prova", TipoAvaliacao.PROVA
        )
        nota_service.salvar_notas(avaliacao, {cenario["matricula"].id: valor})

    def test_media_acima_do_minimo_aprova(self, app, cenario):
        self._lancar(cenario, "8")

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )
        assert resultado.resultado is ResultadoFinal.APROVADO

    def test_media_intermediaria_vai_para_recuperacao(self, app, cenario):
        self._lancar(cenario, "5")

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )
        assert resultado.resultado is ResultadoFinal.RECUPERACAO

    def test_media_baixa_reprova(self, app, cenario):
        self._lancar(cenario, "2")

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )
        assert resultado.resultado is ResultadoFinal.REPROVADO

    def test_sem_nota_o_aluno_esta_cursando(self, app, cenario):
        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )
        assert resultado.resultado is ResultadoFinal.CURSANDO

    def test_frequencia_baixa_reprova_mesmo_com_media_alta(self, app, cenario):
        """A LDB reprova por falta independentemente do desempenho."""
        self._lancar(cenario, "10")

        # 25 aulas, 20 faltas -> 20% de frequencia.
        for indice in range(25):
            aula = frequencia_service.registrar_aula(
                cenario["vinculo"],
                date.today() - timedelta(days=indice),
                conteudo=f"Aula {indice}",
            )
            situacao = (
                SituacaoPresenca.FALTA if indice < 20 else SituacaoPresenca.PRESENTE
            )
            frequencia_service.salvar_chamada(
                aula, {cenario["matricula"].id: situacao.value}
            )

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )
        assert resultado.resultado is ResultadoFinal.REPROVADO_FALTA

    def test_poucas_aulas_nao_reprovam_por_falta(self, app, cenario):
        """No inicio do ano, duas ausencias nao podem reprovar ninguem."""
        self._lancar(cenario, "8")

        for indice in range(3):
            aula = frequencia_service.registrar_aula(
                cenario["vinculo"],
                date.today() - timedelta(days=indice),
                conteudo=f"Aula {indice}",
            )
            frequencia_service.salvar_chamada(
                aula, {cenario["matricula"].id: SituacaoPresenca.FALTA.value}
            )

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )
        assert resultado.resultado is ResultadoFinal.APROVADO

    def test_consolidacao_atualiza_a_matricula(self, app, cenario):
        self._lancar(cenario, "7")

        nota_service.consolidar_matricula(cenario["matricula"])

        assert cenario["matricula"].media_geral == Decimal("7.00")

    def test_boletim_lista_todas_as_disciplinas(self, app, cenario):
        self._lancar(cenario, "7")

        boletim = nota_service.montar_boletim(cenario["matricula"])

        assert boletim["aluno"].id == cenario["matricula"].aluno_id
        assert len(boletim["linhas"]) == 1
        assert boletim["linhas"][0]["disciplina"].nome == "Matematica"
