# Library and discovery

VodLoft supports **Videos**, **Movies**, **Movie Extras**, and **Collections**. Shows, channels, playlists, and seasons are represented as Collections or grouped Collection membership. The same canonical item may appear in several Collections without creating separate media files.

**Discover** accepts public URLs and offers search for Sources that advertise it. Search and URL resolution are previews; import happens only when you choose it. **Library** provides text filtering, item details, references, available formats, Source snapshots, local files, playback, and Collection policies.

Choose a Source/account reference explicitly when an item has several. Refreshing details updates upstream information while preserving your title, description, and classification edits. Source history lets you restore an earlier upstream snapshot without erasing those edits.

To add another Source to an existing item, resolve its URL in **Discover**, select the existing item under **Library identity**, and confirm that it is the same edit, language, and edition. Library managers can link verified references from the same content Domain. Linking preserves metadata, memberships, Movie relationships, and local files; the new Source's snapshot appears in Source history. A generic Video reference can also point to a Movie or Movie Extra you have classified. Choose the new reference explicitly for playback or acquisition. Refresh a linked Collection from that reference to discover its members. A reference already assigned to another item reports a conflict; it is never silently reassigned. Different editions and alternate uploads remain separate items.

The identity selector includes playable Collection members and Movie Extras as well as top-level library items. Formats and capabilities belong to each Source/account reference: one Source may supply metadata while another supplies the playable or downloadable representation. Choosing another reference uses its availability information, without changing the selected item's title or library classification.

A Movie's Extras are strong parent relationships rather than ordinary playlist entries. A shared extra can belong to multiple Movies. Its upstream role may differ by Movie; editing the parent list or extra type preserves your choices during subsequent refreshes.

Refresh Collections to discover members. A failed or partial scan keeps previously known entries and exposes its incomplete checkpoint. Nested Collections expand explicitly with depth/count limits and cycle detection.

When several Sources describe the same Collection, each Source's occurrence IDs and memberships are kept separately. Matching titles or occurrence IDs from another Source do not confirm that two playable items are the same edition; link those items explicitly when appropriate.

Collection acquisition, feed filtering, future-group choices, and output numbering follow the selected Source's memberships. A disabled or ambiguous Collection reference requires an explicit selection before scheduling; it does not silently substitute another Source's entries.

The browser player can use a local file or an upstream session. It supports queues, resume, playback speed, chapter navigation, and available subtitle tracks. An upstream session keeps its chosen delivery and Source runtime if a local download finishes while it is playing.

Removing a Collection removes its policies and membership, while preserving canonical items and files still required elsewhere. See [Downloads and file integrity](Downloads-and-File-Integrity.md) before removing local media.
