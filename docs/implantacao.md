# Implantação e operação do SGE

Guia para colocar o sistema em produção e mantê-lo funcionando.

---

## 1. Escolha do ambiente

| Cenário | Recomendação |
|---|---|
| Até ~200 alunos, um computador na secretaria | SQLite + Waitress no Windows |
| Escola completa, acesso de casa pelos responsáveis | PostgreSQL + Gunicorn + Nginx em VPS Linux |
| Rede interna apenas | Qualquer um dos dois, com IP fixo na rede local |

O SQLite dá conta de uma escola pequena. A troca para PostgreSQL é uma
mudança de variável de ambiente — a aplicação não muda.

---

## 2. Implantação em Linux (recomendada)

### 2.1 Preparar o servidor

```bash
sudo apt update && sudo apt install -y python3.12 python3.12-venv postgresql nginx git
```

### 2.2 Criar o banco

```bash
sudo -u postgres psql
```

```sql
CREATE DATABASE sge;
CREATE USER sge_app WITH PASSWORD 'senha-forte-aqui';
GRANT ALL PRIVILEGES ON DATABASE sge TO sge_app;
\q
```

### 2.3 Instalar a aplicação

```bash
sudo mkdir -p /opt/sge && sudo chown $USER:$USER /opt/sge
git clone <url-do-repositorio> /opt/sge
cd /opt/sge
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt gunicorn "psycopg[binary]"
```

### 2.4 Configurar

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Edite o `.env`:

```
APP_ENV=production
SECRET_KEY=<a chave gerada acima>
DATABASE_URL=postgresql+psycopg://sge_app:senha-forte-aqui@localhost:5432/sge
SESSAO_MINUTOS=120
LOGIN_MAX_TENTATIVAS=5
BACKUP_RETENCAO_DIAS=30
LOG_NIVEL=INFO
```

### 2.5 Criar o esquema

```bash
flask db upgrade
flask criar-estrutura-inicial
flask criar-admin
flask verificar-saude
```

### 2.6 Serviço systemd

`/etc/systemd/system/sge.service`:

```ini
[Unit]
Description=SGE - Sistema de Gestao Escolar
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/opt/sge
Environment="PATH=/opt/sge/venv/bin"
ExecStart=/opt/sge/venv/bin/gunicorn --workers 4 --bind 127.0.0.1:8000 --access-logfile - --error-logfile - wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now sge
sudo systemctl status sge
```

> **Workers:** use `(2 × núcleos) + 1`. Em uma VPS de 2 vCPUs, 4 ou 5.

### 2.7 Nginx

`/etc/nginx/sites-available/sge`:

```nginx
server {
    listen 80;
    server_name sge.suaescola.com.br;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name sge.suaescola.com.br;

    ssl_certificate     /etc/letsencrypt/live/sge.suaescola.com.br/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sge.suaescola.com.br/privkey.pem;

    # Limite alinhado ao MAX_UPLOAD_MB da aplicação
    client_max_body_size 10M;

    # Arquivos estáticos servidos direto pelo Nginx, sem passar pelo Python
    location /static/ {
        alias /opt/sge/app/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/sge /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

> Os cabeçalhos `X-Forwarded-*` são obrigatórios: sem eles, todo acesso
> pareceria vir de `127.0.0.1` e a auditoria de IP ficaria inútil. A aplicação
> já aplica `ProxyFix` em produção.

### 2.8 HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d sge.suaescola.com.br
```

O Certbot renova automaticamente. Sem HTTPS os cookies `Secure` não são
enviados e o login não funciona em produção.

---

## 3. Implantação em Windows

Para escolas sem servidor Linux.

### 3.1 Instalar

```bash
winget install Python.Python.3.12
```

```bash
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt waitress
```

### 3.2 Configurar e criar o banco

Mesmos passos da seção 2.4 e 2.5. Para escola pequena, deixe `DATABASE_URL`
vazio para usar SQLite.

### 3.3 Rodar como serviço

Crie `iniciar_sge.bat`:

```bash
cd /d C:\sge && venv\Scripts\python.exe -m waitress --port=8000 wsgi:app
```

Registre no **Agendador de Tarefas** com gatilho "Ao iniciar o computador" e a
opção "Executar estando o usuário conectado ou não".

---

## 4. Backup

### 4.1 Gerar manualmente

Pela interface: **Sistema → Backup → Gerar backup agora**.

Pela linha de comando:

```bash
flask backup
```

### 4.2 Agendar

**Linux (cron)** — diariamente às 2h:

```bash
crontab -e
```

```
0 2 * * * cd /opt/sge && /opt/sge/venv/bin/flask backup --automatico >> /opt/sge/logs/backup.log 2>&1
```

**Windows** — Agendador de Tarefas, diário às 2h, executando:

```bash
C:\sge\venv\Scripts\flask.exe backup --automatico
```

com "Iniciar em" apontando para `C:\sge`.

### 4.3 Política de retenção

