"""Fase 2: recuperacao final, medias por periodo em JSON, limiar de falta

Tres mudancas de schema, todas vindas da auditoria de calculo:

1. ``anos_letivos.minimo_aulas_para_apurar_falta`` — o limiar estava fixo em
   20 no codigo, contrariando o proprio design (parametros vem do ano letivo).

2. ``avaliacoes.tipo`` ganha ``recuperacao_final`` — antes, a recuperacao de
   bimestre era contada duas vezes: substituia a media do periodo e voltava a
   substituir a media anual.

3. ``resultados_disciplinas`` troca as quatro colunas fixas de media por uma
   coluna JSON. Escola com cinco periodos perdia o ultimo em silencio.

O passo de dados entre as duas estruturas preserva as medias ja apuradas:
dropar as colunas sem copiar apagaria historico escolar.

Revision ID: 12697dcf409a
Revises: 037750e0ef9b
Create Date: 2026-08-02 07:28:19.834079
"""

import json

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "12697dcf409a"
down_revision = "037750e0ef9b"
branch_labels = None
depends_on = None


def upgrade():
    # --- 1. Limiar de apuracao por falta ----------------------------------
    with op.batch_alter_table("anos_letivos", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "minimo_aulas_para_apurar_falta",
                sa.Integer(),
                nullable=False,
                server_default="20",
            )
        )

    # --- 2. Novo tipo de avaliacao ----------------------------------------
    with op.batch_alter_table("avaliacoes", schema=None) as batch_op:
        batch_op.alter_column(
            "tipo",
            existing_type=sa.VARCHAR(length=12),
            type_=sa.Enum(
                "prova", "trabalho", "seminario", "participacao", "projeto",
                "recuperacao", "recuperacao_final", "outro",
                name="tipo_avaliacao", native_enum=False,
            ),
            existing_nullable=False,
        )

    # --- 3. Medias por periodo: colunas fixas -> JSON ----------------------
    with op.batch_alter_table("resultados_disciplinas", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "medias_periodos", sa.JSON(), nullable=False, server_default="{}"
            )
        )

    _copiar_medias_para_json()

    with op.batch_alter_table("resultados_disciplinas", schema=None) as batch_op:
        batch_op.drop_column("media_periodo_1")
        batch_op.drop_column("media_periodo_2")
        batch_op.drop_column("media_periodo_3")
        batch_op.drop_column("media_periodo_4")


def _copiar_medias_para_json() -> None:
    """Move as medias das quatro colunas para o dicionario JSON.

    Feito com SQL direto (sem os models) porque uma migration precisa
    funcionar em qualquer versao futura do codigo — inclusive depois que
    ``ResultadoDisciplina`` deixar de conhecer estas colunas.
    """
    conexao = op.get_bind()

    linhas = conexao.execute(
        sa.text(
            "SELECT id, media_periodo_1, media_periodo_2, "
            "media_periodo_3, media_periodo_4 FROM resultados_disciplinas"
        )
    ).fetchall()

    for linha in linhas:
        medias = {
            str(ordem): (str(valor) if valor is not None else None)
            for ordem, valor in enumerate(linha[1:], start=1)
        }

        conexao.execute(
            sa.text(
                "UPDATE resultados_disciplinas SET medias_periodos = :medias "
                "WHERE id = :id"
            ),
            {"medias": json.dumps(medias), "id": linha[0]},
        )


def downgrade():
    # --- 3. JSON -> colunas fixas -----------------------------------------
    with op.batch_alter_table("resultados_disciplinas", schema=None) as batch_op:
        for ordem in range(1, 5):
            batch_op.add_column(
                sa.Column(
                    f"media_periodo_{ordem}",
                    sa.NUMERIC(precision=5, scale=2),
                    nullable=True,
                )
            )

    _restaurar_medias_das_colunas()

    with op.batch_alter_table("resultados_disciplinas", schema=None) as batch_op:
        batch_op.drop_column("medias_periodos")

    # --- 2. Tipo de avaliacao ---------------------------------------------
    # Avaliacoes de recuperacao final voltam a ser recuperacao comum: e o
    # unico tipo que existe no schema anterior.
    op.execute(
        sa.text(
            "UPDATE avaliacoes SET tipo = 'recuperacao' "
            "WHERE tipo = 'recuperacao_final'"
        )
    )

    with op.batch_alter_table("avaliacoes", schema=None) as batch_op:
        batch_op.alter_column(
            "tipo",
            existing_type=sa.Enum(
                "prova", "trabalho", "seminario", "participacao", "projeto",
                "recuperacao", "recuperacao_final", "outro",
                name="tipo_avaliacao", native_enum=False,
            ),
            type_=sa.VARCHAR(length=12),
            existing_nullable=False,
        )

    # --- 1. Limiar de apuracao --------------------------------------------
    with op.batch_alter_table("anos_letivos", schema=None) as batch_op:
        batch_op.drop_column("minimo_aulas_para_apurar_falta")


def _restaurar_medias_das_colunas() -> None:
    """Devolve as quatro primeiras medias do JSON para as colunas.

    A partir do quinto periodo os valores sao perdidos — o schema antigo nao
    tem onde guarda-los. E justamente a limitacao que motivou a mudanca.
    """
    conexao = op.get_bind()

    linhas = conexao.execute(
        sa.text("SELECT id, medias_periodos FROM resultados_disciplinas")
    ).fetchall()

    for identificador, medias_json in linhas:
        try:
            medias = json.loads(medias_json) if medias_json else {}
        except (TypeError, ValueError):
            medias = {}

        valores = {
            f"media_periodo_{ordem}": medias.get(str(ordem))
            for ordem in range(1, 5)
        }

        conexao.execute(
            sa.text(
                "UPDATE resultados_disciplinas SET "
                "media_periodo_1 = :media_periodo_1, "
                "media_periodo_2 = :media_periodo_2, "
                "media_periodo_3 = :media_periodo_3, "
                "media_periodo_4 = :media_periodo_4 "
                "WHERE id = :id"
            ),
            {**valores, "id": identificador},
        )
