"""Consentimento LGPD por finalidade

Cria ``consentimentos_lgpd``: o registro de quem autorizou o que, quando e
sob qual base legal.

O cadastro do aluno ja tinha ``autoriza_uso_imagem`` e
``autorizado_sair_sozinho``. Os dois **continuam existindo** e sao mantidos
em sincronia pelo ``consentimento_service`` — a tela de cadastro e os filtros
de listagem dependem deles. O que muda e quem decide: a partir daqui, quem
responde "pode?" e ``consentimento_service.pode_tratar()``.

O passo de dados converte cada autorizacao ja marcada em um registro inicial,
para que o historico nao comece vazio. Esses registros nascem sem responsavel
identificado, porque o sistema antigo nao guardava essa informacao — e a
observacao diz exatamente isso. Inventar um nome ali seria pior que admitir a
lacuna: a trilha existe para ser usada como prova.

Sobre ``AcaoAuditoria.CONSENTIMENTO``: nao ha alteracao de schema. Com
``native_enum=False`` e ``create_constraint`` desligado (padrao do SQLAlchemy
2.0), a coluna e um VARCHAR sem CHECK, e ``consentimento`` (13 caracteres)
cabe na largura de 19 fixada na revisao anterior.

O ``downgrade`` **apaga a tabela inteira**, e com ela toda a prova de
consentimento. Backup antes nao e opcional.

Revision ID: cf200ac896c4
Revises: f525476c0fdc
Create Date: 2026-08-04 10:46:37.601184
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "cf200ac896c4"
down_revision = "f525476c0fdc"
branch_labels = None
depends_on = None


FINALIDADES = (
    "vida_escolar",
    "registro_obrigatorio",
    "saude_e_emergencia",
    "saida_desacompanhada",
    "uso_de_imagem",
    "comunicacao_institucional",
    "compartilhamento_externo",
)

BASES_LEGAIS = (
    "obrigacao_legal",
    "execucao_contrato",
    "tutela_da_saude",
    "protecao_da_vida",
    "consentimento",
)

#: Campo antigo -> finalidade correspondente. As duas autorizacoes que ja
#: existiam no cadastro se apoiam em consentimento.
CAMPOS_HERDADOS = (
    ("autoriza_uso_imagem", "uso_de_imagem"),
    ("autorizado_sair_sozinho", "saida_desacompanhada"),
)


def upgrade():
    op.create_table(
        "consentimentos_lgpd",
        sa.Column("aluno_id", sa.Integer(), nullable=False),
        sa.Column(
            "finalidade",
            sa.Enum(
                *FINALIDADES, name="finalidade_tratamento", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column(
            "base_legal",
            sa.Enum(*BASES_LEGAIS, name="base_legal_lgpd", native_enum=False),
            nullable=False,
        ),
        sa.Column("concedido", sa.Boolean(), nullable=False),
        sa.Column("data_decisao", sa.Date(), nullable=False),
        sa.Column("responsavel_id", sa.Integer(), nullable=True),
        sa.Column("responsavel_nome", sa.String(length=150), nullable=True),
        sa.Column("registrado_por_id", sa.Integer(), nullable=True),
        sa.Column("documento", sa.String(length=150), nullable=True),
        sa.Column("observacao", sa.Text(), nullable=True),
        sa.Column("revogado_em", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("criado_em", sa.DateTime(), nullable=False),
        sa.Column("atualizado_em", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["aluno_id"],
            ["alunos.id"],
            name=op.f("fk_consentimentos_lgpd_aluno_id_alunos"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["registrado_por_id"],
            ["usuarios.id"],
            name=op.f("fk_consentimentos_lgpd_registrado_por_id_usuarios"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["responsavel_id"],
            ["responsaveis.id"],
            name=op.f("fk_consentimentos_lgpd_responsavel_id_responsaveis"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consentimentos_lgpd")),
    )

    with op.batch_alter_table("consentimentos_lgpd", schema=None) as batch_op:
        batch_op.create_index(
            "ix_consentimento_aluno_finalidade",
            ["aluno_id", "finalidade", "id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_consentimentos_lgpd_aluno_id"),
            ["aluno_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_consentimentos_lgpd_criado_em"),
            ["criado_em"],
            unique=False,
        )

    _herdar_autorizacoes_do_cadastro()


def _herdar_autorizacoes_do_cadastro() -> None:
    """Converte as autorizacoes ja marcadas em registros iniciais.

    Feito com SQL direto, sem os models: uma migration precisa continuar
    rodando em qualquer versao futura do codigo.
    """
    conexao = op.get_bind()

    for campo, finalidade in CAMPOS_HERDADOS:
        conexao.execute(
            sa.text(
                f"""
                INSERT INTO consentimentos_lgpd (
                    aluno_id, finalidade, base_legal, concedido,
                    data_decisao, responsavel_nome, observacao,
                    criado_em, atualizado_em
                )
                SELECT
                    id,
                    :finalidade,
                    'consentimento',
                    1,
                    COALESCE(data_cadastro, CURRENT_DATE),
                    NULL,
                    :observacao,
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                FROM alunos
                WHERE {campo} = 1 AND excluido_em IS NULL
                """
            ),
            {
                "finalidade": finalidade,
                "observacao": (
                    "Autorizacao herdada do cadastro, anterior ao controle de "
                    "consentimento. O sistema antigo nao registrava quem "
                    "autorizou nem em que data — confirmar com a familia."
                ),
            },
        )


def downgrade():
    with op.batch_alter_table("consentimentos_lgpd", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_consentimentos_lgpd_criado_em"))
        batch_op.drop_index(batch_op.f("ix_consentimentos_lgpd_aluno_id"))
        batch_op.drop_index("ix_consentimento_aluno_finalidade")

    # Apaga o historico de consentimento. Os booleanos do cadastro continuam
    # onde estavam, entao a escola nao perde a autorizacao em si — perde a
    # prova de quem a deu, quando e sob qual termo.
    op.drop_table("consentimentos_lgpd")
