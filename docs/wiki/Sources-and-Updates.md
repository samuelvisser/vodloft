# Sources, accounts, and updates

A **Domain** is a website; a **Source** is the adapter that reads it. Several Sources can support one Domain, and a Source can support many Domains. Local Media Profiles belong to Domains, so changing an adapter does not redefine your output policy.

Management lists adapter versions, upstream dependency versions, capability declarations, Domain catalogues, connection forms, and runtime history. A catalogue can be incomplete; generic URL resolution may support more websites than the displayed list.

A Source connection stores an upstream account's settings and encrypted secret references. Forms are built from the installed Source's declared fields. The yt-dlp Source accepts an optional Netscape `cookies.txt`; The Daily Wire also supports interactive authentication. A Source authentication challenge is separate from signing in to VodLoft.

A library item may have references from different Sources/accounts. Select the intended reference explicitly. VodLoft does not silently switch to another account when the selected one fails.

Sources can supply their own Python environment and native tools in an immutable release bundle. New operations use the active release; queued downloads and existing upstream playback sessions keep the release and bundled tools they started with. A helper or health-check failure keeps the previous Source active. Publisher setup and bundle formats are documented in [Source authoring](../SOURCE_AUTHORING.md).

Choose automatic updates, stable/beta channel, and an optional pinned release. **Check Source bundles** checks trusted mounted wheelhouses and configured signed catalogues. Manual activation and rollback use installed immutable versions.

A failed update retains the previous active runtime. Queued/running acquisitions and current upstream playback sessions continue using their original runtime. New operations use the activated version.

Operators can register another Source or configure a trusted signed publisher without editing core. Installation, signing, and trust configuration are documented in [Source authoring](../SOURCE_AUTHORING.md).
