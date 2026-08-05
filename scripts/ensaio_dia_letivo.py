"""Percorre um ciclo escolar completo pela camada HTTP, como um usuario.

    python scripts/ensaio_dia_letivo.py

Por que existe, se ja ha 369 testes
-----------------------------------
Os testes verificam regras isoladas: este service calcula certo, aquela rota
nega o acesso. Nenhum deles percorre a **sequencia** que a escola percorre —
cadastrar, matricular, avaliar, lancar, fechar, emitir — e e na emenda entre
duas etapas que as coisas quebram.

O bug do campo de peso (setinha parando em 10,1) e o exemplo: passou por
todos os testes, porque nenhum teste clica numa setinha. Este ensaio nao
pega esse tipo de coisa, mas pega o irmao dele: o PDF que so falha quando ha
cinco periodos, a consolidacao que quebra com aluno sem nota, o relatorio que
estoura quando a turma esta vazia.

Isolamento
----------
Roda em banco proprio, em memoria, populado pelo seed de demonstracao. Nao
toca no banco de desenvolvimento — voce pode roda-lo enquanto usa o sistema.

Saida
-----
Uma linha por etapa. `ok` seguiu adiante; `FALHOU` interrompeu o ciclo ali,
com o motivo. No fim, um resumo do que passou e do que nao.
"""

from __future__ import annotations

import re
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.enums import PapelUsuario  # noqa: E402
from app.models.estrutura import (  # noqa: E402
    AnoLetivo,
    PeriodoLetivo,
    Serie,
    Turma,
    TurmaDisciplina,
)
from app.models.matricula import Matricula  # noqa: E402
from app.models.pessoas import Aluno, Professor, Responsavel  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402

SENHA = "Escola@2026"
TOKEN = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')

#: Etapas registradas, na ordem em que a escola as executa.
etapas: list[tuple[str, str, str]] = []


def registrar(etapa: str, ok: bool, detalhe: str = "") -> bool:
    etapas.append((etapa, "ok" if ok else "FALHOU", detalhe))
    marca = "  ok  " if ok else "FALHOU"
    print(f"{marca} {etapa}" + (f"  -- {detalhe}" if detalhe else ""))
    return ok


class Navegador:
    """Cliente HTTP que se comporta como um navegador: sessao e CSRF."""

    def __init__(self, app, email: str) -> None:
        self.app = app
        self.cliente = app.test_client()
        pagina = self.cliente.get("/auth/login").get_data(as_text=True)
        self.cliente.post(
            "/auth/login",
            data={
                "email": email,
                "senha": SENHA,
                "csrf_token": TOKEN.search(pagina).group(1),
            },
        )

    def _token(self, url: str) -> str:
        """Pega um token valido da propria tela que sera submetida."""
        pagina = self.cliente.get(url).get_data(as_text=True)
        achado = TOKEN.search(pagina)
        return achado.group(1) if achado else ""

    def abrir(self, url: str):
        """Segue redirecionamento, como o navegador faz.

        Varias telas do aluno sao atalhos legitimos — `/boletim/meu-boletim`
        leva a `/boletim/aluno/<id>`. Parar no 302 acusaria falha onde nao
        ha. O que importa e onde a navegacao **termina**: se for a tela de
        login, ai sim houve recusa.
        """
        resposta = self.cliente.get(url, follow_redirects=True)
        resposta.caiu_no_login = "/auth/login" in resposta.request.path
        return resposta

    def enviar(self, url: str, dados: dict, tela: str | None = None):
        dados = dict(dados)
        dados.setdefault("csrf_token", self._token(tela or url))
        return self.cliente.post(url, data=dados, follow_redirects=True)


