---
description: Cria um módulo completo do SGE seguindo o checklist da arquitetura (model → service → form → blueprint → template → teste → migration).
argument-hint: <nome-do-modulo>
---

Crie o módulo **$1** no SGE, seguindo o checklist abaixo na ordem.

Antes de começar, leia `CLAUDE.md` e um módulo existente de porte parecido
(`app/blueprints/turmas/` é um bom espelho) para herdar as convenções em vez
de reinventá-las.

## Checklist

### 1. Model — `app/models/`
- Herda `ModeloBase`; `TimestampMixin` e `ExclusaoLogicaMixin` quando fizer
  sentido (dado acadêmico é exclusão lógica).
- Enums em `app/models/enums.py`, sempre `EnumDominio` com rótulo e cor.
- `native_enum=False` nas colunas de enum — portabilidade SQLite/PostgreSQL.
- Se o dado é acadêmico, ele pendura em `Matricula`, **não** em `Aluno`.
- Importe o novo model em `app/models/__init__.py`, senão o Alembic não o vê.

### 2. Service — `app/services/<nome>_service.py`
- Toda a regra de negócio. **Não importe `request`, `session` nem `flash`.**
- Autorização por dentro, para API e CLI: o decorador de rota não roda lá.
- Commit via `_confirmar()`, no padrão dos outros services.
- Exceções de domínio (`ErroValidacao`, `ErroRegraNegocio`, `ErroPermissao`)
  em vez de retornar `None` ou `False`.
- Auditoria nas ações que alteram dado.

### 3. Formulário — `app/blueprints/<nome>/formularios.py`
- WTForms com validação de entrada e mensagens em português.
- Reaproveite os validadores de `app/utils/validadores.py`.

### 4. Blueprint — `app/blueprints/<nome>/`
- `__init__.py` cria o `Blueprint`; `rotas.py` fica fino: valida, delega,
  responde.
- **Toda rota que recebe id leva decorador de escopo**, além da permissão.
- Escopo vindo de querystring é validado explicitamente — os decoradores
  não enxergam `request.args`.
- Registre em `BLUEPRINTS`, em `app/blueprints/__init__.py`.

### 5. Permissões — `app/utils/permissoes.py`
- Constantes novas em `Permissao`, no formato `recurso.acao`.
- Conceda por papel, explicitamente. Não repita o que já está em
  `PERMISSOES_COMUNS`.

### 6. Templates — `app/templates/<nome>/`
- Estenda `base.html`. Reaproveite os componentes de `_componentes.html`.
- Sem `<script>` inline: a CSP é `script-src 'self'`.
- Esconder botão é usabilidade, não segurança — a rota continua protegida.

### 7. Testes — `tests/`
- Autorização: o caso negado **e** o permitido.
- Regra de negócio do service.
- Varredura de rota, se o módulo expõe listagem.

### 8. Migration
```bash
flask backup
flask db migrate -m "adiciona <nome>"
```
**Revise o arquivo gerado antes de aplicar.** O Alembic erra em `ALTER` de
SQLite e em mudança de enum. Se a migration dropa coluna, ela precisa copiar
os dados antes. Teste `upgrade → downgrade → upgrade`.

### 9. Fechamento
```bash
python -m pytest -q
python -m ruff check . --fix
```

Ao terminar, relate: arquivos criados, arquivos modificados, decisões
técnicas e o que ficou de fora.
