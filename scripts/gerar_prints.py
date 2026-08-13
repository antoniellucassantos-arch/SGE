"""Gera capturas de tela das interfaces, para apresentacao.

    python scripts/gerar_prints.py

Como funciona
-------------
O Chrome em modo headless nao consegue fazer login sozinho. Entao o caminho
e outro: a propria aplicacao renderiza cada tela **ja autenticada**, pelo
cliente de teste do Flask, e o HTML resultante e gravado em disco. O Chrome
so fotografa o arquivo.

Efeito colateral util: os HTML ficam salvos junto das imagens. Se algum
detalhe precisar de ajuste na hora da apresentacao, da para abrir o arquivo
no navegador sem subir o servidor.

Os caminhos ``/static/...`` sao reescritos para o disco, senao a pagina
abriria sem folha de estilo — e o print sairia com o HTML cru.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RAIZ = Path(__file__).resolve().parents[1]
DESTINO = RAIZ / "docs" / "apresentacao"
PASTA_HTML = DESTINO / "html"

CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")

SENHA = "1234"
TOKEN = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')

#: Tamanhos capturados.
#:
#: O celular usa 500 px, e nao os 390 do iPhone 14, porque o Chrome no
#: Windows tem largura minima de janela de 500 px: pedindo menos, ele
#: renderiza a 500 e **recorta** a imagem em 390 — o que parece conteudo
#: estourando a tela, quando na verdade e so o print cortado.
#:
#: 500 px continua abaixo do ponto de quebra do sistema (768 px), entao o
#: layout capturado e o de celular: menu em gaveta, cartoes empilhados.
TAMANHOS = {
    "desktop": (1440, 1800),
    "celular": (500, 1400),
}


def _telas(ctx: dict) -> list[tuple[str, str, str, str]]:
    """(perfil, arquivo, titulo, url)."""
    return [
        # -- Administrador ------------------------------------------------
        ("adm", "01-painel", "Painel administrativo", "/"),
        ("adm", "02-alunos", "Lista de alunos", "/alunos/"),
        ("adm", "03-ficha-aluno", "Ficha do aluno",
         f"/alunos/{ctx['aluno_id']}"),
        ("adm", "04-turmas", "Turmas", "/turmas/"),
        ("adm", "05-matriculas", "Matriculas", "/matriculas/"),
        ("adm", "06-relatorios", "Relatorios", "/relatorios/"),
        ("adm", "07-usuarios", "Usuarios e acessos", "/usuarios/"),
        ("adm", "08-auditoria", "Trilha de auditoria", "/auditoria/"),
        ("adm", "09-configuracoes", "Configuracoes", "/configuracoes/"),
        ("adm", "10-backup", "Backup", "/backup/"),
        # -- Professor -----------------------------------------------------
        ("prof", "01-painel", "Painel do professor", "/"),
        ("prof", "02-notas", "Minhas disciplinas", "/notas/"),
        ("prof", "03-lancar-notas", "Lancamento de notas",
         f"/notas/lancar/{ctx['vinculo_id']}"),
        ("prof", "04-diario", "Diario de classe",
         f"/frequencia/diario/{ctx['vinculo_id']}"),
        ("prof", "05-turma", "Turma", f"/turmas/{ctx['turma_id']}"),
        ("prof", "06-boletim-turma", "Boletim da turma",
         f"/boletim/turma/{ctx['turma_id']}"),
        ("prof", "07-horario", "Meu horario", "/horarios/meu-horario"),
        # -- Aluno ---------------------------------------------------------
        ("aluno", "01-painel", "Painel do aluno", "/"),
        ("aluno", "02-boletim", "Meu boletim", "/boletim/meu-boletim"),
        ("aluno", "03-frequencia", "Minha frequencia",
         "/frequencia/minha-frequencia"),
        ("aluno", "04-horario", "Meu horario", "/horarios/meu-horario"),
        ("aluno", "05-avisos", "Avisos", "/avisos/"),
    ]


def _entrar(app, email: str):
    cliente = app.test_client()
    pagina = cliente.get("/auth/login").get_data(as_text=True)
    cliente.post(
        "/auth/login",
        data={
            "email": email,
            "senha": SENHA,
            "csrf_token": TOKEN.search(pagina).group(1),
        },
    )
    return cliente


def _preparar_html(corpo: str) -> str:
    """Aponta os arquivos estaticos para o disco."""
    estaticos = (RAIZ / "app" / "static").as_uri()
    return corpo.replace('="/static/', f'="{estaticos}/')


def _fotografar(arquivo_html: Path, saida: Path, largura: int, altura: int) -> bool:
    saida.parent.mkdir(parents=True, exist_ok=True)
    comando = [
        str(CHROME),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        # Sem isto o Chrome fotografa no instante em que a pagina carrega, e
        # os graficos do Chart.js saem no meio da animacao — a rosca aparece
        # como um pedaco de arco, que num slide parece defeito. O relogio
        # virtual avanca 5 s antes do disparo, entao a animacao termina.
        "--virtual-time-budget=5000",
        f"--window-size={largura},{altura}",
        f"--screenshot={saida}",
        arquivo_html.as_uri(),
    ]
    try:
        subprocess.run(  # noqa: S603 - argumentos controlados
            comando, capture_output=True, check=False, timeout=90
        )
    except (OSError, subprocess.TimeoutExpired) as erro:
        print(f"    falha: {erro}")
        return False
    return saida.exists() and saida.stat().st_size > 1000


def main() -> int:
    if not CHROME.exists():
        print(f"Chrome nao encontrado em {CHROME}")
        return 1

    from app import create_app
    from app.extensions import db
    from app.models.estrutura import Turma
    from app.models.pessoas import Aluno, Professor
    from app.models.usuario import Usuario

    app = create_app("development")

    with app.app_context():
        conta_prof = (
            db.session.query(Usuario)
            .filter(Usuario.email == "prof@gmail.com")
            .first()
        )
        professor = (
            db.session.query(Professor)
            .filter(Professor.usuario_id == conta_prof.id)
            .first()
        )
        vinculo = next(v for v in professor.turmas_disciplinas if v.ativa)
        conta_aluno = (
            db.session.query(Usuario)
            .filter(Usuario.email == "aluno@gmail.com")
            .first()
        )
        aluno = (
            db.session.query(Aluno)
            .filter(Aluno.usuario_id == conta_aluno.id)
            .first()
        )
        turma = db.session.get(Turma, vinculo.turma_id)
        ctx = {
            "aluno_id": aluno.id,
            "vinculo_id": vinculo.id,
            "turma_id": turma.id,
        }

    clientes = {
        "adm": _entrar(app, "adm@gmail.com"),
        "prof": _entrar(app, "prof@gmail.com"),
        "aluno": _entrar(app, "aluno@gmail.com"),
    }

    total = falhas = 0
    indice: list[tuple[str, str, str]] = []

    for perfil, arquivo, titulo, url in _telas(ctx):
        resposta = clientes[perfil].get(url, follow_redirects=True)
        if resposta.status_code != 200:
            print(f"  {perfil}/{arquivo}: HTTP {resposta.status_code} — pulado")
            falhas += 1
            continue

        caminho_html = PASTA_HTML / perfil / f"{arquivo}.html"
        caminho_html.parent.mkdir(parents=True, exist_ok=True)
        caminho_html.write_text(
            _preparar_html(resposta.get_data(as_text=True)), encoding="utf-8"
        )

        for tamanho, (largura, altura) in TAMANHOS.items():
            imagem = DESTINO / tamanho / perfil / f"{arquivo}.png"
            if _fotografar(caminho_html, imagem, largura, altura):
                total += 1
                if tamanho == "desktop":
                    indice.append((perfil, titulo, str(imagem.relative_to(DESTINO))))
            else:
                print(f"  {tamanho}/{perfil}/{arquivo}: nao gerou")
                falhas += 1

        print(f"  ok  {perfil}/{arquivo}  ({titulo})")

    print(f"\n{total} imagens geradas em {DESTINO}")
    if falhas:
        print(f"{falhas} falharam")
    return 0


if __name__ == "__main__":
    sys.exit(main())