def _preparar(app) -> dict:
    """Popula o banco e devolve os identificadores usados no ciclo."""
    from scripts.seed_dados import popular

    db.create_all()

    # A estrutura inicial vem do proprio comando que a escola roda no
    # primeiro dia — ano letivo, bimestres, series e tempos de aula. Usar o
    # comando de verdade, em vez de montar tudo a mao aqui, poe `flask
    # criar-estrutura-inicial` dentro do ensaio: se ele quebrar, o ensaio
    # acusa antes da escola descobrir.
    resultado = app.test_cli_runner().invoke(args=["criar-estrutura-inicial"])
    if resultado.exit_code != 0:
        raise RuntimeError(
            f"criar-estrutura-inicial falhou: {resultado.output}"
        )

    popular(quantidade_alunos=12)

    ano = db.session.query(AnoLetivo).filter(AnoLetivo.corrente.is_(True)).first()
    turma = db.session.query(Turma).filter(Turma.ativa.is_(True)).first()
    vinculo = (
        db.session.query(TurmaDisciplina)
        .filter(TurmaDisciplina.turma_id == turma.id)
        .first()
    )
    periodo = (
        db.session.query(PeriodoLetivo)
        .filter(PeriodoLetivo.ano_letivo_id == ano.id)
        .order_by(PeriodoLetivo.ordem)
        .first()
    )

    contas = {}
    for papel, email in (
        (PapelUsuario.ADMINISTRADOR, "adm@escola.com.br"),
        (PapelUsuario.PROFESSOR, "prof@escola.com.br"),
        (PapelUsuario.ALUNO, "aluno@escola.com.br"),
    ):
        usuario = Usuario(nome_completo=f"{papel.rotulo} do Ensaio", email=email)
        usuario.papel = papel
        usuario.ativo = True
        usuario.definir_senha(SENHA, exigir_troca=False)
        db.session.add(usuario)
        db.session.flush()
        contas[papel] = usuario

    # Professor titular do vinculo escolhido.
    professor = db.session.get(Professor, vinculo.professor_id)
    professor.usuario_id = contas[PapelUsuario.PROFESSOR].id

    # Aluno com matricula ativa na turma.
    matricula = (
        db.session.query(Matricula)
        .filter(Matricula.turma_id == turma.id)
        .order_by(Matricula.id)
        .first()
    )
    matricula.aluno.usuario_id = contas[PapelUsuario.ALUNO].id

    responsavel = db.session.query(Responsavel).first()
    serie = db.session.get(Serie, turma.serie_id)
    db.session.commit()

    return {
        "ano_id": ano.id,
        "turma_id": turma.id,
        "vinculo_id": vinculo.id,
        "periodo_id": periodo.id,
        "matricula_id": matricula.id,
        "aluno_existente_id": matricula.aluno_id,
        "responsavel_id": responsavel.id if responsavel else None,
        "serie_id": serie.id,
        "emails": {p: u.email for p, u in contas.items()},
    }


