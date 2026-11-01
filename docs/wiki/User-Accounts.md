# User Accounts

Without user accounts, VODLoft has one way in: the administrator password from the `VL_ADMIN_AUTH__PASSWORD` environment variable, or no password at all. Everyone who signs in can do everything.

User accounts give each person their own username and password, and only the parts of VODLoft they need. For example, a friend can quick download YouTube videos on their phone without seeing your library, your settings or your Daily Wire sign-in.

## Turning accounts on

Open **Settings → Users** and switch on **Sign in with user accounts**. The first time, VODLoft asks you to create the first administrator, and signs you in as them.

From then on, the sign-in page asks for a username and a password. The environment password only works for recovery while no administrator can sign in (see [Locked out](#locked-out)).

Turning accounts off again signs everyone out. The users are kept, so turning accounts back on brings them back.

## Adding a user

Click **Add user**, give them a username and a **one-time password**, and pick a template:

| Template | What they see |
|---|---|
| **Administrator** | Everything, including Settings and Users. |
| **Library manager** | The library (and changing it), adding media, Downloads, Quick download, using the profiles, their own Stream Profiles, Tasks. |
| **Viewer** | The library and Downloads, read-only, and their own Stream Profiles. |
| **Downloader** | Only Quick download and their own history. |

Picking a template fills in a level for each part of VODLoft. You can change any line afterwards; the user then shows as *customised*. Each part is **Hidden**, **View** (or *Use*, *Own*) or **Manage**. The editor says in plain words what the user will see.

The first time they sign in, they must choose their own password before anything else opens.

### Sources and domains

On the right of the editor you choose which Sources the user may use: every Source, or only some. For a Source that takes links from any site, such as yt-dlp, you can limit them to a few domains. The suggestions add a site's usual domains together, such as `youtube.com` and `youtu.be` for YouTube. A domain also allows its subdomains, so `youtube.com` allows `m.youtube.com`.

These limits apply to looking up links, Browse and Search, adding collections, movies and videos, and Quick download. VODLoft also checks the link a Source resolves to, so a short link or redirect cannot lead somewhere else. A refused link says why, and which domains the user may use. The limits do not hide library items that came from other Sources; that is what the Library level is for.

### Members-only media

The **Members-only media** switch decides whether the user may use the memberships signed in under **Settings → Sources**, such as your Daily Wire membership. Without it, they only get what a free account gets: free episodes, and no members-only movies. Administrators always have it.

### Deleting files

Deleting downloaded files from disk is a separate switch, on top of the user's levels.

## What belongs to whom

- **Quick downloads** belong to whoever asked for them. Users see, fetch and cancel only their own, and only see their own history. Those with **Quick downloads: Everyone's** see everyone's.
- **Stream Profiles** belong to whoever made them. Users see and change only their own feeds; **Stream Profiles: Everyone's** sees all of them. Profiles made before user accounts were turned on belong to the first administrator.
- **Operations** (the progress notifications) show only what the user asked for, unless they may see **Tasks**.
- Collections, movies and videos remember who added them. Administrators see **Added by** on their pages.
- **Quick download preferences.** The rules in **Settings › Quick download** (highest quality, formats, codec, largest file, longest video, Sources) apply to everyone. Within them, each user can tick **Use these as my defaults next time** in the format panel to save their own choice of kind, quality, format, codec and audio to their account. **Use this VODLoft's defaults instead of mine** goes back. With **Lock to defaults** on, everyone gets the install's defaults.
- In **Quick downloads: Everyone's**, ready files and history show who asked for them.

When a user is **disabled**, they are signed out everywhere and their feeds stop answering until they are enabled again. When a user is **deleted**, you choose whether their Stream Profiles go to you (the feeds keep working) or are deleted too.

## Passwords and sessions

- Anyone can change their own password from the account link at the bottom of the sidebar. That signs them out on their other devices.
- An administrator can **Reset password** to a new one-time password, and **Sign out everywhere**.
- After several wrong passwords, VODLoft makes the next attempt wait a little longer each time, per username and per address.

## Locked out

If no administrator can sign in any more:

- With `VL_ADMIN_AUTH__PASSWORD` set, sign in with that password and no username. That only works while no enabled administrator exists, and it can only be used to fix the users.
- Or, on the server, run:

```bash
docker exec -it vodloft backend-api users list
docker exec -it vodloft backend-api users reset-password <username> --administrator
```

The second command asks for a new one-time password, makes the user an administrator, and enables them.
