#!/usr/bin/env bash
# Create the key that signs VODLoft's apt repository. Run this once; the release workflow then signs every
# release's index with it.
#
# Usage: .debian/new-signing-key.sh
#
# It prints the steps that follow: store the private key as the APT_SIGNING_KEY secret of the GitHub
# repository, and keep a backup of it somewhere safe. Users trust this key, so a new key means every user
# has to install the new one by hand.
set -euo pipefail

home="$(mktemp -d)"
trap 'rm -rf "$home"' EXIT
export GNUPGHOME="$home"
gpg --batch --quiet --passphrase '' --quick-generate-key "VODLoft apt repository" ed25519 sign never
fingerprint="$(gpg --batch --list-secret-keys --with-colons | awk -F: '$1 == "fpr" { print $10; exit }')"
gpg --batch --armor --export-secret-keys "$fingerprint" > vodloft-apt-signing-key.private.asc
gpg --batch --armor --export "$fingerprint" > vodloft-apt-signing-key.public.asc
chmod 600 vodloft-apt-signing-key.private.asc

cat <<MESSAGE
Created the VODLoft apt signing key $fingerprint:
  vodloft-apt-signing-key.private.asc  the private key: never commit or share it
  vodloft-apt-signing-key.public.asc   the public key

Next:
  1. Store the private key as the repository secret APT_SIGNING_KEY, either with
       gh secret set APT_SIGNING_KEY --repo samuelvisser/vodloft < vodloft-apt-signing-key.private.asc
     or under Settings > Secrets and variables > Actions on GitHub.
  2. Keep a backup of vodloft-apt-signing-key.private.asc in your password manager, then delete the file.
MESSAGE