def _ciclo(app, ctx: dict) -> None:
    secretaria = Navegador(app, ctx["emails"][PapelUsuario.ADMINISTRADOR])
    professor = Navegador(app, ctx["emails"][PapelUsuario.PROFESSOR])
    aluno = Navegador(app, ctx["emails"][PapelUsuario.ALUNO])

    print("\n--- Secretaria: matricula um aluno novo ---")

    resposta = secretaria.enviar(
        "/alunos/novo",
        {
            "nome_completo": "Maria Aparecida do Ensaio",
            "data_nascimento": "2012-04-15",
            "sexo": "feminino",
            "nacionalidade": "Brasileira",
            "situacao": "ativo",
        },
    )
    with app.app_context():
        novo = (
            db.session.query(Aluno)
            .filter(Aluno.nome_completo == "Maria Aparecida do Ensaio")
            .first()
        )
    if not registrar(
        "cadastrar aluno",
        novo is not None,
        "" if novo else f"HTTP {resposta.status_code}, aluno nao apareceu no banco",
    ):
        return

    if ctx["responsavel_id"]:
        secretaria.enviar(
            f"/alunos/{novo.id}/responsaveis/vincular",
            {
                "responsavel_id": str(ctx["responsavel_id"]),
                "parentesco": "mae",
                "responsavel_legal": "y",
                "ordem_contato": "1",
            },
            tela=f"/alunos/{novo.id}",
        )
        with app.app_context():
            vinculado = db.session.get(Aluno, novo.id)
            total = len(vinculado.vinculos_responsaveis)
        registrar("vincular responsavel", total >= 1, f"{total} vinculo(s)")

    secretaria.enviar(
        "/matriculas/nova",
        {
            "aluno_id": str(novo.id),
            "turma_id": str(ctx["turma_id"]),
            "ano_letivo_id": str(ctx["ano_id"]),
            "data_matricula": date.today().isoformat(),
        },
    )
    with app.app_context():
        matricula_nova = (
            db.session.query(Matricula)
            .filter(Matricula.aluno_id == novo.id)
            .first()
        )
    if not registrar(
        "matricular na turma",
        matricula_nova is not None,
        "" if matricula_nova else "matricula nao foi criada",
    ):
        return

    print("\n--- Professor: avalia e lanca ---")

    professor.enviar(
        f"/notas/vinculo/{ctx['vinculo_id']}/avaliacoes/nova",
        {
            "nome": "Prova do Ensaio",
            "periodo_id": str(ctx["periodo_id"]),
            "tipo": "prova",
            "valor_maximo": "10",
            "peso": "2",
            "data_aplicacao": date.today().isoformat(),
        },
        tela=f"/notas/lancar/{ctx['vinculo_id']}",
    )
    with app.app_context():
        from app.models.avaliacao import Avaliacao

        avaliacao = (
            db.session.query(Avaliacao)
            .filter(Avaliacao.nome == "Prova do Ensaio")
            .first()
        )
        avaliacao_id = avaliacao.id if avaliacao else None
        matriculas_turma = [
            m.id
            for m in db.session.query(Matricula)
            .filter(Matricula.turma_id == ctx["turma_id"])
            .all()
        ]
    if not registrar(
        "criar avaliacao",
        avaliacao_id is not None,
        "" if avaliacao_id else "avaliacao nao foi criada",
    ):
        return

    notas = {f"nota_{mid}": "7.5" for mid in matriculas_turma}
    professor.enviar(
        f"/notas/avaliacao/{avaliacao_id}/notas",
        notas,
        tela=f"/notas/lancar/{ctx['vinculo_id']}",
    )
    with app.app_context():
        from app.models.avaliacao import Nota

        lancadas = (
            db.session.query(Nota)
            .filter(Nota.avaliacao_id == avaliacao_id, Nota.valor.isnot(None))
            .count()
        )
    registrar(
        "lancar notas da turma",
        lancadas > 0,
        f"{lancadas} de {len(matriculas_turma)} alunos",
    )

    # A rota e um alternador: sem `publicar=1` ela **oculta** as notas.
    professor.enviar(
        f"/notas/avaliacao/{avaliacao_id}/publicar",
        {"publicar": "1"},
        tela=f"/notas/lancar/{ctx['vinculo_id']}",
    )
    with app.app_context():
        from app.models.avaliacao import Avaliacao

        publicada = db.session.get(Avaliacao, avaliacao_id).publicada
    registrar("publicar notas", bool(publicada))

    print("\n--- Professor: diario e chamada ---")

    professor.enviar(
        f"/frequencia/diario/{ctx['vinculo_id']}",
        {
            "data_aula": (date.today() - timedelta(days=1)).isoformat(),
            "quantidade_aulas": "2",
            "conteudo": "Aula do ensaio",
        },
    )
    with app.app_context():
        from app.models.frequencia import Aula

        aula = (
            db.session.query(Aula)
            .filter(Aula.conteudo == "Aula do ensaio")
            .first()
        )
        aula_id = aula.id if aula else None
    if not registrar(
        "registrar aula no diario",
        aula_id is not None,
        "" if aula_id else "aula nao foi criada",
    ):
        return

    chamada = {f"situacao_{mid}": "presente" for mid in matriculas_turma}
    if matriculas_turma:
        chamada[f"situacao_{matriculas_turma[0]}"] = "falta"
    professor.enviar(f"/frequencia/chamada/{aula_id}", chamada)
    with app.app_context():
        from app.models.frequencia import Frequencia

        registros = (
            db.session.query(Frequencia).filter(Frequencia.aula_id == aula_id).count()
        )
    registrar("fazer a chamada", registros > 0, f"{registros} registros")

    print("\n--- Fechamento e boletim ---")

    secretaria.enviar(
        f"/notas/turma/{ctx['turma_id']}/consolidar",
        {},
        tela=f"/notas/lancar/{ctx['vinculo_id']}",
    )
    with app.app_context():
        from app.models.avaliacao import ResultadoDisciplina

        consolidados = (
            db.session.query(ResultadoDisciplina)
            .filter(ResultadoDisciplina.turma_disciplina_id == ctx["vinculo_id"])
            .count()
        )
    registrar("consolidar a turma", consolidados > 0, f"{consolidados} resultados")

    for rotulo, url in (
        ("boletim do aluno (tela)", f"/boletim/aluno/{ctx['aluno_existente_id']}"),
        ("boletim do aluno (PDF)", f"/boletim/aluno/{ctx['aluno_existente_id']}/pdf"),
        ("boletim da turma (tela)", f"/boletim/turma/{ctx['turma_id']}"),
        ("boletim da turma (PDF)", f"/boletim/turma/{ctx['turma_id']}/pdf"),
    ):
        resposta = secretaria.abrir(url)
        tamanho = len(resposta.get_data())
        registrar(
            rotulo,
            resposta.status_code == 200
            and tamanho > 500
            and not resposta.caiu_no_login,
            f"HTTP {resposta.status_code}, {tamanho} bytes"
            + (" — caiu no login" if resposta.caiu_no_login else ""),
        )

    print("\n--- Relatorios e exportacao ---")

    for chave in ("alunos", "desempenho", "frequencia"):
        resposta = secretaria.abrir(f"/relatorios/{chave}")
        registrar(
            f"relatorio {chave} (tela)",
            resposta.status_code == 200 and not resposta.caiu_no_login,
            f"HTTP {resposta.status_code}"
            + (" — caiu no login" if resposta.caiu_no_login else ""),
        )
        for formato in ("excel", "pdf"):
            resposta = secretaria.abrir(f"/relatorios/{chave}/{formato}")
            tamanho = len(resposta.get_data())
            registrar(
                f"relatorio {chave} ({formato})",
                resposta.status_code == 200 and tamanho > 500,
                f"HTTP {resposta.status_code}, {tamanho} bytes",
            )

    print("\n--- Aluno: ve o proprio desempenho ---")

    for rotulo, url in (
        ("painel do aluno", "/"),
        ("meu boletim", "/boletim/meu-boletim"),
        ("minha frequencia", "/frequencia/minha-frequencia"),
        ("meu horario", "/horarios/meu-horario"),
        ("avisos", "/avisos/"),
    ):
        resposta = aluno.abrir(url)
        registrar(
            f"aluno: {rotulo}",
            resposta.status_code == 200 and not resposta.caiu_no_login,
            f"HTTP {resposta.status_code}"
            + (" — caiu no login" if resposta.caiu_no_login else ""),
        )

    print("\n--- Direcao: encerra o periodo ---")

    secretaria.enviar(
        f"/configuracoes/periodos/{ctx['periodo_id']}/alternar",
        {},
        tela="/configuracoes/anos-letivos",
    )
    with app.app_context():
        encerrado = db.session.get(PeriodoLetivo, ctx["periodo_id"]).encerrado
    registrar("encerrar o periodo", bool(encerrado))

    resposta = professor.enviar(
        f"/notas/avaliacao/{avaliacao_id}/notas",
        {f"nota_{matriculas_turma[0]}": "10"},
        tela=f"/notas/lancar/{ctx['vinculo_id']}",
    )
    with app.app_context():
        from app.models.avaliacao import Nota

        nota = (
            db.session.query(Nota)
            .filter(
                Nota.avaliacao_id == avaliacao_id,
                Nota.matricula_id == matriculas_turma[0],
            )
            .first()
        )
        travou = nota.valor != 10
    registrar(
        "periodo encerrado bloqueia lancamento",
        travou,
        "nota nao foi alterada" if travou else "ALTEROU a nota com periodo fechado",
    )

    secretaria.enviar(
        f"/configuracoes/periodos/{ctx['periodo_id']}/alternar",
        {},
        tela="/configuracoes/anos-letivos",
    )


def main() -> int:
    app = create_app("testing")
    # A suite desliga o CSRF; aqui ele fica ligado de proposito, para o
    # ensaio exercitar o mesmo caminho que o navegador percorre.
    app.config["WTF_CSRF_ENABLED"] = True
    app.config["SERVER_NAME"] = None

    print("Ensaio de um dia letivo — banco proprio, em memoria.\n")

    with app.app_context():
        contexto = _preparar(app)

    try:
        _ciclo(app, contexto)
    except Exception:  # noqa: BLE001 - o ensaio relata, nao propaga
        print("\nO ciclo foi interrompido por uma excecao:\n")
        traceback.print_exc()
        etapas.append(("excecao nao tratada", "FALHOU", ""))

    falhas = [(e, d) for e, s, d in etapas if s == "FALHOU"]
    print("\n" + "=" * 62)
    print(f"{len(etapas) - len(falhas)} de {len(etapas)} etapas passaram.")
    if falhas:
        print("\nO que quebrou:")
        for etapa, detalhe in falhas:
            print(f"  - {etapa}" + (f": {detalhe}" if detalhe else ""))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
