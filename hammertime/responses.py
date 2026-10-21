"""Response classes that match Express's default headers exactly."""

from __future__ import annotations

import os

from fastapi.responses import JSONResponse as _StarletteJSONResponse
from fastapi.staticfiles import StaticFiles as _StarletteStaticFiles


class JSONResponse(_StarletteJSONResponse):
    """``application/json; charset=utf-8`` — what ``res.json()`` sends in Express.

    Starlette only appends a charset for ``text/*`` media types, so the charset has to
    be part of the media type here to stay byte-identical with the Node server.
    """

    media_type = "application/json; charset=utf-8"


class StaticFiles(_StarletteStaticFiles):
    """Serve files with the same content types ``express.static`` produces.

    Express appends ``; charset=utf-8`` to JSON files, labels ``.ico`` files
    ``image/vnd.microsoft.icon`` (Python's ``mimetypes`` says ``image/x-icon``) and
    labels scripts ``application/javascript`` (Python may say ``text/javascript``).
    """

    #: Extension -> exact content type the Node server sends.
    CONTENT_TYPES = {
        ".ico": "image/vnd.microsoft.icon",
        ".js": "application/javascript; charset=utf-8",
    }

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        content_type = response.headers.get("content-type", "")

        override = self.CONTENT_TYPES.get(os.path.splitext(path)[1].lower())
        if override:
            response.headers["content-type"] = override
        elif content_type == "application/json":
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response
