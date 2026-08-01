"""Formularios de autenticacao."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length

from app.utils.validadores import PoliticaSenha


class LoginForm(FlaskForm):
    """Formulario de entrada no sistema."""

    email = StringField(
        "E-mail",
        validators=[
            DataRequired(message="Informe seu e-mail."),
            Email(message="Informe um e-mail valido."),
            Length(max=150),
        ],
        render_kw={
            "placeholder": "seu.email@escola.com.br",
            "autocomplete": "username",
            "autofocus": True,
            "inputmode": "email",
        },
    )
    senha = PasswordField(
        "Senha",
        validators=[DataRequired(message="Informe sua senha.")],
        render_kw={
            "placeholder": "Sua senha",
            "autocomplete": "current-password",
        },
    )
    lembrar = BooleanField("Manter conectado neste dispositivo")
    enviar = SubmitField("Entrar")


class SolicitarRecuperacaoForm(FlaskForm):
    """Solicitacao do link de redefinicao de senha."""

    email = StringField(
        "E-mail cadastrado",
        validators=[
            DataRequired(message="Informe seu e-mail."),
            Email(message="Informe um e-mail valido."),
            Length(max=150),
        ],
        render_kw={
            "placeholder": "seu.email@escola.com.br",
            "autocomplete": "username",
            "autofocus": True,
            "inputmode": "email",
        },
    )
    enviar = SubmitField("Enviar link de recuperacao")


class RedefinirSenhaForm(FlaskForm):
    """Definicao de nova senha a partir de um token valido."""

    nova_senha = PasswordField(
        "Nova senha",
        validators=[
            DataRequired(message="Informe a nova senha."),
            PoliticaSenha(),
        ],
        render_kw={"autocomplete": "new-password", "autofocus": True},
    )
    confirmar_senha = PasswordField(
        "Confirme a nova senha",
        validators=[
            DataRequired(message="Confirme a nova senha."),
            EqualTo("nova_senha", message="As senhas nao conferem."),
        ],
        render_kw={"autocomplete": "new-password"},
    )
    enviar = SubmitField("Redefinir senha")


class AlterarSenhaForm(FlaskForm):
    """Troca de senha por usuario autenticado."""

    senha_atual = PasswordField(
        "Senha atual",
        validators=[DataRequired(message="Informe sua senha atual.")],
        render_kw={"autocomplete": "current-password", "autofocus": True},
    )
    nova_senha = PasswordField(
        "Nova senha",
        validators=[
            DataRequired(message="Informe a nova senha."),
            PoliticaSenha(),
        ],
        render_kw={"autocomplete": "new-password"},
    )
    confirmar_senha = PasswordField(
        "Confirme a nova senha",
        validators=[
            DataRequired(message="Confirme a nova senha."),
            EqualTo("nova_senha", message="As senhas nao conferem."),
        ],
        render_kw={"autocomplete": "new-password"},
    )
    enviar = SubmitField("Alterar senha")
