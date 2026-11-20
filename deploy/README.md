# Isolar o bot na mesma VPS (usuário próprio + Docker rootless)

Mesma máquina que o Condo Organize, mas **apartamento separado**: usuário Linux
sem sudo, Docker rootless (sem grupo `docker` do sistema), pasta e backups
próprios, painel só por túnel SSH (não mexe no Nginx do outro projeto).

## O que fica separado

| Recurso | Barbearia Bot | Condo Organize |
|---|---|---|
| Usuário Linux | `barbearia` (sem sudo) | o usuário dele |
| Docker | rootless só do `barbearia` | Docker dele (rootful ou outro) |
| Código | `~/barbearia-bot` | pasta dele |
| Banco | volume Docker + SQLite próprios | banco dele |
| Rede | bridge interna do compose | rede dele |
| Memória | teto ~1,6 GB (`mem_limit`) | independente |
| Painel web | `127.0.0.1:8080` via túnel SSH | Nginx dele intacto |

O que **não** separa: se a VPS inteira cair, os dois param. Isolamento total = outra VPS.

## Passo a passo (Ubuntu)

### 1. Como root — criar usuário e Docker rootless

```bash
# clone temporário só para pegar o script (ou baixe o arquivo)
git clone https://github.com/DaviiAlvess/barbearia-bot.git /tmp/barbearia-bot
sudo bash /tmp/barbearia-bot/deploy/setup-rootless.sh
```

Isso cria o usuário `barbearia`, delega cgroups (para o `mem_limit` funcionar),
liga `loginctl enable-linger` (containers sobrevivem ao logout) e instala o
Docker **rootless** só na conta dele.

### 2. Como `barbearia` — instalar o bot

```bash
sudo -iu barbearia
git clone https://github.com/DaviiAlvess/barbearia-bot.git ~/barbearia-bot
bash ~/barbearia-bot/deploy/instalar-bot.sh
```

Na primeira vez o script copia `.env.example` → `.env` e pede para editar:

```bash
nano ~/barbearia-bot/.env
# GEMINI_API_KEY, TELEFONE_DONO, PAINEL_SENHA
bash ~/barbearia-bot/deploy/instalar-bot.sh
```

### 3. Conectar o WhatsApp (QR)

```bash
cd ~/barbearia-bot
docker compose logs -f whatsapp
```

No celular: WhatsApp → Aparelhos conectados → escanear o QR.

### 4. Abrir o painel (túnel SSH, sem Nginx)

No **seu computador**:

```bash
ssh -L 8080:127.0.0.1:8080 barbearia@IP_DA_VPS
```

Abra http://localhost:8080 — usuário `dono`, senha `PAINEL_SENHA`.

O Nginx do Condo Organize **não é usado**. Se um dia quiser domínio público,
use Cloudflare Tunnel ou o `nginx-painel.conf` num *server* separado — nunca
reaproveite o virtual host do outro projeto.

## Comandos úteis (usuário `barbearia`)

```bash
cd ~/barbearia-bot
docker compose ps
docker compose logs -f bot
docker compose restart
docker compose pull && docker compose up -d --build   # atualizar
~/barbearia-bot/deploy/backup.sh                      # backup manual
```

## Por que rootless ajuda se alguém invadir o bot

- O processo Docker **não é root** na máquina.
- O usuário `barbearia` não tem `sudo` e não está no grupo `docker` do sistema.
- Mesmo com escape de container, o invasor fica no namespace/arquivos do
  `barbearia` — não lê o código nem o banco do Condo Organize (desde que as
  permissões das pastas do outro projeto sejam `750`/`640` para o dono dele).

## Se algo falhar

| Sintoma | O que checar |
|---|---|
| `Cannot connect to the Docker daemon` | `systemctl --user status docker` e `echo $DOCKER_HOST` |
| `mem_limit` ignorado | `/etc/systemd/system/user@.service.d/delegate.conf` + `daemon-reload` |
| Chromium / QR não sobe | `docker compose logs whatsapp` (já usa `--no-sandbox`) |
| Painel inacessível de fora | esperado — use o túnel SSH |
| Containers param ao sair do SSH | `loginctl show-user barbearia \| grep Linger` deve ser `yes` |
