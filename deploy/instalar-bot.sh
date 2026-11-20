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
  echo
  echo "Criei .env a partir do .env.example."
  echo "Edite agora com a chave do Gemini e o WhatsApp do dono:"
  echo "  nano $DIR/.env"
  echo
  echo "Campos mínimos: GEMINI_API_KEY, TELEFONE_DONO, PAINEL_SENHA"
  echo "Depois rode de novo: bash deploy/instalar-bot.sh"
  exit 0
fi

# Sanidade mínima do .env
if grep -q 'coloque_sua_chave_aqui' .env || grep -q 'troque_esta_senha' .env; then
  echo "O .env ainda tem valores de exemplo. Edite antes de subir:"
  echo "  nano $DIR/.env"
  exit 1
fi

echo "==> Subindo containers (rootless)"
docker compose up -d --build

echo "==> Agendando backup diário (03:00 America/Bahia ≈ 06:00 UTC)"
CRON_LINHA="0 6 * * * $DIR/deploy/backup.sh >> $HOME/backups/cron.log 2>&1"
(crontab -l 2>/dev/null | grep -v 'deploy/backup.sh' || true; echo "$CRON_LINHA") | crontab -

mkdir -p "$HOME/backups"

echo
echo "Bot no ar (isolado do resto da VPS)."
echo "  Status:   docker compose -f $DIR/docker-compose.yml ps"
echo "  QR code:  docker compose -f $DIR/docker-compose.yml logs -f whatsapp"
echo "  Painel:   só em 127.0.0.1 — use túnel SSH do seu PC:"
echo "            ssh -L 8080:127.0.0.1:8080 barbearia@IP_DA_VPS"
echo "            depois abra http://localhost:8080 (usuário dono)"
echo
echo "Não mexa no Nginx do Condo Organize: o painel não precisa dele."
