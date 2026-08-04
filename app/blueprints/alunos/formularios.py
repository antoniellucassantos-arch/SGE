"""Formularios do cadastro de alunos."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import Length, NumberRange, Optional

from app.models.enums import Parentesco, SituacaoCadastro
from app.utils.formularios import (
    OPCOES_UF,
    FormularioFiltro,
    FormularioPessoa,
)


class AlunoForm(FormularioPessoa):
    """Cadastro e edicao de aluno.

    Herda de :class:`FormularioPessoa` (dados civis, contato, endereco,
    situacao) e acrescenta apenas o que e proprio do aluno.
    """

    # -- Naturalidade e documentos -----------------------------------------
    naturalidade = StringField(
        "Naturalidade",
        validators=[Optional(), Length(max=80)],
        render_kw={"placeholder": "Cidade de nascimento"},
    )
    uf_naturalidade = SelectField(
        "UF de nascimento", choices=OPCOES_UF, validators=[Optional()]
    )
    nacionalidade = StringField(
        "Nacionalidade",
        validators=[Optional(), Length(max=60)],
        default="Brasileira",
    )
    certidao_nascimento = StringField(
        "Certidao de nascimento",
        validators=[Optional(), Length(max=60)],
        render_kw={"placeholder": "Termo / matricula da certidao"},
    )
    nis = StringField(
        "NIS",
        validators=[Optional(), Length(max=11)],
        render_kw={"placeholder": "Numero de Identificacao Social",
                   "inputmode": "numeric"},
    )
    cartao_sus = StringField(
        "Cartao SUS",
        validators=[Optional(), Length(max=15)],
        render_kw={"inputmode": "numeric"},
    )

    # -- Saude --------------------------------------------------------------
    # Dados sensiveis (LGPD art. 11): coletados pelo interesse vital do aluno
    # e visiveis apenas a equipe interna com permissao especifica.
    tipo_sanguineo = SelectField(
        "Tipo sanguineo",
        choices=[
            ("", "Nao informado"),
            ("A+", "A+"), ("A-", "A-"), ("B+", "B+"), ("B-", "B-"),
            ("AB+", "AB+"), ("AB-", "AB-"), ("O+", "O+"), ("O-", "O-"),
        ],
        validators=[Optional()],
    )
    alergias = TextAreaField(
        "Alergias",
        validators=[Optional(), Length(max=1000)],
        render_kw={"rows": 2,
                   "placeholder": "Alimentos, medicamentos, substancias..."},
    )
    medicamentos_continuos = TextAreaField(
        "Medicamentos de uso continuo",
        validators=[Optional(), Length(max=1000)],
        render_kw={"rows": 2},
    )
    condicoes_saude = TextAreaField(
        "Condicoes de saude relevantes",
        validators=[Optional(), Length(max=1000)],
        render_kw={"rows": 2,
                   "placeholder": "Asma, diabetes, epilepsia, TDAH..."},
    )
    possui_deficiencia = BooleanField("Aluno com deficiencia")
    descricao_deficiencia = TextAreaField(
        "Descricao da deficiencia",
        validators=[Optional(), Length(max=1000)],
        render_kw={"rows": 2},
    )
    necessita_acompanhante = BooleanField("Necessita acompanhante especializado")

    # -- Beneficios e autorizacoes -----------------------------------------
    bolsista = BooleanField("Aluno bolsista")
    percentual_bolsa = DecimalField(
        "Percentual da bolsa (%)",
        validators=[Optional(), NumberRange(min=0, max=100)],
        places=2,
        render_kw={"inputmode": "decimal", "step": "0.01"},
    )
    usa_transporte_escolar = BooleanField("Utiliza transporte escolar")
    autorizado_sair_sozinho = BooleanField("Autorizado a sair desacompanhado")
    autoriza_uso_imagem = BooleanField(
        "Responsavel autoriza uso de imagem em midias da escola"
    )

    enviar = SubmitField("Salvar aluno")

    def validate(self, extra_validators=None) -> bool:
        """Validacoes cruzadas entre campos do proprio formulario."""
        if not super().validate(extra_validators):
            return False

        valido = True

        if self.bolsista.data and not self.percentual_bolsa.data:
            self.percentual_bolsa.errors.append(
                "Informe o percentual da bolsa concedida."
            )
            valido = False

        if self.possui_deficiencia.data and not (self.descricao_deficiencia.data or "").strip():
            self.descricao_deficiencia.errors.append(
                "Descreva a deficiencia para orientar o atendimento pedagogico."
            )
            valido = False

        return valido

    def dados_limpos(self, ignorar: set[str] | None = None) -> dict:
        dados = super().dados_limpos(ignorar)

        # Zera o percentual quando o aluno deixa de ser bolsista.
        if not dados.get("bolsista"):
            dados["percentual_bolsa"] = None
        if not dados.get("possui_deficiencia"):
            dados["descricao_deficiencia"] = None

        for campo in ("nis", "cartao_sus", "tipo_sanguineo", "uf_naturalidade"):
            if campo in dados and not (dados[campo] or "").strip():
                dados[campo] = None

        return dados


class FiltroAlunoForm(FormularioFiltro):
    """Filtros da listagem de alunos."""

    situacao = SelectField(
        "Situacao",
        choices=SituacaoCadastro.escolhas(incluir_vazio=True, rotulo_vazio="Todas"),
        validators=[Optional()],
    )
    turma_id = SelectField("Turma", choices=[], validators=[Optional()], coerce=str)
    sem_turma = BooleanField("Somente sem matricula ativa")


class VincularResponsavelForm(FormularioFiltro):
    """Vinculo de um responsavel ao aluno.

    Usa ``FormularioFiltro`` como base apenas pela conveniencia do campo de
    busca; o CSRF e reativado porque este formulario altera dados.
    """

    class Meta:
        csrf = True

    responsavel_id = SelectField(
        "Responsavel", choices=[], validators=[Optional()], coerce=str
    )
    parentesco = SelectField(
        "Parentesco", choices=Parentesco.escolhas(), default=Parentesco.MAE.value
    )
    responsavel_legal = BooleanField("Responsavel legal", default=True)
    responsavel_financeiro = BooleanField("Responsavel financeiro")
    autorizado_buscar = BooleanField("Autorizado a buscar o aluno", default=True)
    ordem_contato = IntegerField(
        "Ordem de contato",
        validators=[Optional(), NumberRange(min=1, max=10)],
        default=1,
        render_kw={"inputmode": "numeric"},
    )
    enviar = SubmitField("Vincular responsavel")


class ConsentimentoForm(FlaskForm):
    """Registro de uma decisao da familia sobre uma finalidade (LGPD).

    ``concedido`` e ``SelectField`` e nao ``BooleanField`` de proposito: um
    checkbox desmarcado e indistinguivel de "ninguem perguntou ainda", e a
    diferenca entre um "nao" registrado e uma pendencia e justamente o que a
    escola precisa saber.

    Herda ``FlaskForm``, e nao ``FormularioFiltro``: o CSRF acompanha a
    configuracao da aplicacao — ligado em producao, desligado na suite. Um
    ``Meta.csrf = True`` fixo obrigaria cada teste de rota a montar o token a
    mao, o que exercita o WTForms e nao a regra.
    """

    finalidade = SelectField("Finalidade", choices=[], coerce=str)
    concedido = SelectField(
        "Decisao",
        choices=[("1", "Concedido"), ("0", "Negado")],
        default="1",
        coerce=str,
    )
    responsavel_id = SelectField(
        "Quem decidiu", choices=[], validators=[Optional()], coerce=str
    )
    data_decisao = DateField("Data da decisao", validators=[Optional()])
    documento = StringField(
        "Termo assinado",
        validators=[Optional(), Length(max=150)],
        render_kw={"placeholder": "Numero ou protocolo do termo"},
    )
    observacao = TextAreaField(
        "Observacao", validators=[Optional(), Length(max=1000)]
    )
    enviar = SubmitField("Registrar decisao")

    def validate_responsavel_id(self, campo) -> None:
        from wtforms.validators import ValidationError

        if not (campo.data or "").strip():
            raise ValidationError("Selecione um responsavel.")
