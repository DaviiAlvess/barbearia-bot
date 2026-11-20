#!/bin/bash
# Rode UMA VEZ como root na VPS (Ubuntu).
# Cria o usuário "barbearia", instala Docker rootless só para ele e isola
# o bot do resto da máquina (ex.: Condo Organize).
#
# Uso:
#   sudo bash deploy/setup-rootless.sh
set -euo pipefail

USUARIO=barbearia
HOME_USER="/home/$USUARIO"

if [ "$(id -u)" -ne 0 ]; then
  echo "Rode como root: sudo bash $0"
  exit 1
fi

echo "==> Pacotes base"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  uidmap dbus-user-session fuse-overlayfs slirp4netns curl ca-certificates git >/dev/null

if ! id "$USUARIO" &>/dev/null; then
  echo "==> Criando usuário $USUARIO (sem sudo)"
  adduser --disabled-password --gecos "Barbearia Bot" "$USUARIO"
else
  echo "==> Usuário $USUARIO já existe"
fi

# Sem acesso ao Docker rootful do sistema — isolamento forte
if getent group docker >/dev/null 2>&1; then
  gpasswd -d "$USUARIO" docker 2>/dev/null || true
fi

if ! grep -q "^${USUARIO}:" /etc/subuid 2>/dev/null; then
  echo "${USUARIO}:100000:65536" >> /etc/subuid
fi
if ! grep -q "^${USUARIO}:" /etc/subgid 2>/dev/null; then
  echo "${USUARIO}:100000:65536" >> /etc/subgid
fi

echo "==> Delegando cgroups (para mem_limit do compose funcionar no rootless)"
mkdir -p /etc/systemd/system/user@.service.d
cat > /etc/systemd/system/user@.service.d/delegate.conf <<'EOF'
[Service]
Delegate=cpu cpuset io memory pids
EOF
systemctl daemon-reload

echo "==> Linger: containers continuam após logout do SSH"
loginctl enable-linger "$USUARIO"

UID_B="$(id -u "$USUARIO")"
RUNTIME="/run/user/${UID_B}"
# Garante a sessão de usuário (XDG_RUNTIME_DIR) sem precisar de login interativo
systemctl start "user@${UID_B}.service" 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [ -d "$RUNTIME" ] && break
  sleep 1
done
if [ ! -d "$RUNTIME" ]; then
  echo "Aviso: $RUNTIME ainda não existe. Faça um login SSH como $USUARIO e rode de novo."
fi

install -d -o "$USUARIO" -g "$USUARIO" -m 750 "$HOME_USER/backups"

# Ubuntu 23.10+ bloqueia user namespaces sem perfil AppArmor do rootlesskit.
# Sem isso o Docker rootless falha; o reload do AppArmor NÃO reinicia Docker/Caddy do sistema.
echo "==> AppArmor: permitindo rootlesskit do usuário $USUARIO"
AA_FILE="/etc/apparmor.d/home.${USUARIO}.bin.rootlesskit"
cat > "$AA_FILE" <<EOF
# ref: https://ubuntu.com/blog/ubuntu-23-10-restricted-unprivileged-user-namespaces
abi <abi/4.0>,
include <tunables/global>

/home/${USUARIO}/bin/rootlesskit flags=(unconfined) {
  userns,

  include if exists <local/home.${USUARIO}.bin.rootlesskit>
}
EOF
if command -v apparmor_parser >/dev/null 2>&1; then
  apparmor_parser -r "$AA_FILE" 2>/dev/null || systemctl reload apparmor.service 2>/dev/null || true
fi

echo "==> Instalando Docker rootless como $USUARIO"
sudo -u "$USUARIO" -H \
  XDG_RUNTIME_DIR="$RUNTIME" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=${RUNTIME}/bus" \
  PATH="/usr/bin:/bin:${HOME_USER}/bin" \
  bash <<'EOSU'
set -euo pipefail
if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com/rootless | sh
fi

BASHRC="$HOME/.bashrc"
if ! grep -q 'Docker rootless (barbearia-bot)' "$BASHRC" 2>/dev/null; then
  cat >> "$BASHRC" <<'EOF'

# Docker rootless (barbearia-bot)
export PATH="$HOME/bin:$PATH"
export DOCKER_HOST="unix:///run/user/$(id -u)/docker.sock"
EOF
fi

export PATH="$HOME/bin:$PATH"
export DOCKER_HOST="unix:///run/user/$(id -u)/docker.sock"
systemctl --user enable docker
systemctl --user restart docker
docker info >/dev/null
EOSU

echo
echo "Pronto. Isolamento ativo:"
echo "  • Usuário Linux:  $USUARIO (sem sudo, fora do grupo docker do sistema)"
echo "  • Docker:         rootless em unix://${RUNTIME}/docker.sock"
echo "  • Código:         $HOME_USER/barbearia-bot  (clone no próximo passo)"
echo "  • Backups:        $HOME_USER/backups"
echo
echo "Próximo passo:"
echo "  sudo -iu $USUARIO"
echo "  git clone https://github.com/DaviiAlvess/barbearia-bot.git ~/barbearia-bot"
echo "  bash ~/barbearia-bot/deploy/instalar-bot.sh"
echo
echo "Guia completo: deploy/README.md"
