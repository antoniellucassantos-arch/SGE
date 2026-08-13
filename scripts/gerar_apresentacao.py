"""Junta as capturas num unico HTML, pronto para apresentar.

    python scripts/gerar_prints.py        # gera as imagens
    python scripts/gerar_apresentacao.py  # junta tudo num arquivo

Resultado: **um arquivo por perfil**, mais um com tudo junto::

    docs/apresentacao/adm.html         telas do administrador
    docs/apresentacao/professor.html   telas do professor
    docs/apresentacao/aluno.html       telas do aluno
    docs/apresentacao/completo.html    os tres perfis no mesmo arquivo

Cada um e **autocontido**: as imagens vao embutidas em base64, entao o
arquivo funciona sozinho — copiado para um pendrive, aberto em outro
computador, enviado por e-mail. Nao depende do servidor, do banco, do Python
nem da pasta de origem.

Separar por perfil e o que faz sentido na hora de apresentar: fala-se de um
publico por vez, e cada arquivo abre mais leve que o conjunto.

Isso importa no dia: se a maquina da apresentacao nao subir o sistema, este
arquivo ainda mostra tudo.

Navegacao: setas do teclado, ou clique na lista lateral. O botao no topo
alterna entre a captura de computador e a de celular.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RAIZ = Path(__file__).resolve().parents[1]
ORIGEM = RAIZ / "docs" / "apresentacao"
#: (arquivo, titulo, subtitulo, perfis incluidos)
ARQUIVOS = [
    ("adm.html", "Perfil Administrador",
     "Enxerga a escola inteira: cadastros, relatorios, usuarios, auditoria, "
     "configuracoes e backup.", ("adm",)),
    ("professor.html", "Perfil Professor",
     "So as proprias turmas. Diario, chamada, lancamento de notas e boletim "
     "— e nada das turmas dos colegas.", ("prof",)),
    ("aluno.html", "Perfil Aluno",
     "So os proprios dados. Boletim, frequencia, horario e avisos "
     "destinados a ele.", ("aluno",)),
    ("completo.html", "Sistema de Gestao Escolar",
     "Nota, frequencia e ficha de aluno num lugar so — cada pessoa vendo "
     "apenas o que lhe cabe. Funciona no computador, no tablet e no celular, "
     "pelo navegador, sem instalar nada.", ("adm", "prof", "aluno")),
]

PERFIS = {
    "adm": ("Administrador", "Enxerga a escola inteira"),
    "prof": ("Professor", "So as proprias turmas"),
    "aluno": ("Aluno", "So os proprios dados"),
}

#: (perfil, arquivo, titulo, o que mostrar ao falar desta tela)
TELAS: list[tuple[str, str, str, str]] = [
    ("adm", "01-painel", "Painel administrativo",
     "Numeros da escola e graficos do ano letivo. Tudo calculado do banco, "
     "nada digitado a mao."),
    ("adm", "02-alunos", "Lista de alunos",
     "Busca por nome, codigo ou CPF, com filtro por turma e situacao. A "
     "busca usa campo indexado sem acento, entao 'jose' encontra 'Jose'."),
    ("adm", "03-ficha-aluno", "Ficha do aluno",
     "Dados, responsaveis, matriculas e a aba de consentimentos da LGPD. "
     "Documentos e saude so aparecem para quem tem a permissao."),
    ("adm", "04-turmas", "Turmas",
     "Turma e o cruzamento de serie, turno e ano letivo. Cada disciplina "
     "tem um professor titular."),
    ("adm", "05-matriculas", "Matriculas",
     "O vinculo aluno x turma x ano. E aqui que nota e frequencia se "
     "penduram — nunca no aluno direto."),
    ("adm", "06-relatorios", "Relatorios",
     "Alunos, desempenho e frequencia em risco. Exporta em Excel e PDF, e "
     "toda exportacao vai para a auditoria com os filtros usados."),
    ("adm", "07-usuarios", "Usuarios e acessos",
     "Seis perfis, 61 permissoes. Criar conta, redefinir senha, bloquear."),
    ("adm", "08-auditoria", "Trilha de auditoria",
     "Quem fez o que, quando e de qual IP — incluindo quem apenas *leu* "
     "ficha de aluno, que a LGPD exige rastrear."),
    ("adm", "09-configuracoes", "Configuracoes",
     "Dados da escola, ano letivo, bimestres, series, salas e tempos de "
     "aula. As regras de aprovacao ficam no ano letivo, nao no codigo."),
    ("adm", "10-backup", "Backup",
     "Backup do banco com historico e retencao. Registra ate as tentativas "
     "que falharam."),
    ("prof", "01-painel", "Painel do professor",
     "Turmas, chamadas pendentes e notas a lancar. So o que e dele."),
    ("prof", "02-notas", "Minhas disciplinas",
     "A lista ja vem filtrada pelo vinculo: disciplina de outro professor "
     "nao aparece."),
    ("prof", "03-lancar-notas", "Lancamento de notas",
     "Uma aba por avaliacao, uma linha por aluno. Peso e nota maxima "
     "explicados com exemplo numerico na propria tela."),
    ("prof", "04-diario", "Diario de classe",
     "Registro de aula com conteudo, e a chamada dos alunos. Aula geminada "
     "conta como duas para o percentual legal."),
    ("prof", "05-turma", "Turma",
     "A turma pelos olhos do professor: alunos, disciplinas, desempenho."),
    ("prof", "06-boletim-turma", "Boletim da turma",
     "Medias de todos os alunos, com o resultado apurado. Sai em PDF."),
    ("prof", "07-horario", "Meu horario",
     "Grade semanal montada a partir dos tempos de aula da escola."),
    ("aluno", "01-painel", "Painel do aluno",
     "Media geral, frequencia, faltas e as ultimas notas lancadas."),
    ("aluno", "02-boletim", "Meu boletim",
     "Desempenho por disciplina e por bimestre, com media e situacao."),
    ("aluno", "03-frequencia", "Minha frequencia",
     "Presencas e faltas por disciplina, com o percentual e o minimo legal."),
    ("aluno", "04-horario", "Meu horario",
     "A grade da turma em que esta matriculado."),
    ("aluno", "05-avisos", "Avisos",
     "Comunicados da escola. O aluno so ve os destinados a ele."),
]

NUMEROS = [
    ("375", "testes automatizados"),
    ("27", "tabelas no banco"),
    ("139", "rotas"),
    ("61", "permissoes"),
    ("22.500", "linhas de Python"),
    ("79", "telas"),
]

ESTILO = """
:root {
  --fundo: #0d1424;
  --painel: #151d31;
  --borda: #24304a;
  --texto: #e8edf7;
  --suave: #94a3bd;
  --destaque: #4b7bec;
  --verde: #22c55e;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--fundo); color: var(--texto);
  font: 15px/1.6 -apple-system, "Segoe UI", Roboto, sans-serif;
  display: flex; min-height: 100vh;
}
a { color: inherit; }

