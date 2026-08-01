# Segurança do SGE

O sistema guarda dados de menores de idade. Este documento descreve o modelo
de ameaças considerado, as defesas implementadas e o que **ainda precisa ser
feito** pela escola antes de operar em produção.

---

## 1. Autenticação

### Hash de senha: Argon2id

Escolhido em vez do PBKDF2 padrão do Werkzeug. Argon2id venceu a Password
Hashing Competition e é a recomendação atual da OWASP: resiste tanto a ataques
por GPU quanto a *side-channel*.

Parâmetros (`app/utils/seguranca.py`): `time_cost=3`, `memory_cost=64 MiB`,
`parallelism=2`. Calibrados para ~50–100 ms por hash — forte contra força
bruta offline, rápido o suficiente para não travar o login.

**Migração transparente:** hashes legados do Werkzeug continuam válidos e são
regravados em Argon2id no próximo login bem-sucedido. Nenhum usuário precisa
trocar de senha.

### Política de senha

Configurável por `.env`. Padrão: mínimo 8 caracteres, com maiúscula, minúscula
e número. Além disso, o validador rejeita:

- senhas de uma lista de comuns (`senha123`, `admin123`, `escola123`...);
- quatro caracteres iguais seguidos (`aaaa1234`);
- sequências óbvias (`1234`, `abcd`, `qwer`).

Todos os problemas são reportados de uma vez — não faz o usuário descobrir as
regras uma por uma.

### Proteção contra força bruta

Duas camadas:

| Camada | Onde | Efeito |
|---|---|---|
| Rate limiting | Flask-Limiter, por IP | 10 tentativas/minuto no login |
| Bloqueio de conta | `Usuario.registrar_falha_login` | Bloqueio temporário após N tentativas |

Após o bloqueio, **nem a senha correta** entra até o prazo expirar. Um
administrador pode desbloquear manualmente.

### Não revelar quais contas existem

Login com e-mail inexistente e login com senha errada devolvem exatamente a
mesma mensagem. A recuperação de senha responde igual exista ou não o e-mail.
Sem isso, um atacante enumera as contas da escola.

### Recuperação de senha

Token assinado (`itsdangerous`), sem estado no servidor — funciona com
múltiplos processos Gunicorn. O payload inclui os últimos 24 caracteres do
hash atual: **trocar a senha invalida todos os tokens emitidos antes**, o que
torna o token de uso único sem precisar de tabela de controle.

Validade padrão: 30 minutos.

---

## 2. Autorização

