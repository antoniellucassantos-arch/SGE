"""Cria as tres contas usadas para percorrer as interfaces do sistema.

    python scripts/criar_contas_de_teste.py

Uma conta por perfil, para ver o sistema com os olhos de cada um:

===================  ===========  ============================================
adm@gmail.com        Administra.  Enxerga tudo: cadastros, backup, auditoria
prof@gmail.com       Professor    Diario, chamada e notas das proprias turmas
aluno@gmail.com      Aluno        Boletim, frequencia e horario proprios
===================  ===========  ============================================

Senha unica: ``1234``.

Por que nao basta criar tres linhas em ``usuarios``
---------------------------------------------------
Professor e aluno so enxergam alguma coisa se estiverem **ligados ao
dominio**. A camada 2 da autorizacao pergunta "de quais turmas voce e
titular?" e "em qual turma voce esta matriculado?" — sem o vinculo e sem a
matricula, as duas contas entram e encontram telas vazias, que e o oposto do
que se quer para testar. Entao o script tambem:

* cria um ``Professor`` e transfere para ele algumas disciplinas ja
  existentes, com diario, aulas e notas que o seed de demonstracao gerou;
* liga a conta de aluno a um aluno ja matriculado, com boletim para ver.

E reexecutavel: se as contas existirem, atualiza a senha e refaz os vinculos
em vez de duplicar.

**Somente para desenvolvimento.** Recusa rodar em producao.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.enums import (  # noqa: E402
    PapelUsuario,
    SituacaoCadastro,
    SituacaoMatricula,
)
from app.models.estrutura import Turma, TurmaDisciplina  # noqa: E402
from app.models.matricula import Matricula  # noqa: E402
from app.models.pessoas import Aluno, Professor  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402

#: Senha unica das tres contas.
#:
#: ``1234`` nao passaria pela politica de senha do sistema — curta demais,
#: sem maiuscula, sequencia obvia. Aqui ela e gravada direto pelo model, que
#: nao aplica a politica; quem aplica e o `usuario_service` e o formulario de
#: troca de senha, e ambos continuam exigindo o de sempre.
#:
#: A escolha e deliberada e vale **so em desenvolvimento**. Duas travas
#: seguram isso: este script recusa rodar fora do ambiente de
#: desenvolvimento, e as contas nao existem em producao.
#:
#: O ponto de atencao real: `run.py` escuta em 0.0.0.0 para dar para abrir do
#: celular. Numa rede compartilhada — a da escola, a de um cafe — qualquer um
#: alcanca a tela de login, e `1234` numa conta de administrador se adivinha
#: de primeira. Para demonstrar fora de casa, troque antes.
SENHA = "1234"

CONTAS = {
    "administrador": ("adm@gmail.com", "Administrador de Teste"),
    "professor": ("prof@gmail.com", "Professor de Teste"),
    "aluno": ("aluno@gmail.com", "Aluno de Teste"),
}

#: Quantas disciplinas o professor de teste assume. Duas turmas diferentes
#: para dar o que comparar — e para o escopo negar visivelmente as outras.
DISCIPLINAS_DO_PROFESSOR = 3


def _conta(email: str, nome: str, papel: PapelUsuario) -> Usuario:
    """Cria ou atualiza a conta, sempre com senha conhecida e sem pendencia.

    ``exigir_troca=False`` de proposito: numa conta de teste, a tela de troca
    obrigatoria so atrapalha quem quer olhar o sistema.
    """
    usuario = db.session.query(Usuario).filter(Usuario.email == email).first()
    if usuario is None:
        usuario = Usuario(email=email)
        db.session.add(usuario)

    usuario.nome_completo = nome
    usuario.papel = papel
    usuario.ativo = True
    usuario.definir_senha(SENHA, exigir_troca=False)
    usuario.desbloquear()

    db.session.flush()
    return usuario


def _ligar_professor(usuario: Usuario) -> list[TurmaDisciplina]:
    """Cria o cadastro de professor e transfere disciplinas para ele."""
    professor = (
        db.session.query(Professor)
        .filter(Professor.usuario_id == usuario.id)
        .first()
    )
    if professor is None:
        professor = Professor(
            nome_completo=usuario.nome_completo,
            registro_funcional="PROF-TESTE",
            situacao=SituacaoCadastro.ATIVO,
            carga_horaria_semanal=20,
            usuario_id=usuario.id,
        )
        db.session.add(professor)
        db.session.flush()

    ja_atribuidas = (
        db.session.query(TurmaDisciplina)
        .filter(TurmaDisciplina.professor_id == professor.id)
        .all()
    )
    if ja_atribuidas:
        return ja_atribuidas

    # Espalha entre turmas diferentes: uma disciplina de cada, ate o limite.
    # Assim da para ver o escopo funcionando — as turmas que sobram devem
    # responder 403 para esta conta.
    escolhidas: list[TurmaDisciplina] = []
    turmas = (
        db.session.query(Turma)
        .filter(Turma.ativa.is_(True), Turma.excluido_em.is_(None))
        .order_by(Turma.id)
        .all()
    )
    for turma in turmas:
        if len(escolhidas) >= DISCIPLINAS_DO_PROFESSOR:
            break
        vinculo = (
            db.session.query(TurmaDisciplina)
            .filter(
                TurmaDisciplina.turma_id == turma.id,
                TurmaDisciplina.ativa.is_(True),
            )
            .order_by(TurmaDisciplina.id)
            .first()
        )
        if vinculo is not None:
            vinculo.professor_id = professor.id
            escolhidas.append(vinculo)

    return escolhidas


def _ligar_aluno(usuario: Usuario) -> tuple[Aluno, Matricula | None]:
    """Liga a conta a um aluno ja matriculado, com historico para ver."""
    aluno = db.session.query(Aluno).filter(Aluno.usuario_id == usuario.id).first()
    if aluno is not None:
        return aluno, aluno.matricula_atual

    # Prefere um aluno com matricula ativa: sem ela, o painel do aluno abre
    # vazio e nao ha boletim nem frequencia para conferir.
    matricula = (
        db.session.query(Matricula)
        .join(Aluno, Matricula.aluno_id == Aluno.id)
        .filter(
            Matricula.situacao == SituacaoMatricula.ATIVA,
            Matricula.excluido_em.is_(None),
            Aluno.usuario_id.is_(None),
            Aluno.excluido_em.is_(None),
        )
        .order_by(Matricula.id)
        .first()
    )
    if matricula is None:
        return None, None

    aluno = matricula.aluno
    aluno.usuario_id = usuario.id
    return aluno, matricula


def main() -> int:
    app = create_app("development")

    if not app.debug and not app.testing:
        print("Recusado: este script e apenas para desenvolvimento.")
        return 1

    with app.app_context():
        admin = _conta(*CONTAS["administrador"], PapelUsuario.ADMINISTRADOR)

        professor_conta = _conta(*CONTAS["professor"], PapelUsuario.PROFESSOR)
        vinculos = _ligar_professor(professor_conta)

        aluno_conta = _conta(*CONTAS["aluno"], PapelUsuario.ALUNO)
        aluno, matricula = _ligar_aluno(aluno_conta)

        db.session.commit()

        print("Contas de teste prontas. Senha unica:", SENHA)
        print()
        print(f"  {admin.email:20} administrador")

        print(f"  {professor_conta.email:20} professor")
        for vinculo in vinculos:
            turma = vinculo.turma
            disciplina = vinculo.disciplina
            print(
                f"      leciona {disciplina.nome} em "
                f"{turma.nome_completo if turma else '?'}"
            )

        print(f"  {aluno_conta.email:20} aluno")
        if aluno is None:
            print("      SEM aluno disponivel — rode flask popular-demonstracao")
        else:
            turma = matricula.turma if matricula else None
            print(
                f"      e {aluno.nome_exibicao}, matriculado em "
                f"{turma.nome_completo if turma else 'nenhuma turma'}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
