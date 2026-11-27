#!/usr/bin/env bash
# Build VODLoft's Debian package (vodloft_<version>_<arch>.deb) in a Debian 12 container.
#
# Usage:
#   .debian/build-deb.sh --ui-image ghcr.io/samuelvisser/vodloft:1.0.0 [--arch amd64|arm64] [--out dist]
#   .debian/build-deb.sh --ui-dir ui/dist [--build-id <id>] [--arch ...] [--out dist]
#
# The UI is taken from the released Docker image, so the package shows exactly the UI the image does,
# Pro icons included, or from a UI you built yourself. The package brings its own Python, because VODLoft
# needs Python 3.13 and Debian 12 and Ubuntu 22.04/24.04 have older ones.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
OUT="$REPO/dist"
UI_IMAGE=""
UI_DIR=""
BUILD_ID=""
BASE_IMAGE="debian:12"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --ui-image) UI_IMAGE="$2"; shift 2 ;;
        --ui-dir) UI_DIR="$2"; shift 2 ;;
        --build-id) BUILD_ID="$2"; shift 2 ;;
        --arch) ARCH="$2"; shift 2 ;;
        --out) OUT="$2"; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
case "$ARCH" in
    amd64) PLATFORM=linux/amd64 ;;
    arm64) PLATFORM=linux/arm64 ;;
    *) echo "Unsupported architecture: $ARCH (amd64 or arm64)" >&2; exit 2 ;;
esac
if { [ -n "$UI_IMAGE" ] && [ -n "$UI_DIR" ]; } || { [ -z "$UI_IMAGE" ] && [ -z "$UI_DIR" ]; }; then
    echo "Name the UI with exactly one of --ui-image or --ui-dir." >&2
    exit 2
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/ui" "$OUT"
OUT="$(cd "$OUT" && pwd)"

if [ -n "$UI_IMAGE" ]; then
    # The UI is the same on every architecture, so any platform of the image will do.
    container="$(docker create "$UI_IMAGE")"
    docker cp "$container:/usr/share/nginx/html/." "$WORK/ui/"
    docker cp "$container:/app/build-id" "$WORK/build-id"
    docker rm "$container" >/dev/null
    # The Docker entrypoint writes this file on every start; the backend answers it itself.
    rm -f "$WORK/ui/config.json"
else
    cp -r "$UI_DIR/." "$WORK/ui/"
    rm -f "$WORK/ui/config.json"
    printf '%s\n' "${BUILD_ID:-$(date -u +%Y%m%d%H%M%S%N)}" > "$WORK/build-id"
fi

# DOCKER_RUN_ARGS: extra options for the build container, such as the settings of a proxy it must go through.
# shellcheck disable=SC2086
docker run --rm --platform "$PLATFORM" ${DOCKER_RUN_ARGS:-} \
    -v "$REPO:/src:ro" -v "$WORK:/work" -v "$OUT:/out" \
    -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" -e DEB_ARCH="$ARCH" \
    "$BASE_IMAGE" bash /src/.debian/stage.sh
