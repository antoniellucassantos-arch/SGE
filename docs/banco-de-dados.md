# Modelo de dados do SGE

23 tabelas organizadas em cinco grupos. Este documento descreve a estrutura,
os relacionamentos e as regras de integridade.

---

## Diagrama de relacionamentos

```
                          ┌──────────┐
                          │ usuarios │
                          └────┬─────┘
              ┌────────────────┼────────────────┬──────────────┐
              │ 1:1            │ 1:1            │ 1:1          │ 1:1
         ┌────▼───┐      ┌─────▼──────┐   ┌─────▼──────┐  ┌────▼────────┐
         │ alunos │      │professores │   │funcionarios│  │responsaveis │
         └───┬────┘      └─────┬──────┘   └────────────┘  └──────┬──────┘
             │                 │                                 │
             │  N:N (alunos_responsaveis)                        │
             └───────────────────────────────────────────────────┘
             │
             │  ┌──────────────┐        ┌────────┐      ┌───────┐
             │  │ anos_letivos │───────>│ turmas │<─────│ series│
             │  └──────┬───────┘        └───┬────┘      └───────┘
             │         │                    │      │
             │         │ 1:N                │      │ N:1
             │  ┌──────▼──────────┐         │   ┌──▼────┐
             │  │periodos_letivos │         │   │ salas │
             │  └──────┬──────────┘         │   └───────┘
             │         │                    │
             └─────────┼────────────────────┤
                       │   ┌────────────────▼──────────┐
                  ┌────▼───▼───┐        │turmas_disciplinas│───> disciplinas
                  │ matriculas │        └────┬─────────────┘
                  └─────┬──────┘             │
          ┌─────────────┼──────────┐    ┌────┴──────┬──────────┐
          │             │          │    │           │          │
      ┌───▼───┐  ┌──────▼─────┐ ┌──▼────▼──┐  ┌─────▼────┐ ┌───▼─────┐
      │ notas │  │frequencias │ │  aulas   │  │avaliacoes│ │horarios │
      └───▲───┘  └──────▲─────┘ └──────────┘  └────┬─────┘ └────┬────┘
          │             │                          │            │
          └─────────────┴──────────────────────────┘       ┌────▼──────┐
                                                            │tempos_aula│
                                                            └───────────┘

   resultados_disciplinas ──> matriculas + turmas_disciplinas

   avisos ──< avisos_leituras >── usuarios
   configuracoes_escola · logs_auditoria · registros_backup
```

---

## Grupo 1 — Identidade e acesso

### `usuarios`

Conta de acesso. Guarda **identidade e credenciais**; os dados específicos de
cada papel ficam nas tabelas de perfil.

| Campo | Tipo | Observações |
|---|---|---|
| `id` | Integer PK | |
| `nome_completo` | String(150) | |
| `nome_normalizado` | String(150) | Sem acentos, minúsculo — indexado para busca |
| `email` | String(150) | **Único**, login do sistema |
| `cpf` | String(11) | Único quando informado |
| `senha_hash` | String(255) | Argon2id |
| `papel` | Enum | administrador, direcao, secretaria, professor, aluno, responsavel |
| `ativo` | Boolean | Conta inativa não autentica |
| `deve_trocar_senha` | Boolean | Força troca no próximo acesso |
| `tentativas_falhas` | Integer | Contador para bloqueio |
| `bloqueado_ate` | DateTime | Bloqueio temporário |
| `ultimo_login_em` / `_ip` | DateTime / String(45) | Auditoria de acesso |

**Índices:** `(papel, ativo)` para as listagens; `nome_normalizado` para busca.

### Por que separar identidade de perfil

1. **Alunos pequenos não têm login.** `alunos.usuario_id` é opcional — a
   secretaria cadastra a criança sem inventar um e-mail para ela.
2. **Uma pessoa pode acumular papéis.** Um professor que também é pai de aluno
   usa o mesmo login para os dois perfis.
3. **Desligamento não apaga histórico.** Desativar o usuário corta o acesso;
   o perfil e o histórico acadêmico permanecem.

---

## Grupo 2 — Pessoas

