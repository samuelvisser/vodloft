# Downloads and local files

Acquisition jobs resolve metadata, transfer bytes, process the requested representation, finalize files, and record availability. The UI shows progress, failures, and job history. Failed stages and public error codes help distinguish authentication, format, disk, and runtime failures.

A queued job pins its Source/runtime, reference and account scope. At first dispatch it adopts the current applicable Local Media Profile and records an immutable specification with the profile revision, selected representation, metadata and output template. Profile edits can affect queued work; running work and retries retain their dispatched specification. Changing account credentials invalidates queued acquisition scope and requires a new request. Token renewal for the same account preserves that scope.

A database lease prevents two workers from running the same job. Global, Source, Domain and account limits cover acquisition and upstream synchronization. Retry attempts are bounded, honor backoff and give rate-limited Sources a longer delay. Canceling active Source work terminates its process; canceling queued work releases its active identity. TaskOperations expose the durable job's server-provided stage, explanation and progress, including indeterminate progress while the total is unknown.

When a Source/account is busy, another acquisition stays queued without occupying a global download slot. Canceling it takes effect immediately. Collection scan history also records failures before the first page, and automatic retries use the same bounded budget as later-page failures.

Downloads are prepared in staging and published through a recovery journal. Startup recovery reconciles interrupted finalization and retains an earlier working presentation if replacement was interrupted. A missing configured media mount is reported rather than recreated as an empty replacement library.

Canonical artifacts and profile/server presentation files are separate. Compatible profiles share acquired bytes. Each direct download, Collection policy, or stream preparation holds a demand explaining why a representation is kept.

Retention and removal release demands. Files required by another policy/profile or active local playback remain. Already published RSS enclosures own separate immutable copies until their subscription is revoked.

An intentional removal/cancellation suppresses automatic recreation. Explicitly resume/retry when you want automation to acquire it again. Source disappearance does not erase a local artifact.

Verify the configured root and mounted directory before deleting or moving media manually. Back up both database and files together.
