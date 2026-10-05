# Collection Download Profiles

A Collection Download Profile chooses **which members** to acquire. Its selected Local Media Profiles choose **which files** to create.

On a Collection, add a Download Profile and select its Source/account reference, Local Media Profiles, refresh interval, and backfill rule. Backfill can cover all members, the newest count, a publication date range, or metadata only. Newest selection uses publication dates and falls back to Collection position when dates are unavailable. The Discover import review offers the same choices before automation is created and requires explicit confirmation before queueing an entire archive.

Filter by publication dates, title, member roles, and groups such as seasons. Decide whether groups discovered in future scans should be included. A mixed-Domain Collection needs applicable Local Media Profiles for each member Domain; skipped members report why they could not be scheduled.

Run the profile to refresh and queue matching items, or allow automatic scheduling. Frequent refreshes use lightweight incremental enumeration; daily full reconciliation catches older additions, ordering changes and removals. Large scans checkpoint each page and continue in bounded batches. Metadata hydration remains a separate action.

An incomplete upstream scan does not remove previously known members. Only a completed exhaustive scan retires absent membership for its selected Source/account; canonical items and shared files remain. Changing runtime or account configuration restarts a bounded scan under a new cursor scope. Scan and acquisition retries honor their attempt budgets and backoff instead of creating an endless new job on each scan. Collection history exposes progress, failures, checkpoints, cancellation and resume.

Retention may keep the newest count or a number of days. It releases this policy's demand; a file remains when another policy, direct download, stream profile, or active playback still requires it.

An intentionally removed/canceled representation stays suppressed until explicitly resumed/retried. Removing a Collection Download Profile does not erase shared canonical media.