Detalhado em [arquitetura.md](arquitetura.md#5-autorização-em-duas-camadas).
Resumo:

```python
@requer_permissao(Permissao.ALUNO_VISUALIZAR)   # o perfil pode?
@exigir_acesso_aluno()                          # pode ESTE aluno?
```

**Broken Access Control (OWASP A01)** é a falha mais comum e mais grave em
sistemas escolares. Verificar apenas o perfil deixaria o responsável ver o
boletim de qualquer aluno trocando o ID na URL.

Os testes em `tests/integration/test_autorizacao.py` cobrem explicitamente as
negações:

- responsável não acessa boletim, frequência nem ficha de aluno não vinculado;
- professor não acessa diário nem notas de turma que não leciona;
- professor não **lança** nota em turma alheia (barrar leitura não basta);
- secretaria não acessa usuários, backup nem auditoria.

Contas inativas, excluídas ou bloqueadas perdem **todas** as permissões, mesmo
com sessão ativa — a desativação de um funcionário desligado tem efeito
imediato.

### Travas administrativas

- Um administrador não pode rebaixar nem desativar a própria conta.
- O sistema recusa remover o último administrador ativo.

---

## 3. Sessão e cookies

| Configuração | Valor | Motivo |
|---|---|---|
| `HttpOnly` | sempre | JavaScript não lê o cookie (mitiga roubo via XSS) |
| `SameSite` | `Lax` | Bloqueia envio em navegação cross-site |
| `Secure` | produção | Cookie só trafega em HTTPS |
| `PERMANENT_SESSION_LIFETIME` | 120 min | Expiração por inatividade |
| `session_protection` | `strong` | Flask-Login invalida sessão se o contexto mudar |

---

## 4. Proteção das requisições

### CSRF

Token em todos os formulários via Flask-WTF. O blueprint da API **não** é
isento: como todas as rotas atuais são `GET`, o Flask-WTF não as intercepta,
e rotas de escrita futuras já nascem protegidas.

O JavaScript envia o token em `X-CSRFToken` (ver `SGE.requisitar`).

### Open redirect

O parâmetro `next` do login é validado contra o próprio host antes do
redirecionamento. Sem isso, `?next=https://site-falso` levaria o usuário
recém-autenticado para fora do domínio — técnica clássica de phishing.

### Cabeçalhos de segurança

Aplicados em toda resposta (`app/__init__.py`):

```
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: geolocation=(), microphone=(), camera=()
Content-Security-Policy: default-src 'self'; script-src 'self'; ...
Strict-Transport-Security: max-age=31536000  (apenas com HTTPS)
```

Implementados manualmente, e não via Flask-Talisman, para manter a lista
explícita e auditável — e uma dependência a menos.

### CSP sem script inline

`script-src 'self'` proíbe qualquer `<script>` inline. Consequências no
projeto:

- Bootstrap, Bootstrap Icons e Chart.js servidos de `static/vendor/`.
- Dados de gráfico vão em atributos `data-*`, lidos por `graficos.js`.

Isso elimina **por construção** o XSS por interpolação de variável dentro de
`<script>` — mesmo que alguém escreva o código errado no futuro, o navegador
não executa.

`'unsafe-inline'` é liberado apenas em `style-src`, concessão pontual ao
Bootstrap.

---

## 5. Entrada de dados

### Injeção de SQL

Exclusivamente ORM com consultas parametrizadas. Nenhuma concatenação de SQL
no projeto.

A ordenação de listagens usa **lista de permissão**: o nome da coluna vindo da
URL é validado contra um dicionário antes de chegar ao SQL. Sem isso,
`?ordenar=<expressão>` seria vetor de injeção e de vazamento de estrutura.

### XSS

Autoescape do Jinja2 ativo. O filtro `quebra_linha` é seguro por construção:
o Jinja escapa o texto **antes** do filtro rodar, então apenas as tags geradas
pelo próprio filtro são HTML.

O sistema não usa `|safe` com dado de usuário em lugar nenhum.

### Upload de arquivos

Defesa em cinco camadas (`app/utils/arquivos.py`):

1. **Extensão em lista de permissão** — nunca lista de bloqueio.
2. **Assinatura binária verificada** — um `.php` renomeado para `.jpg` falha.
3. **Nome gerado pelo servidor** — elimina *path traversal* e colisões; o
   componente aleatório impede adivinhar a URL da foto de um aluno.
4. **Reencodificação da imagem** — descarta metadados EXIF (que trazem
   geolocalização) e qualquer payload escondido.
5. **Limite de tamanho** — `MAX_CONTENT_LENGTH`, padrão 8 MB.

A remoção de arquivo valida que o caminho resolvido permanece dentro da pasta
de uploads.

---

## 6. Auditoria

Trilha imutável em `logs_auditoria`. Não existe rota de edição ou exclusão
individual.

Registra: criação, atualização (com o *delta* antes/depois), exclusão, login,
falha de login, acesso negado, alteração de senha, backup, restauração e
exportação.

**Decisões de implementação:**

- **Falha silenciosa proposital.** Se a gravação do log falhar, a operação do
  usuário não é abortada — a escola não pode ficar sem lançar notas porque a
  auditoria teve um problema. A falha vai para o log da aplicação.
- **Sessão separada para eventos negativos.** Falha de login e acesso negado
  são gravados com commit imediato, porque a transação principal sofre
  rollback logo em seguida.
- **Cópia do nome do usuário.** A trilha permanece legível mesmo após a
  exclusão da conta.
- **Campos sensíveis mascarados.** Senhas e tokens nunca aparecem no detalhe.

---

## 7. LGPD

| Requisito | Implementação |
|---|---|
| Minimização | Listagens exibem CPF parcial; ficha completa exige permissão específica |
| Dados sensíveis (art. 11) | Saúde e deficiência visíveis apenas a administrador, direção e secretaria |
| Consentimento | Autorização de uso de imagem registrada por aluno |
| Geolocalização | EXIF removido de toda imagem enviada |
| Rastreabilidade | Auditoria registra quem acessou e alterou o quê |
| Retenção | Comando `flask limpar-auditoria --dias N` |

**Pendente para a escola:** publicar a política de privacidade, designar o
encarregado de dados (DPO) e definir o procedimento de atendimento a
solicitações de titulares.

---

## 8. Backup

Ver [implantacao.md](implantacao.md#backup). Pontos de segurança:

- SQLite usa a API `sqlite3.Connection.backup()`, que garante consistência
  transacional — copiar o arquivo com `shutil.copy` pode capturar estado
  corrompido.
- PostgreSQL usa `pg_dump` com argumentos em lista (nunca `shell=True`) e
  senha por variável de ambiente `PGPASSWORD` — na linha de comando ela ficaria
  visível para qualquer usuário do servidor via `ps`.
- Backups parciais de tentativas falhas são removidos do disco, para que
  ninguém tente restaurá-los.
- O download valida que o caminho resolvido está dentro da pasta de backups.
- **A restauração não é automatizada pela web.** Ela sobrescreve o banco
  inteiro e é irreversível; um clique acidental destruiria o ano letivo. O
  sistema exibe as instruções para execução no servidor.

---

## 9. Checklist antes de operar em produção

### Obrigatório

- [ ] `SECRET_KEY` forte no `.env` (a aplicação **se recusa a iniciar** com a padrão)
- [ ] `APP_ENV=production`
- [ ] HTTPS configurado no Nginx com certificado válido
- [ ] PostgreSQL em uso, com usuário dedicado e senha forte
- [ ] Backup automático agendado **e testado**
- [ ] Cópias de backup guardadas **fora do servidor**
- [ ] `DEBUG=False` (garantido pela config de produção)
- [ ] Firewall: apenas 80/443 expostos; banco não acessível externamente

### Recomendado

- [ ] `RATELIMIT_STORAGE_URI` apontando para Redis (limite compartilhado entre workers)
- [ ] Monitoramento de erros (Sentry, mesmo no plano gratuito)
- [ ] `pip-audit` na rotina de manutenção
- [ ] Restauração de backup testada trimestralmente
- [ ] Revisão periódica de contas ativas e perfis concedidos

### Operação contínua

- [ ] Revisar a auditoria mensalmente, especialmente acessos negados
- [ ] Desativar contas de funcionários desligados no mesmo dia
- [ ] Atualizar dependências a cada trimestre
- [ ] Backup manual antes de qualquer atualização ou migração

---

## 10. O que este sistema **não** faz

Transparência sobre os limites do escopo atual:

- **Não tem autenticação de dois fatores.** Recomendável para contas de
  administrador em uma evolução futura.
- **Não criptografa dados em repouso no nível de coluna.** A proteção depende
  da criptografia de disco do servidor.
- **Não envia e-mail.** O link de recuperação de senha vai para o log da
  aplicação até que o SMTP da escola seja configurado.
- **Não tem varredura de antivírus nos uploads.** A validação é estrutural
  (extensão, assinatura, reencodificação), não de conteúdo malicioso.
- **Não implementa exclusão automática de dados por retenção**, exceto para a
  auditoria. A remoção de dados de ex-alunos é decisão da escola, conforme a
  obrigação legal de guarda do histórico escolar.
