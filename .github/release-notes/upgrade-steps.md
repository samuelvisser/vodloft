Back up your `config` folder first. Then, in the folder with your `docker-compose.yml`, run:

```bash
docker pull ghcr.io/samuelvisser/vodloft:${version} && docker tag ghcr.io/samuelvisser/vodloft:${version} ghcr.io/samuelvisser/vodloft:latest
docker compose up -d
```

This installs exactly ${version}, even if a newer version is out. New to Docker, or want to go back? See [Upgrade VODLoft](https://github.com/samuelvisser/vodloft/wiki/Backups-and-Upgrades#upgrade-vodloft) in the wiki.
