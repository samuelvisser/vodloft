# VodLoft 1.0 design acceptance

This record follows the supplied **VodLoft Technical Architecture Design**. The application is derived from WireLoft commit `7853ee7bdf1137111193932fe9da7e8243442bd5`, whose original ancestry is preserved in Git.

## Required scenarios

Tests below live in `tests/unit/test_vodloft_architecture.py` unless another file is named. Fixture Sources isolate deterministic lifecycle checks from provider account/network availability.

| Design scenario | Implemented behavior | Regression evidence |
| --- | --- | --- |
| 1. Add a third Source without core edits | Operator registry, installed worker entry point, typed process contract, generic discovery/forms. | `test_operator_registered_third_source_appears_in_generic_endpoint`; `test_independent_source_bundle_install_health_failure_and_rollback`; third-process contract test in `test_vodloft_prototype.py`. |
| 2. Two Sources support one Domain explicitly | Source matching prefers a declared specific match; explicit selection never silently falls back to another Source/account. | `test_source_selection_prefers_specific_match_and_never_silently_falls_back`; `test_source_account_references_share_media_without_leaking_secrets`. |
| 3. One canonical item belongs to multiple Collections | Canonical identity and Collection occurrences are stored separately; compatible profiles reuse acquired bytes. | `test_shared_media_partial_scan_download_and_playback` in `test_vodloft_prototype.py`; `test_stable_collection_occurrences_survive_reordering`; `test_compatible_profiles_share_one_artifact_without_crossing_source_accounts`. |
| 4. Partial scans never delete known members | Bounded pages, persistent runtime/account cursor scope, incomplete checkpoints, preserved membership. | `test_paged_collection_refresh_keeps_known_members_on_partial_failure`; shared-media prototype test. |
| 5. Failed update retains previous active release | Exact wheel/digest verification, staged installation, protocol/schema/interpreter/package/health/configuration checks, atomic activation, rollback. | `test_bad_source_bundle_digest_never_activates`; `test_independent_source_bundle_install_health_failure_and_rollback`; `test_source_update_failure_isolated_to_one_release`; signed-catalogue and publisher round-trip tests. |
| 6. Queued/running jobs pin their runtime | Frozen command/reference/profile specification and a renewable database lease. | `test_running_job_keeps_queued_source_runtime_command`; `test_profile_representation_is_frozen_and_partitions_artifact_reuse`; `test_job_lease_prevents_duplicate_execution`. |
| 7. Upstream disappearance preserves local media | Canonical items/artifacts remain available independently of later Collection enumeration. | `test_upstream_disappearance_and_server_outage_preserve_local_acquisition`. |
| 8. Local arrival does not interrupt upstream playback | Playback-session transport, lease, representation, and worker command remain pinned; new sessions may choose local. | `test_upstream_session_stays_pinned_when_local_file_arrives`; `test_hls_child_renews_signed_uri_and_keeps_one_representation`. |
| 9. Integration outage does not fail acquisition | Separate persisted export state, scan/availability verification, retry lifecycle. | `test_upstream_disappearance_and_server_outage_preserve_local_acquisition`; media-server matching and RSS-pull lifecycle tests. |
| 10. Deleting profiles/Collections preserves shared-demand files | Durable demands, profile retirement, queued cancellation, shared retention, active-session protection, immutable published copies. | `test_profile_deletion_cancels_queued_work_and_preserves_shared_artifact`; `test_retention_preserves_shared_demands_and_active_local_session`; shared-media prototype test. |

## Feature coverage

