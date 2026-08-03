# SGE — Sistema de Gestão Escolar

Sistema web de gestão escolar construído para uso real: matrículas, turmas,
diário de classe, notas, boletins, horários, comunicados e relatórios, com
controle de acesso por perfil e trilha de auditoria.

Funciona no navegador de computador, tablet, Android e iPhone — sem instalação.

**Stack:** Python 3.12 · Flask · SQLAlchemy · SQLite (dev) / PostgreSQL (prod) ·
Bootstrap 5 · Chart.js

---

## Sumário

- [Instalação](#instalação)
- [Primeiro acesso](#primeiro-acesso)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Arquitetura](#arquitetura)
- [Perfis de acesso](#perfis-de-acesso)
- [Comandos disponíveis](#comandos-disponíveis)
- [Testes](#testes)
- [Segurança](#segurança)
- [Publicação em produção](#publicação-em-produção)
- [Documentação adicional](#documentação-adicional)

---

## Instalação

### Requisitos

- Python 3.12 ou superior
- Git

### Passo a passo

```bash
git clone <url-do-repositorio> sge
cd sge
```

Crie e ative o ambiente virtual:

```bash
python -m venv venv
```

**Windows (PowerShell):**

```bash
venv\Scripts\Activate.ps1
```

**Linux/macOS:**

```bash
source venv/bin/activate
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Copie o arquivo de variáveis de ambiente:

```bash
cp .env.example .env
```

Gere uma chave secreta e coloque em `SECRET_KEY` no `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Crie o banco de dados:

```bash
flask db upgrade
```

Crie a estrutura inicial (ano letivo, séries, tempos de aula):

```bash
flask criar-estrutura-inicial
```

Crie o administrador:

```bash
flask criar-admin
```

Inicie o servidor:

```bash
python run.py
```

Acesse `http://localhost:5000`.

> Para testar em celular ou tablet na mesma rede, use o IP da máquina:
> `http://192.168.x.x:5000`. O servidor já escuta em `0.0.0.0`.

---

## Primeiro acesso

1. Entre com o e-mail e a senha definidos em `flask criar-admin`.
2. Vá em **Configurações → Dados da escola** e preencha nome, CNPJ, endereço,
   diretor e secretário. Esses dados aparecem nos boletins e declarações.
3. Em **Configurações → Anos letivos**, confira o ano corrente e os bimestres.
4. Cadastre **Disciplinas**, depois **Turmas**, e atribua as disciplinas a cada
   turma (aba *Grade de disciplinas* na tela da turma).
5. Cadastre **Professores** e crie o acesso de cada um (botão *Criar acesso* na
   ficha) — a senha temporária aparece uma única vez.
6. Cadastre **Alunos** e **Responsáveis**, vincule-os e faça as **Matrículas**.

Para explorar o sistema com dados fictícios antes da carga real:

```bash
flask popular-demonstracao --alunos 60
```

> ⚠️ Nunca execute o comando acima em produção.

---

## Estrutura do projeto

```
sge/
├── app/
│   ├── __init__.py            # Application Factory (create_app) — só orquestra
│   ├── versao.py              # __version__
│   ├── extensions.py          # Instâncias das extensões Flask
│   ├── logging_config.py      # Log em arquivo rotativo e console
│   ├── errors.py              # Handlers de erro e negociação HTML/JSON
│   ├── hooks.py               # before/after request, cabeçalhos de segurança
│   ├── jinja_setup.py         # Filtros, globais e contexto dos templates
│   ├── commands/              # Comandos `flask ...`
│   │   ├── banco.py           # Estrutura e dados iniciais
│   │   ├── usuarios.py        # Contas de acesso
│   │   └── manutencao.py      # Backup, retenção e diagnóstico
│   │
│   ├── models/                # Camada de dados (SQLAlchemy)
│   │   ├── base.py            # ModeloBase e mixins comuns
│   │   ├── enums.py           # Enumerações do domínio
│   │   ├── mixins.py          # PessoaMixin, EnderecoMixin
│   │   ├── usuario.py         # Identidade e credenciais
│   │   ├── estrutura.py       # Ano letivo, série, turma, disciplina
│   │   ├── pessoas.py         # Aluno, professor, funcionário, responsável
│   │   ├── matricula.py       # Vínculo aluno × turma × ano
│   │   ├── frequencia.py      # Aula e frequência
│   │   ├── avaliacao.py       # Avaliação, nota, resultado
│   │   ├── horario.py         # Tempos de aula e grade
│   │   ├── comunicacao.py     # Avisos e leituras
│   │   └── sistema.py         # Configuração, auditoria, backup
│   │
│   ├── services/              # Camada de regras de negócio
│   ├── blueprints/            # Camada HTTP (rotas + formulários)
│   ├── utils/                 # Segurança, validação, permissões, formatação
│   ├── templates/             # Jinja2
│   └── static/                # CSS, JS e bibliotecas locais
│
├── config/                    # Configuração por ambiente
├── migrations/                # Migrações Alembic
├── tests/                     # Suíte automatizada
├── scripts/                   # Seed de demonstração
├── docs/                      # Documentação técnica
├── backups/                   # Backups gerados
├── uploads/                   # Arquivos enviados
└── instance/                  # Banco SQLite local (não versionado)
```

### Sobre `routes/` e `controllers/`

O planejamento previa duas pastas separadas. Em Flask, a função de rota **é** o
controlador — separá-las cria uma camada de indireção sem ganho. A separação
que realmente produz código testável é outra, e foi essa a adotada:

| Camada | Onde | Responsabilidade |
|---|---|---|
| HTTP | `blueprints/<módulo>/rotas.py` | Validar formulário, chamar service, renderizar |
| Negócio | `services/` | Regras, transações, validações contra o banco |
| Dados | `models/` | Esquema, relacionamentos, propriedades derivadas |

Os *services* não conhecem `request`, `session` nem `flash`. Por isso a mesma
regra atende à interface web, aos comandos CLI, aos testes e — sem reescrita —
à futura API do aplicativo Android.

---

## Arquitetura

```
┌──────────────────────────────────────────────────────────┐
│  Navegador — computador · tablet · Android · iPhone      │
└───────────────────────────┬──────────────────────────────┘
                            │ HTTPS
┌───────────────────────────▼──────────────────────────────┐
│  blueprints/  — rotas finas, formulários WTForms         │
├──────────────────────────────────────────────────────────┤
│  services/    — regras de negócio, transações            │
├──────────────────────────────────────────────────────────┤
│  models/      — SQLAlchemy + Alembic                     │
├──────────────────────────────────────────────────────────┤
│  SQLite (desenvolvimento) · PostgreSQL (produção)        │
└──────────────────────────────────────────────────────────┘
```

**Decisão central da modelagem:** notas e frequência apontam para
`Matricula`, nunca diretamente para `Aluno`. Um aluno reprovado cursa a mesma
disciplina em dois anos; ancorar em `Matricula` mantém cada ano letivo isolado
e o histórico escolar correto.

---

## Perfis de acesso

| Perfil | O que faz |
|---|---|
| **Administrador** | Acesso irrestrito, incluindo usuários, configurações, backup e auditoria |
| **Direção** | Todos os módulos acadêmicos e administrativos; vê auditoria; não gerencia contas |
| **Secretaria** | Alunos, matrículas, turmas, horários, boletins e relatórios; **não lança notas** |
| **Professor** | Diário de classe e notas **apenas das turmas que leciona** |
| **Aluno** | Consulta o próprio boletim, frequência, horários e avisos |
| **Responsável** | Consulta os dados **apenas dos alunos vinculados a ele** |

O controle acontece em duas camadas: permissão funcional (o perfil pode?) e
escopo do recurso (pode agir sobre *este* registro?). Sem a segunda, trocar o
ID na URL vazaria dados de outro aluno.

---

## Comandos disponíveis

```bash
flask criar-admin                    # Cria ou promove um administrador
flask criar-estrutura-inicial        # Ano letivo, séries e tempos de aula
flask popular-demonstracao           # Dados fictícios (nunca em produção)
flask listar-usuarios                # Lista as contas cadastradas
flask redefinir-senha                # Gera senha temporária para um usuário
flask backup                         # Gera backup do banco
flask backup --automatico            # Marca como backup automático (para o agendador)
flask limpar-auditoria --dias 365    # Remove eventos antigos
flask verificar-saude                # Diagnóstico da instalação
flask db upgrade                     # Aplica migrações pendentes
```

---

## Testes

```bash
pip install -e ".[dev]"
```

Rodar a suíte completa:

```bash
pytest
```

Com relatório de cobertura:

```bash
pytest --cov=app --cov-report=term-missing
```

Apenas os testes de segurança e autorização:

```bash
pytest tests/integration/test_autorizacao.py -v
```

**Cobertura atual:** 307 testes. A prioridade é regra de negócio e controle de
acesso, não percentual: `permissoes` 99%, `seguranca` 95%, `auth_service` 90%.

O arquivo `tests/integration/test_rotas.py` percorre **todas** as rotas GET
registradas e falha se qualquer tela retornar erro. Telas novas entram na
cobertura automaticamente.

Os arquivos `test_auditoria_fase1.py` a `test_auditoria_fase4.py` guardam as
correções da auditoria de código: cada teste ali falhava antes da respectiva
correção. Não os remova ao refatorar — são a prova de que o bug existiu.

### Ganchos de qualidade

```bash
pip install pre-commit && pre-commit install
```

Antes de cada commit: lint, higiene de arquivo, e duas verificações próprias
do projeto — nenhum upload dentro de `app/static/` e nenhum `<script>` inline
nos templates. As duas correspondem a falhas reais encontradas na auditoria.

O CI (`.github/workflows/ci.yml`) roda a suíte em **SQLite e em PostgreSQL
16**, além de aplicar toda a sequência de migrations no Postgres do zero
(`upgrade → downgrade → upgrade`). O desenvolvimento é SQLite; sem esse job,
as incompatibilidades só apareceriam no dia da entrega.

### PostgreSQL local

```bash
docker compose up -d --wait
export DATABASE_URL=postgresql+psycopg://sge:sge@localhost:5433/sge
flask db upgrade
```

Para voltar ao SQLite, remova a variável `DATABASE_URL`.

---

## Segurança

| Defesa | Implementação |
|---|---|
| Senhas | Argon2id (recomendação OWASP), com migração transparente de hashes antigos |
| Força bruta | Bloqueio temporário após N tentativas + *rate limiting* no login |
| Sessão | Cookie `HttpOnly`, `SameSite=Lax`, `Secure` em produção, expiração por inatividade |
| CSRF | Token em todos os formulários (Flask-WTF) |
| XSS | Autoescape do Jinja2 + CSP com `script-src 'self'` (nenhum script inline) |
| SQL Injection | Exclusivamente ORM com consultas parametrizadas |
| Broken Access Control | RBAC + verificação de escopo em toda rota com ID, coberta por testes |
| Open redirect | Parâmetro `next` validado contra o próprio host |
| Upload | Lista de permissão + validação da assinatura binária + reencodificação da imagem |
| Path traversal | Nome gerado pelo servidor + validação do caminho resolvido |
| Auditoria | Trilha imutável: sem rota de edição ou exclusão individual |
| LGPD | Dados de saúde restritos por permissão, EXIF removido das fotos, consentimento de imagem registrado |

Verificar vulnerabilidades nas dependências:

```bash
pip-audit
```

---

## Publicação em produção

Resumo — o passo a passo completo está em [docs/implantacao.md](docs/implantacao.md).

1. Configure `.env` com `APP_ENV=production`, `SECRET_KEY` forte e
   `DATABASE_URL` do PostgreSQL.
2. Instale os extras de produção:

```bash
pip install gunicorn "psycopg[binary]"
```

3. Aplique as migrações:

```bash
flask db upgrade
```

4. Suba com Gunicorn atrás do Nginx:

```bash
gunicorn --workers 4 --bind 127.0.0.1:8000 wsgi:app
```

5. Configure HTTPS no Nginx e agende o backup diário.

A aplicação **se recusa a iniciar** em produção com a `SECRET_KEY` padrão ou
sem `DATABASE_URL` — falha rápida em vez de operar de forma insegura.

---

## Documentação adicional

- [CLAUDE.md](CLAUDE.md) — regras operacionais de quem mexe no código (leia
  primeiro; as demais explicam o porquê, esta diz o quê fazer)
- [docs/arquitetura.md](docs/arquitetura.md) — camadas, decisões e trade-offs
- [docs/banco-de-dados.md](docs/banco-de-dados.md) — modelo de dados e relacionamentos
- [docs/seguranca.md](docs/seguranca.md) — modelo de ameaças e defesas
- [docs/implantacao.md](docs/implantacao.md) — publicação, backup e operação
- [docs/api.md](docs/api.md) — API JSON e caminho para o aplicativo Android
- [PLANEJAMENTO.md](PLANEJAMENTO.md) — planejamento técnico original
