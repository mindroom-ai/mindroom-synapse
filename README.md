# MindRoom Synapse
> This is the MindRoom fork of Element Synapse. It exists to support MindRoom Matrix workloads, including high-frequency edit streaming, while keeping compatibility with the Matrix ecosystem.

This repository tracks upstream Synapse and carries a small set of fork-specific changes.

## Fork-specific additions
- Compact edit timeline mode to collapse superseded `m.replace` events in client-facing timelines.
- Optional storage purge for superseded edits (`experimental_features.mindroom_edit_purge`), including a background job and admin trigger API (`POST /_synapse/admin/v1/purge_edits`).
- `/versions` unstable feature advertisement for `org.mindroom.compact_edits`.
- Fork CI and Docker publishing workflows for `ghcr.io/mindroom-ai/mindroom-synapse`.
- Nix shell entrypoint (`shell.nix`) for local development on NixOS.

## Docker images (fork)
Images are published from this fork to:
- `ghcr.io/mindroom-ai/mindroom-synapse:develop` (develop branch)
- `ghcr.io/mindroom-ai/mindroom-synapse:<branch>`
- `ghcr.io/mindroom-ai/mindroom-synapse:commit-<sha>`

## Upstream documentation
Upstream Synapse docs and installation guidance remain valid for this fork:
- [README.rst](./README.rst)
- https://element-hq.github.io/synapse/latest/

## Fork change log
See [FORK_CHANGES.md](./FORK_CHANGES.md) for a commit-by-commit changelog and operational runbook for fork-specific behavior.
