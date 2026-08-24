#!/bin/sh

set -eu

ROOT_DIR=$(unset CDPATH; cd -- "$(dirname -- "$0")/.." && pwd)
MODE=manual

usage() {
    cat <<'EOF'
Uso: ./scripts/deploy.sh [--automatic]

Actualiza main desde origin y despliega Pinendar con Docker Compose.
--automatic respeta PINENDAR_AUTO_UPDATE; sin la opción, siempre despliega.
EOF
}

case "${1:-}" in
    "") ;;
    --automatic) MODE=automatic ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

cd "$ROOT_DIR"

if [ "$(git branch --show-current)" != main ]; then
    printf '%s\n' "El despliegue debe usar la rama main." >&2
    exit 1
fi

schedule_status=0
./scripts/configure-auto-update.sh || schedule_status=$?
if [ "$schedule_status" -eq 2 ]; then
    exit 2
elif [ "$schedule_status" -ne 0 ]; then
    printf '%s\n' "Aviso: el despliegue continuará sin modificar la programación automática." >&2
fi

if [ "$MODE" = automatic ]; then
    enabled_status=0
    ./scripts/configure-auto-update.sh --is-enabled || enabled_status=$?
    case "$enabled_status" in
        0) ;;
        1)
            printf '%s\n' "Actualización automática desactivada."
            exit 0
            ;;
        *) exit "$enabled_status" ;;
    esac
fi

git_common_dir=$(git rev-parse --git-common-dir)
case "$git_common_dir" in
    /*) ;;
    *) git_common_dir=$ROOT_DIR/$git_common_dir ;;
esac

lock_dir=$git_common_dir/pinendar-deploy.lock
if ! mkdir "$lock_dir" 2>/dev/null; then
    printf '%s\n' "Ya hay otro despliegue de Pinendar en curso." >&2
    exit 1
fi
trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT HUP INT TERM

if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
    printf '%s\n' "Hay cambios locales; se cancela para no sobrescribirlos." >&2
    exit 1
fi

printf '%s\n' "Buscando una nueva versión de main..."
git fetch --quiet origin main

current_revision=$(git rev-parse HEAD)
target_revision=$(git rev-parse FETCH_HEAD)
deployed_revision_file=$git_common_dir/pinendar-deployed-revision
deployed_revision=
[ ! -f "$deployed_revision_file" ] || deployed_revision=$(sed -n '1p' "$deployed_revision_file")

if [ "$MODE" = automatic ] && [ "$current_revision" = "$target_revision" ] && [ "$deployed_revision" = "$target_revision" ]; then
    printf '%s\n' "Pinendar ya está actualizado."
    exit 0
fi

if [ "$current_revision" != "$target_revision" ] && ! git merge-base --is-ancestor HEAD FETCH_HEAD; then
    printf '%s\n' "La rama local ha divergido de origin/main; se requiere revisión manual." >&2
    exit 1
fi

if [ "$current_revision" != "$target_revision" ]; then
    git merge --ff-only FETCH_HEAD
fi

printf '%s\n' "Construyendo la nueva versión..."
docker compose build --pull pinendar

printf '%s\n' "Aplicando el despliegue..."
docker compose up -d --no-build --remove-orphans --wait --wait-timeout 120

printf '%s\n' "$target_revision" >"$deployed_revision_file"

printf '%s\n' "Despliegue completado en $target_revision."
