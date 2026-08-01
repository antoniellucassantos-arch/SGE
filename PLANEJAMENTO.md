# SGE — Sistema de Gestão Escolar
## Documento de Planejamento Técnico

**Versão:** 1.0
**Status:** Aguardando aprovação para iniciar implementação
**Stack obrigatória:** Python 3.12, Flask, SQLAlchemy, SQLite (dev) / PostgreSQL (prod), HTML5, CSS3, JavaScript, Bootstrap 5

---

## 1. Objetivo do Sistema

Fornecer a uma escola real uma plataforma web única, segura e responsiva para gerenciar toda a operação acadêmica e administrativa: matrícula de alunos, cadastro de turmas e disciplinas, lançamento de notas e frequência, comunicação entre escola/professores/responsáveis, e emissão de relatórios e boletins.

Objetivos específicos:
- Centralizar dados hoje espalhados em planilhas, papel e sistemas isolados.
- Reduzir erros manuais de lançamento de notas e faltas.
- Dar visibilidade em tempo real a professores, coordenação, secretaria e responsáveis.
- Ser acessível de qualquer dispositivo (desktop, tablet, celular) sem instalação, via navegador, com caminho futuro para um app Android nativo consumindo a mesma API.
- Ser seguro o suficiente para lidar com dados de menores de idade (LGPD).

## 2. Problema que o Sistema Resolve

Escolas de pequeno/médio porte frequentemente operam com:
- Planilhas Excel duplicadas e sem controle de versão para notas e frequência.
- Comunicação informal (WhatsApp, papel) entre escola e responsáveis, sem histórico.
- Ausência de auditoria: não se sabe quem alterou uma nota ou quando.
- Dificuldade de gerar boletins e relatórios consolidados rapidamente.
- Nenhum controle de acesso granular (qualquer pessoa com a planilha vê tudo).
- Nenhuma solução acessível em múltiplos dispositivos ao mesmo tempo, com dados sempre sincronizados.

O SGE resolve isso com um sistema único, com banco de dados relacional, controle de permissões por perfil, trilha de auditoria e interface responsiva.

## 3. Arquitetura Completa do Projeto

### 3.1 Visão geral
Arquitetura monolítica modular (Modular Monolith) no backend, servida por Flask, seguindo o padrão **Application Factory + Blueprints**, com camadas bem definidas. Isso é apropriado para o porte de uma escola (não justifica microsserviços) mas mantém o código organizado para crescer.