Configurada em `.env`: `BACKUP_RETENCAO_DIAS` e `BACKUP_MAXIMO_ARQUIVOS`.
Ambos os critérios são aplicados; **o backup mais recente nunca é removido**,
mesmo fora da janela.

### 4.4 Guardar fora do servidor

> Backup no mesmo disco do banco **não é backup**. Não protege contra falha de
> hardware nem contra ransomware.

Exemplo com `rclone` para armazenamento em nuvem:

```bash
0 3 * * * rclone sync /opt/sge/database/backups remoto:sge-backups --max-age 30d
```

### 4.5 Restaurar

A restauração **não** é feita pela interface web — ela sobrescreve o banco
inteiro e é irreversível. A tela de backup exibe as instruções prontas para o
banco em uso.

Procedimento resumido:

1. Avise os usuários e escolha um horário sem movimento.
2. Pare a aplicação: `sudo systemctl stop sge`
3. **Gere um backup do estado atual** — é o único caminho de volta.
4. Restaure:

```bash
gunzip -c /opt/sge/database/backups/sge_AAAAMMDD_HHMMSS_manual.sql.gz | psql "$DATABASE_URL"
```

5. Reinicie: `sudo systemctl start sge`
6. Valide: `flask verificar-saude` e confira algumas telas.

### 4.6 Testar a restauração

**Trimestralmente**, restaure um backup em um banco de teste. Backup que nunca
foi restaurado é uma suposição, não uma garantia.

---

## 5. Atualização do sistema

```bash
cd /opt/sge
source venv/bin/activate

flask backup                      # 1. Backup obrigatório antes de tudo
sudo systemctl stop sge           # 2. Parar a aplicação
git pull                          # 3. Atualizar o código
pip install -r requirements.txt   # 4. Atualizar dependências
flask db upgrade                  # 5. Aplicar migrações
sudo systemctl start sge          # 6. Subir
flask verificar-saude             # 7. Validar
```

---

## 6. Monitoramento

### Logs

```bash
tail -f /opt/sge/logs/sge.log        # aplicação
sudo journalctl -u sge -f            # serviço
sudo tail -f /var/log/nginx/error.log
```

Rotação automática: 5 MB por arquivo, 10 arquivos mantidos.

### Diagnóstico

```bash
flask verificar-saude
```

Verifica conexão com o banco, tabelas, pastas de trabalho, existência de
administrador ativo, ano letivo corrente e uso da `SECRET_KEY` padrão.

### Erros em produção (recomendado)

```bash
pip install sentry-sdk[flask]
```

E em `create_app`:

```python
import sentry_sdk
sentry_sdk.init(dsn="...", traces_sample_rate=0.1)
```

---

## 7. Rotina de manutenção

| Frequência | Tarefa |
|---|---|
| Diária | Conferir que o backup automático rodou |
| Semanal | Revisar acessos negados na auditoria |
| Mensal | Revisar contas ativas; desativar desligados |
| Trimestral | Testar restauração de backup; rodar `pip-audit`; atualizar dependências |
| Anual | Criar o novo ano letivo; encerrar o anterior; consolidar resultados |

### Virada de ano letivo

1. Consolide os resultados de todas as turmas (**Boletins → Ata → Consolidar**).
2. Emita e arquive os boletins finais em PDF.
3. Encerre o ano letivo em **Configurações → Anos letivos → Encerrar**.
   Isso torna notas e frequência daquele ano somente leitura.
4. Crie o novo ano letivo, com os períodos.
5. Crie as turmas do novo ano.
6. Matricule os alunos.

---

## 8. Solução de problemas

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `RuntimeError: SECRET_KEY não configurada` | `.env` ausente ou sem a chave | Gerar a chave e preencher |
| `RuntimeError: DATABASE_URL não configurada` | Falta a URI em produção | Preencher `DATABASE_URL` |
| Login não persiste | Cookie `Secure` sem HTTPS | Configurar o certificado |
| Todos os IPs aparecem como `127.0.0.1` | Nginx sem `X-Forwarded-For` | Ajustar o `proxy_set_header` |
| CSS não carrega | `alias` do `/static/` errado | Conferir o caminho no Nginx |
| `pg_dump: command not found` | Utilitários do PostgreSQL ausentes | `sudo apt install postgresql-client` |
| Erro 413 no upload | `client_max_body_size` menor que o limite da app | Alinhar Nginx e `MAX_UPLOAD_MB` |
| Rate limiting inconsistente | Armazenamento em memória com vários workers | Apontar `RATELIMIT_STORAGE_URI` para Redis |

---

## 9. Implantação em homologação (recomendado)

Antes de colocar em produção, rode 2 a 4 semanas em paralelo ao processo
atual da escola:

1. Suba uma segunda instância com banco separado.
2. Carregue dados reais **anonimizados** ou uma amostra pequena.
3. Treine secretaria e professores nesse ambiente.
4. Colete os ajustes necessários antes da virada.
5. Mantenha o processo antigo como contingência no primeiro bimestre.
