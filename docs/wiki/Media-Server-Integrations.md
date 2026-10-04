# Plex, Jellyfin, and Audiobookshelf

In **Management**, add a media-server target with its server URL, API token, library ID, local path prefix, and server-visible path prefix. Test the connection before selecting it on a Local Media Profile.

The path prefixes describe the same shared files as seen by VodLoft and the server. For example, VodLoft may publish under `/downloads/library` while Jellyfin sees `/media/library`. Both containers need mounts that refer to the same host directory. A successful API connection does not prove those mounts match.

VodLoft creates a target-specific presentation, requests a library scan, and looks up the server item by mapped path in the selected library. Item details expose downstream availability and a server link when mapping succeeds. Acquisition can succeed while a server is unavailable; delivery records retain errors and can be retried separately.

Jellyfin receives explicit NFO metadata and optional artwork. Plex checks the server identity, library scanner, and agent before choosing a compatible metadata/local-assets presentation. Check the connection result and your server's library settings if metadata is missing.

Audiobookshelf supports two delivery modes:

| Mode | Files and retention |
| --- | --- |
| Shared folder | VodLoft owns its local presentation; Audiobookshelf scans the mounted podcast library. |
| RSS pull | VodLoft owns immutable feed enclosures; Audiobookshelf downloads and retains its own copies. Revoking delivery stops feed access and retains copies already downloaded by Audiobookshelf. |

RSS-pull delivery requires a publicly reachable feed base URL from the Audiobookshelf server. VodLoft tracks the remote podcast and downloaded episodes rather than reporting success solely because a subscription was created.

For Audiobookshelf listening progress, explicitly map a local account to its remote user ID and that user's API token. VodLoft verifies the identity before using it. **Import listening progress** uses the mapped user's token and never moves local progress backwards. It does not guess matching usernames or use an administrator token as every listener.

The adapters have automated fixture coverage. Your server credentials, permissions, scanner/agent, and mounts still need a deployment connection test.