```
┌─────────────────────────────────────────────────────────┐
│                     CLIENTE (Browser)                     │
│   Desktop / Tablet / Android / iPhone — HTML5+CSS3+JS+BS5  │
└───────────────────────────┬────────────────────────────────┘
                            │ HTTPS
┌───────────────────────────▼────────────────────────────────┐
│                      CAMADA WEB (Flask)                     │
│  Blueprints: auth, alunos, turmas, notas, frequencia,       │
│  financeiro, comunicados, relatorios, admin, api            │
├──────────────────────────────────────────────────────────────┤
│                CAMADA DE SERVIÇOS (Service Layer)            │
│  Regras de negócio, validações, orquestração de casos de uso │
├──────────────────────────────────────────────────────────────┤
│              CAMADA DE REPOSITÓRIO / ORM (SQLAlchemy)         │
│  Models, Repositories, Migrations (Alembic)                  │
├──────────────────────────────────────────────────────────────┤
│         BANCO DE DADOS: SQLite (dev) / PostgreSQL (prod)     │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Padrão arquitetural em camadas
- **Presentation Layer**: rotas Flask (Blueprints), templates Jinja2, arquivos estáticos, ou futuramente API REST em JSON pura para consumo do app Android.
- **Service Layer**: funções/classes que implementam regras de negócio (ex.: `MatriculaService`, `BoletimService`), independentes do Flask — facilita testes e reuso pela futura API mobile.
- **Data Access Layer**: Models SQLAlchemy + Repositórios (funções de consulta), migrações via Alembic.
- **Cross-cutting concerns**: autenticação (Flask-Login), autorização (decorators de papel), logging, auditoria, validação de formulários (Flask-WTF/WTForms), tratamento de erros centralizado.

### 3.3 Preparação para API/Mobile
Desde o início, a camada de serviços não deve depender de `request`/`session` do Flask diretamente — recebe dados já validados e devolve objetos/DTOs. Isso permite, no futuro, expor um Blueprint `api/` (JSON + JWT) que reutiliza os mesmos serviços usados pelas views HTML, sem duplicar regra de negócio. Essa é a base para o app Android (item 19).

### 3.4 Ambientes
- **Desenvolvimento**: SQLite, `DEBUG=True`, servidor Flask embutido.
- **Homologação/Produção**: PostgreSQL, Gunicorn atrás de Nginx, `DEBUG=False`, variáveis de ambiente via `.env`/secrets do servidor.

### 3.5 Configuração por ambiente
Uso de classes de configuração (`config.py`) com `DevelopmentConfig`, `TestingConfig`, `ProductionConfig`, selecionadas via variável de ambiente `FLASK_ENV` / `APP_ENV`, seguindo o padrão de Application Factory (`create_app(config_name)`).

## 4. Estrutura de Pastas Recomendada

```
sge/
├── app/
│   ├── __init__.py                # Application Factory (create_app)
│   ├── extensions.py              # db, login_manager, migrate, csrf, etc.
│   ├── config.py                  # Classes de configuração por ambiente
│   │
│   ├── models/                    # Models SQLAlchemy (um arquivo por domínio)
│   │   ├── __init__.py
│   │   ├── usuario.py
│   │   ├── aluno.py
│   │   ├── responsavel.py
│   │   ├── professor.py
│   │   ├── turma.py
│   │   ├── disciplina.py
│   │   ├── matricula.py
│   │   ├── nota.py
│   │   ├── frequencia.py
│   │   ├── comunicado.py
│   │   ├── financeiro.py
│   │   └── auditoria.py
│   │
│   ├── blueprints/                # Um blueprint por módulo funcional
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py
│   │   │   └── forms.py
│   │   ├── alunos/
│   │   ├── turmas/
│   │   ├── notas/
│   │   ├── frequencia/
│   │   ├── financeiro/
│   │   ├── comunicados/
│   │   ├── relatorios/
│   │   ├── admin/
│   │   └── api/                   # Preparado para consumo mobile (JSON/JWT)
│   │
│   ├── services/                  # Regras de negócio (independentes do Flask request)
│   │   ├── matricula_service.py
│   │   ├── boletim_service.py
│   │   ├── frequencia_service.py
│   │   ├── notificacao_service.py
│   │   └── auditoria_service.py
│   │
│   ├── repositories/              # Consultas encapsuladas (opcional, cresce com o projeto)
│   │
│   ├── static/
│   │   ├── css/
│   │   ├── js/
│   │   └── img/
│   │
│   ├── templates/
│   │   ├── base.html
│   │   ├── auth/
│   │   ├── alunos/
│   │   ├── turmas/
│   │   ├── notas/
│   │   ├── frequencia/
│   │   ├── financeiro/
│   │   ├── comunicados/
│   │   ├── relatorios/
│   │   └── admin/
│   │
│   └── utils/
│       ├── decorators.py          # @requer_papel('admin'), etc.
│       ├── validators.py
│       └── formatters.py
│
├── migrations/                    # Alembic (gerado por Flask-Migrate)
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
│
├── scripts/
│   ├── seed_dados.py               # Popular banco com dados de exemplo
│   └── backup_db.py
│
├── instance/
│   └── sge.db                      # SQLite local (não versionado)
│
├── logs/
├── .env.example
├── .gitignore
├── requirements.txt
├── requirements-dev.txt
├── wsgi.py                         # Entry point produção (Gunicorn)
├── run.py                          # Entry point desenvolvimento
└── README.md
```

## 5. Modelagem Completa do Banco de Dados

> Nomenclatura: tabelas em `snake_case`, singular por entidade lógica, chaves primárias `id`, chaves estrangeiras `<entidade>_id`.

### 5.1 `usuarios`
Conta de acesso ao sistema (login). Toda pessoa com acesso (admin, secretaria, professor, responsável) tem um registro aqui.

| Campo | Tipo | Observações |
|---|---|---|
| id | Integer PK | |
| nome | String(150) | |
| email | String(150) | unique, not null |
| senha_hash | String(255) | hash via Werkzeug/Argon2 |
| papel | Enum | admin, secretaria, coordenador, professor, responsavel |
| ativo | Boolean | default True |
| ultimo_login | DateTime | nullable |
| criado_em | DateTime | default now |
| atualizado_em | DateTime | onupdate now |

### 5.2 `professores`
| Campo | Tipo |
|---|---|
| id | Integer PK |
| usuario_id | FK → usuarios.id (1:1) |
| registro_funcional | String(50) |
| formacao | String(150) |
| telefone | String(20) |

### 5.3 `responsaveis`
| Campo | Tipo |
|---|---|
| id | Integer PK |
| usuario_id | FK → usuarios.id (1:1) |
| cpf | String(14) unique |
| telefone | String(20) |
| endereco | String(255) |

### 5.4 `alunos`
| Campo | Tipo |
|---|---|
| id | Integer PK |
| nome | String(150) |
| data_nascimento | Date |
| cpf | String(14) nullable |
| sexo | Enum(M, F, Outro) |
| endereco | String(255) |
| foto_url | String(255) nullable |
| ativo | Boolean default True |
| criado_em | DateTime |

### 5.5 `aluno_responsavel` (associativa N:N — aluno pode ter mais de um responsável)
| Campo | Tipo |
|---|---|
| id | Integer PK |
| aluno_id | FK → alunos.id |
| responsavel_id | FK → responsaveis.id |
| parentesco | String(50) (mãe, pai, tutor legal...) |
| responsavel_financeiro | Boolean |

### 5.6 `anos_letivos`
| Campo | Tipo |
|---|---|
| id | Integer PK |
| ano | Integer unique (ex.: 2026) |
| data_inicio | Date |
| data_fim | Date |
| ativo | Boolean |

### 5.7 `series` (ou "níveis" — ex.: 1º Ano EF, 2º Ano EM)
| Campo | Tipo |
|---|---|
| id | Integer PK |
| nome | String(50) |
| nivel_ensino | Enum(infantil, fundamental1, fundamental2, medio) |
| ordem | Integer |

### 5.8 `turmas`
| Campo | Tipo |
|---|---|
| id | Integer PK |
| nome | String(50) (ex.: "9º Ano A") |
| serie_id | FK → series.id |
| ano_letivo_id | FK → anos_letivos.id |
| turno | Enum(manha, tarde, noite, integral) |
| capacidade_maxima | Integer |

### 5.9 `disciplinas`
| Campo | Tipo |
|---|---|
| id | Integer PK |
| nome | String(100) |
| codigo | String(20) unique |
| carga_horaria | Integer |

### 5.10 `turma_disciplina_professor` (associativa — quem leciona o quê, em qual turma)
| Campo | Tipo |
|---|---|
| id | Integer PK |
| turma_id | FK → turmas.id |
| disciplina_id | FK → disciplinas.id |
| professor_id | FK → professores.id |
| ano_letivo_id | FK → anos_letivos.id |

Unique constraint: (turma_id, disciplina_id, ano_letivo_id)

### 5.11 `matriculas`
| Campo | Tipo |
|---|---|
| id | Integer PK |
| aluno_id | FK → alunos.id |
| turma_id | FK → turmas.id |
| ano_letivo_id | FK → anos_letivos.id |
| data_matricula | Date |
| status | Enum(ativa, trancada, transferida, cancelada, concluida) |
| numero_matricula | String(30) unique |

Unique constraint: (aluno_id, ano_letivo_id) — aluno só pode ter 1 matrícula ativa por ano.

### 5.12 `periodos_avaliativos` (bimestres/trimestres)
| Campo | Tipo |
|---|---|
| id | Integer PK |
| ano_letivo_id | FK → anos_letivos.id |
| nome | String(30) (ex.: "1º Bimestre") |
| data_inicio | Date |
| data_fim | Date |
| ordem | Integer |

### 5.13 `avaliacoes` (instrumento de avaliação: prova, trabalho, etc.)
| Campo | Tipo |
|---|---|
| id | Integer PK |
| turma_disciplina_professor_id | FK |
| periodo_avaliativo_id | FK → periodos_avaliativos.id |
| nome | String(100) (ex.: "Prova 1") |
| peso | Numeric(4,2) |
| data_aplicacao | Date |
| valor_maximo | Numeric(5,2) default 10.00 |

### 5.14 `notas`
| Campo | Tipo |
|---|---|
| id | Integer PK |
| avaliacao_id | FK → avaliacoes.id |
| matricula_id | FK → matriculas.id |
| valor | Numeric(5,2) nullable |
| observacao | String(255) nullable |
| lancado_por_id | FK → usuarios.id |
| atualizado_em | DateTime |

Unique constraint: (avaliacao_id, matricula_id)

### 5.15 `aulas` (registro de aula dada — base para frequência)
| Campo | Tipo |
|---|---|
| id | Integer PK |
| turma_disciplina_professor_id | FK |
| data_aula | Date |
| conteudo_ministrado | Text nullable |

### 5.16 `frequencias`
| Campo | Tipo |
|---|---|
| id | Integer PK |
| aula_id | FK → aulas.id |
| matricula_id | FK → matriculas.id |
| presente | Boolean |
| justificativa | String(255) nullable |

Unique constraint: (aula_id, matricula_id)

### 5.17 `comunicados`
| Campo | Tipo |
|---|---|
| id | Integer PK |
| titulo | String(150) |
| mensagem | Text |
| autor_id | FK → usuarios.id |
| publico_alvo | Enum(todos, turma, responsaveis, professores) |
| turma_id | FK → turmas.id (nullable, se publico_alvo=turma) |
| criado_em | DateTime |

### 5.18 `comunicado_leitura` (associativa — controle de leitura por usuário)
| Campo | Tipo |
|---|---|
| id | Integer PK |
| comunicado_id | FK → comunicados.id |
| usuario_id | FK → usuarios.id |
| lido_em | DateTime nullable |

### 5.19 `mensalidades` (módulo financeiro básico)
| Campo | Tipo |
|---|---|
| id | Integer PK |
| matricula_id | FK → matriculas.id |
| competencia | String(7) (ex.: "2026-03") |
| valor | Numeric(10,2) |
| vencimento | Date |
| status | Enum(pendente, pago, atrasado, cancelado) |
| pago_em | Date nullable |

### 5.20 `auditoria_logs`
| Campo | Tipo |
|---|---|
| id | Integer PK |
| usuario_id | FK → usuarios.id nullable |
| acao | String(50) (create, update, delete, login, login_failed) |
| entidade | String(50) |
| entidade_id | Integer nullable |
| detalhes | JSON/Text nullable |
| ip_origem | String(45) |
| criado_em | DateTime |

## 6. Relação Entre Todas as Tabelas

```
usuarios (1) ────── (1) professores
usuarios (1) ────── (1) responsaveis

