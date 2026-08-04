"""Registro de consentimento e base legal (LGPD).

Por que uma tabela, e nao um campo booleano no aluno
----------------------------------------------------
O cadastro ja tinha ``autoriza_uso_imagem`` e ``autorizado_sair_sozinho``.
Um booleano responde "pode?", que e a pergunta operacional — mas nao responde
nenhuma das que a lei faz quando alguem reclama:

* **quem** autorizou (o pai? a mae? a tia que buscou naquele dia?);
* **quando**;
* sob **qual base legal**;
* o que a familia leu antes de decidir;
* e, se o consentimento foi revogado, **quando** deixou de valer.

Historico, e nao estado
-----------------------
A tabela e **append-only**: revogar nao apaga nem edita o registro anterior,
cria um novo. O estado atual de uma finalidade e o ultimo registro dela.

Isso e proposital. A LGPD (art. 8, paragrafo 2) poe sobre o controlador o
onus de provar que o consentimento existiu. Um registro sobrescrito prova o
presente e destroi a evidencia do passado — que e justamente o que se pede
quando a familia contesta uma foto publicada ano passado.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import ModeloBase, TimestampMixin, agora_utc
from app.models.enums import BaseLegalLGPD, FinalidadeTratamento


class ConsentimentoLGPD(ModeloBase, TimestampMixin):
    """Uma decisao sobre uma finalidade de tratamento, para um aluno."""

    __tablename__ = "consentimentos_lgpd"
    __table_args__ = (
        # A consulta que importa e sempre "qual o ultimo registro deste aluno
        # para esta finalidade". O `id` no fim resolve o desempate.
        Index("ix_consentimento_aluno_finalidade", "aluno_id", "finalidade", "id"),
    )

    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), nullable=False, index=True
    )

    finalidade: Mapped[FinalidadeTratamento] = mapped_column(
        SAEnum(
            FinalidadeTratamento,
            name="finalidade_tratamento",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
    )

    # Copiada da finalidade no momento do registro, de proposito. Se a escola
    # reclassificar uma finalidade amanha, os registros antigos continuam
    # dizendo sob qual hipotese a decisao foi tomada na epoca — que e o que
    # vale se a decisao for questionada.
    base_legal: Mapped[BaseLegalLGPD] = mapped_column(
        SAEnum(
            BaseLegalLGPD,
            name="base_legal_lgpd",
            values_callable=lambda enum: [m.value for m in enum],
            native_enum=False,
        ),
        nullable=False,
    )

    concedido: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Decisao registrada. Um 'nao' tambem precisa constar.",
    )

    data_decisao: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today
    )

    # -- Quem decidiu -------------------------------------------------------
    responsavel_id: Mapped[int | None] = mapped_column(
        ForeignKey("responsaveis.id", ondelete="SET NULL"), nullable=True
    )
    responsavel_nome: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
        doc="Copia do nome no momento da decisao: sobrevive a exclusao do cadastro.",
    )

    # -- Quem registrou no sistema ------------------------------------------
    registrado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True
    )

    documento: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
        doc="Referencia ao termo assinado (numero, protocolo, local do arquivo).",
    )
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)

    revogado_em: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        doc="Preenchido quando este registro deixa de valer por revogacao.",
    )

    # -- Relacionamentos ----------------------------------------------------
    aluno = relationship("Aluno", foreign_keys=[aluno_id])
    responsavel = relationship("Responsavel", foreign_keys=[responsavel_id])
    registrado_por = relationship("Usuario", foreign_keys=[registrado_por_id])

    # ------------------------------------------------------------------
    @property
    def vigente(self) -> bool:
        """Se esta decisao autoriza o tratamento neste momento."""
        return self.concedido and self.revogado_em is None

    @property
    def nome_de_quem_decidiu(self) -> str:
        if self.responsavel:
            return self.responsavel.nome_completo
        return self.responsavel_nome or "Nao identificado"

    @property
    def situacao_rotulo(self) -> str:
        if self.revogado_em is not None:
            return "Revogado"
        return "Concedido" if self.concedido else "Negado"

    @property
    def situacao_cor(self) -> str:
        if self.revogado_em is not None:
            return "secondary"
        return "success" if self.concedido else "danger"

    def revogar(self) -> None:
        """Marca a decisao como encerrada.

        Nao apaga nem inverte o registro: quem revoga cria um registro novo
        e este passa a ser historico. Ver o docstring do modulo.
        """
        self.revogado_em = agora_utc()

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ConsentimentoLGPD aluno={self.aluno_id} "
            f"{self.finalidade.value} {self.situacao_rotulo}>"
        )


__all__ = ["ConsentimentoLGPD"]
