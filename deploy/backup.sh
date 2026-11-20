#!/bin/sh
# Backup diário do banco da barbearia. Agende com: crontab -e
#   0 3 * * * /opt/barbearia-bot/deploy/backup.sh
set -e
DESTINO=/opt/backups/barbearia
mkdir -p "$DESTINO"
cd /opt/barbearia-bot
docker compose exec -T bot python -c "import sqlite3; s=sqlite3.connect('/app/dados/barbearia.db'); d=sqlite3.connect('/app/dados/backup.db'); s.backup(d); d.close()"
docker compose cp bot:/app/dados/backup.db "$DESTINO/barbearia-$(date +%F).db"
find "$DESTINO" -name 'barbearia-*.db' -mtime +30 -delete   # guarda 30 dias
echo "Backup ok: $DESTINO/barbearia-$(date +%F).db"