alunos (N) ─── aluno_responsavel ─── (N) responsaveis

anos_letivos (1) ──< turmas
anos_letivos (1) ──< matriculas
anos_letivos (1) ──< periodos_avaliativos
anos_letivos (1) ──< turma_disciplina_professor

series (1) ──< turmas

turmas (1) ──< matriculas
turmas (1) ──< turma_disciplina_professor
turmas (1) ──< comunicados (quando direcionado a turma)

alunos (1) ──< matriculas

disciplinas (1) ──< turma_disciplina_professor

professores (1) ──< turma_disciplina_professor

turma_disciplina_professor (1) ──< aulas
turma_disciplina_professor (1) ──< avaliacoes

periodos_avaliativos (1) ──< avaliacoes

avaliacoes (1) ──< notas
matriculas (1) ──< notas
matriculas (1) ──< frequencias
matriculas (1) ──< mensalidades

aulas (1) ──< frequencias

usuarios (1) ──< comunicados (autor)
comunicados (1) ──< comunicado_leitura
usuarios (1) ──< comunicado_leitura

usuarios (1) ──< auditoria_logs
```

**Resumo das entidades centrais:**
- `usuarios` é a raiz de identidade/autenticação; `professores` e `responsaveis` estendem `usuarios` (herança 1:1).
- `alunos` é independente de login (aluno não acessa o sistema neste escopo — pode ser incluído futuramente).
- `matriculas` é a tabela-pivô que liga aluno → turma → ano letivo, e é referenciada por notas, frequência e financeiro (em vez de referenciar `alunos` diretamente), garantindo que o histórico correto por ano letivo seja preservado.

## 7. Todos os Módulos do Sistema

1. **Autenticação e Perfil (auth)** — login, logout, recuperação de senha, troca de senha, edição de perfil.
2. **Administração (admin)** — gestão de usuários, papéis, anos letivos, séries, configurações gerais do sistema.
3. **Alunos** — cadastro, edição, histórico, vínculo com responsáveis, upload de foto/documentos.
4. **Responsáveis** — cadastro, vínculo com alunos.
5. **Turmas** — criação de turmas por ano letivo/série/turno, alocação de capacidade.
6. **Disciplinas e Grade** — cadastro de disciplinas, atribuição de professor a turma/disciplina/ano.
7. **Matrículas** — matricular, transferir, trancar, cancelar, gerar número de matrícula.
8. **Notas e Avaliações** — criação de avaliações por período, lançamento e edição de notas, cálculo de médias.
9. **Frequência** — registro de aula, chamada (presença/falta), justificativas, relatório de faltas.
10. **Boletim e Relatórios Acadêmicos** — boletim individual, ata de resultados, relatório de turma.
11. **Comunicados** — envio de avisos gerais/por turma, controle de leitura.
12. **Financeiro (básico)** — geração e controle de mensalidades, status de pagamento, relatório de inadimplência.
13. **Auditoria** — log de ações sensíveis (quem alterou o quê e quando), consulta pela administração.
14. **Dashboard** — visão geral por perfil (indicadores: nº de alunos, pendências, avisos recentes).
15. **API (futuro imediato)** — camada JSON/JWT reaproveitando os `services`, base para o app Android.

## 8. Fluxo de Navegação Entre as Telas

```
[Tela de Login]
     │
     ▼
