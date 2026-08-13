# SGE — Sistema de Gestão Escolar
### Resumo para apresentação

---

## 1. O que é

Sistema web de gestão escolar. Substitui as planilhas e os cadernos de papel
que hoje guardam **nota, frequência e ficha de aluno** — e os substitui de
um jeito que a escola inteira usa ao mesmo tempo, cada pessoa vendo só o que
lhe cabe.

Roda no navegador. Funciona em **computador, tablet, Android e iPhone** sem
instalar nada: o professor faz a chamada pelo celular na sala, a secretária
matricula pelo PC, o aluno vê a nota pelo telefone em casa.

### O problema concreto

| Antes | Com o sistema |
|---|---|
| Nota em planilha, uma por professor | Um lugar só, com histórico por ano letivo |
| Boletim digitado à mão a cada bimestre | Gerado em PDF, com média e frequência já calculadas |
| Ficha do aluno em pasta de papel | Cadastro digital, com quem pode ver cada campo |
| "Quem mudou essa nota?" sem resposta | Trilha de auditoria com autor, data e valor anterior |
| Backup = copiar a pasta na mão | Comando único, com histórico e retenção |

---

## 2. Tecnologias

### Linguagens

| Linguagem | Onde | Volume |
|---|---|---|
| **Python 3.12** | Toda a lógica do servidor | 22.500 linhas |
| **HTML5** (Jinja2) | 79 telas | 10.120 linhas |
| **CSS3** | Design próprio | 1.056 linhas |
| **JavaScript ES6** | Interações no navegador | 938 linhas |
| **SQL** | Via ORM e migrações | 1.479 linhas |

### Bibliotecas principais

| Camada | Tecnologia | Por que esta |
|---|---|---|
| Framework web | **Flask 3.0** | Leve e explícito — nada acontece "por mágica", o que importa num sistema que guarda dado de menor de idade |
| Banco / ORM | **SQLAlchemy 2.0** | Escreve-se Python, não SQL colado em string; elimina injeção de SQL por construção |
| Migrações | **Flask-Migrate / Alembic** | O banco evolui sem perder dado; toda mudança é versionada e reversível |
| Autenticação | **Flask-Login + Argon2id** | Argon2 venceu a competição de hash de senhas de 2015; é o padrão atual |
| Formulários | **Flask-WTF** | Validação e proteção CSRF em todo formulário |
| Interface | **Bootstrap 5** | Base responsiva madura — o mesmo HTML serve PC e celular |
| Gráficos | **Chart.js** | Painéis do dashboard |
| PDF | **ReportLab** | Python puro: instala no Windows sem dependência externa |
| Planilhas | **openpyxl** | Exportação em Excel |
| Imagens | **Pillow** | Redimensiona foto e **remove o EXIF** — que carrega a localização de onde a foto foi tirada |

---

## 3. Banco de dados

**SQLite** em desenvolvimento, **PostgreSQL** em produção. O mesmo código
serve os dois: quem conversa com o banco é o SQLAlchemy.

**27 tabelas**, organizadas em cinco grupos:

| Grupo | Tabelas |
|---|---|
| Identidade | `usuarios` |
| Estrutura acadêmica | `anos_letivos`, `periodos_letivos`, `series`, `turmas`, `disciplinas`, `turmas_disciplinas`, `salas` |
| Pessoas | `alunos`, `professores`, `funcionarios`, `responsaveis`, `alunos_responsaveis` |
| Vida escolar | `matriculas`, `aulas`, `frequencias`, `avaliacoes`, `notas`, `resultados_disciplinas` |
| Grade e comunicação | `tempos_aula`, `horarios`, `avisos`, `avisos_leituras` |
| Sistema | `configuracoes_escola`, `logs_auditoria`, `registros_backup`, `consentimentos_lgpd` |

### Três decisões de modelagem que valem citar

**Nota e frequência penduram na `matricula`, nunca no `aluno`.**
A matrícula é o vínculo *aluno × turma × ano letivo*. Isso mantém cada ano
isolado: um aluno reprovado que refaz a série tem duas matrículas, dois
conjuntos de notas, e o histórico continua correto. Pendurar no aluno
misturaria os anos — e essa é a fonte clássica de histórico escolar errado.