/* --- Lista lateral --- */
aside {
  width: 290px; flex-shrink: 0; background: var(--painel);
  border-right: 1px solid var(--borda); height: 100vh;
  overflow-y: auto; position: sticky; top: 0;
}
.marca { padding: 22px 20px; border-bottom: 1px solid var(--borda); }
.marca h1 { font-size: 19px; letter-spacing: -.3px; }
.marca p { color: var(--suave); font-size: 12.5px; margin-top: 3px; }
.grupo { padding: 16px 20px 6px; color: var(--suave);
  font-size: 11px; letter-spacing: .09em; text-transform: uppercase; }
.grupo span { display: block; text-transform: none; letter-spacing: 0;
  font-size: 11.5px; opacity: .65; margin-top: 2px; }
.item {
  display: block; width: 100%; text-align: left; background: none;
  border: 0; color: var(--texto); padding: 9px 20px 9px 34px;
  font-size: 13.5px; cursor: pointer; border-left: 3px solid transparent;
  font-family: inherit;
}
.item:hover { background: #1c2740; }
.item.ativo { background: #1c2740; border-left-color: var(--destaque);
  color: #fff; font-weight: 600; }

/* --- Area principal --- */
main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.topo {
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  padding: 18px 28px; border-bottom: 1px solid var(--borda);
  position: sticky; top: 0; background: var(--fundo); z-index: 5;
}
.topo h2 { font-size: 18px; }
.etiqueta {
  font-size: 11px; padding: 3px 9px; border-radius: 999px;
  background: #1c2740; color: var(--suave); border: 1px solid var(--borda);
}
/* Na capa o contador fica vazio; sem isto sobra uma pilula em branco. */
.etiqueta:empty { display: none; }
.espaco { flex: 1; }
.botao {
  background: #1c2740; color: var(--texto); border: 1px solid var(--borda);
  padding: 7px 14px; border-radius: 8px; cursor: pointer;
  font-size: 13px; font-family: inherit;
}
.botao:hover { border-color: var(--destaque); }
.botao.ligado { background: var(--destaque); border-color: var(--destaque);
  color: #fff; }

.conteudo { padding: 26px 28px 60px; }
.explicacao {
  color: var(--suave); max-width: 760px; margin-bottom: 20px;
  font-size: 14.5px;
}
.moldura {
  border: 1px solid var(--borda); border-radius: 12px; overflow: hidden;
  background: #fff; box-shadow: 0 18px 50px rgba(0,0,0,.45);
  max-width: 100%; width: fit-content;
}
.moldura img { display: block; max-width: 100%; height: auto; }
.moldura.celular { max-width: 420px; }

/* --- Capa --- */
.capa { padding: 70px 28px; max-width: 900px; }
.capa h2 { font-size: 40px; letter-spacing: -1px; line-height: 1.15; }
.capa .sub { color: var(--suave); font-size: 17px; margin: 14px 0 34px; }
/* Tres colunas fixas: seis cartoes viram 3+3. Com `auto-fit` sobrava um
   cartao sozinho na segunda linha, o que parece descuido num slide. */
.numeros { display: grid; gap: 14px;
  grid-template-columns: repeat(2, minmax(0, 1fr)); }
@media (min-width: 720px) {
  .numeros { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
.numero { background: var(--painel); border: 1px solid var(--borda);
  border-radius: 12px; padding: 18px; }
.numero b { display: block; font-size: 27px; letter-spacing: -.5px; }
.numero span { color: var(--suave); font-size: 12.5px; }
.pilha { margin-top: 34px; display: flex; flex-wrap: wrap; gap: 8px; }
.pilha span { background: var(--painel); border: 1px solid var(--borda);
  border-radius: 999px; padding: 6px 14px; font-size: 13px; }
.dica { margin-top: 40px; color: var(--suave); font-size: 13.5px;
  border-left: 3px solid var(--verde); padding-left: 14px; }

@media (max-width: 900px) {
  body { flex-direction: column; }
  aside { width: 100%; height: auto; position: static; }
}
"""

SCRIPT = """
const TELAS = __DADOS__;
let atual = -1;      // -1 = capa
let modo = 'desktop';

const conteudo = document.getElementById('conteudo');
const titulo = document.getElementById('titulo');
const etiqueta = document.getElementById('etiqueta');
const contador = document.getElementById('contador');

function desenhar() {
  // Compara com o indice declarado no proprio botao. Usar a posicao do
  // elemento na lista quebrou uma vez: o botao "Visao geral" tambem tem a
  // classe `item`, entao tudo andava uma casa — clicava em "Ficha do aluno"
  // e abria "Turmas".
  document.querySelectorAll('[data-indice]').forEach((b) => {
    b.classList.toggle('ativo', Number(b.dataset.indice) === atual);
  });

  if (atual < 0) {
    titulo.textContent = 'Visao geral';
    etiqueta.textContent = 'inicio';
    contador.textContent = '';
    conteudo.innerHTML = document.getElementById('modelo-capa').innerHTML;
    return;
  }

  const tela = TELAS[atual];
  titulo.textContent = tela.titulo;
  etiqueta.textContent = tela.perfil;
  contador.textContent = (atual + 1) + ' de ' + TELAS.length;
  conteudo.innerHTML =
    '<p class="explicacao">' + tela.texto + '</p>' +
    '<div class="moldura ' + (modo === 'celular' ? 'celular' : '') + '">' +
    '<img alt="' + tela.titulo + '" src="' + tela[modo] + '">' +
    '</div>';
  window.scrollTo(0, 0);
}

function ir(indice) {
  atual = Math.max(-1, Math.min(TELAS.length - 1, indice));
  desenhar();
}

document.querySelectorAll('[data-indice]').forEach((botao) => {
  botao.addEventListener('click', () => ir(Number(botao.dataset.indice)));
});
document.getElementById('capa').addEventListener('click', () => ir(-1));

document.querySelectorAll('[data-modo]').forEach((botao) => {
  botao.addEventListener('click', () => {
    modo = botao.dataset.modo;
    document.querySelectorAll('[data-modo]').forEach((b) => {
      b.classList.toggle('ligado', b.dataset.modo === modo);
    });
    desenhar();
  });
});

document.addEventListener('keydown', (evento) => {
  if (evento.key === 'ArrowRight' || evento.key === 'PageDown') ir(atual + 1);
  if (evento.key === 'ArrowLeft' || evento.key === 'PageUp') ir(atual - 1);
  if (evento.key === 'Home') ir(-1);
});

desenhar();
"""


def _embutir(caminho: Path) -> str:
    """Imagem como data URI, para o arquivo nao depender de pasta nenhuma."""
    if not caminho.exists():
        return ""
    dados = base64.b64encode(caminho.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{dados}"


def _montar(titulo_pagina: str, subtitulo: str, perfis: tuple[str, ...]) -> str:
    """Monta um arquivo HTML com as telas dos perfis pedidos."""
    dados = []
    for perfil, arquivo, titulo, texto in TELAS:
        if perfil not in perfis:
            continue
        desktop = _embutir(ORIGEM / "desktop" / perfil / f"{arquivo}.png")
        celular = _embutir(ORIGEM / "celular" / perfil / f"{arquivo}.png")
        if not desktop:
            print(f"    faltando: desktop/{perfil}/{arquivo}.png")
            continue
        dados.append(
            {
                "perfil": PERFIS[perfil][0],
                "titulo": titulo,
                "texto": texto,
                "desktop": desktop,
                "celular": celular or desktop,
            }
        )

    # A lista lateral so ganha cabecalho de grupo quando ha mais de um
    # perfil no arquivo — num arquivo de perfil unico o cabecalho seria
    # repeticao do titulo da pagina.
    lateral = []
    indice = 0
    for chave in perfis:
        if len(perfis) > 1:
            nome, resumo = PERFIS[chave]
            lateral.append(
                f'<div class="grupo">{nome}<span>{resumo}</span></div>'
            )
        for perfil, _, titulo, _ in TELAS:
            if perfil == chave:
                lateral.append(
                    f'<button class="item" data-indice="{indice}">'
                    f"{titulo}</button>"
                )
                indice += 1

    numeros = "".join(
        f'<div class="numero"><b>{valor}</b><span>{rotulo}</span></div>'
        for valor, rotulo in NUMEROS
    )
    pilha = "".join(
        f"<span>{item}</span>"
        for item in (
            "Python 3.12", "Flask 3", "SQLAlchemy 2", "PostgreSQL", "SQLite",
            "Bootstrap 5", "Jinja2", "JavaScript ES6", "Chart.js",
            "ReportLab", "Argon2id",
        )
    )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SGE — {titulo_pagina}</title>
<style>{ESTILO}</style>
</head>
<body>

<aside>
  <div class="marca">
    <h1>SGE</h1>
    <p>{titulo_pagina}</p>
  </div>
  <div class="grupo"><button class="item" id="capa"
       style="padding-left:20px">Visao geral</button></div>
  {"".join(lateral)}
</aside>

<main>
  <div class="topo">
    <h2 id="titulo">Visao geral</h2>
    <span class="etiqueta" id="etiqueta">inicio</span>
    <span class="espaco"></span>
    <span class="etiqueta" id="contador"></span>
    <button class="botao ligado" data-modo="desktop">Computador</button>
    <button class="botao" data-modo="celular">Celular</button>
  </div>
  <div class="conteudo" id="conteudo"></div>
</main>

<template id="modelo-capa">
  <div class="capa">
    <h2>{titulo_pagina}</h2>
    <p class="sub">{subtitulo}</p>
    <div class="numeros">{numeros}</div>
    <div class="pilha">{pilha}</div>
    <p class="dica">
      Use as setas do teclado para navegar. O botao <b>Celular</b> mostra a
      mesma tela na largura de um telefone.
    </p>
  </div>
</template>

<script>{SCRIPT.replace("__DADOS__", json.dumps(dados, ensure_ascii=False))}</script>
</body>
</html>
""", len(dados)


def main() -> int:
    if not (ORIGEM / "desktop").exists():
        print("Capturas nao encontradas. Rode antes:")
        print("    python scripts/gerar_prints.py")
        return 1

    for arquivo, titulo, subtitulo, perfis in ARQUIVOS:
        html, telas = _montar(titulo, subtitulo, perfis)
        destino = ORIGEM / arquivo
        destino.write_text(html, encoding="utf-8")
        tamanho = destino.stat().st_size / (1024 * 1024)
        print(f"  {arquivo:18} {telas:>2} telas  {tamanho:>4.1f} MB")

    print(f"\nArquivos autocontidos em {ORIGEM}")
    print("Abrem em qualquer computador, sem servidor e sem Python.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
