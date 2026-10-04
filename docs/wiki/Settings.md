# Settings

The administrator's **Settings** screen controls acquisition concurrency, retry budget, download timeout, retry backoff, and automatic scheduling.

Source accounts and update policy, Local Media Profiles, Collection policies, media-server targets, users, and approval requests are managed in **Management** or on the relevant library item.

Configuration is persisted in `config.yml`. `WL_*` environment overrides take precedence over saved configuration; use the same settings names as the application. The container uses `WL_CONFIG_FILE=/config/config.yml` and `WL_DATABASE_PATH=/config/vodloft.db` by default.

The default Docker media root is `/downloads`. Set `downloadSettings.downloadRoot` in your persisted YAML when changing its mount. Output templates keep the logical `/downloads/` prefix.

Set the bootstrap administrator password with `WL_ADMIN_AUTH__PASSWORD` and restart. Set the timezone using `TZ` in Compose. Back up configuration alongside the database, Source secrets/runtimes, and media.
