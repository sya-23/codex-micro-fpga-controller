from __future__ import annotations

import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .core import Controller, Mode
from .slots import SessionIdentity, SlotStatus

SLOT_PATH = re.compile(r"^/v1/slots/([0-3])(?:/(bind|activate|status))?$")


class ControllerHTTPServer(ThreadingHTTPServer):
    def __init__(self, address, controller: Controller):
        self.controller = controller
        super().__init__(address, ControllerRequestHandler)


class ControllerRequestHandler(BaseHTTPRequestHandler):
    server: ControllerHTTPServer

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/health":
            self._json({"ok": True})
        elif path == "/v1/slots":
            self._json(self.server.controller.snapshot())
        else:
            self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/v1/sync":
                self.server.controller.sync()
                self._json(self.server.controller.snapshot())
                return
            if path == "/v1/mode":
                body = self._body()
                self.server.controller.set_mode(Mode(int(body["mode"])))
                self._json(self.server.controller.snapshot())
                return
            match = SLOT_PATH.match(path)
            if not match:
                self._error(HTTPStatus.NOT_FOUND, "not found")
                return
            index = int(match.group(1))
            action = match.group(2)
            if action == "bind":
                body = self._body()
                if "session_id" in body:
                    result = self.server.controller.bind_identity(
                        index,
                        SessionIdentity(
                            session_id=str(body["session_id"]),
                            deeplink=str(body.get("deeplink", "")),
                            title=str(body.get("title", "")),
                        ),
                    )
                else:
                    result = self.server.controller.bind_current(index)
            elif action == "activate":
                result = self.server.controller.activate_slot(index)
            elif action == "status":
                body = self._body()
                result = self.server.controller.set_status(index, SlotStatus(int(body["status"])))
            else:
                self._error(HTTPStatus.BAD_REQUEST, "missing action")
                return
            self._json(result)
        except (ValueError, IndexError, KeyError, RuntimeError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        match = SLOT_PATH.match(path)
        if not match or match.group(2):
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        try:
            self._json(self.server.controller.clear_slot(int(match.group(1))))
        except (ValueError, IndexError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))

    def log_message(self, format: str, *args) -> None:
        return

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _json(self, data, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json({"error": message}, status)
