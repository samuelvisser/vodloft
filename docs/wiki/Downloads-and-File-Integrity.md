# Downloads and local files

Acquisition jobs resolve metadata, transfer bytes, process the requested representation, finalize files, and record availability. The UI shows progress, failures, and job history. Failed stages and public error codes help distinguish authentication, format, disk, and runtime failures.

A queued job freezes its Source/account and Local Media Profile specification. A database lease prevents two workers from running the same job. Retry attempts are bounded; scheduler retries respect backoff. Canceling an active Source stops its process, and canceling queued work releases its active identity.

Downloads are prepared in staging and published through a recovery journal. Startup recovery reconciles interrupted finalization and retains an earlier working presentation if replacement was interrupted. A missing configured media mount is reported rather than recreated as an empty replacement library.

Canonical artifacts and profile/server presentation files are separate. Compatible profiles share acquired bytes. Each direct download, Collection policy, or stream preparation holds a demand explaining why a representation is kept.

Retention and removal release demands. Files required by another policy/profile or active local playback remain. Already published RSS enclosures own separate immutable copies until their subscription is revoked.

An intentional removal/cancellation suppresses automatic recreation. Explicitly resume/retry when you want automation to acquire it again. Source disappearance does not erase a local artifact.

Verify the configured root and mounted directory before deleting or moving media manually. Back up both database and files together.