[Dashboard] ── (conteúdo varia por papel)
     │
     ├── Admin/Secretaria
     │     ├── Usuários ─ [Listar] → [Criar/Editar] → [Detalhe]
     │     ├── Anos Letivos / Séries / Turmas ─ [Listar] → [Criar/Editar]
     │     ├── Disciplinas / Grade ─ [Listar] → [Atribuir Professor]
     │     ├── Alunos ─ [Listar] → [Cadastrar] → [Ficha do Aluno]
     │     │                                           ├── Dados pessoais
     │     │                                           ├── Responsáveis
     │     │                                           ├── Matrículas (histórico)
     │     │                                           ├── Boletim
     │     │                                           └── Financeiro
     │     ├── Matrículas ─ [Nova Matrícula] → [Confirmação]
     │     ├── Financeiro ─ [Mensalidades] → [Detalhe/Baixa de Pagamento]
     │     ├── Comunicados ─ [Listar] → [Novo Comunicado]
     │     └── Auditoria ─ [Logs] → [Filtro por usuário/ação]
     │
     ├── Coordenador
     │     ├── Turmas → [Relatório de Desempenho da Turma]
     │     ├── Frequência → [Relatório Consolidado]
     │     └── Comunicados
     │
     ├── Professor
     │     ├── Minhas Turmas ─ [Selecionar Turma/Disciplina]
     │     │                        ├── Diário de Classe (aulas)
     │     │                        ├── Lançar Notas (por avaliação)
     │     │                        └── Fazer Chamada (frequência)
     │     └── Comunicados (visualizar / enviar à própria turma)
     │
     └── Responsável
           ├── Meus Filhos ─ [Selecionar Aluno]
           │                     ├── Boletim
           │                     ├── Frequência
           │                     └── Financeiro (2ª via, status)
           └── Comunicados (visualizar)

