#!/usr/bin/env bash
# Runs inside the Debian 12 build container of build-deb.sh: installs VODLoft into /opt/vodloft the way the
# Docker image installs it into /app, and packs it with the files in .debian/files into a .deb.
set -euo pipefail

UV_VERSION="${UV_VERSION:-0.11.32}"
PYTHON_VERSION="${PYTHON_VERSION:-3.13}"
SRC=/src
PKG=/build/pkg
PREFIX=/opt/vodloft

apt-get update -qq
apt-get install -y -qq --no-install-recommends ca-certificates curl >/dev/null
curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_UNMANAGED_INSTALL=/usr/local/bin sh >/dev/null

VERSION="$(sed -n -E 's/^version = "([^"]+)"/\1/p' "$SRC/pyproject.toml" | head -n1)"
echo "Building VODLoft $VERSION for $DEB_ARCH"

# The virtual environment names its interpreter by absolute path, so VODLoft is installed at the path it
# will have on the user's computer, and copied into the package from there.
export UV_PYTHON_INSTALL_DIR="$PREFIX/python" \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT="$PREFIX/app/.venv" \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1
uv python install "$PYTHON_VERSION" >/dev/null
mkdir -p "$PREFIX/app/config" "$PREFIX/bin" "$PREFIX/lib"
cp "$SRC/pyproject.toml" "$SRC/uv.lock" "$PREFIX/app/"
cp -r "$SRC/server" "$PREFIX/app/server"
find "$PREFIX/app/server" -name __pycache__ -prune -exec rm -rf {} +
(cd "$PREFIX/app" && uv sync --frozen --no-dev --python "$PYTHON_VERSION" >/dev/null)
# Python's own test suite is a large part of the interpreter and never runs.
rm -rf "$PREFIX"/python/*/lib/python3.*/test "$PREFIX"/python/.lock "$PREFIX"/python/.temp

# The default settings, with the package's paths in place of the Docker volumes.
{
    printf '%s\n' \
        "# Default VODLoft configuration, copied to /var/lib/vodloft/config.yml when VODLoft starts and" \
        "# finds none. Safe to edit in-place afterwards: it is only ever copied once."
    # The first four lines say where the Docker image copies the file; the lines above replace them.
    sed '1,4d' "$SRC/config/config.yml.default"
} | sed -e 's#/config/#/var/lib/vodloft/#g' \
      -e 's#downloadRoot: /downloads#downloadRoot: /var/lib/vodloft/downloads#' \
      -e 's#^  \# on the /downloads volume: anything outside a mounted volume is lost when#  \# on a disk with room for your media. The vodloft user must be able to write#' \
      -e 's#^  \# the container is recreated\.#  \# in it.#' \
    > "$PREFIX/app/config/config.yml.default"

cp /work/build-id "$PREFIX/app/build-id"
cp -r /work/ui "$PREFIX/ui"
install -m 0755 "$SRC/.debian/files/vodloft-service" "$PREFIX/bin/vodloft-service"
install -m 0644 "$SRC/.debian/files/environment.sh" "$PREFIX/lib/environment.sh"

rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/lib/systemd/system" "$PKG/etc/vodloft" \
    "$PKG/usr/share/doc/vodloft"
cp -a "$PREFIX" "$PKG/opt/"
install -m 0755 "$SRC/.debian/files/vodloft" "$PKG/usr/bin/vodloft"
install -m 0644 "$SRC/.debian/files/vodloft.service" "$PKG/lib/systemd/system/vodloft.service"
install -m 0640 "$SRC/.debian/files/vodloft.env" "$PKG/etc/vodloft/vodloft.env"
install -m 0644 "$SRC/.debian/copyright" "$PKG/usr/share/doc/vodloft/copyright"
for script in postinst prerm postrm; do
    install -m 0755 "$SRC/.debian/files/$script" "$PKG/DEBIAN/$script"
done
echo /etc/vodloft/vodloft.env > "$PKG/DEBIAN/conffiles"

installed_size="$(du -sk --exclude=DEBIAN "$PKG" | cut -f1)"
sed -e "s/@VERSION@/$VERSION/" -e "s/@ARCH@/$DEB_ARCH/" -e "s/@INSTALLED_SIZE@/$installed_size/" \
    "$SRC/.debian/control" > "$PKG/DEBIAN/control"

deb="/out/vodloft_${VERSION}_${DEB_ARCH}.deb"
dpkg-deb --root-owner-group -Zxz --build "$PKG" "$deb" >/dev/null
chown "$HOST_UID:$HOST_GID" "$deb"
echo "Built $(basename "$deb") ($(du -h "$deb" | cut -f1))"
