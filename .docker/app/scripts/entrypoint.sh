#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${VL_CONFIG_FILE:-/config/config.yml}"
DATABASE_PATH="${VL_DATABASE_PATH:-/config/vodloft.db}"
# Matches downloadSettings.downloadRoot in config/config.yml.default; not an
# env var since download_root is set via that file (see its header comment).
DOWNLOAD_ROOT=/downloads
KEYRING_DATA_HOME="${XDG_DATA_HOME:-/config/keyring/data}"
KEYRING_CONFIG_HOME="${XDG_CONFIG_HOME:-/config/keyring/config}"

# Make sure every directory backed by a volume mount actually exists. The
# database file itself is created by Alembic when migrations run below.
mkdir -p \
    "$(dirname "$CONFIG_FILE")" \
    "$(dirname "$DATABASE_PATH")" \
    "$DOWNLOAD_ROOT" \
    "$KEYRING_DATA_HOME" \
    "$KEYRING_CONFIG_HOME"

# UMASK: the permissions VODLoft gives the files and folders it creates, such as 002 for files the
# group may change too. Unset keeps the image's default, 022.
if [ -n "${UMASK:-}" ]; then
    if [[ ! "$UMASK" =~ ^0?[0-7]{3}$ ]]; then
        echo "[entrypoint] UMASK must be three octal digits, such as 022 or 002, not '$UMASK'" >&2
        exit 1
    fi
    umask "$UMASK"
fi

# PUID and PGID: the user and group VODLoft runs as, so its files belong to the same user as the rest
# of your media. Unset runs VODLoft as root, as before. nginx keeps running as root to listen on :80.
as_user=()
if [ -n "${PUID:-}" ] || [ -n "${PGID:-}" ]; then
    PUID="${PUID:-0}"
    PGID="${PGID:-$PUID}"
    if [[ ! "$PUID" =~ ^[0-9]+$ ]] || [[ ! "$PGID" =~ ^[0-9]+$ ]]; then
        echo "[entrypoint] PUID and PGID must be numbers, such as 1000, not '$PUID' and '$PGID'" >&2
        exit 1
    fi
    # Programs VODLoft runs, such as yt-dlp, keep their caches in the home folder.
    export HOME="$(dirname "$CONFIG_FILE")/home"
    TEMPORARY_ROOT="${TMPDIR:-/tmp}/vodloft-downloads"
    mkdir -p "$HOME" "$TEMPORARY_ROOT"
    # Everything in /config and the temporary downloads becomes theirs; only what still belongs to
    # someone else is changed, so later starts are quick. Of /downloads only the folder itself is
    # changed: your media keeps its owners, and VODLoft needs to be able to write in it.
    for folder in "$(dirname "$CONFIG_FILE")" "$(dirname "$DATABASE_PATH")" "$KEYRING_DATA_HOME" "$KEYRING_CONFIG_HOME" \
            "$HOME" "$TEMPORARY_ROOT"; do
        find "$folder" \( \! -uid "$PUID" -o \! -gid "$PGID" \) -exec chown "$PUID:$PGID" {} +
    done
    chown "$PUID:$PGID" "$DOWNLOAD_ROOT"
    as_user=(setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --)
    echo "[entrypoint] Running VODLoft as user $PUID and group $PGID"
fi

# Seed a default config.yml on first run (mirrors config/config.yml.default).
if [ ! -f "$CONFIG_FILE" ] && [ -f /app/config/config.yml.default ]; then
    cp /app/config/config.yml.default "$CONFIG_FILE"
    if [ "${#as_user[@]}" -gt 0 ]; then
        chown "$PUID:$PGID" "$CONFIG_FILE"
    fi
    echo "[entrypoint] Seeded default config at $CONFIG_FILE"
fi

# The UI fetches /config.json at startup for the API base URL. Regenerate it
# on every boot so it always matches how this container is being served,
# while still allowing an override via API_URL.
cat > /usr/share/nginx/html/config.json <<EOF
{"API_URL": "${API_URL:-/api}"}
EOF

run_supervised() {
    echo "[entrypoint] Starting VODLoft backend on 127.0.0.1:5001"
    "${as_user[@]}" backend-api run --host 127.0.0.1 --port 5001 &
    backend_pid=$!

    echo "[entrypoint] Starting nginx on :80 (UI + /api proxy)"
    nginx -g 'daemon off;' &
    nginx_pid=$!

    shutdown() {
        trap - TERM INT
        kill -TERM "$backend_pid" "$nginx_pid" 2>/dev/null || true
        wait "$backend_pid" "$nginx_pid" 2>/dev/null || true
    }
    trap shutdown TERM INT

    # If either process exits, tear the other down and stop the container so
    # Docker's restart policy can bring it back up cleanly.
    wait -n
    exit_code=$?
    shutdown
    exit "$exit_code"
}

if [ "$#" -eq 0 ]; then
    echo "[entrypoint] Applying database migrations"
    "${as_user[@]}" backend-api db upgrade
    run_supervised
else
    # Escape hatch for one-off maintenance, e.g.:
    #   docker compose run --rm vodloft backend-api db current
    exec "${as_user[@]}" "$@"
fi