[Perfil do Usuário] (acessível de qualquer tela via menu superior)
[Logout]
```

Navegação implementada com layout base (`base.html`) com barra superior + menu lateral colapsável (offcanvas do Bootstrap 5) para boa usabilidade em mobile/tablet.

## 9. Tipos de Usuários e Permissões

| Papel | Descrição | Principais permissões |
|---|---|---|
| **Admin** | Gestor do sistema/direção | Acesso total: usuários, configurações, todos os módulos, auditoria |
| **Secretaria** | Equipe administrativa | Alunos, matrículas, turmas, financeiro, comunicados — sem gestão de usuários/config do sistema |
| **Coordenador** | Coordenação pedagógica | Leitura de notas/frequência de todas as turmas, relatórios, comunicados — sem edição financeira |
| **Professor** | Docente | CRUD de notas e frequência apenas das turmas/disciplinas atribuídas a ele; leitura do próprio diário |
| **Responsável** | Pai/mãe/tutor | Leitura (somente visualização) dos dados dos alunos vinculados a ele: boletim, frequência, financeiro, comunicados |

**Estratégia de autorização:**
- Controle por papel (RBAC) usando decorator customizado, ex.: `@requer_papel('admin', 'secretaria')`.
- Controle de **posse/escopo** além do papel: professor só acessa turmas onde está em `turma_disciplina_professor`; responsável só acessa alunos vinculados em `aluno_responsavel`. Isso é validado na camada de serviço, não apenas na rota.
- Toda entidade sensível exposta por `id` na URL deve validar que o usuário logado tem direito àquele registro específico (evita IDOR — Insecure Direct Object Reference).

## 10. Funcionalidades de Cada Módulo

**Auth**: login com e-mail/senha, bloqueio após tentativas falhas, recuperação de senha por token expirável, forçar troca de senha no primeiro acesso, logout, sessão expira por inatividade.

**Admin**: CRUD de usuários e definição de papéis, ativar/desativar ano letivo, configurar séries e turnos, parâmetros gerais (nome da escola, ano letivo corrente, etc.).

**Alunos**: cadastro completo, busca/filtro, inativação (nunca exclusão física de aluno com histórico), anexos de documentos, vínculo de responsáveis.

**Turmas/Disciplinas**: criação de turmas por ano/série/turno, atribuição de professores a disciplinas dentro da turma, controle de vagas.

**Matrículas**: nova matrícula com geração automática de número, transferência entre turmas, trancamento, cancelamento com motivo, histórico de matrículas do aluno.

**Notas**: criação de avaliações com peso e data, lançamento de notas em lote (grade da turma), edição com trilha de auditoria, cálculo automático de média por período e final, indicação visual de aprovado/recuperação/reprovado.

**Frequência**: registro de aula (data + conteúdo), chamada rápida (grade com todos os alunos da turma), justificativa de falta, cálculo de percentual de frequência, alerta de risco por excesso de faltas.

**Boletim/Relatórios**: boletim em tela e exportável em PDF, relatório de turma (médias/frequência agregada), relatório de inadimplência, exportação em CSV/Excel para relatórios gerenciais.

**Comunicados**: criação com público-alvo, marcação de lido/não lido, listagem cronológica, notificação visual de não lidos no dashboard.

**Financeiro**: geração de mensalidades (individual ou em lote por competência), baixa manual de pagamento, status automático "atrasado" por data, relatório de inadimplência. (Escopo inicial não inclui gateway de pagamento online — pode ser evolução futura, item 14.)

**Auditoria**: registro automático (via hooks do SQLAlchemy ou decorators de serviço) de criação/edição/exclusão em entidades sensíveis (notas, frequência, financeiro, usuários), consulta filtrável por admin.

**Dashboard**: cards com indicadores relevantes ao papel logado (ex.: professor vê "aulas de hoje", responsável vê "últimas notas lançadas").

## 11. Estratégia de Autenticação

- **Flask-Login** para gestão de sessão do usuário autenticado.
- Senhas armazenadas com hash forte (Werkzeug `generate_password_hash` com `pbkdf2:sha256` no mínimo, ou preferencialmente **Argon2** via `argon2-cffi`/`Flask-Bcrypt` alternativa).
- Cookies de sessão: `HttpOnly`, `Secure` (em produção com HTTPS), `SameSite=Lax`.
- **CSRF protection** via Flask-WTF em todos os formulários.
- Login com **rate limiting** (Flask-Limiter) para mitigar força bruta (ex.: 5 tentativas/minuto por IP+usuário).
- Bloqueio temporário de conta após N tentativas falhas consecutivas, registrado em auditoria.
- Recuperação de senha via token assinado (itsdangerous), expiração curta (ex.: 30 min), envio por e-mail (Flask-Mail).
- Sessão expira por tempo de inatividade configurável (`PERMANENT_SESSION_LIFETIME`).
- Preparação para futuro: endpoint de API com **JWT** (Flask-JWT-Extended) para o app Android, convivendo com a sessão de cookie usada pela interface web — dois mecanismos de auth sobre os mesmos `services`.

## 12. Estratégia de Segurança

- **Autorização em profundidade**: verificação de papel (RBAC) + verificação de posse do recurso (escopo) em toda rota sensível, nunca confiar apenas no que o menu esconde na tela.
- **Proteção contra OWASP Top 10**:
  - *Injection*: uso exclusivo do ORM SQLAlchemy com queries parametrizadas; nunca concatenar SQL.
  - *XSS*: Jinja2 com autoescape habilitado (padrão), nunca usar `|safe` com dados de usuário.
  - *CSRF*: token em todos os formulários (Flask-WTF).
  - *Broken Access Control*: testes de autorização item 17.
  - *Security Misconfiguration*: `DEBUG=False` em produção, headers de segurança via Flask-Talisman (CSP, HSTS, X-Frame-Options, X-Content-Type-Options).
  - *Sensitive Data Exposure*: HTTPS obrigatório em produção, dados de CPF/documentos tratados como sensíveis (LGPD).
- **Validação de entrada**: WTForms com validadores server-side em todos os formulários (nunca confiar só em validação client-side).
- **Upload de arquivos** (fotos/documentos): validação de extensão e MIME real, limite de tamanho, renomeação do arquivo (evitar path traversal), armazenamento fora da pasta pública direta ou com controle de acesso.
- **Variáveis sensíveis** (SECRET_KEY, credenciais de banco, SMTP) em variáveis de ambiente (`.env`, nunca commitado — `.gitignore`).
- **Logs de auditoria** imutáveis (sem endpoint de exclusão) para ações sensíveis.
- **LGPD**: minimização de dados coletados, finalidade clara, política de retenção, mecanismo de exportação/exclusão de dados de titular mediante solicitação formal à escola, controle de acesso restrito a dados de menores.
- **Dependências**: atualização periódica e verificação de vulnerabilidades (`pip-audit` ou `safety`).
- **Backup criptografado** (ver item 18).

## 13. Roadmap Dividido em Pequenas Etapas de Desenvolvimento

**Fase 0 — Fundação**
1. Estrutura do projeto (Application Factory, config por ambiente, extensões).
2. Configuração de banco (SQLite dev), Flask-Migrate/Alembic.
3. Modelos base: `usuarios`, `professores`, `responsaveis`.
4. Autenticação: login/logout, hash de senha, decorators de papel.

**Fase 1 — Cadastros Base**
5. CRUD de `anos_letivos`, `series`, `turmas`.
6. CRUD de `disciplinas` e `turma_disciplina_professor`.
7. CRUD de `alunos` e `aluno_responsavel`.

**Fase 2 — Matrículas**
8. CRUD de `matriculas` (nova matrícula, transferência, trancamento, cancelamento).

**Fase 3 — Acadêmico**
9. `periodos_avaliativos` + `avaliacoes`.
10. Lançamento de `notas` (tela de grade por turma/disciplina).
11. Cálculo de médias e status (aprovado/recuperação/reprovado).
12. `aulas` + `frequencias` (chamada).
13. Boletim (tela + exportação PDF).

**Fase 4 — Comunicação e Financeiro**
14. `comunicados` + leitura.
15. `mensalidades` (geração, baixa, relatório de inadimplência).

**Fase 5 — Qualidade e Operação**
16. Auditoria (`auditoria_logs`) integrada às ações das fases anteriores.
17. Dashboard por papel.
18. Testes automatizados (unitários + integração) cobrindo regras críticas.
19. Hardening de segurança (Talisman, rate limiting, revisão OWASP).
20. Ajustes de responsividade final (mobile/tablet) em todas as telas.

**Fase 6 — Preparação para Produção**
21. Migração de config para PostgreSQL, variáveis de ambiente, Gunicorn+Nginx.
22. Rotina de backup automatizado.
23. Deploy em ambiente de homologação com dados reais anonimizados para validação da escola.
24. Treinamento dos usuários da escola + ajustes finais.

**Fase 7 — Evoluções (pós-lançamento)**
25. Blueprint `api/` com JWT, reaproveitando os `services` — base do app Android.

Cada etapa deve ser pequena o suficiente para ser entregue, testada manualmente e aprovada antes de avançar para a próxima — evitando retrabalho grande.

## 14. Sugestões de Melhorias Futuras

- App Android nativo consumindo a API (item 19).
- Notificações push/e-mail automáticas (nota lançada, falta registrada, comunicado novo).
- Emissão de declarações e documentos automáticos (declaração de matrícula, histórico escolar em PDF com assinatura digital).
- Portal do próprio aluno (login para alunos maiores de idade ou ensino médio).
- Gateway de pagamento online integrado (Pix, boleto) no módulo financeiro.
- Módulo de biblioteca (empréstimo de livros).
- Módulo de eventos/calendário escolar integrado.
- Relatórios com gráficos (Chart.js) de desempenho e evasão.
- Exportação de dados para o censo escolar (Educacenso, no contexto brasileiro).
- Sistema de mensageria interna escola↔responsável (chat simples).
- Multi-escola/multi-unidade (caso a rede cresça para mais de uma unidade).

## 15. Convenções de Código

- **Python**: PEP 8, formatação automática com **Black**, lint com **Ruff** ou **Flake8**, imports organizados com **isort**.
- **Nomenclatura**:
  - Variáveis e funções: `snake_case`.
  - Classes: `PascalCase`.
  - Constantes: `UPPER_SNAKE_CASE`.
  - Tabelas do banco: `snake_case`, plural (`alunos`, `turmas`).
  - Templates Jinja2: `snake_case.html`, organizados por módulo em subpastas.
- **Idioma**: nomes de tabelas/campos/rotas em português (domínio da escola brasileira), nomes de classes Python e variáveis internas também em português para consistência com o domínio, salvo termos técnicos consagrados em inglês (`service`, `repository`, `blueprint`).
- **Docstrings** apenas onde a lógica de negócio não é óbvia (cálculo de média, regras de aprovação).
- **Type hints** obrigatórios em funções de `services/` e `utils/`.
- **Commits**: Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`).
- **Branches**: `main` (produção), `develop` (integração), `feature/<nome>` por funcionalidade.
- **Templates**: herança consistente de `base.html`, componentes reutilizáveis em `templates/_components/` (ex.: paginação, alertas).
- **Formulários**: sempre via Flask-WTF (nunca `request.form` direto sem validação).
- **Respostas de erro**: páginas customizadas 403/404/500, nunca stack trace exposto em produção.

