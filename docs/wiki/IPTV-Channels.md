# IPTV Channels

An **IPTV Stream Profile** turns a collection into a TV channel. Add its playlist to a TV app, such as TiviMate or
Kodi's IPTV Simple, and the collection shows up next to your other channels, with a programme guide. A live episode
plays live; between live episodes the channel keeps showing something, and catch-up lets you play an earlier episode
from its place in the guide.

> [!CAUTION]
> **Treat the playlist, guide and episode playlist URLs like passwords.** They contain a secret token, and anyone with
> one of them can watch your channels without signing in to VODLoft. See [If an address leaks](#if-an-address-leaks).

## Create a channel

1. Open **Profiles → Stream Profiles**, choose **Add**, pick **IPTV** and the collection.
2. Choose where the media comes from, the same way as for a podcast feed: your downloads, the site's own streams,
   or both (see [[Podcast-RSS-Feeds#choose-where-media-comes-from]]).
3. Save, and copy the **Playlist URL** into your TV app.

Most TV apps find the guide in the playlist. When an app asks for an *EPG* address, give it the **Guide URL**.

Your TV app has to reach VODLoft. On your own network a local address is enough; away from home, use a VPN or your
own HTTPS reverse proxy (see [[Security-and-Remote-Access]]).

## Channel settings

- **Channel number** — where the channel sits in your TV app's channel list. Leave it empty for the next free number.
- **Channel group** — the group your TV app lists the channel under, such as *News*. Left empty, it is the site's
  name, such as *YouTube*.
- **Stream live episodes** — a live episode plays live on the channel, on sites that stream live.
- **Maximum episodes in the guide** — only the newest episodes play on the channel and fill its guide. 0 means no
  limit.

### Between live episodes

What the channel shows while none of its episodes is on:

- **Newest episode** (the default) plays the newest episode the channel aired, on a loop, until the next one starts.
- **Off air** shows an off-air screen until the next episode starts.
- **Hide channel** lists the channel only while one of its episodes is live. Your TV app may only notice when it next
  reloads the playlist.

### Catch-up

The **Catch-up window** says how far back the guide reaches, from 1 to 30 days (7 by default). TV apps with
catch-up, such as TiviMate and Kodi, play an episode again from its place in the guide. Apps without catch-up still
show the guide.

### Episodes on their own

**Also list episodes on their own** adds an **Episode playlist URL**: a playlist with every episode as an entry of
its own. Open it in VLC or another app without a guide to pick an episode yourself.

## All your channels in one playlist

Your account page has a **Watch in other apps** card with one playlist, one guide and one episode playlist holding
all your IPTV channels. Add that playlist once, and channels you create later appear in it by themselves.

## If an address leaks

Choose **Regenerate** next to the address. The old address stops working at once, and apps that used it need the new
one. On the channel's page this changes that channel's addresses; on your account page it changes the addresses with
all your channels and WebDAV shows.
