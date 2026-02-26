# MindRoom Synapse Fork - Changes Since 16245f055096e8d0ab33b62e5769ade4b1a375c3

This document enumerates every fork change after base commit
`16245f055096e8d0ab33b62e5769ade4b1a375c3`.

Rules followed:
- No guessing. If intent is not explicit in commit message or diff, it is marked TODO.
- Each change lists files touched and observable behavior impact.

## How To Regenerate
- Commit list: `git log --reverse --format="%H %ad %s" 16245f0550..HEAD`
- Per-commit diff: `git show <sha>`

## Working Tree (Not Yet Committed)
No uncommitted repository file changes documented.

## Commit-by-Commit Changes

### Add fork Docker publishing workflow and CI guards
Commit:
- `ec7c8535a913f1a2706bec1ff942d3a9bb63cb27`

Files changed:
- `.github/workflows/docker-publish-push.yml`
- `.github/workflows/docker.yml`
- `shell.nix`

What changed:
- Added a fork-owned Docker publish workflow that pushes to `ghcr.io/${{ github.repository }}` on every branch push.
- Guarded upstream `docker.yml` so upstream image publish jobs run only when `github.repository_owner == 'element-hq'`.
- Added `shell.nix` that points to the flake dev shell (NixOS-friendly entrypoint).

Why:
- Stated in commit subject.

### Collapse superseded replace edits and advertise support
Commit:
- `4600d32cc549ab48dfe028f7844163f346d8e601`

Files changed:
- `synapse/config/experimental.py`
- `synapse/handlers/pagination.py`
- `synapse/handlers/relations.py`
- `synapse/handlers/room.py`
- `synapse/handlers/sliding_sync/__init__.py`
- `synapse/handlers/sync.py`
- `synapse/rest/client/versions.py`
- `tests/rest/client/test_delayed_events.py`
- `tests/rest/client/test_relations.py`

What changed:
- Added `experimental_features.mindroom_compact_edits_enabled` (default `false`).
- Added `RelationsHandler.collapse_superseded_replace_events(...)` to keep at most one `m.replace` relation event per target in response timelines.
- Applied collapse logic to:
  - `/sync` timeline handling
  - Sliding Sync timeline handling
  - Pagination (`/messages`) event responses
  - Room context (`/context`) before/after event windows
- Added unstable feature advertisement:
  - `/versions` now reports `unstable_features["org.mindroom.compact_edits"]` when enabled.
- Added tests to validate collapse behavior and delayed-event compatibility.

Why:
- Stated in commit subject.

### Purge superseded edit events from storage
Commit:
- `1c1ce96c54` through `b88cda0fbf` (feature/edit-purge branch)

Files changed:
- `synapse/config/experimental.py`
- `synapse/storage/databases/main/purge_edits.py` (new)
- `synapse/storage/databases/main/__init__.py`
- `synapse/handlers/purge_edits.py` (new)
- `synapse/rest/admin/purge_edits.py` (new)
- `synapse/rest/admin/__init__.py`
- `synapse/server.py`
- `tests/rest/client/test_relations.py`

What changed:
- Added `experimental_features.mindroom_edit_purge` config block:
  - `enabled` (default `false`)
  - `min_age_seconds` (default `86400`) — only purge edits older than this
  - `interval_seconds` (default `3600`) — background purge cycle interval
  - `batch_size` (default `1000`) — max events to purge per cycle
  - `dry_run` (default `false`) — log what would be purged without deleting
- Requires `mindroom_compact_edits_enabled: true` (enforced at config load).
- Created `PurgeEditsStore` with SQL to find and hard-delete superseded
  `m.replace` events from storage tables. Uses same sender+type matching
  logic as `get_applicable_edits`.
- Purge selection is stateless per run (no persisted stream cursor), so:
  - `dry_run: true` does not consume work from subsequent non-dry-run purges.
  - Selection cannot skip long-lived candidates due to cursor/age skew.
- Created `PurgeEditsHandler` with periodic background task via `looping_call`.
- Created admin API endpoint `POST /_synapse/admin/v1/purge_edits` for
  on-demand purge with optional `min_age_seconds`, `batch_size`, `dry_run`
  overrides.
- Admin API now explicitly rejects manual purge calls when
  `mindroom_edit_purge.enabled` is `false`.
- Added 17 tests covering: basic purge, min-age respect, original event
  preservation, dry-run mode, dry-run non-mutating behavior, single/no edits
  edge cases, multi-target purge, batch-size behavior, receipt-anchored edit
  preservation, admin API auth/overrides/validation, disabled-feature API
  rejection, and same-sender-only semantics.

Why:
- The compact edits feature hides intermediate edits from API responses but
  keeps them in the database indefinitely. This feature complements it by
  actually reclaiming storage after a configurable grace period.

## Runbook

## Purpose
The fork-specific feature reduces timeline event volume from rapid edit streaming while preserving canonical Matrix event storage.

## Enable compact edit collapsing
In `homeserver.yaml`:

```yaml
experimental_features:
  mindroom_compact_edits_enabled: true
```

Default is `false`.

## Verify feature advertisement
Check `/versions`:

```bash
curl -s http://<homeserver>/_matrix/client/versions
```

Expected when enabled:
- `unstable_features["org.mindroom.compact_edits"] == true`

## Behavior summary
- Canonical `m.replace` events are still persisted and federated normally.
- Client-facing timeline responses collapse superseded replace edits to one per edited target in the returned batch.
- This reduces reload/sync payload noise in edit-heavy conversations.

## Federation compatibility
- No change to federation payload semantics.
- No change to event immutability.
- No change to event persistence model.

## Enable edit purge
In `homeserver.yaml` (requires `mindroom_compact_edits_enabled: true`):

```yaml
experimental_features:
  mindroom_compact_edits_enabled: true
  mindroom_edit_purge:
    enabled: true
    min_age_seconds: 86400    # 24h grace period (default)
    interval_seconds: 3600    # purge cycle every hour (default)
    batch_size: 1000          # max events per cycle (default)
    dry_run: false            # set true to log without deleting
```

## Trigger manual purge (admin API)
```bash
curl -s -X POST \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"min_age_seconds": 3600, "batch_size": 500, "dry_run": true}' \
  http://<homeserver>/_synapse/admin/v1/purge_edits
```

Response: `{"purged": 42}`

If `experimental_features.mindroom_edit_purge.enabled` is `false`, this endpoint
returns `400` with `M_INVALID_PARAM`.

## Known scope limits
- Compacting applies to response timelines (`/sync`, Sliding Sync timelines, pagination, context).
- Edit purge permanently deletes superseded edits from storage — they cannot be recovered.
- Only edits matching the original event's sender and type are considered (same logic as `get_applicable_edits`).