| Design area | Implementation |
| --- | --- |
| Source/core/integration separation | `server/source_contracts`, `server/source_ytdlp`, `server/source_dailywire`, `server/source_media`; core `backend/source_manager`; separate downstream export lifecycle. AST checks enforce contract/gateway and inherited API dependency boundaries. |
| Domain support and canonical library | `backend/db/models/vodloft`; Source/account-scoped references, manager-confirmed cross-Source identity linking, normalized snapshots, independent membership, Source history and user edits. |
| Movies and shared Extras | Strong `MovieExtraParent` links, per-parent roles, generic parent-list editing, explicit user overrides retained across Source refresh. |
| Local Media Profiles and templates | Domain/type applicability; quality, language/fallback, subtitles, container/codecs, artwork/chapters/tags, selected targets; Jinja AST validation, sanitized rooted output, CodeMirror completion and scoped previews. |
| Collection acquisition | Source/account selection, backfill, dates/title, groups/roles/future groups, mixed Domains, pagination, explicit bounded nesting, retention, suppression and retry budget. |
| Durable jobs and filesystem | Frozen execution specifications, global/Source/Domain/account limits, process cancellation, progress/stage history, leases, backoff, finalization journals, recovery and unavailable-mount protection. |
| RSS and live admission | Portable normal-queue preparation, per-user revocable tokens, immutable copies, HEAD/ranges, rendition fallback, admission retained through live/archive transition. |
| Web playback | Owned encrypted sessions, local/upstream selection, opaque HLS manifests/children, private renewal, representation pinning, queue/resume/speed/chapters/subtitles. |
| Plex/Jellyfin/Audiobookshelf | Actual server discovery/scans, path mapping, metadata/artwork, persisted downstream IDs and availability, compatible Plex strategy, ABS episode mapping and explicit non-rewinding progress import. |
| Audiobookshelf RSS pull | Owned feed subscription/delivery, remote podcast/episode availability, independent file retention, explicit verified listener tokens. |
| Local accounts and requests | Admin/member/manager boundaries, Source/target grants, subscription permission, quotas, optional automatic approval, approval/rejection/withdrawal, independent progress. |
| Source release lifecycle | Independent locked wheelhouses, package/digest inventories, own interpreters, signed digest-pinned native executables, pinned helper lookup/health, signed HTTPS publisher/catalogues, stable/beta, pin/manual/rollback, saved-schema validation and draining pinned work. |
| Product workspace | Home, Discover, Library, Management, Settings, Source-independent welcome screen, generic connection/challenge forms, request/user/integration/feed controls. |
| WireLoft upgrade | Alembic schema chain plus background conversion of populated Shows/Episodes/Movies/Extras, profiles, account references, feeds/live flags, files, original Git history. `test_vodloft_upgrade.py` exercises a populated pinned database. |

## Reproduce the checks

```sh
uv sync --frozen
npm ci --registry=https://registry.npmjs.org
uv run --frozen pytest tests/unit/test_vodloft_architecture.py tests/unit/test_vodloft_prototype.py tests/unit/test_vodloft_upgrade.py -q
npm run build
npm --prefix ui audit --audit-level=moderate --registry=https://registry.npmjs.org
uv run backend-api db history
uv run backend-api background-migrations history
```

`.github/workflows/vodloft-ci.yml` runs the regression suite, dependency advisory check, production frontend build, and independent Source wheel builds. It builds the actual Docker image, starts a fresh authenticated installation, checks production assets/API/library and both isolated Sources, verifies the persistent media root, runs real FFmpeg AAC/M4A processing with edited tags and chapters, and checks backend/nginx logs for bearer-token leakage. Only extraction/HTTP transfer use a deterministic audio fixture in that media check; FFmpeg and the installed Source's normal processing path run unchanged.

The schema chain ends at `1c9ad7e430b8`; the background chain ends at `c64f8092de17`. The populated upgrade check compares against the actual current head rather than a fixed obsolete revision.

## Verification boundaries

The deterministic suite and container checks are reproducible. Interactive visual verification could not be completed because the workspace browser blocked the local application. The three downstream adapters have fixture coverage, not a claim of live-server validation without server credentials/mounts. Operator configuration and account entitlements remain necessary for those deployments.

The full inherited WireLoft suite contains baseline failures and imports of migration files absent from the pinned checkout; it is not reported as a passing VodLoft suite. The Source process boundary is dependency isolation and trusted-adapter separation, not an operating-system sandbox.
