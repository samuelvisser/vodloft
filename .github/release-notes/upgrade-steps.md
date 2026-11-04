Back up your `config` folder first. Then, in the folder with your `docker-compose.yml`, run:

```bash
sed -i 's#ghcr.io/samuelvisser/vodloft[:a-z0-9.-]*#ghcr.io/samuelvisser/vodloft:${version}#' docker-compose.yml
docker compose pull && docker compose up -d
```

This installs exactly ${version}, even if a newer version is out. New to Docker, on a Mac, or want to go back? See [Upgrade VODLoft](https://github.com/samuelvisser/vodloft/wiki/Backups-and-Upgrades#upgrade-vodloft) in the wiki.
