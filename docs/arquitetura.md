# Arquitetura do SGE

Documento para quem vai manter ou estender o sistema. Explica **por que** as
decisões foram tomadas, não apenas o que existe.

---

## 1. Visão geral

Monolito modular servido por Flask, organizado em três camadas:

```
blueprints/  →  services/  →  models/  →  banco
   (HTTP)      (negócio)      (dados)
```

A dependência é sempre para baixo. Um *service* nunca importa um blueprint;
um *model* nunca importa um service. Isso mantém o grafo acíclico e permite
testar cada camada isoladamente.

### Por que monolito

Uma escola de porte médio tem dezenas de usuários simultâneos, não milhares.
Microsserviços aqui adicionariam latência de rede, complexidade de deploy e
consistência eventual — custos reais sem benefício correspondente. A
modularidade interna já dá o que importa: limites claros e código navegável.

---

## 2. Application Factory

`create_app()` constrói a aplicação; nenhum objeto `Flask` é criado no import.

```python
app = create_app("production")
```

Isso permite:

- subir com configurações diferentes (dev, teste, produção);
- criar uma instância isolada por teste, sem vazamento de estado;
- evitar import circular entre models, services e blueprints.

**Ordem de inicialização** (cada etapa depende da anterior):

```
configuração → logging → proxy → extensões → models
→ blueprints → handlers de erro → hooks → Jinja → CLI
```

### Registro declarativo de blueprints

A lista `BLUEPRINTS` no topo de `app/__init__.py` declara módulo, atributo e
prefixo de URL. Saber o que existe e em qual endereço é ler uma lista — não
caçar `register_blueprint` espalhados pelo código.

---

## 3. Camada de serviços

### O contrato

1. Services **não** conhecem `request`, `session` nem `flash`.
2. Recebem dados já validados; devolvem objetos ou lançam exceções de domínio.
3. Controlam a transação (`commit`/`rollback`).

### Por que isso importa

O mesmo código atende a quatro consumidores sem reescrita:

| Consumidor | Situação |
|---|---|
| Interface web | Hoje |
| Comandos CLI | Hoje (`flask criar-admin`, seed, backup) |
| Testes | Hoje — testam a regra sem simular HTTP |
| API do app Android | Futuro — só precisa da camada de serialização |

Se os services chamassem `abort(400)` ou lessem `request.form`, cada novo
consumidor exigiria duplicar a regra. Duplicação de regra de negócio é como
notas divergentes entre a tela e o boletim.

### Exceções de domínio

```
ErroDominio (raiz)
├── ErroValidacao        400 — dados inválidos segundo o negócio
├── ErroRegraNegocio     409 — operação proibida pelas regras da escola
├── RegistroNaoEncontrado 404
├── ErroPermissao        403
├── ErroAutenticacao     401
├── ErroConflito         409 — violação de unicidade
├── ErroArquivo          400 — upload inválido
└── ErroOperacaoBanco    500 — falha de persistência, já com rollback
```

Cada camada decide como reagir. O handler global em `app/__init__.py`:

- **403 e 404** → renderiza a página de erro com o código HTTP correto.
  Um `302` diria "sua requisição foi aceita" quando foi negada — enganoso
  para o usuário e para o monitoramento.
- **Demais** → `flash` + redirect de volta. São erros previsíveis e
  corrigíveis (turma lotada, matrícula duplicada): a pessoa volta para onde
  estava, com a explicação.

> Detalhe de implementação: a página é renderizada diretamente, não com
> `abort()`. Uma exceção levantada **dentro** de um error handler não é
> redespachada pelo Flask — ela sobe como erro não tratado.

---

## 4. Modelagem de dados

### Matrícula como âncora

Notas e frequência apontam para `Matricula`, nunca para `Aluno`.

```
Aluno ──< Matricula >── Turma
              │
              ├──< Nota
              ├──< Frequencia
              └──< ResultadoDisciplina
```

**Motivo:** um aluno reprovado cursa a mesma disciplina em dois anos. Se as
notas apontassem para o aluno, os dois anos se misturariam e o histórico
escolar sairia errado. Ancorando em `Matricula`, cada ano letivo mantém seu
conjunto isolado e auditável.

### Pessoas: mixin de colunas, não tabela compartilhada

Aluno, professor, funcionário e responsável compartilham dados civis. Duas
opções foram consideradas:

| Abordagem | Prós | Contras |
|---|---|---|
| Tabela `pessoas` + herança | "Mais normalizado" | `JOIN` extra em **toda** consulta, incluindo listagens paginadas e relatórios |
| **Mixin de colunas** (adotada) | Consultas diretas, índices por tabela | Estrutura semelhante repetida |

Repetir *colunas* não viola normalização — normalização trata de redundância
de **dados** dentro de uma relação, não de semelhança estrutural entre
relações distintas. Cada CPF existe uma única vez, com restrição de unicidade
própria.

