# Backups and Upgrades

VODLoft is easy to back up when its persistent data is kept outside the container.

## What to back up

### `/config` — essential

Back up the entire `/config` directory. It contains the state needed to restore your VODLoft installation, including:

- the SQLite database;
- `config.yml`;
- the application secret key;
- Daily Wire authentication state;
- other persistent application data stored alongside the configuration.

Backing up the complete directory is safer than maintaining a hand-picked file list as VODLoft evolves.

### `/downloads` — optional, depending on your storage policy

`/downloads` contains the media VODLoft downloaded.

Back it up when those files are important or expensive to recreate. You may choose not to back it up when downloads are treated as replaceable media and you are comfortable fetching them again.

Remember that VODLoft cannot guarantee The Daily Wire will continue to make every old file available forever, especially member-exclusive media.

## Make a consistent database backup

VODLoft uses SQLite. The simplest reliable backup is to stop VODLoft while copying `/config`:

```bash
docker compose stop vodloft
# back up ./config here
docker compose start vodloft
```

If your storage/backup system supports application-consistent SQLite snapshots, you can use that instead.

Do not run two VODLoft backends against the same SQLite database at the same time. For example, avoid starting a local development backend and a Docker instance that both point to the same `vodloft.db`.

## Do not lose the application key

The normal Docker setup keeps VODLoft's generated application key under `/config`. Preserve it together with the database.

Restoring only `vodloft.db` while losing the accompanying key and authentication state can result in an incomplete restore.

## Upgrade VODLoft

Every [VODLoft release](https://github.com/samuelvisser/vodloft/releases) lists the commands to upgrade to exactly that version. This section explains them step by step. The examples use version `0.7.0`; use the version from the release you want instead.

These steps are for the standard Docker Compose setup from [[Installation]]. Type each command in a terminal on the computer or server that runs VODLoft, and press Enter after each one.

1. **Go to your VODLoft folder**, the folder with your `docker-compose.yml` in it. If you followed [[Installation]], that is the `vodloft` folder in your home folder:

   ```bash
   cd ~/vodloft
   ```

   To check you are in the right place, run `ls`. You should see `docker-compose.yml` and a `config` folder.

2. **Stop VODLoft and back up** its `config` folder, which holds your database and settings. With this backup you can always go back.

   ```bash
   docker compose stop
   sudo cp -a config config-before-0.7.0
   ```

   `sudo` may ask for your own password. If your system has no `sudo`, for example because you are logged in as root, leave it out.

3. **Choose the version.** This command changes the `image:` line in `docker-compose.yml` so it names version 0.7.0, and the second shows the result:

   ```bash
   sed -i 's#ghcr.io/samuelvisser/vodloft[:a-z0-9.-]*#ghcr.io/samuelvisser/vodloft:0.7.0#' docker-compose.yml
   grep image: docker-compose.yml
   ```

   It should show `image: ghcr.io/samuelvisser/vodloft:0.7.0`. On a Mac, write `sed -i ''` instead of `sed -i`. You can also make this change by hand: open `docker-compose.yml` in a text editor, such as `nano docker-compose.yml`, and change the `image:` line.

4. **Download the new version and start it:**

   ```bash
   docker compose pull
   docker compose up -d
   ```

5. **Check that it worked.** Open VODLoft in your browser. The bottom of the sidebar shows the version, such as **v0.7.0**. The first start after an upgrade can take a minute while VODLoft upgrades its database. If VODLoft does not open, this shows what went wrong:

   ```bash
   docker compose logs --tail 100
   ```

Keep the `config-before-0.7.0` folder until you are sure everything works. After that you can delete it with `sudo rm -rf config-before-0.7.0`.

Once `docker-compose.yml` names a version, `docker compose pull` on its own no longer moves you to a newer one: you decide when VODLoft changes, and a backup always matches a known version. With `ghcr.io/samuelvisser/vodloft:latest` instead, every `docker compose pull` takes whatever version is newest at that moment.

### If a command does not work

- `docker compose` gives "unknown command" or "is not a docker command": your Docker is older. Type `docker-compose` (with a dash) instead of `docker compose`.
- Docker says "permission denied": put `sudo` in front of each `docker` command.

### Go back to an earlier version

A new version may have upgraded the database, and an older version cannot read the upgraded one. Going back therefore puts back the backup from step 2. Anything you changed in VODLoft since the upgrade is lost; downloaded files stay where they are.

In your VODLoft folder, with the version you are going back to (here `0.6.1`):

```bash
docker compose stop
sudo mv config config-from-0.7.0
sudo mv config-before-0.7.0 config
sed -i 's#ghcr.io/samuelvisser/vodloft[:a-z0-9.-]*#ghcr.io/samuelvisser/vodloft:0.6.1#' docker-compose.yml
docker compose pull
docker compose up -d
```

VODLoft applies required database migrations when the new container starts. Because `/config` and `/downloads` live outside the container, recreating the container does not remove those mounted directories.

## Configuration after an upgrade

VODLoft does not replace your existing `config.yml` with a newly shipped default file.

Settings you explicitly changed remain yours. Settings that are not present in your file use the defaults supplied by the new VODLoft version.

The Settings page also writes only values you actually change instead of filling `config.yml` with every possible default.

After a larger update, it is worth opening **Settings** and checking for new options that may be useful to your installation.

## Restore procedure

A typical restore is:

1. Stop VODLoft.
2. Restore the complete saved `/config` directory to the path mounted into the container.
3. Restore `/downloads` if it was included in the backup.
4. Confirm the container has permission to read and write the restored directories.
5. Start VODLoft.
6. Check Home and Library.
7. Verify the Daily Wire connection under Settings.
8. Open a known completed download and confirm the file is available.
9. Test any private RSS feeds you rely on.

If the restored installation uses a different hostname, edit the RSS Stream Profile URLs so podcast clients can reach the new address. You only need to regenerate the secret token if you intentionally want to revoke the old feed URL.

## Before experimenting with database or migration commands

Take a `/config` backup first. Database maintenance commands can be useful during development or recovery, but they are not a substitute for a known-good backup.

For ordinary upgrades, let the container apply its normal migrations automatically.