Todas herdam `PessoaMixin` (nome, nome social, nascimento, sexo, CPF, RG,
telefones, e-mail, endereço, situação, foto, observações).

### `alunos`

Acrescenta: `codigo` (RA único, formato `AAAANNNNN`), naturalidade,
certidão de nascimento, NIS, cartão SUS, dados de saúde (tipo sanguíneo,
alergias, medicamentos, condições, deficiência), benefícios (bolsista,
transporte escolar) e autorizações (sair sozinho, uso de imagem).

> Os campos de saúde são dados sensíveis (LGPD art. 11). São visíveis apenas
> para perfis com `aluno.ver_dados_sensiveis` — administrador, direção e
> secretaria. Professores não os acessam.

### `professores`

Acrescenta: `registro_funcional` (único), formação, titulação, instituição,
admissão, desligamento, carga horária contratual, estado civil.

### `funcionarios`

Acrescenta: `matricula_funcional` (única), cargo, setor, admissão,
desligamento, carga horária.

### `responsaveis`

Acrescenta: profissão, local de trabalho, telefone comercial. CPF é
**obrigatório** — é o documento usado em contratos e declarações.

### `alunos_responsaveis`

Vínculo N:N com atributos próprios, o que a torna uma entidade de domínio:

| Campo | Observações |
|---|---|
| `parentesco` | mãe, pai, avô, tio, irmão, tutor legal, outro |
| `responsavel_legal` | Responde juridicamente pelo aluno |
| `responsavel_financeiro` | Apenas um por aluno (garantido pelo service) |
| `autorizado_buscar` | Pode retirar o aluno da escola |
| `ordem_contato` | Ordem de acionamento em emergência |

**Regra:** um aluno menor de idade não pode ficar sem responsável legal. O
service recusa a remoção do último vínculo legal.

---

## Grupo 3 — Estrutura acadêmica

### `anos_letivos`

| Campo | Observações |
|---|---|
| `ano` | Único |
| `data_inicio` / `data_fim` | `CHECK (data_fim > data_inicio)` |
| `situacao` | planejamento · em_andamento · encerrado |
| `corrente` | Apenas um ano marcado; define o contexto padrão do sistema |
| `media_aprovacao`, `media_recuperacao`, `frequencia_minima`, `nota_maxima` | **Cópia das regras vigentes naquele ano** |

> As regras ficam no ano letivo, não em constantes no código. Alterar os
> parâmetros gerais em 2027 não reescreve os resultados apurados em 2026.
> Ano encerrado torna notas e frequência somente leitura.

### `periodos_letivos`

Bimestres ou trimestres. `UNIQUE(ano_letivo_id, ordem)`. Um período encerrado
bloqueia novas avaliações.

### `series`, `salas`, `disciplinas`

- **Séries** são independentes do ano letivo: "9º Ano" existe todos os anos.
- **Disciplinas** têm código curto (usado em boletins) e cor (usada na grade).
- **Salas** registram capacidade e recursos (projetor, ar-condicionado,
  acessibilidade).

### `turmas`

`UNIQUE(ano_letivo_id, serie_id, nome)` — não existem duas turmas "A" da mesma
série no mesmo ano. `CHECK (capacidade > 0)`.

### `turmas_disciplinas`

**Entidade central do módulo acadêmico.** Liga turma × disciplina × professor.
Aulas, avaliações e horários apontam para este vínculo, não para a turma ou a
disciplina isoladamente.

Isso responde com uma consulta "quem leciona o quê, para quem" — e sustenta
todo o controle de escopo do professor.

`UNIQUE(turma_id, disciplina_id)`.

---

## Grupo 4 — Vida escolar

### `matriculas`

| Campo | Observações |
|---|---|
| `numero` | Único, formato `AAAA-NNNNN`, impresso em declarações |
| `situacao` | ativa · trancada · transferida · cancelada · concluída |
| `resultado_final` | aprovado · aprovado_conselho · recuperação · reprovado · reprovado_falta · cursando |
| `media_geral`, `percentual_frequencia`, `total_faltas` | Consolidação anual |
| `escola_origem` / `escola_destino` | Transferências |

