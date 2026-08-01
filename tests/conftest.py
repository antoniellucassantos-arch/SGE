"""Fixtures compartilhadas pela suite de testes.

Estrategia
----------
Cada teste roda contra um banco SQLite **em memoria**, criado e destruido no
escopo da funcao. Isso garante isolamento total: nenhum teste enxerga dados
deixados por outro, e a suite roda em segundos sem tocar em disco.

O hash de senha usa PBKDF2 com poucas iteracoes nos testes (via
``monkeypatch`` em ``criar_usuario``). Argon2 e proposital e caro — usa-lo em
dezenas de fixtures multiplicaria o tempo da suite sem aumentar a cobertura.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from app import create_app
from app.extensions import db as _db
from app.models.enums import (
    NivelEnsino,
    PapelUsuario,
    SituacaoAnoLetivo,
    SituacaoCadastro,
    SituacaoMatricula,
    Turno,
)
from app.models.estrutura import (
    AnoLetivo,
    Disciplina,
    PeriodoLetivo,
    Serie,
    Turma,
    TurmaDisciplina,
)
from app.models.horario import TempoAula
from app.models.matricula import Matricula
from app.models.pessoas import Aluno, Professor, Responsavel
from app.models.sistema import ConfiguracaoEscola
from app.models.usuario import Usuario
from app.utils.seguranca import gerar_hash_werkzeug

SENHA_PADRAO = "Teste@2026"


# ---------------------------------------------------------------------------
# Aplicacao e banco
# ---------------------------------------------------------------------------
@pytest.fixture
def app():
    """Instancia da aplicacao configurada para testes."""
    aplicacao = create_app("testing")

    with aplicacao.app_context():
        _db.create_all()
        yield aplicacao
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    """Sessao do banco ja dentro do contexto da aplicacao."""
    return _db


@pytest.fixture
def cliente(app):
    """Cliente HTTP sem autenticacao."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Fabricas de dados
# ---------------------------------------------------------------------------
def criar_usuario(
    email: str = "usuario@escola.com.br",
    papel: PapelUsuario = PapelUsuario.ADMINISTRADOR,
    nome: str = "Usuario de Teste",
    senha: str = SENHA_PADRAO,
    ativo: bool = True,
    deve_trocar_senha: bool = False,
) -> Usuario:
    """Cria um usuario com hash rapido, adequado a suite de testes."""
    usuario = Usuario(
        nome_completo=nome,
        email=email,
        papel=papel,
        ativo=ativo,
        deve_trocar_senha=deve_trocar_senha,
    )
    # Hash barato: o custo do Argon2 nao agrega nada aos testes.
    usuario.senha_hash = gerar_hash_werkzeug(senha)
    _db.session.add(usuario)
    _db.session.commit()
    return usuario


@pytest.fixture
def admin(app) -> Usuario:
    return criar_usuario("admin@escola.com.br", PapelUsuario.ADMINISTRADOR, "Admin Teste")


@pytest.fixture
def secretaria(app) -> Usuario:
    return criar_usuario(
        "secretaria@escola.com.br", PapelUsuario.SECRETARIA, "Secretaria Teste"
    )


@pytest.fixture
def ano_letivo(app) -> AnoLetivo:
    """Ano letivo corrente com um bimestre aberto."""
    ano = AnoLetivo(
        ano=date.today().year,
        descricao="Ano de teste",
        data_inicio=date(date.today().year, 1, 1),
        data_fim=date(date.today().year, 12, 31),
        situacao=SituacaoAnoLetivo.EM_ANDAMENTO,
        corrente=True,
        media_aprovacao=6,
        media_recuperacao=4,
        frequencia_minima=75,
    )
    _db.session.add(ano)
    _db.session.flush()

    _db.session.add(
        PeriodoLetivo(
            ano_letivo_id=ano.id,
            nome="1o Bimestre",
            ordem=1,
            data_inicio=ano.data_inicio,
            data_fim=ano.data_fim,
        )
    )
    _db.session.commit()
    return ano


@pytest.fixture
def serie(app) -> Serie:
    registro = Serie(
        nome="6o Ano", nivel_ensino=NivelEnsino.FUNDAMENTAL_II, ordem=1, ativa=True
    )
    _db.session.add(registro)
    _db.session.commit()
    return registro


