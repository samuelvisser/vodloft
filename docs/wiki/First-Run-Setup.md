# First-Run Setup

On first launch, VODLoft shows the services it can add media from, helps you review security, and adds your first media. You can skip optional steps and finish them later from the normal interface.

## 1. Sources

VODLoft calls the services it adds media from **Sources**. The first-run setup lists each Source, and offers its sign-in as an optional step. Today that is The Daily Wire.

VODLoft uses The Daily Wire's device authorization flow. Follow the instructions shown by VODLoft and authorize the connection on The Daily Wire's own site.

VODLoft does **not** ask for your The Daily Wire password.

Signing in is only needed for member-exclusive content. You can continue without signing in and use what The Daily Wire makes publicly available.

You can sign in, reconnect or change the session later from **Settings → Sources**.

## 2. Decide how VODLoft should be protected

VODLoft's administrator login is separate from your The Daily Wire account.

If your installation is only reachable on a trusted private network, the administrator login is optional. If VODLoft is reachable through a reverse proxy or from an untrusted network, configure a long unique password with:

```yaml
environment:
  - VL_ADMIN_AUTH__PASSWORD=choose-a-long-unique-password
```

Restart the container after changing it.

Private RSS feeds do not use this administrator login. Each feed has its own secret URL. See [[Security-and-Remote-Access]].

## 3. Add your first show or movie

Paste a link to a show, an episode or a movie. VODLoft finds the Source that recognises the link, shows a preview, and continues to the normal Add Show wizard or movie page. A link to an episode opens its show. You can also browse The Daily Wire's catalogue instead.

### Shows

When you add a show, the wizard can set up any combination of:

- the show itself, with no automatic downloads;
- a **Local Media Profile** describing the file format, download behavior, and output path;
- a **Download Profile** for automatic podcast or series downloads;
- an **RSS Stream Profile** for a private podcast/video feed.

You do not have to configure everything at once. A good first step is to add the show, confirm its seasons and episodes look correct, and then add the download/RSS behavior you want.

### Movies

Movies use Movie Local Media Profiles and are downloaded manually from their movie page. When The Daily Wire provides extras such as trailers or featurettes, those can be downloaded from the same page using the movie profile.

Upcoming movies can remain in your Library before the actual media is available.

## A simple first configuration

For most installations:

1. Make sure `/config` and `/downloads` are persistent.
2. Set `TZ` to your local timezone.
3. Sign in to The Daily Wire under Settings → Sources if you use member content.
4. Protect the VODLoft UI if it is not confined to a trusted network.
5. Add one show with **Add media** in the Library.
6. Create a Local Media Profile with the format and folder structure you want.
7. Add a Download Profile if you want automatic downloads.
8. Add an RSS Stream Profile only if you want to use VODLoft as a private podcast/video feed.

From there, **Home** shows the current health of the instance, **Library** contains your managed media, and **Downloads** shows actual file activity.

For the profile concepts in more detail, see [[Local-Media-Profiles]], [[Download-Profiles]], and [[Podcast-RSS-Feeds]].