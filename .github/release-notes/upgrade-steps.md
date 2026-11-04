### Upgrade step by step

These steps install exactly **VODLoft ${version}**, even if a newer version has come out since. They are written for the standard Docker Compose setup from the [Installation guide](https://github.com/samuelvisser/vodloft/wiki/Installation). Type each command in a terminal on the computer or server that runs VODLoft, and press Enter after each one.

1. **Go to your VODLoft folder**, the folder with your `docker-compose.yml` in it. If you followed the Installation guide, that is the `vodloft` folder in your home folder:

   ```bash
   cd ~/vodloft
   ```

   To check you are in the right place, run `ls`. You should see `docker-compose.yml` and a `config` folder.

2. **Stop VODLoft and make a backup** of its `config` folder, which holds your database and settings. With this backup you can always go back.

   ```bash
   docker compose stop
   sudo cp -a config config-before-${version}
   ```

   `sudo` may ask for your own password. If your system has no `sudo`, for example because you are logged in as root, leave out `sudo`.

3. **Choose version ${version}.** This command changes the `image:` line in `docker-compose.yml` so it names version ${version}:

   ```bash
   sed -i 's#ghcr.io/samuelvisser/vodloft[:a-z0-9.-]*#ghcr.io/samuelvisser/vodloft:${version}#' docker-compose.yml
   grep image: docker-compose.yml
   ```

   It should show `image: ghcr.io/samuelvisser/vodloft:${version}`. On a Mac, write `sed -i ''` instead of `sed -i`. You can also make this change by hand: open `docker-compose.yml` in a text editor, such as `nano docker-compose.yml`, and change the `image:` line to `image: ghcr.io/samuelvisser/vodloft:${version}`.

4. **Download VODLoft ${version} and start it:**

   ```bash
   docker compose pull
   docker compose up -d
   ```

5. **Check that it worked.** Open VODLoft in your browser. The bottom of the sidebar shows **v${version}**. The first start after an upgrade can take a minute while VODLoft upgrades its database. If VODLoft does not open, this shows what went wrong:

   ```bash
   docker compose logs --tail 100
   ```

Keep the `config-before-${version}` folder until you are sure everything works. After that you can delete it with `sudo rm -rf config-before-${version}`.

Because `docker-compose.yml` now names version ${version}, `docker compose pull` on its own no longer moves you to a newer version. To upgrade later, follow the steps on that version's release page.

If `docker compose` gives "unknown command" or "is not a docker command", your Docker is older: type `docker-compose` (with a dash) instead of `docker compose` everywhere. If Docker says "permission denied", put `sudo` in front of each `docker` command.

<details>
<summary>Going back to VODLoft ${previous_version}</summary>

VODLoft ${version} may have upgraded the database, and VODLoft ${previous_version} cannot read the upgraded one. Going back therefore puts back the backup from step 2. Anything you changed in VODLoft since the upgrade is lost; downloaded files stay where they are.

Run these commands in your VODLoft folder:

```bash
docker compose stop
sudo mv config config-from-${version}
sudo mv config-before-${version} config
sed -i 's#ghcr.io/samuelvisser/vodloft[:a-z0-9.-]*#ghcr.io/samuelvisser/vodloft:${previous_version}#' docker-compose.yml
docker compose pull
docker compose up -d
```

</details>

<details>
<summary>Installing VODLoft ${version} for the first time</summary>

```bash
mkdir ~/vodloft
cd ~/vodloft
curl -O https://raw.githubusercontent.com/samuelvisser/vodloft/v${version}/.docker/docker-compose.yml
sed -i 's#ghcr.io/samuelvisser/vodloft[:a-z0-9.-]*#ghcr.io/samuelvisser/vodloft:${version}#' docker-compose.yml
docker compose up -d
```

Then open http://localhost:5274 in your browser and follow the first-run setup. The [Installation guide](https://github.com/samuelvisser/vodloft/wiki/Installation) explains the settings in `docker-compose.yml`, such as your timezone and a password.

</details>
