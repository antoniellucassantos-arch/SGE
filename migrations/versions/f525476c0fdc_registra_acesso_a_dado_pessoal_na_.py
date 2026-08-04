"""Registra acesso a dado pessoal na auditoria

Acrescenta ``acesso_dado_pessoal`` ao vocabulario de ``logs_auditoria.acao``.

A trilha sabia dizer quem *alterou* a ficha de um aluno, nunca quem a *leu*.
A LGPD exige rastrear a leitura quando o dado e de saude de menor de idade
(art. 11 e art. 37).

Detalhe que a versao gerada pelo Alembic nao tratava: o valor novo tem 19
caracteres e a coluna era ``VARCHAR(16)`` — o maior valor anterior era
``senha_recuperada``. Como ``native_enum=False``, o tipo e um VARCHAR com
CHECK, e tanto o tamanho quanto a lista de valores precisam mudar.

O ``downgrade`` **apaga** os registros de acesso antes de estreitar a
coluna. Nao ha para onde converte-los: nenhuma acao anterior significa
"alguem consultou dado sensivel", e reetiqueta-los como outra coisa
falsificaria a trilha. Quem voltar desta revisao perde o historico de
consulta — por isso o backup antes da migration nao e opcional.

Revision ID: f525476c0fdc
Revises: 12697dcf409a
Create Date: 2026-08-04 10:33:28.407636
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f525476c0fdc"
down_revision = "12697dcf409a"
branch_labels = None
depends_on = None

#: Vocabulario anterior a esta revisao.
VALORES_ANTERIORES = (
    "criacao",
    "atualizacao",
    "exclusao",
    "login",
    "logout",
    "login_falhou",
    "senha_alterada",
    "senha_recuperada",
    "acesso_negado",
    "backup",
    "restauracao",
    "exportacao",
)

VALOR_NOVO = "acesso_dado_pessoal"
VALORES_ATUAIS = (*VALORES_ANTERIORES, VALOR_NOVO)


def _tipo(valores: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(
        *valores, name="acao_auditoria", native_enum=False
    )


def upgrade():
    with op.batch_alter_table("logs_auditoria", schema=None) as batch_op:
        batch_op.alter_column(
            "acao",
            existing_type=sa.VARCHAR(length=16),
            type_=_tipo(VALORES_ATUAIS),
            existing_nullable=False,
        )


def downgrade():
    # A coluna volta a VARCHAR(16) e o CHECK volta a recusar o valor novo:
    # qualquer linha que tenha sobrado quebraria a restricao.
    op.execute(
        sa.text("DELETE FROM logs_auditoria WHERE acao = :acao").bindparams(
            acao=VALOR_NOVO
        )
    )

    with op.batch_alter_table("logs_auditoria", schema=None) as batch_op:
        batch_op.alter_column(
            "acao",
            existing_type=_tipo(VALORES_ATUAIS),
            type_=sa.VARCHAR(length=16),
            existing_nullable=False,
        )
