#!/bin/bash
# Rode como o usuário "barbearia" (NÃO como root), depois do setup-rootless.sh.
# Clona/atualiza o repo, pede o .env se faltar e sobe o docker compose rootless.
#
# Uso:
#   sudo -iu barbearia
#   bash deploy/instalar-bot.sh          # se já está dentro do clone
#   # ou:
#   bash ~/barbearia-bot/deploy/instalar-bot.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/DaviiAlvess/barbearia-bot.git}"
DIR="${BARBEARIA_DIR:-$HOME/barbearia-bot}"

if [ "$(id -u)" -eq 0 ]; then
  echo "Não rode como root. Use: sudo -iu barbearia"
  exit 1
fi

export PATH="${HOME}/bin:${PATH}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker rootless não encontrado. Rode antes (como root):"
  echo "  sudo bash deploy/setup-rootless.sh"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker rootless não está respondendo. Tentando subir o serviço..."
  systemctl --user start docker || true
  sleep 2
  if ! docker info >/dev/null 2>&1; then
    echo "Falha: DOCKER_HOST=$DOCKER_HOST"
    echo "Confira: systemctl --user status docker"
    exit 1
  fi
fi

echo "==> Repositório em $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only || true
else
  if [ -d "$DIR" ] && [ -n "$(ls -A "$DIR" 2>/dev/null || true)" ]; then
    echo "A pasta $DIR já tem arquivos e não é um git clone. Pare e confira."
    exit 1
  fi
  git clone "$REPO_URL" "$DIR"
fi
cd "$DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  KEY=$(openssl rand -hex 24)
  sed -i "s/EVOLUTION_API_KEY=troque_por_uma_chave_longa/EVOLUTION_API_KEY=$KEY/" .env
  echo
  echo "Criei .env a partir do .env.example."
  echo "Edite agora com a chave do Gemini e o WhatsApp do dono:"
  echo "  nano $DIR/.env"
  echo
  echo "Campos mínimos: GEMINI_API_KEY, TELEFONE_DONO, PAINEL_SENHA, EVOLUTION_API_KEY"
  echo "Depois rode de novo: bash deploy/instalar-bot.sh"
  exit 0
fi

# Sanidade mínima do .env
if grep -q 'coloque_sua_chave_aqui' .env || grep -q 'troque_esta_senha' .env || grep -q 'troque_por_uma_chave_longa' .env; then
  echo "O .env ainda tem valores de exemplo. Edite antes de subir:"
  echo "  nano $DIR/.env"
  echo "  (GEMINI_API_KEY, TELEFONE_DONO, PAINEL_SENHA, EVOLUTION_API_KEY)"
  exit 1
fi
# Se a chave Evolution ainda for a de exemplo em deploy antigo, gera uma
if ! grep -q '^EVOLUTION_API_KEY=' .env; then
  echo "EVOLUTION_API_KEY=$(openssl rand -hex 24)" >> .env
  echo "Adicionei EVOLUTION_API_KEY ao .env"
fi

echo "==> Subindo containers (rootless)"
docker compose up -d --build

echo "==> Agendando backup diário (03:00 America/Bahia ≈ 06:00 UTC)"
CRON_LINHA="0 6 * * * $DIR/deploy/backup.sh >> $HOME/backups/cron.log 2>&1"
(crontab -l 2>/dev/null | grep -v 'deploy/backup.sh' || true; echo "$CRON_LINHA") | crontab -

mkdir -p "$HOME/backups"

echo
echo "Bot no ar (isolado do resto da VPS) — Evolution API + painel."
echo "  Status:   docker compose -f $DIR/docker-compose.yml ps"
echo "  QR code:  abra o painel → /whatsapp"
echo "  Painel:   só em 127.0.0.1 — use o subdomínio ou túnel SSH:"
echo "            ssh -L 8080:127.0.0.1:8080 barbearia@IP_DA_VPS"
echo "            depois abra http://localhost:8080"
echo
echo "Não mexa no Nginx/Caddy do Condo Organize além do handle do subdomínio."
