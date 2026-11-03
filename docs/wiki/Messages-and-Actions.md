# Messages and actions

VODLoft can tell you when something happens, and do something about it: push a message to your phone, send it to
Discord, Telegram, email or any of the 100+ services Apprise supports, refresh your Jellyfin, Emby or Plex library,
call a webhook, or run your own script.

Administrators set this up in **Settings › Messages and actions**. Everyone can choose their own push messages in
**Account › Notifications**.

## Out of the box

A new VODLoft only tells administrators about problems, as a push message to the devices where they turned push on:

- a download failed after its retries;
- a sign-in expired, or a site wants cookies;
- the disk is almost full;
- a task keeps failing;
- a new VODLoft version is out (once per version).

A daily summary at 08:00 is already there but switched off, so it is one switch away. New downloads are not a shared
default, because they are the noisy ones: each person chooses them on their own page.

The same problem (the same Collection, the same reason) is sent again only after a day.

## Destinations and services

The first list holds everywhere VODLoft can send a message or that it can call:

- **Push to the installed app** is built in. Each person turns it on per device (see below).
- **Send a message** goes through [Apprise](https://appriseit.com/services/). Pick a service and fill in its fields,
  or paste an Apprise URL. The test button sends a test message.
- **Jellyfin, Emby and Plex** get a library refresh. Enter the address and the API key (for Plex, the Plex token).
  By default only the changed folder is refreshed, and refreshes are collected for about a minute, so 40 downloads in a
  row are one refresh. If the media server sees your files under another path (for example `/downloads` in VODLoft and
  `/media` in Jellyfin), fill in the path mapping.
- **Webhook** sends the details as JSON to an address. The form shows exactly what it sends. A failed call is tried
  again three times over a few minutes.
- **Script** runs an executable from the `scripts` folder next to your `config.yml` (`/config/scripts` in Docker).
  VODLoft never stores the script itself, stops it after its time limit, and writes its output to the log. The script
  receives `VODLOFT_EVENT`, `VODLOFT_TITLE`, `VODLOFT_MESSAGE`, `VODLOFT_COLLECTION`, `VODLOFT_EPISODE`,
  `VODLOFT_FILE_PATH` and `VODLOFT_FOLDER` as environment variables. Its test runs it on the newest download.

Passwords, API keys and tokens are stored encrypted and never shown again; the list shows a safe version. Adding a
destination does not change any rule: you add it to the rules you want.

When a destination fails, its row says so with the error. A media server, webhook or script that keeps failing
counts as a problem, so the default "a task keeps failing" rule tells administrators.

## Rules

Each rule is a sentence: *When an episode is downloaded in any Collection, refresh Jellyfin and send it to Discord.*

- **When**: an episode is downloaded, replaced by a better version, or deleted; a download fails; new episodes are found
  but not downloaded (for Collections that download nothing by themselves); a sign-in expires; a task keeps failing;
  the disk is almost full; an update is out; or, for a daily summary, anything happens.
- **In**: any Collection, or only the ones you choose.
- **Then**: push it to administrators, and/or send it to destinations. Media servers, webhooks and scripts only run for
  downloads, replacements and deletions.
- **Send it**: right away, grouped per Collection once an hour, or in a daily summary at a time you choose.

New downloads of one Collection that arrive close together always go out as one message, so a backlog of 40 episodes
is one message, not 40.

Switch a rule off to keep it without using it. **Restore default rules** brings back any default rule you deleted,
without touching your own rules.

The **History** section shows what was sent lately, and why something failed.

## Your own notifications

**Account › Notifications** is each person's own page:

- **This device**: turn push on for the browser or phone you are using. Push needs VODLoft over HTTPS. On an iPhone or
  iPad, first add VODLoft to the home screen from the share menu, then turn it on from the installed app.
- **What to push me about**: your own rules. A new account starts with "my Quick download finishes" on and "an episode
  is downloaded in Collections I added" off. You only ever hear about Collections you can see.
- **Sent to you in the last 30 days**.

## Installing VODLoft as an app

VODLoft can be installed like an app from your browser (for example **Add to Home Screen** on a phone, or the install
button in the address bar on a computer). The installed app opens without the browser around it, shows an offline page
when your server cannot be reached, and can receive push messages.