O caso "uma pessoa acumula papéis" (professor que também é pai de aluno) é
resolvido pelo vínculo com `Usuario`, não por duplicação.

### Exclusão sempre lógica

Dados acadêmicos usam `ExclusaoLogicaMixin`. A escola tem obrigação legal de
preservar histórico escolar, e uma exclusão acidental de aluno seria
irreversível.

Além disso, há travas de integridade no service:

- aluno com matrícula ativa não pode ser excluído;
- turma com alunos matriculados não pode ser excluída;
- disciplina vinculada a turmas não pode ser excluída;
- vínculo com aulas ou avaliações lançadas não pode ser removido.

### Enums como strings estáveis

`EnumDominio` herda de `str`. O valor gravado é `"ativo"`, não um inteiro.

- O dump do banco continua legível por um humano.
- Evita o `ALTER TYPE` do `Enum` nativo do PostgreSQL, que exige migração
  para adicionar um valor.
- `native_enum=False` mantém a portabilidade entre SQLite e PostgreSQL.

Cada membro carrega rótulo e cor Bootstrap, o que elimina `if/elif` de
tradução espalhados pelos templates.

### Convenção de nomes das constraints

`app/extensions.py` define `CONVENCAO_NOMES` no metadata. Sem isso, o SQLite
gera constraints anônimas e o Alembic não consegue aplicar `ALTER`/`DROP` em
migrações futuras — o erro "Constraint must have a name" aparece justamente
na primeira alteração de esquema em produção.

---

## 5. Autorização em duas camadas

```python
@bp.route("/alunos/<int:aluno_id>")
@requer_permissao(Permissao.ALUNO_VISUALIZAR)   # camada 1: o perfil pode?
@exigir_acesso_aluno()                          # camada 2: pode este aluno?
def detalhe(aluno_id):
    ...
```

| Camada | Onde | Pergunta |
|---|---|---|
| Permissão funcional | `utils/permissoes.py` | O perfil pode executar a ação? |
| Escopo do recurso | `utils/decoradores.py` + services | Pode agir sobre *este* registro? |

Verificar apenas a camada 1 produz **Broken Access Control** (OWASP A01): o
responsável tem permissão de ver boletim, e sem a camada 2 veria o boletim de
qualquer aluno trocando o ID na URL.

A matriz concede permissões **explicitamente** por perfil, sem herança
implícita. É mais verboso, mas auditável: para saber o que a secretaria pode
fazer, lê-se uma lista.

Esconder o botão no menu é usabilidade, nunca segurança. A rota permanece
protegida pelo decorador.

---

## 6. Front-end

### Sem CDN

A CSP define `script-src 'self'`. Bootstrap, Bootstrap Icons e Chart.js são
servidos de `static/vendor/`.

Ganhos: funciona sem internet externa, não vaza navegação dos usuários para
terceiros, e não quebra se um CDN sair do ar.

### Gráficos sem script inline

Dados vão em atributos `data-*` serializados com `|tojson`; `graficos.js` lê e
desenha. Além de respeitar a CSP, isso elimina por construção o XSS por
interpolação de variável dentro de `<script>`.

### Responsividade

| Recurso | Motivo |
|---|---|
| Sidebar vira gaveta abaixo de 992px | Tela pequena não comporta menu fixo |
| `font-size: 16px` nos inputs | Abaixo disso o Safari do iPhone dá zoom ao focar |
| Alvos de toque ≥ 40px | Professor faz chamada em pé, no tablet |
| Tabelas com rolagem própria | O corpo da página nunca rola na horizontal |
| Ações de formulário fixas no rodapé (mobile) | Botão salvar sempre alcançável |

---

## 7. Pontos de atenção para quem for estender

**Ao criar um novo módulo:**

1. Model em `models/`, exportado em `models/__init__.py`.
2. Regras em `services/` — sem `request`, sem `flash`.
3. Blueprint em `blueprints/<nome>/` com `rotas.py` e `formularios.py`.
4. Registrar em `BLUEPRINTS` no `app/__init__.py`.
5. Permissões novas em `utils/permissoes.py`, concedidas por perfil.
6. Migração: `flask db migrate -m "descrição"` e revisar o arquivo gerado.
7. Testes: regra de negócio e, principalmente, **negações de acesso**.

**Armadilhas conhecidas:**

- `len(turma.matriculas)` carrega todas as linhas para contar. Use
  `turma.contar_matriculas_ativas()`, que conta no banco.
- Nota `None` significa "não lançada"; zero significa "tirou zero". Confundir
  os dois produz boletim errado.
- Campo desabilitado no HTML não é enviado no POST. O serviço de notas trata
  isso considerando a união de notas informadas e ausências marcadas.
- Ao adicionar rota com parâmetro de ID, acrescente-o à fixture
  `base_completa` em `tests/integration/test_rotas.py` — o teste falha
  explicitamente pedindo isso.
