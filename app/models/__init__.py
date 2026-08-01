"""Pacote de models do SGE.

Importar este pacote registra **todos** os models no ``metadata`` do
SQLAlchemy. Isso e o que permite ao Alembic detectar o schema completo com
``flask db migrate`` e ao ``db.create_all()`` dos testes criar todas as
tabelas de uma vez.

Mapa das entidades
------------------
Identidade e acesso
    ``Usuario``, ``LogAuditoria``
Pessoas
    ``Aluno``, ``Professor``, ``Funcionario``, ``Responsavel``,
    ``AlunoResponsavel``
Estrutura academica
    ``AnoLetivo``, ``PeriodoLetivo``, ``Serie``, ``Sala``, ``Disciplina``,
    ``Turma``, ``TurmaDisciplina``
Vida escolar
    ``Matricula``, ``Aula``, ``Frequencia``, ``Avaliacao``, ``Nota``,
    ``ResultadoDisciplina``
Grade
    ``TempoAula``, ``Horario``
Comunicacao
    ``Aviso``, ``AvisoLeitura``
Infraestrutura
    ``ConfiguracaoEscola``, ``RegistroBackup``
"""

from app.models.avaliacao import Avaliacao, Nota, ResultadoDisciplina
from app.models.base import (
    ExclusaoLogicaMixin,
    ModeloBase,
    TimestampMixin,
    agora_utc,
)
from app.models.comunicacao import Aviso, AvisoLeitura
from app.models.enums import (
    AcaoAuditoria,
    DiaSemana,
    EstadoCivil,
    NivelEnsino,
    PapelUsuario,
    Parentesco,
    PrioridadeAviso,
    PublicoAviso,
    ResultadoFinal,
    Sexo,
    SituacaoAnoLetivo,
    SituacaoCadastro,
    SituacaoMatricula,
    SituacaoPresenca,
    TipoAvaliacao,
    Turno,
)
from app.models.estrutura import (
    AnoLetivo,
    Disciplina,
    PeriodoLetivo,
    Sala,
    Serie,
    Turma,
    TurmaDisciplina,
)
from app.models.frequencia import Aula, Frequencia
from app.models.horario import Horario, TempoAula
from app.models.matricula import Matricula
from app.models.mixins import EnderecoMixin, PessoaMixin, VinculoUsuarioMixin
from app.models.pessoas import (
    Aluno,
    AlunoResponsavel,
    Funcionario,
    Professor,
    Responsavel,
)
from app.models.sistema import ConfiguracaoEscola, LogAuditoria, RegistroBackup

# A ordem de import importa: models referenciados por chave estrangeira
# precisam estar registrados antes de quem os referencia ser configurado.
from app.models.usuario import Usuario

__all__ = [
    # Base
    "ModeloBase",
    "TimestampMixin",
    "ExclusaoLogicaMixin",
    "PessoaMixin",
    "EnderecoMixin",
    "VinculoUsuarioMixin",
    "agora_utc",
    # Enums
    "PapelUsuario",
    "SituacaoCadastro",
    "Sexo",
    "EstadoCivil",
    "Parentesco",
    "NivelEnsino",
    "Turno",
    "SituacaoAnoLetivo",
    "SituacaoMatricula",
    "ResultadoFinal",
    "TipoAvaliacao",
    "SituacaoPresenca",
    "DiaSemana",
    "PublicoAviso",
    "PrioridadeAviso",
    "AcaoAuditoria",
    # Identidade
    "Usuario",
    # Estrutura academica
    "AnoLetivo",
    "PeriodoLetivo",
    "Serie",
    "Sala",
    "Disciplina",
    "Turma",
    "TurmaDisciplina",
    # Pessoas
    "Aluno",
    "Professor",
    "Funcionario",
    "Responsavel",
    "AlunoResponsavel",
    # Vida escolar
    "Matricula",
    "Aula",
    "Frequencia",
    "Avaliacao",
    "Nota",
    "ResultadoDisciplina",
    # Grade
    "TempoAula",
    "Horario",
    # Comunicacao
    "Aviso",
    "AvisoLeitura",
    # Infraestrutura
    "ConfiguracaoEscola",
    "LogAuditoria",
    "RegistroBackup",
]