## 16. Bibliotecas Recomendadas

**Core:**
- `Flask` — framework web
- `Flask-SQLAlchemy` — ORM
- `Flask-Migrate` (Alembic) — migrações de banco
- `Flask-Login` — autenticação/sessão
- `Flask-WTF` / `WTForms` — formulários e CSRF
- `Flask-Bcrypt` ou `argon2-cffi` — hash de senha
- `python-dotenv` — variáveis de ambiente

**Segurança:**
- `Flask-Talisman` — headers de segurança/HTTPS
- `Flask-Limiter` — rate limiting
- `itsdangerous` — tokens assinados (recuperação de senha)

**Produção:**
- `gunicorn` — servidor WSGI
- `psycopg2-binary` — driver PostgreSQL

**Utilitários:**
- `Flask-Mail` — envio de e-mails
- `WeasyPrint` ou `ReportLab` — geração de PDF (boletins, declarações)
- `openpyxl` — exportação Excel
- `Flask-Caching` — cache de relatórios pesados

**Futuro (API/Mobile):**
- `Flask-JWT-Extended` — autenticação via token para app Android
- `marshmallow` ou `flask-smorest` — serialização/validação de API + documentação OpenAPI

**Frontend:**
- `Bootstrap 5` (CSS/JS)
- `Bootstrap Icons`
- Vanilla JavaScript (evitar frameworks pesados nesta fase — manter simples e leve para bom desempenho em dispositivos móveis)

