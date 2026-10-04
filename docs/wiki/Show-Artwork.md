# Artwork

Sources normalize artwork candidates with their role and dimensions. VodLoft selects a compatible landscape, square, or portrait candidate for library/player presentation, downloads it through the selected Source boundary, and caches a decoded JPEG.

Artwork is sanitized rather than serving arbitrary upstream image bytes directly. Missing artwork leaves the library item usable.

A Local Media Profile can request artwork in the acquired representation. Media-server presentations can receive artwork sidecars according to the target's supported metadata/scanner behavior.

Source refresh may update upstream artwork. Local media and published feed bytes keep their own lifecycle.