`UNIQUE(aluno_id, ano_letivo_id, turma_id)`. A regra "apenas uma ativa por
ano" é reforçada no service, porque uma matrícula cancelada e outra ativa no
mesmo ano são legítimas (aluno cancelou e voltou no segundo semestre).

### `aulas` e `frequencias`

Duas tabelas em vez de "gravar apenas as faltas". **Motivo:** sem o registro
da aula não há como distinguir "aluno presente" de "chamada nunca feita", e o
percentual do boletim ficaria incorreto. Com o registro explícito, a
coordenação consegue cobrar chamadas pendentes.

- `aulas`: `UNIQUE(turma_disciplina_id, data_aula, ordem_no_dia)` — a ordem
  permite aulas geminadas. `quantidade_aulas` conta para o percentual legal.
- `frequencias`: `UNIQUE(aula_id, matricula_id)`. Situação: presente · falta ·
  falta justificada · atraso.

> Atraso e falta justificada **contam como presença** no cálculo legal de
> frequência, mas são registrados separadamente para acompanhamento
> pedagógico.

### `avaliacoes`, `notas`, `resultados_disciplinas`

- `avaliacoes`: peso, valor máximo, tipo, período, flag `publicada` (enquanto
  falsa, as notas ficam visíveis só ao professor).
- `notas`: `valor` é **nullable** de propósito — vazio significa "não
  lançada", diferente de zero ("tirou zero"). Confundir os dois é um erro
  grave em boletim. `ausente` marca falta na avaliação.
- `resultados_disciplinas`: tabela derivada, recalculada pelo service.
  Existe por dois motivos: (1) o boletim de uma turma exigiria dezenas de
  agregações em tempo real; (2) o resultado apurado no fechamento deve
  permanecer congelado.

### Cálculo de médias

```
media_periodo = Σ(nota_i × peso_i) / Σ(peso_i)
```

- Avaliações de **recuperação** ficam fora da média ponderada; elas
  *substituem* o resultado quando forem maiores.
- Notas em escala diferente (trabalho de 20 pontos) são normalizadas para 0–10.
- `media_anual` = média aritmética das médias de período lançadas.
- `media_final` = maior entre média anual e recuperação final.

### Apuração do resultado

Na ordem:

1. **Frequência mínima** — a LDB reprova por falta independentemente da nota.
   Só é apurada com pelo menos 20 aulas, para não reprovar alguém no início do
   ano por duas ausências.
2. **Média** — `>= media_aprovacao` aprova; `>= media_recuperacao` vai para
   recuperação; abaixo disso, reprova.
3. Sem nota lançada, o resultado é "cursando".

---

## Grupo 5 — Grade, comunicação e infraestrutura

### `tempos_aula` e `horarios`

- `tempos_aula`: slots por turno (1º tempo, intervalo...).
  `UNIQUE(turno, ordem)`, `CHECK (hora_fim > hora_inicio)`.
- `horarios`: aloca um `turma_disciplina` em dia × tempo.
  `UNIQUE(turma_id, dia_semana, tempo_aula_id)`.

