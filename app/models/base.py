"""Classe base e mixins reutilizados por todos os models do SGE.

Concentrar aqui o comportamento comum (chave primaria, timestamps, exclusao
logica, serializacao) evita repeticao em ~20 models e garante que uma
mudanca de politica (ex.: passar a gravar timezone) seja feita em um unico
lugar.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Integer, inspect
from sqlalchemy.orm import Mapped, declarative_mixin, declared_attr, mapped_column

from app.extensions import db


def agora_utc() -> datetime:
    """Instante atual em UTC, sem informacao de fuso.

    Todo o banco grava UTC *naive*. A conversao para o fuso da escola e
    responsabilidade exclusiva da camada de apresentacao
    (``app/utils/formatadores.py``), o que mantem o banco portavel entre
    SQLite e PostgreSQL e imune a mudancas de horario de verao.
    """
    return datetime.now(UTC).replace(tzinfo=None)


@declarative_mixin
class TimestampMixin:
    """Adiciona controle automatico de criacao e atualizacao."""

    @declared_attr
    def criado_em(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime,
            nullable=False,
            default=agora_utc,
            index=True,
            doc="Data e hora (UTC) de criacao do registro.",
        )

    @declared_attr
    def atualizado_em(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime,
            nullable=False,
            default=agora_utc,
            onupdate=agora_utc,
            doc="Data e hora (UTC) da ultima alteracao do registro.",
        )


@declarative_mixin
class ExclusaoLogicaMixin:
    """Exclusao logica (*soft delete*).

    Registros academicos nunca sao removidos fisicamente: a escola tem
    obrigacao legal de preservar historico escolar, e uma exclusao acidental
    de aluno seria irreversivel. Em vez de ``DELETE``, marcamos o registro
    como excluido e o filtramos nas consultas.
    """

    @declared_attr
    def excluido_em(cls) -> Mapped[datetime | None]:
        return mapped_column(
            DateTime,
            nullable=True,
            index=True,
            doc="Preenchido quando o registro e excluido logicamente.",
        )

    @declared_attr
    def excluido_por_id(cls) -> Mapped[int | None]:
        return mapped_column(
            Integer,
            nullable=True,
            doc="Usuario responsavel pela exclusao logica.",
        )

    @property
    def esta_excluido(self) -> bool:
        return self.excluido_em is not None

    def excluir(self, usuario_id: int | None = None) -> None:
        """Marca o registro como excluido sem remove-lo do banco."""
        self.excluido_em = agora_utc()
        self.excluido_por_id = usuario_id

    def restaurar(self) -> None:
        """Desfaz uma exclusao logica."""
        self.excluido_em = None
        self.excluido_por_id = None

    @classmethod
    def ativos(cls):
        """Query base ja filtrando registros nao excluidos."""
        return db.session.query(cls).filter(cls.excluido_em.is_(None))


class ModeloBase(db.Model):
    """Model abstrato com chave primaria inteira e utilitarios comuns."""

    __abstract__ = True

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # -- Helpers de consulta -------------------------------------------------
    @classmethod
    def buscar_por_id(cls, identificador: int | str | None):
        """Recupera por chave primaria tolerando entrada invalida.

        Util em rotas onde o ``id`` vem da URL: evita repetir ``try/except``
        em cada controlador.
        """
        if identificador is None:
            return None
        try:
            chave = int(identificador)
        except (TypeError, ValueError):
            return None
        return db.session.get(cls, chave)

    # -- Persistencia --------------------------------------------------------
    def salvar(self, commit: bool = True) -> ModeloBase:
        """Adiciona a sessao e, por padrao, confirma a transacao."""
        db.session.add(self)
        if commit:
            db.session.commit()
        return self

    def remover(self, commit: bool = True) -> None:
        """Remove fisicamente o registro.

        Use apenas em entidades sem valor historico (ex.: vinculos de grade).
        Entidades academicas devem usar :class:`ExclusaoLogicaMixin`.
        """
        db.session.delete(self)
        if commit:
            db.session.commit()

    # -- Serializacao --------------------------------------------------------
    def para_dicionario(
        self,
        incluir: Iterable[str] | None = None,
        excluir: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Converte as colunas do model em ``dict`` serializavel.

        Base para as respostas JSON usadas pelos graficos do dashboard e pela
        futura API consumida por um aplicativo Android.
        """
        excluir = set(excluir or ())
        colunas = {c.key for c in inspect(self.__class__).mapper.column_attrs}
        selecionadas = set(incluir) & colunas if incluir else colunas
        selecionadas -= excluir

        dados: dict[str, Any] = {}
        for nome in sorted(selecionadas):
            valor = getattr(self, nome)
            if isinstance(valor, datetime):
                dados[nome] = valor.isoformat()
            elif hasattr(valor, "value"):  # enums de dominio
                dados[nome] = valor.value
            else:
                dados[nome] = valor
        return dados

    def atualizar_campos(self, **valores: Any) -> ModeloBase:
        """Atribui apenas atributos que realmente existem no model.

        Protege contra *mass assignment*: um campo extra vindo de formulario
        nunca cria atributos inesperados no objeto.
        """
        colunas = {c.key for c in inspect(self.__class__).mapper.column_attrs}
        for nome, valor in valores.items():
            if nome in colunas and nome != "id":
                setattr(self, nome, valor)
        return self

    def __repr__(self) -> str:  # pragma: no cover - auxilio a depuracao
        return f"<{self.__class__.__name__} id={self.id}>"
