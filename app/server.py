#!/usr/bin/env python3
"""Tiny deterministic HTTP target for the isolated routing lab."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from datetime import datetime, timezone


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/health"):
            self.send_error(404)
            return
        body = json.dumps(
            {
                "service": "routing-path-lab",
                "status": "ok",
                "hostname": socket.gethostname(),
                "utc": datetime.now(timezone.utc).isoformat(),
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(json.dumps({"client": self.client_address[0], "request": fmt % args}))


ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