**Desenvolvimento/Qualidade:**
- `pytest`, `pytest-flask`, `pytest-cov`
- `factory-boy` — fixtures de teste
- `Black`, `Ruff`/`Flake8`, `isort`
- `pip-audit` — auditoria de dependências vulneráveis

## 17. Plano de Testes

**Testes Unitários** (`tests/unit/`): funções da camada `services/` isoladas (ex.: cálculo de média, regra de aprovação, cálculo de percentual de frequência), validadores customizados, sem tocar banco real (uso de mocks ou SQLite em memória).

**Testes de Integração** (`tests/integration/`): rotas Flask completas usando `pytest-flask`/test client, banco SQLite em memória por teste, cobrindo:
- Fluxo de autenticação (login válido/inválido, bloqueio por tentativas).
- Autorização por papel (professor não acessa turma de outro professor — teste de IDOR).
- CRUD completo de cada módulo principal (alunos, turmas, matrículas, notas, frequência).
- Regras de negócio críticas (matrícula duplicada no mesmo ano deve falhar, nota fora do intervalo válido deve falhar).

**Testes de Regressão**: suíte completa executada antes de cada merge para `develop`/`main` (idealmente via CI — GitHub Actions).

**Testes Manuais/Aceitação**: checklist de responsividade (Chrome DevTools + dispositivo real Android/iPhone) para cada tela antes do fechamento de cada fase do roadmap.

