# Security and remote access

Configure the administrator password before exposing VodLoft to other people. Without one, the bootstrap installation is unrestricted administrator mode. Use local member/manager accounts for shared access and grant only the upstream connections and server targets they need.

Use HTTPS through a reverse proxy for remote access. Preserve the public Host and scheme when forwarding requests. Allow RSS and enclosure paths to reach VodLoft; podcast clients authenticate with their unguessable feed URL rather than the browser session cookie.

Treat feed URLs as credentials. Rotation/revocation immediately invalidates the old subscription URL. VodLoft redacts feed and opaque playback tokens from backend access logs and suppresses their nginx request/error logs. Apply equivalent redaction in an outer proxy.

Source connection secrets and media-server tokens are encrypted on disk. Back up their keys with the database. Limit access to the configuration volume and trusted Source registry/bundle mounts.

Public media URL resolution rejects private/local destinations and embedded credentials. Trusted configured media-server endpoints are a separate operator decision. A Source process is trusted code; its separate Python environment is not an operating-system sandbox. Use network/container restrictions when you need to constrain native-helper access.
