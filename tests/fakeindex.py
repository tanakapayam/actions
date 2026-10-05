"""A package index on localhost, for testing what happens *after* an upload.

It serves the distributions in a directory the way PyPI does -- the JSON API
(``/pypi/<project>/<version>/json``), the simple index (``/simple/<project>/``), the files
(``/files/<name>``) and provenance (``/integrity/<project>/<version>/<name>/provenance``) --
and it can misbehave on purpose: not list the release yet, list a wrong hash, serve other
bytes than it lists, or lack provenance. ``pip`` talks to it like to any index.

As a script it serves a directory until interrupted (the ``dogfood`` job runs the real
``python/verify-published`` action against it):

    python tests/fakeindex.py DIST_DIR --port 8765
"""

import argparse
import contextlib
import hashlib
import json
import sys
import threading
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import pyrelease


class FakeIndex:
    """Serve ``dist``'s files. Use as a context manager; ``.url`` is the index root."""

    def __init__(
        self,
        dist: Path,
        *,
        port: int = 0,
        lag: int = 0,
        wrong_listed_hash: Iterable[str] = (),
        tampered_bytes: Iterable[str] = (),
        unlisted: Iterable[str] = (),
        provenance: str = "ok",
    ) -> None:
        self.dists = pyrelease.find_dists(dist)
        self.files = {path.name: path.read_bytes() for path in self.dists.files}
        self.lag = lag  # how many times the release's JSON answers 404 before it is listed
        self.wrong_listed_hash = set(wrong_listed_hash)
        self.tampered_bytes = set(tampered_bytes)
        self.unlisted = set(unlisted)
        self.provenance = provenance  # "ok", "missing" or "empty"
        self.requests: list[str] = []
        self._json_requests = 0
        self._server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self) -> "FakeIndex":
        self._thread.start()
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def listed_digest(self, name: str) -> str:
        if name in self.wrong_listed_hash:
            return "0" * 64
        return hashlib.sha256(self.files[name]).hexdigest()

    def served(self, name: str) -> bytes:
        data = self.files[name]
        return data + b"\0" if name in self.tampered_bytes else data

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        index = self
        project, version = self.dists.project, self.dists.version

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                index.requests.append(self.path)

            def reply(self, status: int, body: bytes = b"", kind: str = "application/json") -> None:
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                path = self.path.split("#")[0]
                prefix = f"/pypi/{project}/{version}/json"
                names = [name for name in index.files if name not in index.unlisted]
                if path == prefix:
                    index._json_requests += 1
                    if index._json_requests <= index.lag:
                        return self.reply(404)
                    urls = [
                        {
                            "filename": name,
                            "digests": {"sha256": index.listed_digest(name)},
                            "url": f"{index.url}/files/{name}",
                        }
                        for name in names
                    ]
                    return self.reply(200, json.dumps({"urls": urls}).encode())
                if path in (f"/simple/{project}/", f"/simple/{project}"):
                    links = "".join(
                        f'<a href="{index.url}/files/{name}#sha256={index.listed_digest(name)}">'
                        f"{name}</a><br>"
                        for name in names
                    )
                    return self.reply(
                        200, f"<html><body>{links}</body></html>".encode(), "text/html"
                    )
                if path.startswith("/files/") and path[7:] in index.files:
                    return self.reply(200, index.served(path[7:]), "application/octet-stream")
                if path.startswith(f"/integrity/{project}/{version}/") and path.endswith(
                    "/provenance"
                ):
                    if index.provenance == "missing":
                        return self.reply(404)
                    bundles = [{"attestations": []}] if index.provenance == "ok" else []
                    return self.reply(200, json.dumps({"attestation_bundles": bundles}).encode())
                return self.reply(404)

        return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dist", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    index = FakeIndex(args.dist, port=args.port)
    print(f"serving {index.dists.project} {index.dists.version} at {index.url}", flush=True)
    with contextlib.suppress(KeyboardInterrupt):
        index.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