**Cobertura mínima recomendada**: 80% para `services/`, 60% geral, com foco em regras de negócio e autorização acima de cobertura de template/rota trivial.

**Dados de teste**: script de seed (`scripts/seed_dados.py`) para gerar massa de dados fictícios e permitir testes exploratórios consistentes.

## 18. Estratégia de Backup dos Dados

- **Desenvolvimento**: arquivo SQLite versionado apenas como schema (não como dados); dados de teste gerados via seed.
- **Produção (PostgreSQL)**:
  - Backup automático diário via `pg_dump`, agendado (cron) fora do horário escolar.
  - Retenção: diários por 14 dias, semanais por 3 meses, mensais por 1 ano (ajustável à política da escola).
  - Backups armazenados **fora do mesmo servidor** (storage externo/nuvem), com criptografia em repouso.
  - Teste periódico de restauração (simulação de recuperação de desastre) — no mínimo trimestral.
  - Script dedicado (`scripts/backup_db.py`) documentando o processo, com logging de sucesso/falha e alerta (e-mail) em caso de falha do backup.
- **Antes de migrações de schema em produção**: backup manual adicional obrigatório antes de rodar `flask db upgrade`.

## 19. Estrutura para Futura Criação de um APK Android Usando o Mesmo Backend

Preparação arquitetural desde a Fase 0 (sem implementar agora):

- **Separação services vs. views**: como definido no item 3.3, toda regra de negócio vive em `app/services/`, sem dependência de `flask.request`/`session`. Isso permite que tanto as rotas HTML quanto uma futura API JSON chamem exatamente o mesmo código.
- **Blueprint `api/` dedicado**: rotas sob prefixo `/api/v1/`, retornando JSON puro, versionado desde o início (`v1`) para permitir evolução sem quebrar clientes antigos.
- **Autenticação da API**: JWT (Flask-JWT-Extended) com access/refresh token, independente da sessão de cookie usada pela versão web — o app Android nunca usará cookies de sessão.
- **Serialização**: `marshmallow`/`flask-smorest` para schemas de entrada/saída consistentes e documentação automática (OpenAPI/Swagger), facilitando o time mobile a consumir a API sem precisar ler o código Python.
- **CORS**: configurável (Flask-CORS) apenas se o app for híbrido (WebView); para app nativo puro consumindo API REST, não é estritamente necessário.
- **Endpoints prioritários para o app** (quando essa fase chegar): login, dashboard resumido, boletim do aluno, frequência, comunicados, notificações push.
- **Infra**: o mesmo backend Flask/PostgreSQL atende simultaneamente a versão web e o app Android — não é necessário backend separado, apenas a camada `api/` adicional.

Essa preparação não exige nenhum código extra agora — apenas a disciplina de manter `services/` desacoplado do Flask, o que já está no plano de arquitetura.

## 20. Recomendações para Qualidade Adequada a uma Escola Real

1. **Nunca excluir fisicamente dados acadêmicos** (aluno, nota, frequência) — usar exclusão lógica (`ativo=False`, `status=cancelado`), preservando histórico exigido legalmente.
2. **Trilha de auditoria real desde o primeiro módulo sensível** (notas/frequência), não deixar para o final — é difícil reconstruir retroativamente.
3. **Validar regras de negócio no backend, sempre**, mesmo que a interface já impeça (JS pode ser burlado).
4. **Homologação com a escola antes de produção**: rodar 2-4 semanas em paralelo ao processo manual atual antes de desligar o processo antigo.
5. **Plano de rollback**: manter processo manual/planilha como contingência no primeiro bimestre de uso real.
6. **Treinamento e manual do usuário** para secretaria e professores — a melhor arquitetura falha se o usuário final não sabe operar.
7. **Suporte definido**: canal claro (e-mail/telefone) para a escola reportar problemas, com SLA combinado.
8. **Conformidade com LGPD** desde o design (item 12), essencial por lidar com dados de menores.
9. **Ambiente de homologação separado de produção**, nunca testar diretamente com dados reais dos alunos.
10. **Monitoramento básico em produção**: logs de erro centralizados, alerta em caso de exceção não tratada (ex.: Sentry, mesmo no plano gratuito).
11. **Documentação técnica mínima** (README com setup, variáveis de ambiente, como rodar migrações) para que o projeto não dependa de uma única pessoa.
12. **Revisão de acessibilidade básica** (contraste, tamanho de fonte, navegação por teclado) — sistema será usado por professores de diferentes idades e familiaridade digital.

---

## Próximos Passos

Este documento cobre todo o planejamento solicitado. **Nenhum código foi escrito**, conforme solicitado.

Aguardando sua aprovação para iniciar a implementação a partir da **Fase 0** do roadmap (item 13).
