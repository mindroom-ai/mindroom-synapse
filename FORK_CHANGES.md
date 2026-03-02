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

## Known scope limits
- Compacting applies to response timelines (`/sync`, Sliding Sync timelines, pagination, context).
- It does not rewrite historical storage.
