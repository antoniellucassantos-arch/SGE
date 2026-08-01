# API JSON e caminho para o aplicativo Android

O sistema já expõe uma API JSON versionada em `/api/v1/`. Este documento
descreve o que existe hoje e o que falta para publicar um APK Android usando o
**mesmo backend**.

---

## 1. O que já está pronto

A decisão arquitetural que viabiliza o aplicativo foi tomada no início do
projeto: **os services não conhecem `request`, `session` nem `flash`**.

```
                    ┌──────────────────┐
Interface web ─────>│                  │
Comandos CLI ──────>│    services/     │────> models/ ────> banco
Testes ────────────>│  (regra única)   │
App Android ───────>│                  │
                    └──────────────────┘
```

Consequência prática: a API não reimplementa nenhuma regra. Ela serializa o
resultado dos mesmos services usados pela web. Uma correção na regra de
cálculo de média vale para os dois clientes automaticamente.

---

## 2. Endpoints existentes

Todas as respostas usam o mesmo envelope:

```json
{"sucesso": true,  "dados": ...}
{"sucesso": false, "erro": "mensagem"}
```

### Público

```
GET /api/v1/status
```

Health check para monitoramento externo. Não expõe dado sensível.

```json
{"sucesso": true, "dados": {"aplicacao": "SGE", "versao": "1.0.0", "estado": "online"}}
```

### Autenticado

| Endpoint | Retorna |
|---|---|
| `GET /api/v1/sessao` | Usuário atual: nome, e-mail, papel, ano letivo |
| `GET /api/v1/painel/indicadores` | Contadores do painel administrativo |
| `GET /api/v1/painel/graficos` | Séries dos gráficos (série, turno, mês, situação) |
| `GET /api/v1/turmas` | Turmas do ano letivo, com vagas |
| `GET /api/v1/turmas/<id>/alunos` | Alunos matriculados na turma |
| `GET /api/v1/disciplinas` | Disciplinas ativas |
| `GET /api/v1/avisos` | Avisos destinados ao usuário, com contagem de não lidos |

As mesmas permissões e o mesmo controle de escopo da web se aplicam. Um
responsável que chamar `/api/v1/turmas/5/alunos` recebe `403` em JSON.

### Autenticação atual

Sessão por cookie — a mesma da interface web. Atende às chamadas AJAX do
próprio sistema.

---

## 3. O que falta para o aplicativo

### 3.1 Autenticação por JWT

Aplicativo nativo não usa cookie. O caminho:

```bash
pip install flask-jwt-extended
```

Acrescentar em `app/blueprints/api/rotas.py`:

```python
@bp.route("/auth/token", methods=["POST"])
def obter_token():
    """Troca credenciais por um par de tokens."""
    dados = request.get_json() or {}

    # Reaproveita exatamente o service da interface web:
    # bloqueio por tentativas, conta inativa, auditoria — tudo já vem junto.
    usuario = auth_service.autenticar(
        dados.get("email", ""), dados.get("senha", ""), request.remote_addr
    )

    return _ok({
        "access_token": create_access_token(identity=usuario.id),
        "refresh_token": create_refresh_token(identity=usuario.id),
    })
```

Requisições com `Authorization: Bearer <token>` não carregam cookie e, por
isso, não sofrem CSRF.

### 3.2 Serialização declarativa

Para muitos endpoints, montar dicionário à mão fica repetitivo:

```bash
pip install marshmallow flask-smorest
```

Ganho adicional: documentação OpenAPI/Swagger gerada automaticamente, o que
permite ao time mobile consumir a API sem ler o código Python.

### 3.3 Endpoints prioritários para o app

Na ordem de valor para o responsável:

1. `POST /api/v1/auth/token` — login
2. `GET  /api/v1/meus-alunos` — alunos vinculados ao responsável
3. `GET  /api/v1/alunos/<id>/boletim` — notas por disciplina e período
4. `GET  /api/v1/alunos/<id>/frequencia` — percentual e faltas
5. `GET  /api/v1/avisos` — já existe
6. `POST /api/v1/avisos/<id>/lido` — confirmação de leitura
7. `GET  /api/v1/alunos/<id>/horarios` — grade da turma

Para o professor, adicionalmente:

8. `GET  /api/v1/minhas-turmas`
9. `POST /api/v1/aulas/<id>/chamada` — chamada pelo celular
10. `POST /api/v1/avaliacoes/<id>/notas` — lançamento de notas

### 3.4 Notificações push

Exigem uma tabela de tokens de dispositivo:

```
dispositivos: id · usuario_id · token_push · plataforma · ativo · ultimo_uso
```

E um gancho no `aviso_service.criar` para disparar a notificação ao público
segmentado.

---

## 4. Como construir o APK

Três caminhos, do mais rápido ao mais trabalhoso:

| Abordagem | Esforço | Resultado |
|---|---|---|
| **PWA** (Progressive Web App) | Baixo | Instalável pelo navegador, funciona offline parcialmente. **Não precisa de API nova.** |
| **WebView + Capacitor** | Médio | APK na Play Store envolvendo a interface web; push nativo |
| **Nativo (Kotlin) ou Flutter** | Alto | Melhor desempenho e experiência; consome a API JSON |

### Recomendação

Comece pelo **PWA**. Basta adicionar `manifest.json` e um service worker — a
interface já é responsiva e funciona bem em celular. A escola tem o ícone na
tela inicial sem custo de desenvolvimento, e você valida se o aplicativo é
mesmo necessário antes de investir nele.

Se a Play Store for requisito (ou se push nativo for essencial), o Capacitor é
o próximo degrau, e só então o desenvolvimento nativo.

---

## 5. Infraestrutura

**Não é necessário backend separado.** A mesma instância Flask/PostgreSQL
atende simultaneamente a interface web e o aplicativo — apenas a camada
`api/` cresce.

Ajustes necessários quando o app existir:

| Item | Ação |
|---|---|
| CORS | Só é preciso para app híbrido em WebView; app nativo não sofre CORS |
| Rate limiting | Considerar limite por token, além de por IP |
| Versionamento | Manter `/api/v1/` estável; mudanças incompatíveis vão para `/api/v2/` |
| Expiração de token | Access curto (15–60 min) + refresh longo |
| Revogação | Tabela de tokens revogados, para desligamento imediato de um usuário |

---

## 6. Exemplo de consumo

```javascript
// Login
const resposta = await fetch('https://sge.escola.com.br/api/v1/auth/token', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, senha }),
});
const { dados } = await resposta.json();

// Chamadas seguintes
const boletim = await fetch(
  `https://sge.escola.com.br/api/v1/alunos/${alunoId}/boletim`,
  { headers: { Authorization: `Bearer ${dados.access_token}` } },
);
```

No próprio sistema web, use o wrapper já disponível — ele injeta o token CSRF
e trata erros de forma uniforme:

```javascript
const dados = await SGE.requisitar('/api/v1/painel/graficos');
```
