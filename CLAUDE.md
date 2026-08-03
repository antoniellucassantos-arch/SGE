# SGE — regras de trabalho

Sistema de Gestão Escolar em Flask, para uma escola real. Guarda **nota,
frequência e dado pessoal de menor de idade**. Um bug aqui não é um bug de
exercício: reprova um aluno ou vaza a ficha de saúde de uma criança.

Este arquivo tem as regras operacionais. O desenho completo está em
[PLANEJAMENTO.md](PLANEJAMENTO.md) (39 KB) e em [docs/](docs/) —
consulte quando precisar do porquê, não a cada tarefa.

---

## Camadas: quem pode importar quem

```
blueprints/  →  services/  →  models/
                    ↓
                 utils/
```

| Pasta | Faz | Nunca faz |
|---|---|---|
| `blueprints/` | Traduz HTTP ↔ service. Valida formulário, delega, devolve resposta. | Regra de negócio. Consulta direta ao banco. |
| `services/` | Regra de negócio. Conhece o banco. | Importa `request`, `session` ou `flash`. |
| `models/` | Estrutura e propriedades do dado. | Importa service ou blueprint. |
| `utils/` | Função pura. | Consulta tabela. Abre transação. |

**`services/` não pode importar `request`/`session`/`flash`.** É o que
permite o mesmo código servir a tela, a API, a CLI e os testes. Se um
service precisa saber quem é o usuário, ele recebe por parâmetro.

**`utils/` que importa model é service disfarçado** e muda de pasta. As duas
exceções são `models.enums` (vocabulário do domínio) e `services.excecoes`
(classes sem comportamento). `decoradores.py` consulta o banco porque a
camada 2 da autorização precisa olhar o registro — está documentado lá.

---

## Autorização: as duas camadas são obrigatórias

1. **Permissão funcional** — `app/utils/permissoes.py`. O papel pode fazer
   esta ação?
2. **Escopo do recurso** — `app/utils/decoradores.py`. Pode fazer sobre
   *este* registro?

Checar só a camada 1 é a vulnerabilidade que a auditoria encontrou três
vezes. As regras que saíram dela:

- **Toda rota que recebe id precisa de decorador de escopo**, não só de
  permissão. `@requer_permissao` + `@exigir_acesso_aluno()`.
- **Escopo por querystring exige validação explícita.** Os decoradores leem
  de `kwargs` (parâmetros de rota), não de `request.args`. Um `turma_id=7`
  na URL passa por eles sem ser visto — valide com `pode_acessar_turma()`.
- **Autorização também dentro do service.** API e CLI não passam por
  decorador. `salvar_notas()` chama `pode_lancar_em_vinculo()` por isso.
- **Filtre na query SQL, não no template.** Esconder linha no Jinja não
  esconde nada: o dado já foi lido e já viajou.

---

## Dado pessoal

- **Upload nunca em `static/`.** Tudo em `static/` é servido pelo servidor
  web, sem passar por login. São fotos de crianças. Vão para `uploads/` na
  raiz e saem por rota autenticada (`app/utils/arquivos.py`).
- **Nome de arquivo é UUID**, nunca `cpf.jpg` nem `<id>.jpg`.
- **Campo sensível de aluno é filtrado no service**, não no template. Ver
  `Aluno.CAMPOS_SENSIVEIS` e `aluno_service.montar_ficha()`.
- **Exportação vai para a auditoria antes da entrega**, com os filtros
  aplicados. Sem os filtros não há como saber o que saiu.

---

## Frontend

A CSP é `script-src 'self'`. Sem CDN, **sem `<script>` inline**.

Dado que o JavaScript precisa ler vai por atributo `data-*` (com `|tojson`)
ou por `<script type="application/json">` lido com `JSON.parse`. Nunca
gerado como código. Há um teste que varre as telas e falha se aparecer
`<script>` inline executável.

---

## Convenções

- **Português sem acentuação** em código, comentário e docstring. Acentos em
  texto de interface e em `.md`, sim.
- **`rotas.py`**, não `routes.py`. **`servico`/`_service`**, não `service`.
- **Commit em transação vai por `_confirmar()`**, o helper de cada service —
  ele trata `IntegrityError` e faz rollback. Não chame `db.session.commit()`
  solto no meio de uma função.
- **Nota e frequência penduram em `Matricula`, nunca em `Aluno`.** É o que
  mantém cada ano letivo isolado e o histórico correto.
- **Exclusão é lógica** (`ExclusaoLogicaMixin`) para todo dado acadêmico.
- **Comentário explica o porquê**, não o quê. Se a linha é óbvia, não
  comente; se ela existe por causa de uma armadilha, registre a armadilha.

---

## Comandos

```bash
pip install -e ".[dev]"          # dependências (fonte: pyproject.toml)
python -m pytest -q              # suíte completa
python -m ruff check . --fix     # lint
flask db upgrade                 # aplica migrations
flask db migrate -m "descricao"  # gera migration (SEMPRE revise o gerado)
flask verificar-saude            # diagnóstico da instalação
flask backup                     # backup antes de migration destrutiva
```

**Antes de qualquer migration que dropa coluna: `flask backup`.** E a
migration precisa **copiar os dados** antes do `drop` — dropar sem copiar
apaga histórico escolar. Teste `upgrade → downgrade → upgrade`.

`render_as_batch=True` já está ligado: o SQLite não faz `ALTER`/`DROP`
direto. A convenção de nomes em `app/extensions.py` é o que torna isso
possível — não a remova.

---

## Como trabalhar aqui

- **Teste primeiro para correção de bug.** Escreva o teste que falha, depois
  corrija. Sem isso não há prova de que o bug existia.
- **Não misture correção e refatoração no mesmo commit.**
- Rode a suíte antes de dizer que terminou. O hook `Stop` roda sozinho, mas
  não conte com ele para descobrir o que você já deveria saber.
- Ao mexer em cálculo de nota, pergunte: o que acontece numa escola com
  cinco períodos? E com trimestre? Já quebrou aqui uma vez.