**Exclusão é lógica, não física.**
Excluir um aluno marca a data de exclusão; o registro continua no banco. O
histórico escolar de quem passou pela escola não pode sumir porque alguém
clicou no botão errado.

**Cada ano letivo guarda as próprias regras.**
Média de aprovação, média de recuperação e frequência mínima ficam no ano
letivo, não fixas no código. Se a escola mudar a regra em 2027, o histórico
de 2026 continua tendo sido apurado pela regra de 2026.

---

## 4. Arquitetura

```
Navegador
    ↓
blueprints/   Traduz HTTP. Valida formulário, delega, responde.
    ↓
services/     Regra de negócio. Conhece o banco.
    ↓
models/       Estrutura do dado.
```

**Por que separar assim:** a camada `services/` não conhece HTTP. O mesmo
código que a tela usa serve a **API JSON**, a **linha de comando** e os
**testes** — e serviria um aplicativo Android amanhã, sem reescrever regra
nenhuma.

**20 módulos**, **139 rotas**. Cada módulo é uma pasta com o mesmo formato,
então quem aprende um aprende todos.

---

## 5. Segurança

Este é o ponto que diferencia o sistema de um trabalho de faculdade. Ele
guarda **CPF, RG, endereço, foto e ficha de saúde de crianças**.

### Autorização em duas camadas

1. **O papel pode fazer esta ação?** — 61 permissões, 6 perfis
2. **Pode fazer sobre *este* registro?** — o professor lança nota, mas só
   nas turmas em que leciona; o responsável vê boletim, mas só do filho

Checar só a primeira é a falha mais comum em sistema web (OWASP A01): basta
trocar o número na barra de endereços para ler o dado de outra pessoa. **Há
um teste automático que percorre as 139 rotas** e exige a segunda camada em
toda rota que recebe um identificador.

### Demais defesas

| Ameaça | Defesa |
|---|---|
| Senha vazada | Argon2id, o padrão atual de hash |
| Força bruta | Limite de tentativas por minuto, com teste automatizado |
| Injeção de SQL | ORM — nenhuma consulta é montada com texto |
| XSS | Escape automático do Jinja2 + CSP sem script inline |
| CSRF | Token em todo formulário |
| Foto de aluno acessível por URL | Uploads fora de `static/`, saem só por rota autenticada, nome em UUID |
| Alteração de nota sem rastro | Auditoria com autor, data, IP e valor anterior |
| Nota mudada depois do boletim | Período encerrado bloqueia lançamento |

### LGPD

- Dados de saúde e documentos filtrados **no servidor**, não escondidos na
  tela — quem não pode ver não recebe o dado
- **Registro de quem *leu*** ficha de aluno, não só de quem alterou
- **Consentimento por finalidade**, com base legal, quem autorizou, quando e
  a revogação — guardado como histórico, porque a lei põe sobre a escola o
  ônus de provar que o consentimento existiu
- EXIF removido das fotos (elimina a geolocalização)

---

## 6. Qualidade

| Indicador | Número |
|---|---|
| Testes automatizados | **375**, todos passando |
| Linhas de teste | 5.152 |
| Cobertura prioritária | Permissões 99%, segurança 95%, autenticação 90% |
| Auditoria de código | 6 fases, 27 correções |
| Integração contínua | Roda em SQLite **e** PostgreSQL a cada envio |

Além dos testes unitários, existe um **ensaio de dia letivo**: um roteiro
que percorre as 29 etapas do ciclo escolar — matricular, avaliar, lançar,
fazer chamada, consolidar, emitir boletim, exportar, encerrar período. Ele
achou dois defeitos que os 369 testes não pegavam.

---

## 7. Perfis de acesso

