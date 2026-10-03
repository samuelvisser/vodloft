# Backups and upgrades

Back up the configuration directory, SQLite database, Source secret keys/runtimes, trusted update configuration, and media directory together. Stop VodLoft while copying SQLite and related state so the backup is consistent.

For an existing WireLoft installation, retain the original media mount and configuration. Set `WL_DATABASE_PATH` to that installation's actual database filename; VodLoft's default is `/config/vodloft.db`, which may differ from an older WireLoft filename.

Rebuild/start the VodLoft image. Schema migrations run first. Background migrations import existing Shows, Episodes, Movies, shared Extras, profiles, Source account references, membership, stream policies, feeds, live admissions, and usable files. They prepare owned playback copies while preserving originals. Scheduled work waits for this conversion.

Check the resulting library, Local Media Profiles, Source connections, and feed settings before removing an old installation. Keep original files and the backup until you have verified playback and server path mapping.

For Source-only updates, use Management's channel, pin, activation, and rollback controls; rebuilding the entire app is unnecessary when using trusted mounted/signed releases. A failed update keeps the prior version active.

A database schema rollback is not a substitute for restoring a complete backup. Do not run two application instances against the same SQLite/media paths.
