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

"""Storage methods for purging superseded m.replace (edit) events."""

import logging
from collections import defaultdict
from typing import List, Tuple

from synapse.storage.database import (
    LoggingTransaction,
    make_in_list_sql_clause,
)
from synapse.storage.databases.main.cache import CacheInvalidationWorkerStore
logger = logging.getLogger(__name__)


class PurgeEditsStore(CacheInvalidationWorkerStore):
    """Store methods for finding and deleting superseded edit events."""

    async def get_superseded_edit_event_ids(
        self,
        min_age_ms: int,
        batch_size: int,
        now_ms: int,
    ) -> List[Tuple[str, str, str]]:
        """Find superseded m.replace events older than the given age threshold.

        For each target event that has more than one m.replace relation from the
        same sender with the same event type, all but the latest applicable edit
        are considered superseded.

        Args:
            min_age_ms: Minimum age in milliseconds. Events with
                origin_server_ts < (now_ms - min_age_ms) are candidates.
            batch_size: Maximum number of event IDs to return.
            now_ms: Current server time in milliseconds.

        Returns:
            A list of (event_id, target_event_id, room_id) tuples for
            superseded edits.
        """
        cutoff_ts = now_ms - min_age_ms

        sql = """
            SELECT
                er.event_id,
                er.relates_to_id AS target_id,
                edit.room_id
            FROM event_relations er
            INNER JOIN events AS edit ON edit.event_id = er.event_id
            INNER JOIN events AS original ON
                original.event_id = er.relates_to_id
                AND edit.type = original.type
                AND edit.sender = original.sender
                AND edit.room_id = original.room_id
            WHERE er.relation_type = 'm.replace'
              AND edit.origin_server_ts < ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM receipts_linearized AS rl
                  WHERE rl.room_id = edit.room_id
                    AND rl.event_id = er.event_id
              )
              AND EXISTS (
                  SELECT 1
                  FROM event_relations er2
                  INNER JOIN events AS newer ON newer.event_id = er2.event_id
                  WHERE er2.relation_type = 'm.replace'
                    AND er2.relates_to_id = er.relates_to_id
                    AND newer.type = original.type
                    AND newer.sender = original.sender
                    AND newer.room_id = original.room_id
                    AND (
                        newer.origin_server_ts > edit.origin_server_ts
                        OR (
                            newer.origin_server_ts = edit.origin_server_ts
                            AND newer.event_id > edit.event_id
                        )
                    )
              )
            ORDER BY edit.stream_ordering ASC, edit.event_id ASC
            LIMIT ?
        """

        def _get_superseded_txn(
            txn: LoggingTransaction,
        ) -> List[Tuple[str, str, str]]:
            txn.execute(sql, (cutoff_ts, batch_size))
            return [(row[0], row[1], row[2]) for row in txn]

        return await self.db_pool.runInteraction(
            "get_superseded_edit_event_ids",
            _get_superseded_txn,
        )

    async def delete_events_by_ids(
        self,
        event_ids: List[str],
        event_id_to_room_id: dict[str, str] | None = None,
    ) -> None:
        """Hard-delete the given events from storage tables.

        Removes rows from event_json, events, event_relations, and related
        tables.  This is a destructive operation — the events cannot be
        recovered.

        Args:
            event_ids: The event IDs to purge.
            event_id_to_room_id: Optional mapping of event_id to room_id,
                used to avoid an extra lookup before cache invalidation.
        """
        if not event_ids:
            return

        # Tables to delete from, ordered to respect foreign key constraints.
        # We delete from the most dependent tables first.
        tables_with_event_id = [
            "event_json",
            "event_edges",
            "event_push_actions_staging",
            "event_relations",
            "event_to_state_groups",
            "event_auth_chains",
            "event_auth_chain_to_calculate",
            "event_auth",
            "redactions",
            "rejections",
            "state_events",
            "partial_state_events",
            "event_forward_extremities",
            "event_search",
            "events",
        ]

        def _delete_events_txn(txn: LoggingTransaction) -> None:
            # Resolve the event->room mapping in-transaction so cache invalidation
            # remains correct even if callers do not provide it.
            if event_id_to_room_id is None:
                event_id_to_room_map: dict[str, str] = {}
            else:
                event_id_to_room_map = dict(event_id_to_room_id)

            missing_event_ids = [
                event_id
                for event_id in event_ids
                if event_id not in event_id_to_room_map
            ]
            if missing_event_ids:
                clause, args = make_in_list_sql_clause(
                    txn.database_engine, "event_id", missing_event_ids
                )
                txn.execute(
                    f"SELECT event_id, room_id FROM events WHERE {clause}",
                    args,
                )
                event_id_to_room_map.update(
                    {event_id: room_id for event_id, room_id in txn}
                )

            for table in tables_with_event_id:
                clause, args = make_in_list_sql_clause(
                    txn.database_engine, "event_id", event_ids
                )
                txn.execute(f"DELETE FROM {table} WHERE {clause}", args)

            # event_push_actions has its useful index on (room_id, event_id),
            # so delete with both columns instead of event_id alone.
            event_ids_by_room_id: dict[str, list[str]] = defaultdict(list)
            for event_id in event_ids:
                room_id = event_id_to_room_map.get(event_id)
                if room_id is not None:
                    event_ids_by_room_id[room_id].append(event_id)

            for room_id, room_event_ids in event_ids_by_room_id.items():
                clause, args = make_in_list_sql_clause(
                    txn.database_engine, "event_id", room_event_ids
                )
                txn.execute(
                    f"DELETE FROM event_push_actions WHERE room_id = ? AND {clause}",
                    [room_id] + list(args),
                )

            # Invalidate caches so Synapse stops serving deleted events.
            # invalidate_get_event_cache_after_txn is provided by
            # EventsWorkerStore which is a sibling in the DataStore MRO.
            for event_id in event_ids:
                self.invalidate_get_event_cache_after_txn(txn, event_id)  # type: ignore[attr-defined]

            self._invalidate_cache_and_stream_bulk(
                txn,
                self.have_seen_event,  # type: ignore[attr-defined]
                [
                    (event_id_to_room_map[event_id], event_id)
                    for event_id in event_ids
                    if event_id in event_id_to_room_map
                ],
            )

            # Replicate room event cache invalidation so all workers drop stale
            # per-room event/relation/edit caches after hard-deleting edits.
            for room_id in {room_id for room_id in event_id_to_room_map.values()}:
                self._invalidate_caches_for_room_events_and_stream(txn, room_id)

        await self.db_pool.runInteraction(
            "delete_events_by_ids",
            _delete_events_txn,
        )
