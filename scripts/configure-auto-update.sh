#!/bin/sh

set -eu

ROOT_DIR=$(unset CDPATH; cd -- "$(dirname -- "$0")/.." && pwd)
MARKER="# Pinendar automatic update: $ROOT_DIR"

read_dotenv_value() {
    key=$1
    file=$2

    awk -v key="$key" '
        /^[[:space:]]*#/ { next }
        {
            line = $0
            sub(/^[[:space:]]*/, "", line)
            if (index(line, key "=") != 1) next
            value = substr(line, length(key) + 2)
            sub(/[[:space:]]*#[[:space:]].*$/, "", value)
            sub(/^[[:space:]]*/, "", value)
            sub(/[[:space:]]*$/, "", value)
            if ((substr(value, 1, 1) == "\"" && substr(value, length(value), 1) == "\"") ||
                (substr(value, 1, 1) == "\047" && substr(value, length(value), 1) == "\047")) {
                value = substr(value, 2, length(value) - 2)
            }
            print value
            exit
        }
    ' "$file"
}

auto_update_enabled() {
    if [ "${PINENDAR_AUTO_UPDATE+x}" = x ]; then
        value=$PINENDAR_AUTO_UPDATE
    elif [ -f "$ROOT_DIR/.env" ]; then
        value=$(read_dotenv_value PINENDAR_AUTO_UPDATE "$ROOT_DIR/.env")
    else
        value=true
    fi

    [ -n "$value" ] || value=true
    value=$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')

    case "$value" in
        true|1|yes|on) return 0 ;;
        false|0|no|off) return 1 ;;
        *)
            printf '%s\n' "PINENDAR_AUTO_UPDATE debe ser true o false; recibido: $value" >&2
            exit 2
            ;;
    esac
}

if [ "${1:-}" = --is-enabled ]; then
    auto_update_enabled
    exit $?
fi

if [ "$#" -ne 0 ]; then
    printf '%s\n' "Uso: ./scripts/configure-auto-update.sh [--is-enabled]" >&2
    exit 2
fi

case "$ROOT_DIR" in
    *[!A-Za-z0-9_./-]*)
        printf '%s\n' "La ruta del repositorio contiene caracteres no compatibles: $ROOT_DIR" >&2
        exit 1
        ;;
esac

if ! command -v crontab >/dev/null 2>&1; then
    if auto_update_enabled; then
        printf '%s\n' "No se puede programar la actualización: crontab no está disponible." >&2
        exit 1
    fi
    printf '%s\n' "Actualización automática desactivada."
    exit 0
fi

current_crontab=$(mktemp)
new_crontab=$(mktemp)
trap 'rm -f "$current_crontab" "$new_crontab"' EXIT HUP INT TERM

crontab -l >"$current_crontab" 2>/dev/null || true
awk -v marker="$MARKER" 'index($0, marker) == 0' "$current_crontab" >"$new_crontab"

if auto_update_enabled; then
    if ! command -v logger >/dev/null 2>&1; then
        printf '%s\n' "No se puede programar la actualización: logger no está disponible." >&2
        exit 1
    fi

    checksum=$(printf '%s' "$(uname -n):$ROOT_DIR" | cksum)
    checksum=${checksum%% *}
    minute=$((checksum % 60))
    logger_path=$(command -v logger)

    printf '%s\n' "$minute * * * * PATH=/usr/local/bin:/usr/bin:/bin $ROOT_DIR/scripts/deploy.sh --automatic 2>&1 | $logger_path -t pinendar-auto-update $MARKER" >>"$new_crontab"
    crontab "$new_crontab"
    printf '%s\n' "Actualización automática programada cada hora, en el minuto $minute."
else
    crontab "$new_crontab"
    printf '%s\n' "Actualización automática desactivada; se eliminó únicamente la tarea de Pinendar."
fi
