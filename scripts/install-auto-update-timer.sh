#!/bin/sh

set -eu

ROOT_DIR=$(unset CDPATH; cd -- "$(dirname -- "$0")/.." && pwd)
UNIT_DIR=/etc/systemd/system
SERVICE_FILE=$UNIT_DIR/pinendar-auto-update.service
TIMER_FILE=$UNIT_DIR/pinendar-auto-update.timer

if [ "$(id -u)" -ne 0 ]; then
    printf '%s\n' "Ejecuta este instalador con sudo." >&2
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    printf '%s\n' "Este instalador requiere systemd." >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    printf '%s\n' "Docker Compose no está disponible." >&2
    exit 1
fi

if [ "$(git -C "$ROOT_DIR" branch --show-current)" != main ]; then
    printf '%s\n' "Instala el temporizador desde una copia en la rama main." >&2
    exit 1
fi

case "$ROOT_DIR" in
    *[!A-Za-z0-9_./-]*)
        printf '%s\n' "La ruta del repositorio contiene caracteres no compatibles: $ROOT_DIR" >&2
        exit 1
        ;;
esac

DEPLOY_USER=${SUDO_USER:-root}

umask 022
cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Actualizar y desplegar Pinendar desde main
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$DEPLOY_USER
WorkingDirectory=$ROOT_DIR
ExecStart=$ROOT_DIR/scripts/deploy.sh --automatic
TimeoutStartSec=30min
EOF

cat >"$TIMER_FILE" <<'EOF'
[Unit]
Description=Comprobar actualizaciones de Pinendar

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
RandomizedDelaySec=30s
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now pinendar-auto-update.timer

printf '%s\n' "Actualización automática instalada para $ROOT_DIR."
