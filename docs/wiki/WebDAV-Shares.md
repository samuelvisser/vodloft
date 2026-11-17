# WebDAV Shares

A **WebDAV Stream Profile** shares a collection as a network folder laid out like a TV show: a folder for the show,
season folders and episode files with names media players understand. Add the share to Infuse, Kodi, VLC or your
file manager, and the collection shows up there as a TV show, with its artwork and episode details.

The share is read-only: apps can play the episodes, but cannot change or delete anything.

> [!CAUTION]
> **Treat the share URL like a password.** The address is the key: the share opens without signing in, so anyone
> with the address can watch what is in it. See [If an address leaks](#if-an-address-leaks).

## What is in the share

The share lists an episode once VODLoft has a whole file of it:

- a download of the episode, or
- a video VODLoft already prepared for another app, such as a podcast feed, in the Stream Video Cache.

Media players jump around in a file while you watch, which they cannot do in a live stream, so episodes VODLoft only
has as a stream are left out. Choose where the media comes from the same way as for a podcast feed (see
[[Podcast-RSS-Feeds#choose-where-media-comes-from]]).

**Maximum episodes in the folder** keeps only the newest episodes in the share. 0 means no limit.

## Show settings

- **Folder name** — the show's folder in the share, and the name in front of each episode. Left empty, it is the
  collection's title.
- **Season folders**:
  - **One per season** (the default) puts each season's episodes in a *Season 01* folder, and names them *S01E05*.
  - **One per year** puts each year's episodes in a *Season 2026* folder, and names them by date.
  - **All in one folder** puts every episode in the show's folder, named by date.
- **Files for media players**:
  - **NFO files and artwork** (the default) lists `tvshow.nfo`, `season.nfo` and an NFO file per episode, with the
    show's poster and each episode's picture.
  - **Artwork only** lists the poster and the pictures, for players that look up the rest themselves.
  - **Media files only** lists only the episodes.

The names in the share are always the same TV-show names, whatever your Local Media Profiles name the files on
disk, so a player recognises the show.

## Add the share to an app

Copy the **Share URL** from the Stream Profile and add it as a WebDAV share. If the app asks for a user name and
password, leave them empty. Windows only connects to a share over HTTPS, so use your own HTTPS reverse proxy for it
(see [[Security-and-Remote-Access]]).

Your account page has a **Watch in other apps** card with one share that holds a folder for each of your WebDAV
shows. Add that share once, and shows you create later appear in it by themselves.

## If an address leaks

Choose **Regenerate** next to the address. The old address stops working at once, and apps that used it need the new
one. On the show's Stream Profile this changes that share's address; on your account page it changes the addresses
with all your shows and IPTV channels.
