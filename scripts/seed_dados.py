"""Populacao do banco com dados ficticios para desenvolvimento e demonstracao.

NUNCA execute em producao. Os dados aqui sao inventados e servem apenas para
exercitar as telas, validar consultas e permitir demonstrar o sistema para a
escola antes da carga real.

Uso::

    flask popular-demonstracao --alunos 60
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from app.extensions import db
from app.models.avaliacao import Avaliacao, Nota
from app.models.comunicacao import Aviso
from app.models.enums import (
    NivelEnsino,
    PapelUsuario,
    Parentesco,
    PrioridadeAviso,
    PublicoAviso,
    Sexo,
    SituacaoCadastro,
    SituacaoMatricula,
    SituacaoPresenca,
    TipoAvaliacao,
    Turno,
)
from app.models.estrutura import (
    AnoLetivo,
    Disciplina,
    Sala,
    Serie,
    Turma,
    TurmaDisciplina,
)
from app.models.frequencia import Aula, Frequencia
from app.models.matricula import Matricula
from app.models.pessoas import (
    Aluno,
    AlunoResponsavel,
    Funcionario,
    Professor,
    Responsavel,
)
from app.models.usuario import Usuario

# Semente fixa: rodar o seed duas vezes produz a mesma base, o que torna
# comparacoes e capturas de tela reproduziveis.
ALEATORIO = random.Random(2026)

NOMES = [
    "Ana", "Bruno", "Carla", "Daniel", "Eduarda", "Felipe", "Gabriela",
    "Henrique", "Isabela", "Joao", "Karina", "Lucas", "Mariana", "Nicolas",
    "Olivia", "Pedro", "Rafaela", "Samuel", "Tatiana", "Vinicius", "Yasmin",
    "Arthur", "Beatriz", "Caio", "Daniela", "Enzo", "Fernanda", "Gustavo",
    "Helena", "Igor", "Julia", "Kaique", "Larissa", "Matheus", "Natalia",
]

SOBRENOMES = [
    "Silva", "Santos", "Oliveira", "Souza", "Rodrigues", "Ferreira", "Alves",
    "Pereira", "Lima", "Gomes", "Costa", "Ribeiro", "Martins", "Carvalho",
    "Almeida", "Lopes", "Soares", "Fernandes", "Vieira", "Barbosa",
]

DISCIPLINAS = [
    ("Lingua Portuguesa", "PORT", 200, "#e02424"),
    ("Matematica", "MAT", 200, "#1a56db"),
    ("Historia", "HIST", 80, "#c27803"),
    ("Geografia", "GEO", 80, "#057a55"),
    ("Ciencias", "CIE", 120, "#0694a2"),
    ("Ingles", "ING", 80, "#7e3af2"),
    ("Educacao Fisica", "EDF", 80, "#ff5a1f"),
    ("Arte", "ART", 40, "#e74694"),
]

CARGOS = [
    ("Secretario escolar", "Secretaria"),
    ("Auxiliar administrativo", "Secretaria"),
    ("Coordenador pedagogico", "Coordenacao"),
    ("Bibliotecario", "Biblioteca"),
    ("Porteiro", "Portaria"),
    ("Auxiliar de servicos gerais", "Limpeza"),
]


def _nome_completo() -> str:
    return (
        f"{ALEATORIO.choice(NOMES)} "
        f"{ALEATORIO.choice(SOBRENOMES)} {ALEATORIO.choice(SOBRENOMES)}"
    )


def _cpf_ficticio(semente: int) -> str:
    """Gera um CPF com digitos verificadores validos, a partir de um indice.

    Precisa ser matematicamente valido porque os proprios validadores do
    sistema recusariam um numero aleatorio.
    """
    base = [int(d) for d in f"{semente:09d}"]

    for _ in range(2):
        peso = len(base) + 1
        soma = sum(digito * (peso - i) for i, digito in enumerate(base))
        verificador = (soma * 10) % 11
        base.append(0 if verificador == 10 else verificador)

    return "".join(str(d) for d in base)


def _telefone() -> str:
    return f"119{ALEATORIO.randint(10000000, 99999999)}"


def popular(quantidade_alunos: int = 60) -> dict[str, int]:
    """Cria a base de demonstracao e devolve um resumo do que foi gerado."""
    resumo = {
        "disciplinas": 0, "salas": 0, "professores": 0, "funcionarios": 0,
        "turmas": 0, "alunos": 0, "responsaveis": 0, "matriculas": 0,
        "aulas": 0, "avaliacoes": 0, "notas": 0, "avisos": 0,
    }

    ano_letivo = (
        db.session.query(AnoLetivo).filter(AnoLetivo.corrente.is_(True)).first()
    )
    if ano_letivo is None:
        raise RuntimeError(
            "Nenhum ano letivo corrente. Execute 'flask criar-estrutura-inicial'."
        )

    resumo["disciplinas"] = _criar_disciplinas()
    resumo["salas"] = _criar_salas()
    professores = _criar_professores()
    resumo["professores"] = len(professores)
    resumo["funcionarios"] = _criar_funcionarios()

    turmas = _criar_turmas(ano_letivo, professores)
    resumo["turmas"] = len(turmas)

    alunos, responsaveis = _criar_alunos(quantidade_alunos)
    resumo["alunos"] = len(alunos)
    resumo["responsaveis"] = len(responsaveis)

    matriculas = _matricular(alunos, turmas, ano_letivo)
    resumo["matriculas"] = len(matriculas)

    resumo["aulas"], resumo["avaliacoes"], resumo["notas"] = _lancar_academico(
        turmas, ano_letivo
    )
    resumo["avisos"] = _criar_avisos(turmas)

    db.session.commit()
    return resumo


# ---------------------------------------------------------------------------
# Estrutura
# ---------------------------------------------------------------------------
def _criar_disciplinas() -> int:
    criadas = 0
    for nome, codigo, carga, cor in DISCIPLINAS:
        if db.session.query(Disciplina).filter(Disciplina.codigo == codigo).first():
            continue
        db.session.add(
            Disciplina(nome=nome, codigo=codigo, carga_horaria=carga, cor=cor)
        )
        criadas += 1
    db.session.flush()
    return criadas


def _criar_salas() -> int:
    criadas = 0
    for numero in range(1, 9):
        nome = f"Sala {numero:02d}"
        if db.session.query(Sala).filter(Sala.nome == nome).first():
            continue
        db.session.add(
            Sala(
                nome=nome,
                bloco="A" if numero <= 4 else "B",
                andar="Terreo" if numero <= 4 else "1o andar",
                capacidade=35,
                possui_projetor=numero % 2 == 0,
                acessivel=numero <= 4,
            )
        )
        criadas += 1
    db.session.flush()
    return criadas


def _criar_professores() -> list[Professor]:
    existentes = db.session.query(Professor).all()
    if existentes:
        return existentes

    titulacoes = ["Graduacao", "Especializacao", "Mestrado"]
    professores = []

    for indice in range(8):
        nome = _nome_completo()
        email = f"professor{indice + 1}@escola.com.br"

        usuario = Usuario(
            nome_completo=nome,
            email=email,
            papel=PapelUsuario.PROFESSOR,
            ativo=True,
        )
        usuario.definir_senha("Professor@2026", exigir_troca=False)
        db.session.add(usuario)
        db.session.flush()

        professor = Professor(
            nome_completo=nome,
            registro_funcional=f"PROF{indice + 1:05d}",
            cpf=_cpf_ficticio(100000000 + indice),
            email=email,
            celular=_telefone(),
            sexo=ALEATORIO.choice(list(Sexo)),
            data_nascimento=date(
                ALEATORIO.randint(1975, 1995), ALEATORIO.randint(1, 12), 15
            ),
            formacao=f"Licenciatura em {DISCIPLINAS[indice][0]}",
            titulacao=ALEATORIO.choice(titulacoes),
            data_admissao=date(ALEATORIO.randint(2015, 2024), 2, 1),
            carga_horaria_semanal=ALEATORIO.choice([20, 30, 40]),
            situacao=SituacaoCadastro.ATIVO,
            usuario_id=usuario.id,
        )
        db.session.add(professor)
        professores.append(professor)

    db.session.flush()
    return professores


def _criar_funcionarios() -> int:
    if db.session.query(Funcionario).count():
        return 0

    for indice, (cargo, setor) in enumerate(CARGOS):
        db.session.add(
            Funcionario(
                nome_completo=_nome_completo(),
                matricula_funcional=f"FUNC{indice + 1:05d}",
                cargo=cargo,
                setor=setor,
                cpf=_cpf_ficticio(200000000 + indice),
                celular=_telefone(),
                sexo=ALEATORIO.choice(list(Sexo)),
                data_admissao=date(ALEATORIO.randint(2016, 2024), 3, 1),
                situacao=SituacaoCadastro.ATIVO,
            )
        )

    db.session.flush()
    return len(CARGOS)


def _criar_turmas(ano_letivo: AnoLetivo, professores: list[Professor]) -> list[Turma]:
    existentes = (
        db.session.query(Turma)
        .filter(Turma.ano_letivo_id == ano_letivo.id)
        .all()
    )
    if existentes:
        return existentes

    series = (
        db.session.query(Serie)
        .filter(Serie.nivel_ensino == NivelEnsino.FUNDAMENTAL_II)
        .order_by(Serie.ordem)
        .all()
    )
    salas = db.session.query(Sala).order_by(Sala.nome).all()
    disciplinas = db.session.query(Disciplina).all()

    turmas = []
    for indice, serie in enumerate(series[:4]):
        turma = Turma(
            nome="A",
            ano_letivo_id=ano_letivo.id,
            serie_id=serie.id,
            sala_id=salas[indice % len(salas)].id if salas else None,
            professor_regente_id=professores[indice % len(professores)].id,
            turno=Turno.MATUTINO,
            capacidade=30,
            ativa=True,
        )
        db.session.add(turma)
        db.session.flush()

        for posicao, disciplina in enumerate(disciplinas):
            db.session.add(
                TurmaDisciplina(
                    turma_id=turma.id,
                    disciplina_id=disciplina.id,
                    professor_id=professores[posicao % len(professores)].id,
                    carga_horaria_semanal=ALEATORIO.choice([2, 3, 4]),
                    ativa=True,
                )
            )

        turmas.append(turma)

    db.session.flush()
    return turmas


# ---------------------------------------------------------------------------
# Pessoas
# ---------------------------------------------------------------------------
def _criar_alunos(quantidade: int) -> tuple[list[Aluno], list[Responsavel]]:
    if db.session.query(Aluno).count():
        return db.session.query(Aluno).all(), db.session.query(Responsavel).all()

    alunos: list[Aluno] = []
    responsaveis: list[Responsavel] = []

    for indice in range(quantidade):
        # Responsavel primeiro: o aluno precisa do vinculo ao ser criado.
        responsavel = Responsavel(
            nome_completo=_nome_completo(),
            cpf=_cpf_ficticio(300000000 + indice),
            celular=_telefone(),
            email=f"responsavel{indice + 1}@exemplo.com",
            sexo=ALEATORIO.choice(list(Sexo)),
            profissao=ALEATORIO.choice(
                ["Comerciante", "Professor", "Autonomo", "Enfermeiro", "Motorista"]
            ),
            situacao=SituacaoCadastro.ATIVO,
        )
        db.session.add(responsavel)
        db.session.flush()
        responsaveis.append(responsavel)

        aluno = Aluno(
            nome_completo=_nome_completo(),
            codigo=Aluno.gerar_codigo(),
            cpf=_cpf_ficticio(400000000 + indice),
            data_nascimento=date(
                ALEATORIO.randint(2010, 2014),
                ALEATORIO.randint(1, 12),
                ALEATORIO.randint(1, 28),
            ),
            sexo=ALEATORIO.choice(list(Sexo)),
            celular=_telefone(),
            cidade="Sao Paulo",
            uf="SP",
            nacionalidade="Brasileira",
            situacao=SituacaoCadastro.ATIVO,
            bolsista=indice % 10 == 0,
            percentual_bolsa=50 if indice % 10 == 0 else None,
            usa_transporte_escolar=indice % 4 == 0,
            autoriza_uso_imagem=indice % 3 != 0,
            alergias="Alergia a amendoim" if indice % 15 == 0 else None,
        )
        db.session.add(aluno)
        db.session.flush()

        db.session.add(
            AlunoResponsavel(
                aluno_id=aluno.id,
                responsavel_id=responsavel.id,
                parentesco=ALEATORIO.choice([Parentesco.MAE, Parentesco.PAI]),
                responsavel_legal=True,
                responsavel_financeiro=True,
                autorizado_buscar=True,
                ordem_contato=1,
            )
        )

        alunos.append(aluno)

    db.session.flush()
    return alunos, responsaveis


def _matricular(
    alunos: list[Aluno], turmas: list[Turma], ano_letivo: AnoLetivo
) -> list[Matricula]:
    if db.session.query(Matricula).count():
        return db.session.query(Matricula).all()

    matriculas = []
    for indice, aluno in enumerate(alunos):
        turma = turmas[indice % len(turmas)]

        matricula = Matricula(
            numero=Matricula.gerar_numero(ano_letivo.ano),
            aluno_id=aluno.id,
            turma_id=turma.id,
            ano_letivo_id=ano_letivo.id,
            data_matricula=ano_letivo.data_inicio + timedelta(days=indice % 20),
            situacao=SituacaoMatricula.ATIVA,
        )
        db.session.add(matricula)
        db.session.flush()
        matriculas.append(matricula)

    return matriculas


# ---------------------------------------------------------------------------
# Vida academica
# ---------------------------------------------------------------------------
def _lancar_academico(turmas: list[Turma], ano_letivo: AnoLetivo) -> tuple[int, int, int]:
    """Cria aulas com chamada e avaliacoes com notas."""
    if db.session.query(Aula).count():
        return 0, 0, 0

    periodo = ano_letivo.periodos[0] if ano_letivo.periodos else None
    if periodo is None:
        return 0, 0, 0

    total_aulas = total_avaliacoes = total_notas = 0
    hoje = date.today()

    for turma in turmas:
        matriculas = (
            db.session.query(Matricula)
            .filter(
                Matricula.turma_id == turma.id,
                Matricula.situacao == SituacaoMatricula.ATIVA,
            )
            .all()
        )
        if not matriculas:
            continue

        # Apenas duas disciplinas por turma: o objetivo e demonstrar as
        # telas, nao gerar dezenas de milhares de linhas.
        for vinculo in turma.turmas_disciplinas[:2]:
            # --- Aulas com chamada ---
            for dia in range(8):
                data_aula = hoje - timedelta(days=dia * 3 + 1)
                if not ano_letivo.contem_data(data_aula):
                    continue

                aula = Aula(
                    turma_disciplina_id=vinculo.id,
                    data_aula=data_aula,
                    ordem_no_dia=1,
                    quantidade_aulas=1,
                    conteudo=f"Aula {dia + 1} de "
                    f"{vinculo.disciplina.nome if vinculo.disciplina else 'disciplina'}",
                    chamada_realizada=True,
                )
                db.session.add(aula)
                db.session.flush()
                total_aulas += 1

                for matricula in matriculas:
                    # ~8% de faltas, proporcao realista para uma escola.
                    situacao = (
                        SituacaoPresenca.FALTA
                        if ALEATORIO.random() < 0.08
                        else SituacaoPresenca.PRESENTE
                    )
                    db.session.add(
                        Frequencia(
                            aula_id=aula.id,
                            matricula_id=matricula.id,
                            situacao=situacao,
                        )
                    )

            # --- Avaliacoes com notas ---
            for numero, (nome, tipo, peso) in enumerate(
                [
                    ("Prova 1", TipoAvaliacao.PROVA, 3),
                    ("Trabalho", TipoAvaliacao.TRABALHO, 2),
                ],
                start=1,
            ):
                avaliacao = Avaliacao(
                    turma_disciplina_id=vinculo.id,
                    periodo_id=periodo.id,
                    nome=nome,
                    tipo=tipo,
                    peso=peso,
                    valor_maximo=10,
                    data_aplicacao=hoje - timedelta(days=numero * 10),
                    publicada=True,
                )
                db.session.add(avaliacao)
                db.session.flush()
                total_avaliacoes += 1

                for matricula in matriculas:
                    db.session.add(
                        Nota(
                            avaliacao_id=avaliacao.id,
                            matricula_id=matricula.id,
                            valor=round(ALEATORIO.uniform(3.0, 10.0), 1),
                        )
                    )
                    total_notas += 1

    db.session.flush()
    return total_aulas, total_avaliacoes, total_notas


def _criar_avisos(turmas: list[Turma]) -> int:
    if db.session.query(Aviso).count():
        return 0

    admin = (
        db.session.query(Usuario)
        .filter(Usuario.papel == PapelUsuario.ADMINISTRADOR)
        .first()
    )

    modelos = [
        (
            "Reuniao de pais e mestres",
            "A reuniao do primeiro bimestre acontecera no proximo sabado, "
            "das 9h as 12h, no auditorio da escola. A presenca do responsavel "
            "e fundamental para o acompanhamento do desenvolvimento do aluno.",
            PublicoAviso.RESPONSAVEIS,
            PrioridadeAviso.ALTA,
            True,
        ),
        (
            "Entrega de boletins",
            "Os boletins do primeiro bimestre ja estao disponiveis no sistema. "
            "Acesse o portal para consultar as notas e a frequencia.",
            PublicoAviso.TODOS,
            PrioridadeAviso.NORMAL,
            False,
        ),
        (
            "Semana de provas",
            "A semana de avaliacoes comeca na proxima segunda-feira. "
            "Confira o cronograma com o professor de cada disciplina.",
            PublicoAviso.ALUNOS,
            PrioridadeAviso.ALTA,
            False,
        ),
        (
            "Conselho de classe",
            "O conselho de classe do bimestre acontecera na sexta-feira, "
            "as 14h. A participacao de todos os professores e obrigatoria.",
            PublicoAviso.PROFESSORES,
            PrioridadeAviso.URGENTE,
            False,
        ),
    ]

    for titulo, mensagem, publico, prioridade, fixado in modelos:
        db.session.add(
            Aviso(
                titulo=titulo,
                mensagem=mensagem,
                publico=publico,
                prioridade=prioridade,
                fixado=fixado,
                publicado=True,
                data_inicio=date.today() - timedelta(days=2),
                autor_id=admin.id if admin else None,
            )
        )

    if turmas:
        db.session.add(
            Aviso(
                titulo="Passeio pedagogico",
                mensagem="A turma realizara um passeio ao museu na proxima "
                "quinta-feira. A autorizacao assinada deve ser entregue ate "
                "terca-feira na secretaria.",
                publico=PublicoAviso.TURMA,
                turma_id=turmas[0].id,
                prioridade=PrioridadeAviso.ALTA,
                publicado=True,
                data_inicio=date.today() - timedelta(days=1),
                autor_id=admin.id if admin else None,
            )
        )
        db.session.flush()
        return len(modelos) + 1

    db.session.flush()
    return len(modelos)
