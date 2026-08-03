"""Testes da Fase 2 da auditoria: bugs de calculo.

Nao sao exploraveis, mas corrompem historico escolar — o que e mais dificil
de reverter do que uma falha de acesso. Todos falhavam antes da correcao.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.enums import (
    ResultadoFinal,
    SituacaoAnoLetivo,
    SituacaoMatricula,
    SituacaoPresenca,
    TipoAvaliacao,
)
from app.models.estrutura import PeriodoLetivo
from app.services import (
    frequencia_service,
    matricula_service,
    nota_service,
    pdf_service,
)


# ===========================================================================
# Cenario: ano letivo com quatro bimestres
# ===========================================================================
@pytest.fixture
def ano_com_quatro_periodos(app, ano_letivo):
    """Completa o ano da fixture padrao ate quatro bimestres."""
    inicio = ano_letivo.data_inicio

    # A fixture base ja cria o 1o bimestre cobrindo o ano inteiro; ajusta.
    primeiro = ano_letivo.periodos[0]
    primeiro.data_fim = inicio + timedelta(days=80)

    for ordem in range(2, 5):
        db.session.add(
            PeriodoLetivo(
                ano_letivo_id=ano_letivo.id,
                nome=f"{ordem}o Bimestre",
                ordem=ordem,
                data_inicio=inicio + timedelta(days=80 * (ordem - 1) + 1),
                data_fim=inicio + timedelta(days=80 * ordem),
            )
        )
    db.session.commit()
    db.session.refresh(ano_letivo)
    return ano_letivo


@pytest.fixture
def cenario(app, vinculo, aluno, turma, ano_com_quatro_periodos):
    matricula = matricula_service.matricular(
        aluno.id, turma.id, ano_com_quatro_periodos.id
    )
    return {
        "matricula": matricula,
        "vinculo": vinculo,
        "ano": ano_com_quatro_periodos,
        "periodos": sorted(
            ano_com_quatro_periodos.periodos, key=lambda p: p.ordem
        ),
    }


def _lancar(cenario, periodo, valor: str, tipo=TipoAvaliacao.PROVA,
            nome: str | None = None, valor_maximo=10):
    """Cria uma avaliacao no periodo e lanca a nota do aluno."""
    avaliacao = nota_service.criar_avaliacao(
        cenario["vinculo"],
        periodo.id,
        nome or f"{tipo.rotulo} {periodo.ordem}",
        tipo,
        valor_maximo=valor_maximo,
    )
    nota_service.salvar_notas(avaliacao, {cenario["matricula"].id: valor})
    return avaliacao


# ===========================================================================
# 2.1 — Recuperacao de periodo contada duas vezes
# ===========================================================================
class TestRecuperacaoDuplicada:
    def test_recuperacao_de_periodo_nao_vira_recuperacao_final(self, app, cenario):
        """4,0 / rec 7,0 / 4,0 / 4,0 deve resultar em 4,75 — nao em 7,0.

        A recuperacao do 2o bimestre ja substituiu a media daquele periodo.
        Conta-la de novo como recuperacao **final** infla a nota do ano.
        """
        periodos = cenario["periodos"]

        _lancar(cenario, periodos[0], "4")
        _lancar(cenario, periodos[1], "4")
        _lancar(
            cenario, periodos[1], "7",
            tipo=TipoAvaliacao.RECUPERACAO, nome="Recuperacao do 2o bimestre",
        )
        _lancar(cenario, periodos[2], "4")
        _lancar(cenario, periodos[3], "4")

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )

        # A recuperacao do periodo elevou apenas o 2o bimestre.
        assert resultado.media_periodo_2 == Decimal("7.00")
        assert resultado.media_anual == Decimal("4.75")
        # E nao pode reaparecer como recuperacao final.
        assert resultado.nota_recuperacao is None
        assert resultado.media_final == Decimal("4.75")

    def test_recuperacao_final_substitui_a_media_anual(self, app, cenario):
        """A recuperacao final existe e continua funcionando."""
        for periodo in cenario["periodos"]:
            _lancar(cenario, periodo, "4")

        _lancar(
            cenario, cenario["periodos"][3], "6",
            tipo=TipoAvaliacao.RECUPERACAO_FINAL, nome="Recuperacao final",
        )

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )

        assert resultado.media_anual == Decimal("4.00")
        assert resultado.nota_recuperacao == Decimal("6.00")
        assert resultado.media_final == Decimal("6.00")

    def test_recuperacao_final_menor_nao_reduz_a_media(self, app, cenario):
        for periodo in cenario["periodos"]:
            _lancar(cenario, periodo, "8")

        _lancar(
            cenario, cenario["periodos"][3], "5",
            tipo=TipoAvaliacao.RECUPERACAO_FINAL, nome="Recuperacao final",
        )

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )
        assert resultado.media_final == Decimal("8.00")

    def test_recuperacao_de_um_periodo_nao_afeta_outro(self, app, cenario):
        periodos = cenario["periodos"]

        _lancar(cenario, periodos[0], "3")
        _lancar(cenario, periodos[1], "3")
        _lancar(
            cenario, periodos[0], "9",
            tipo=TipoAvaliacao.RECUPERACAO, nome="Recuperacao do 1o",
        )

        media_1 = nota_service.calcular_media_periodo(
            cenario["matricula"].id, cenario["vinculo"].id, periodos[0].id
        )
        media_2 = nota_service.calcular_media_periodo(
            cenario["matricula"].id, cenario["vinculo"].id, periodos[1].id
        )

        assert media_1 == Decimal("9.00")
        assert media_2 == Decimal("3.00")


# ===========================================================================
# 2.2 — Recuperacao nao normalizada de escala
# ===========================================================================
class TestNormalizacaoDaRecuperacao:
    def test_recuperacao_final_em_outra_escala_e_normalizada(self, app, cenario):
        """Recuperacao valendo 100 nao pode substituir tudo automaticamente."""
        for periodo in cenario["periodos"]:
            _lancar(cenario, periodo, "8")

        # 50 em 100 equivale a 5,0 — abaixo da media anual de 8,0.
        _lancar(
            cenario, cenario["periodos"][3], "50",
            tipo=TipoAvaliacao.RECUPERACAO_FINAL,
            nome="Recuperacao final", valor_maximo=100,
        )

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )

        assert resultado.nota_recuperacao == Decimal("5.00")
        assert resultado.media_final == Decimal("8.00")

    def test_recuperacao_de_periodo_em_outra_escala_e_normalizada(
        self, app, cenario
    ):
        periodo = cenario["periodos"][0]

        _lancar(cenario, periodo, "4")
        # 90 em 100 equivale a 9,0.
        _lancar(
            cenario, periodo, "90",
            tipo=TipoAvaliacao.RECUPERACAO, nome="Rec", valor_maximo=100,
        )

        media = nota_service.calcular_media_periodo(
            cenario["matricula"].id, cenario["vinculo"].id, periodo.id
        )
        assert media == Decimal("9.00")


# ===========================================================================
# 2.3 — Aluno "aprovado" em marco
# ===========================================================================
class TestResultadoParcial:
    def test_um_periodo_lancado_mantem_cursando(self, app, cenario):
        """Com 1 de 4 bimestres lancados, o boletim nao pode dizer APROVADO."""
        _lancar(cenario, cenario["periodos"][0], "7")

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )

        assert resultado.media_periodo_1 == Decimal("7.00")
        assert resultado.resultado is ResultadoFinal.CURSANDO

    def test_todos_os_periodos_lancados_apura_o_resultado(self, app, cenario):
        for periodo in cenario["periodos"]:
            _lancar(cenario, periodo, "7")

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )
        assert resultado.resultado is ResultadoFinal.APROVADO

    def test_ano_encerrado_apura_mesmo_com_periodo_faltando(self, app, cenario):
        """Ano fechado com bimestre sem nota ainda precisa dar um resultado."""
        _lancar(cenario, cenario["periodos"][0], "3")
        _lancar(cenario, cenario["periodos"][1], "3")

        cenario["ano"].situacao = SituacaoAnoLetivo.ENCERRADO
        db.session.commit()

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )
        assert resultado.resultado is ResultadoFinal.REPROVADO

    def test_reprovacao_por_falta_vale_mesmo_cursando(self, app, cenario):
        """Frequencia e apurada continuamente — nao espera o fim do ano."""
        _lancar(cenario, cenario["periodos"][0], "10")

        for indice in range(30):
            aula = frequencia_service.registrar_aula(
                cenario["vinculo"],
                date.today() - timedelta(days=indice),
                conteudo=f"Aula {indice}",
            )
            situacao = (
                SituacaoPresenca.FALTA if indice < 25 else SituacaoPresenca.PRESENTE
            )
            frequencia_service.salvar_chamada(
                aula, {cenario["matricula"].id: situacao.value}
            )

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )
        assert resultado.resultado is ResultadoFinal.REPROVADO_FALTA


# ===========================================================================
# 2.4 — Numeros magicos contrariando o proprio design
# ===========================================================================
class TestParametrosNoAnoLetivo:
    def test_limiar_de_apuracao_por_falta_vem_do_ano(self, app, cenario):
        """O `>= 20` estava fixo no codigo, contrariando o docstring."""
        cenario["ano"].minimo_aulas_para_apurar_falta = 4
        db.session.commit()

        for periodo in cenario["periodos"]:
            _lancar(cenario, periodo, "10")

        for indice in range(5):
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
        assert resultado.resultado is ResultadoFinal.REPROVADO_FALTA

    def test_ano_com_cinco_periodos_nao_perde_o_ultimo(self, app, cenario):
        """`periodos[:4]` descartava o 5o periodo em silencio."""
        ano = cenario["ano"]
        db.session.add(
            PeriodoLetivo(
                ano_letivo_id=ano.id,
                nome="5o Periodo",
                ordem=5,
                data_inicio=ano.data_fim - timedelta(days=20),
                data_fim=ano.data_fim,
            )
        )
        db.session.commit()
        db.session.refresh(ano)

        periodos = sorted(ano.periodos, key=lambda p: p.ordem)
        for periodo in periodos[:4]:
            _lancar(cenario, periodo, "10")
        _lancar(cenario, periodos[4], "0")

        resultado = nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )

        # (10+10+10+10+0)/5 = 8,0. Se o 5o fosse descartado, daria 10,0.
        assert resultado.media_anual == Decimal("8.00")
        assert len(resultado.medias_por_periodo()) == 5

    def test_ano_trimestral_funciona(self, app, vinculo, aluno, turma, ano_letivo):
        """Tres periodos: nao pode sobrar coluna vazia nem faltar media."""
        matricula = matricula_service.matricular(aluno.id, turma.id, ano_letivo.id)

        inicio = ano_letivo.data_inicio
        ano_letivo.periodos[0].data_fim = inicio + timedelta(days=100)
        for ordem in (2, 3):
            db.session.add(
                PeriodoLetivo(
                    ano_letivo_id=ano_letivo.id,
                    nome=f"{ordem}o Trimestre",
                    ordem=ordem,
                    data_inicio=inicio + timedelta(days=100 * (ordem - 1) + 1),
                    data_fim=inicio + timedelta(days=100 * ordem),
                )
            )
        db.session.commit()
        db.session.refresh(ano_letivo)

        contexto = {"matricula": matricula, "vinculo": vinculo, "ano": ano_letivo}
        for periodo in sorted(ano_letivo.periodos, key=lambda p: p.ordem):
            _lancar(contexto, periodo, "6")

        resultado = nota_service.calcular_resultado_disciplina(matricula, vinculo)

        assert len(resultado.medias_por_periodo()) == 3
        assert resultado.media_anual == Decimal("6.00")
        assert resultado.resultado is ResultadoFinal.APROVADO

    def test_boletim_exibe_todos_os_periodos(self, app, cenario):
        """Corrigir so o calculo nao basta: o 5o periodo tem de aparecer.

        O boletim (tela e PDF) truncava em quatro colunas. O aluno via a
        media anual mudar sem conseguir descobrir de onde ela veio.
        """
        ano = cenario["ano"]
        db.session.add(
            PeriodoLetivo(
                ano_letivo_id=ano.id,
                nome="5o Periodo",
                ordem=5,
                data_inicio=ano.data_fim - timedelta(days=20),
                data_fim=ano.data_fim,
            )
        )
        db.session.commit()
        db.session.refresh(ano)

        for periodo in sorted(ano.periodos, key=lambda p: p.ordem):
            _lancar(cenario, periodo, "7")

        nota_service.calcular_resultado_disciplina(
            cenario["matricula"], cenario["vinculo"]
        )

        dados = nota_service.montar_boletim(cenario["matricula"])

        assert len(dados["periodos"]) == 5
        assert len(dados["linhas"][0]["medias"]) == 5

        # O PDF precisa montar a tabela sem estourar a largura da pagina.
        assert pdf_service.gerar_boletim(dados).getbuffer().nbytes > 0


# ===========================================================================
# 2.5 — matriculas_da_turma() so retornava ATIVA
# ===========================================================================
class TestMatriculasInativas:
    def test_por_padrao_apenas_ativas(self, app, cenario, turma):
        assert len(nota_service.matriculas_da_turma(turma.id)) == 1

        matricula_service.transferir_escola(
            cenario["matricula"], "Outra Escola"
        )
        assert nota_service.matriculas_da_turma(turma.id) == []

    def test_incluir_inativas_permite_boletim_de_transferido(
        self, app, cenario, turma
    ):
        """Aluno transferido em outubro precisa de boletim parcial."""
        matricula_service.transferir_escola(cenario["matricula"], "Outra Escola")

        matriculas = nota_service.matriculas_da_turma(
            turma.id, incluir_inativas=True
        )

        assert len(matriculas) == 1
        assert matriculas[0].situacao is SituacaoMatricula.TRANSFERIDA

    def test_consolidacao_de_turma_alcanca_transferidos(self, app, cenario, turma):
        """Sem isso, nao ha como corrigir a nota de quem saiu no meio do ano."""
        _lancar(cenario, cenario["periodos"][0], "7")
        matricula_service.transferir_escola(cenario["matricula"], "Outra Escola")

        total = nota_service.consolidar_turma(turma, incluir_inativas=True)

        assert total == 1
