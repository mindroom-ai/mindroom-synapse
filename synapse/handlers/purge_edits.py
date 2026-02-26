#
# This file is licensed under the Affero General Public License (AGPL) version 3.
#
# Copyright (C) 2025 MindRoom
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# See the GNU Affero General Public License for more details:
# <https://www.gnu.org/licenses/agpl-3.0.html>.
#

"""Handler for purging superseded m.replace (edit) events from storage."""

import logging
from typing import TYPE_CHECKING

from synapse.util.duration import Duration

if TYPE_CHECKING:
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)


class PurgeEditsHandler:
    """Periodically deletes superseded m.replace events from the database.

    This is the storage-level complement to the sync-time compaction provided
    by ``mindroom_compact_edits_enabled``.  While compaction hides intermediate
    edits from API responses, this handler actually removes them from storage
    to reclaim disk space.
    """

    def __init__(self, hs: "HomeServer") -> None:
        self._store = hs.get_datastores().main
        self._clock = hs.get_clock()
        self._config = hs.config.experimental
        self._is_master = hs.config.worker.worker_app is None

        if self._config.mindroom_edit_purge_enabled and self._is_master:
            interval_ms = self._config.mindroom_edit_purge_interval_seconds * 1000
            logger.info(
                "Scheduling edit purge background job every %d seconds "
                "(min_age=%ds, batch_size=%d, dry_run=%s)",
                self._config.mindroom_edit_purge_interval_seconds,
                self._config.mindroom_edit_purge_min_age_seconds,
                self._config.mindroom_edit_purge_batch_size,
                self._config.mindroom_edit_purge_dry_run,
            )
            self._clock.looping_call(
                hs.run_as_background_process,
                Duration(milliseconds=interval_ms),
                "mindroom_purge_superseded_edits",
                self._purge_superseded_edits,
            )

    async def _purge_superseded_edits(
        self,
        min_age_seconds: int | None = None,
        batch_size: int | None = None,
        dry_run: bool | None = None,
    ) -> int:
        """Run a single purge cycle.

        Args:
            min_age_seconds: Override for the configured min age.
            batch_size: Override for the configured batch size.
            dry_run: Override for the configured dry-run flag.

        Returns:
            The number of events purged (or that would have been purged in
            dry-run mode).
        """
        if min_age_seconds is None:
            min_age_seconds = self._config.mindroom_edit_purge_min_age_seconds
        if batch_size is None:
            batch_size = self._config.mindroom_edit_purge_batch_size
        if dry_run is None:
            dry_run = self._config.mindroom_edit_purge_dry_run

        min_age_ms = min_age_seconds * 1000
        now_ms = self._clock.time_msec()

        superseded = await self._store.get_superseded_edit_event_ids(
            min_age_ms=min_age_ms,
            batch_size=batch_size,
            now_ms=now_ms,
        )

        if not superseded:
            logger.debug("Edit purge: no superseded edits found")
            return 0

        event_ids = [eid for eid, _, _ in superseded]
        target_ids = {tid for _, tid, _ in superseded}
        event_id_to_room_id = {eid: rid for eid, _, rid in superseded}

        if dry_run:
            logger.info(
                "Edit purge (dry run): would purge %d superseded edits "
                "for %d target events",
                len(event_ids),
                len(target_ids),
            )
            return len(event_ids)

        await self._store.delete_events_by_ids(
            event_ids,
            event_id_to_room_id=event_id_to_room_id,
        )

        logger.info(
            "Edit purge: purged %d superseded edits for %d target events",
            len(event_ids),
            len(target_ids),
        )

        return len(event_ids)

    async def run_purge(
        self,
        min_age_seconds: int | None = None,
        batch_size: int | None = None,
        dry_run: bool | None = None,
    ) -> int:
        """Public entry point for the admin API to trigger a manual purge.

        Args:
            min_age_seconds: Override for the configured min age.
            batch_size: Override for the configured batch size.
            dry_run: Override for the configured dry-run flag.

        Returns:
            The number of events purged.
        """
        return await self._purge_superseded_edits(
            min_age_seconds=min_age_seconds,
            batch_size=batch_size,
            dry_run=dry_run,
        )