| Perfil | Enxerga |
|---|---|
| **Administrador** | Tudo: cadastros, usuários, configurações, backup, auditoria |
| **Direção** | Gestão pedagógica, relatórios, correção de nota, redefinição de senha |
| **Secretaria** | Cadastros, matrículas, documentos — **não lança nota** (é ato pedagógico) |
| **Professor** | Diário, chamada e notas **das próprias turmas** |
| **Aluno** | Boletim, frequência e horário **próprios** |
| **Responsável** | O mesmo, dos dependentes |

---

## 8. Roteiro de demonstração

Servidor:

```bash
python run.py
```

Depois abra `http://localhost:5000`. Senha das três contas: **1234**

| Passo | Conta | O que mostrar |
|---|---|---|
| 1 | `adm@gmail.com` | Painel com os indicadores e gráficos |
| 2 | `adm@gmail.com` | Ficha de um aluno — aba **Consentimentos** (LGPD) |
| 3 | `prof@gmail.com` | Lançamento de notas — criar avaliação, explicar peso |
| 4 | `prof@gmail.com` | Diário de classe e chamada |
| 5 | `prof@gmail.com` | Tentar abrir uma turma que não é dele → **403** |
| 6 | `aluno@gmail.com` | Boletim e frequência do próprio aluno |
| 7 | `adm@gmail.com` | Auditoria — mostrar o registro do que o professor acabou de fazer |

**O passo 5 é o mais forte da demonstração.** Mostra que a segurança não é
enfeite: o sistema recusa, e o recusado vai para a trilha de auditoria.

Se houver projetor com celular, abra pelo telefone na mesma rede — a mesma
tela se reorganiza sozinha.

---

## 9. Perguntas prováveis

**"Por que Flask e não Django?"**
Django traz painel administrativo e ORM prontos, mas as regras dele são
implícitas. Num sistema que guarda dado de menor, é melhor que cada decisão
de autorização esteja escrita e visível. Flask obriga a isso.

**"Por que SQLite se PostgreSQL é melhor?"**
SQLite é o banco de desenvolvimento; produção é PostgreSQL. O mesmo código
serve os dois, e a integração contínua roda os testes nos dois justamente
para garantir que não divergem.

**"Aguenta quantos alunos?"**
A modelagem e os índices foram feitos pensando em milhares. O gargalo
prático não é o banco: é o servidor onde for publicado.

**"E se o servidor cair? Perde as notas?"**
Backup por comando, com histórico e política de retenção. Antes de qualquer
migração que altere estrutura, o backup é obrigatório.

**"Vira aplicativo?"**
A API JSON já existe. Como a regra de negócio está separada do HTML, um
aplicativo Android consumiria o mesmo servidor sem reescrever nada.

**"Quanto falta para a escola usar?"**
O sistema está funcional e testado. Falta publicar: servidor, HTTPS,
PostgreSQL e o backup automático agendado.

---

## 10. As capturas de tela

Pasta: **`docs/apresentacao/`**

```
docs/apresentacao/
├── adm.html           ← 10 telas do administrador   (2,9 MB)
├── professor.html     ←  7 telas do professor       (1,3 MB)
├── aluno.html         ←  5 telas do aluno           (0,7 MB)
├── completo.html      ← os tres perfis juntos       (4,9 MB)
├── RESUMO.md          este documento
├── desktop/           as imagens soltas, 1440 px
├── celular/           as mesmas, 500 px
└── html/              as paginas em HTML, plano B
```

**Os quatro HTML sao autocontidos.** As imagens vao embutidas no proprio
arquivo, entao funcionam num pendrive, em outro computador, sem servidor e
sem Python. Navegacao pelas setas do teclado; o botao **Celular** mostra a
mesma tela na largura de um telefone.

Para regerar tudo:

```bash
python scripts/gerar_prints.py
python scripts/gerar_apresentacao.py
```

**44 imagens.** As de `desktop/` são as do projetor; as de `celular/`
servem para o slide "funciona no telefone", que costuma impressionar mais
que qualquer explicação de arquitetura.

Sugestão de ordem nos slides: `adm/01-painel` → `prof/03-lancar-notas` →
`aluno/02-boletim` → `celular/aluno/01-painel` → `adm/08-auditoria`.