@pytest.fixture
def turma(app, ano_letivo, serie) -> Turma:
    registro = Turma(
        nome="A",
        ano_letivo_id=ano_letivo.id,
        serie_id=serie.id,
        turno=Turno.MATUTINO,
        capacidade=30,
        ativa=True,
    )
    _db.session.add(registro)
    _db.session.commit()
    return registro


@pytest.fixture
def disciplina(app) -> Disciplina:
    registro = Disciplina(
        nome="Matematica", codigo="MAT", carga_horaria=200, ativa=True
    )
    _db.session.add(registro)
    _db.session.commit()
    return registro


@pytest.fixture
def professor(app) -> Professor:
    usuario = criar_usuario(
        "professor@escola.com.br", PapelUsuario.PROFESSOR, "Professor Teste"
    )
    registro = Professor(
        nome_completo="Professor Teste",
        registro_funcional="PROF00001",
        situacao=SituacaoCadastro.ATIVO,
        carga_horaria_semanal=20,
        usuario_id=usuario.id,
    )
    _db.session.add(registro)
    _db.session.commit()
    return registro


@pytest.fixture
def vinculo(app, turma, disciplina, professor) -> TurmaDisciplina:
    """Vinculo turma x disciplina x professor."""
    registro = TurmaDisciplina(
        turma_id=turma.id,
        disciplina_id=disciplina.id,
        professor_id=professor.id,
        carga_horaria_semanal=4,
        ativa=True,
    )
    _db.session.add(registro)
    _db.session.commit()
    return registro


@pytest.fixture
def aluno(app) -> Aluno:
    registro = Aluno(
        nome_completo="Aluno de Teste",
        codigo=Aluno.gerar_codigo(),
        data_nascimento=date(2012, 5, 10),
        situacao=SituacaoCadastro.ATIVO,
    )
    _db.session.add(registro)
    _db.session.commit()
    return registro


@pytest.fixture
def responsavel(app) -> Responsavel:
    usuario = criar_usuario(
        "responsavel@escola.com.br", PapelUsuario.RESPONSAVEL, "Responsavel Teste"
    )
    registro = Responsavel(
        nome_completo="Responsavel Teste",
        cpf="52998224725",  # CPF valido para testes
        situacao=SituacaoCadastro.ATIVO,
        usuario_id=usuario.id,
    )
    _db.session.add(registro)
    _db.session.commit()
    return registro


@pytest.fixture
def matricula(app, aluno, turma, ano_letivo) -> Matricula:
    registro = Matricula(
        numero=Matricula.gerar_numero(ano_letivo.ano),
        aluno_id=aluno.id,
        turma_id=turma.id,
        ano_letivo_id=ano_letivo.id,
        data_matricula=date.today(),
        situacao=SituacaoMatricula.ATIVA,
    )
    _db.session.add(registro)
    _db.session.commit()
    return registro


@pytest.fixture
def escola(app) -> ConfiguracaoEscola:
    return ConfiguracaoEscola.obter()


@pytest.fixture
def tempo_aula(app) -> TempoAula:
    registro = TempoAula(
        turno=Turno.MATUTINO,
        ordem=1,
        nome="1o tempo",
        hora_inicio=time(7, 0),
        hora_fim=time(7, 50),
        ativo=True,
    )
    _db.session.add(registro)
    _db.session.commit()
    return registro


# ---------------------------------------------------------------------------
# Autenticacao nos testes de rota
# ---------------------------------------------------------------------------
@pytest.fixture
def autenticar(cliente):
    """Devolve uma funcao que faz login com um usuario existente."""

    def _login(usuario: Usuario, senha: str = SENHA_PADRAO):
        return cliente.post(
            "/auth/login",
            data={"email": usuario.email, "senha": senha},
            follow_redirects=True,
        )

    return _login


@pytest.fixture
def cliente_admin(cliente, admin, autenticar):
    """Cliente ja autenticado como administrador."""
    autenticar(admin)
    return cliente


@pytest.fixture
def cliente_professor(cliente, professor, autenticar):
    """Cliente ja autenticado como professor."""
    autenticar(professor.usuario)
    return cliente
