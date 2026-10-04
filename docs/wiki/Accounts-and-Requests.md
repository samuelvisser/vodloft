# Local accounts and media requests

Local VodLoft accounts control access to the application. Source connections authorize upstream providers; media-server mappings identify listeners elsewhere. These are separate identities.

The bootstrap administrator is `admin`, protected by `WL_ADMIN_AUTH__PASSWORD` when configured. In **Management**, the administrator can create local **member** and **manager** accounts, change their password/role, or disable them.

Choose which Source connections and media-server targets each account can use. Public Source access does not require a saved upstream connection. Disabling an account or withdrawing its Source grant also prevents continued use of a protected upstream playback session.

Members can discover/import media, watch permitted items, save their own progress, and request an acquisition. Managers can additionally approve/reject requests and edit/remove library metadata. Source installation, application settings, profile configuration, and account administration remain administrator operations.

Set an open-request quota and whether requests are automatically approved. A request names the Local Media Profile and intended Source/account; approval goes through the normal durable acquisition queue. Request state and rejection reasons remain visible to the requester. Users can withdraw their own pending requests.

Feed subscription permission is separate from acquisition approval. Each user's feed token and playback progress are scoped to that user. Audiobookshelf listening progress needs an explicit verified remote-user mapping.