O banco garante que a turma não tenha duas aulas no mesmo horário. Os outros
dois conflitos — professor em duas turmas, sala ocupada — são detectados pelo
service, que devolve mensagem útil ("Prof. Ana já leciona para o 9º A neste
horário") em vez de um erro de integridade opaco.

`dia_semana` é gravado como índice ISO (1 = segunda), o que permite ordenar a
grade no banco e comparar com `date.isoweekday()`.

### `avisos` e `avisos_leituras`

Segmentação por público: todos · equipe · professores · alunos · responsáveis
· turma específica.

`avisos_leituras` registra quem leu e quando. Sem essa tabela, a escola não
tem como provar que um comunicado importante chegou ao responsável.

### `configuracoes_escola`

Tabela de **linha única** (`id = 1`). Modelar como tabela — e não como arquivo
de configuração — permite que a secretaria altere logo, cabeçalho dos
documentos e regras acadêmicas pela própria interface, sem depender de um
desenvolvedor e sem reiniciar a aplicação.

### `logs_auditoria`

Trilha **imutável**. Não há rota de edição nem de exclusão individual — por
definição, um registro alterável não serve como evidência.

| Campo | Observações |
|---|---|
| `usuario_id` | Nulo em eventos anônimos (falha de login com e-mail inexistente) |
| `usuario_nome` | **Cópia** do nome no momento do evento — a trilha sobrevive à exclusão da conta |
| `acao` | criação · atualização · exclusão · login · falha de login · acesso negado · backup · exportação · **acesso a dado pessoal** · **consentimento** |
| `detalhes` | JSON com o *delta* (antes/depois), com campos sensíveis mascarados |
| `endereco_ip`, `navegador`, `rota` | Contexto da requisição |

Eventos negativos (falha de login, acesso negado) são gravados em sessão
própria com commit imediato — a transação principal sofre rollback logo em
seguida, e o registro do incidente seria perdido junto. `acesso_dado_pessoal`
usa o mesmo caminho por outro motivo: abrir uma ficha é um `GET`, e sem
commit próprio o registro morreria no teardown.

### `consentimentos_lgpd`

Uma decisão da família sobre uma finalidade de tratamento, para um aluno.

| Campo | Observações |
|---|---|
| `finalidade` | O que a escola quer fazer com o dado (`FinalidadeTratamento`) |
| `base_legal` | **Cópia** da base declarada pela finalidade na época — se a escola reclassificar amanhã, os registros antigos continuam dizendo sob qual hipótese a decisão foi tomada |
| `concedido` | Um "não" também precisa constar: decisão tomada ≠ pendência |
| `responsavel_id` / `responsavel_nome` | Quem decidiu, com cópia do nome |
| `registrado_por_id` | Quem da escola lançou no sistema |
| `documento` | Referência ao termo assinado |
| `revogado_em` | Preenchido quando esta decisão deixa de valer |

Tabela **append-only**: revogar não apaga nem edita o registro anterior. O
estado atual de uma finalidade é o último registro dela — daí o índice
`(aluno_id, finalidade, id)`.

### `registros_backup`

Histórico de backups, incluindo os que **falharam** (`sucesso=False` com a
mensagem de erro). Assim a escola enxerga a tentativa malsucedida, em vez de
simplesmente não ver backup nenhum.

---

## Índices e desempenho

Pensando em milhares de alunos:

| Índice | Consulta que atende |
|---|---|
| `usuarios(papel, ativo)` | Listagem de contas por perfil |
| `alunos(situacao, nome_normalizado)` | Listagem com busca e filtro |
| `alunos(nome_normalizado)` | Busca textual sem acento |
| `matriculas(turma_id, situacao)` | Lista de chamada da turma |
| `matriculas(ano_letivo_id, situacao)` | Indicadores do painel |
| `frequencias(matricula_id, situacao)` | Apuração de frequência |
| `notas(matricula_id)` | Boletim do aluno |
| `aulas(data_aula)` | Chamadas pendentes |
| `horarios(dia_semana, tempo_aula_id)` | Detecção de conflito |
| `logs_auditoria(usuario_id, criado_em)` | Consulta de auditoria |

**Regras de consulta adotadas:**

- Contagens usam `COUNT` no banco, nunca `len(colecao)`.
- Listagens são sempre paginadas, com teto no `por_pagina` (impede
  `?por_pagina=100000` derrubar o servidor).
- Ordenação aceita apenas colunas de uma lista de permissão — o nome vindo da
  URL nunca chega ao SQL.
- `pool_pre_ping` evita o erro "server closed the connection unexpectedly" em
  PostgreSQL.

---

## Migrações

```bash
flask db migrate -m "descrição da mudança"   # gera
flask db upgrade                             # aplica
flask db downgrade                           # reverte a anterior
```

**Sempre revise o arquivo gerado** antes de aplicar. O autogenerate do Alembic
não detecta renomeações (interpreta como drop + add, o que apaga dados) nem
mudanças de tipo com conversão.

**Antes de migrar em produção, gere um backup manual:**

```bash
flask backup
flask db upgrade
```
