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

"""Admin API endpoint for triggering manual edit purge."""

from http import HTTPStatus
from typing import TYPE_CHECKING

from synapse.api.errors import Codes, SynapseError
from synapse.http.servlet import RestServlet, parse_json_object_from_request
from synapse.http.site import SynapseRequest
from synapse.rest.admin._base import admin_patterns, assert_requester_is_admin
from synapse.types import JsonDict

if TYPE_CHECKING:
    from synapse.server import HomeServer


class PurgeEditsRestServlet(RestServlet):
    """Trigger an on-demand purge of superseded edit events.

    POST /_synapse/admin/v1/purge_edits

    Request body (all fields optional):
        {
            "min_age_seconds": 86400,
            "batch_size": 1000,
            "dry_run": false
        }

    Response:
        {
            "purged": 42
        }
    """

    PATTERNS = admin_patterns("/purge_edits$")

    def __init__(self, hs: "HomeServer") -> None:
        self._auth = hs.get_auth()
        self._config = hs.config.experimental
        self._purge_edits_handler = hs.get_purge_edits_handler()

    async def on_POST(
        self, request: SynapseRequest
    ) -> tuple[int, JsonDict]:
        await assert_requester_is_admin(self._auth, request)

        if not self._config.mindroom_edit_purge_enabled:
            raise SynapseError(
                HTTPStatus.BAD_REQUEST,
                "mindroom_edit_purge is disabled",
                errcode=Codes.INVALID_PARAM,
            )

        body = parse_json_object_from_request(request, allow_empty_body=True)

        min_age_seconds: int | None = body.get("min_age_seconds")
        if min_age_seconds is not None:
            if type(min_age_seconds) is not int or min_age_seconds < 0:  # noqa: E721
                raise SynapseError(
                    HTTPStatus.BAD_REQUEST,
                    "min_age_seconds must be a non-negative integer",
                    errcode=Codes.BAD_JSON,
                )

        batch_size: int | None = body.get("batch_size")
        if batch_size is not None:
            if type(batch_size) is not int or batch_size < 1:  # noqa: E721
                raise SynapseError(
                    HTTPStatus.BAD_REQUEST,
                    "batch_size must be a positive integer",
                    errcode=Codes.BAD_JSON,
                )

        dry_run: bool | None = body.get("dry_run")
        if dry_run is not None and not isinstance(dry_run, bool):
            raise SynapseError(
                HTTPStatus.BAD_REQUEST,
                "dry_run must be a boolean",
                errcode=Codes.BAD_JSON,
            )

        purged = await self._purge_edits_handler.run_purge(
            min_age_seconds=min_age_seconds,
            batch_size=batch_size,
            dry_run=dry_run,
        )

        return HTTPStatus.OK, {"purged": purged}
