#!/usr/bin/env bash
# Make the signed apt repository index for the .deb files in a folder, in that same folder.
#
# Usage: .debian/apt-repo.sh <folder with vodloft_*.deb> [signing key id]
#
# Every GitHub Release holds its .debs and this index side by side, so the release page is a complete
# "flat" apt repository. Users point apt at releases/latest/download, which GitHub sends to the newest
# published release: `apt upgrade` sees a version once its draft is published, and never a draft.
# The key signing the index must be in gpg's keyring; without a key id, its only secret key is used.
set -euo pipefail

folder="$1"
key="${2:-}"
cd "$folder"
# Written elsewhere first: the index must not list itself.
TMPDIR_RELEASE="$(mktemp)"
ls vodloft_*.deb >/dev/null

rm -f Packages Packages.gz Release InRelease Release.gpg
apt-ftparchive packages . > Packages
gzip -9nc Packages > Packages.gz
apt-ftparchive \
    -o APT::FTPArchive::Release::Origin=VODLoft \
    -o APT::FTPArchive::Release::Label=VODLoft \
    -o APT::FTPArchive::Release::Suite=stable \
    -o APT::FTPArchive::Release::Architectures="$(sed -n 's/^Architecture: //p' Packages | sort -u | paste -sd ' ')" \
    -o APT::FTPArchive::Release::Description="VODLoft packages" \
    release . > "$TMPDIR_RELEASE"
mv "$TMPDIR_RELEASE" Release

signer=()
if [ -n "$key" ]; then
    signer=(--local-user "$key")
fi
gpg --batch --yes "${signer[@]}" --clearsign --digest-algo SHA512 -o InRelease Release
gpg --batch --yes "${signer[@]}" --detach-sign --armor --digest-algo SHA512 -o Release.gpg Release
# The key users install to trust this repository.
gpg --batch --yes --export "${key:-$(gpg --batch --list-secret-keys --with-colons | awk -F: '$1 == "fpr" { print $10; exit }')}" \
    > vodloft-archive-keyring.gpg
echo "Signed the index of $(ls vodloft_*.deb | wc -l) package(s) in $folder"
