# Automation and background work

With automatic scheduling enabled, VodLoft checks Source updates, refreshes due Collections, prepares subscribed feeds, and retries eligible failed acquisitions. Download policies and Stream Profiles have their own refresh intervals and member filters.

Recovery, delivery retries, playback expiry, and retention continue to reconcile application state separately. A downstream server outage is recorded on delivery rather than converting a completed download into a failure.

The Settings screen controls automatic scheduling, concurrent acquisitions, maximum attempts, timeout, and retry backoff. Additional Source/Domain/account concurrency limits prevent one provider connection from monopolizing the worker queue.

Background migrations import an existing WireLoft installation without blocking the initial web shell. Scheduled acquisition pauses until migrations complete. Database schema migrations run before backend startup.

Activity and item/job history show acquisition stages. Source update history records failed installation and activation attempts without exposing credentials. Check those histories before repeatedly retrying an authentication or disk failure.
