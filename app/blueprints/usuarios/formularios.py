"""Formularios de gestao de contas de acesso."""

from __future__ import annotations

from flask_wtf.file import FileAllowed, FileField
from wtforms import (
    BooleanField,
    EmailField,
    SelectField,
    StringField,
    SubmitField,
    TelField,
)
from wtforms.validators import DataRequired, Email, Length, Optional

from app.models.enums import PapelUsuario
from app.utils.formularios import IMAGENS_PERMITIDAS, FormularioBase, FormularioFiltro
from app.utils.validadores import CPF, NomeCompleto, Telefone


class UsuarioForm(FormularioBase):
    """Criacao e edicao de conta de acesso."""

    nome_completo = StringField(
        "Nome completo",
        validators=[
            DataRequired(message="Informe o nome completo."),
            Length(min=3, max=150),
            NomeCompleto(),
        ],
    )
    email = EmailField(
        "E-mail (login)",
        validators=[
            DataRequired(message="Informe o e-mail."),
            Email(message="Informe um e-mail valido."),
            Length(max=150),
        ],
        render_kw={"placeholder": "usuario@escola.com.br", "inputmode": "email"},
    )
    cpf = StringField(
        "CPF",
        validators=[Optional(), CPF()],
        render_kw={"placeholder": "000.000.000-00", "data-mascara": "cpf",
                   "inputmode": "numeric"},
    )
    telefone = TelField(
        "Telefone",
        validators=[Optional(), Telefone()],
        render_kw={"placeholder": "(00) 00000-0000", "data-mascara": "telefone",
                   "inputmode": "tel"},
    )
    papel = SelectField(
        "Perfil de acesso",
        choices=PapelUsuario.escolhas(),
        validators=[DataRequired()],
    )
    ativo = BooleanField("Conta ativa", default=True)

    enviar = SubmitField("Salvar usuario")


class PerfilForm(FormularioBase):
    """Edicao dos proprios dados pelo usuario autenticado.

    Nao expoe papel nem situacao: sao atribuicoes administrativas, e
    permitir que o usuario as edite seria escalonamento de privilegio.
    """

    nome_completo = StringField(
        "Nome completo",
        validators=[
            DataRequired(message="Informe o nome completo."),
            Length(min=3, max=150),
            NomeCompleto(),
        ],
    )
    telefone = TelField(
        "Telefone",
        validators=[Optional(), Telefone()],
        render_kw={"data-mascara": "telefone", "inputmode": "tel"},
    )
    foto = FileField(
        "Foto de perfil",
        validators=[FileAllowed(IMAGENS_PERMITIDAS, "Envie uma imagem PNG, JPG ou WEBP.")],
        render_kw={"accept": "image/png,image/jpeg,image/webp"},
    )

    enviar = SubmitField("Salvar alteracoes")


class FiltroUsuarioForm(FormularioFiltro):
    """Filtros da listagem de usuarios."""

    papel = SelectField(
        "Perfil",
        choices=PapelUsuario.escolhas(incluir_vazio=True, rotulo_vazio="Todos"),
        validators=[Optional()],
    )
    situacao = SelectField(
        "Situacao",
        choices=[
            ("", "Todas"),
            ("ativo", "Ativas"),
            ("inativo", "Inativas"),
            ("bloqueado", "Bloqueadas"),
        ],
        validators=[Optional()],
    )
