# Shared by the VODLoft service and the vodloft command: where VODLoft keeps its files.
VODLOFT_HOME=/var/lib/vodloft
export PATH="/opt/vodloft/app/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PYTHONUNBUFFERED=1
export VL_CONFIG_FILE="$VODLOFT_HOME/config.yml"
export VL_DATABASE_PATH="$VODLOFT_HOME/vodloft.db"
export VL_UI_DIRECTORY=/opt/vodloft/ui
export PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring
export XDG_DATA_HOME="$VODLOFT_HOME/keyring/data"
export XDG_CONFIG_HOME="$VODLOFT_HOME/keyring/config"
# Programs VODLoft runs, such as yt-dlp, keep their caches in the home folder.
export HOME="$VODLOFT_HOME/home"
# Temporary downloads can be large, and /tmp is often kept in memory.
export TMPDIR=/var/cache/vodloft/tmp
