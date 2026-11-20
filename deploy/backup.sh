#!/bin/sh
# Backup diário do banco da barbearia (só este projeto; não toca no Condo Organize).
# Agendado pelo instalar-bot.sh no crontab do usuário barbearia.
# Manual:  ~/barbearia-bot/deploy/backup.sh
set -e
DIR="${BARBEARIA_DIR:-$HOME/barbearia-bot}"
DESTINO="${BARBEARIA_BACKUPS:-$HOME/backups}"
export PATH="${HOME}/bin:${PATH}"
export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"

mkdir -p "$DESTINO"
cd "$DIR"
docker compose exec -T bot python -c "import sqlite3; s=sqlite3.connect('/app/dados/barbearia.db'); d=sqlite3.connect('/app/dados/backup.db'); s.backup(d); d.close()"
docker compose cp bot:/app/dados/backup.db "$DESTINO/barbearia-$(date +%F).db"
find "$DESTINO" -name 'barbearia-*.db' -mtime +30 -delete
echo "Backup ok: $DESTINO/barbearia-$(date +%F).db"
