"""Offline API fixture for source-access UI tests; never contacts municipal sites."""

import datetime as dt
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

now = dt.datetime.now(dt.UTC).isoformat()
old = (dt.datetime.now(dt.UTC) - dt.timedelta(days=8)).isoformat()


def commune(bfs, name, documents, status, stale=False):
    return dict(
        bfs_id=bfs,
        name=name,
        canton="ZH",
        documents=documents,
        decisions=0,
        website="https://commune.example",
        holdings=[],
        access=[
            dict(
                status=status,
                checked_at=old if stale else now,
                restricted_at=old if stale else now if status == "restricted" else None,
                stale=stale,
                source_url="https://commune.example/docs/",
                robots_url="https://commune.example/robots.txt",
            )
        ],
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        communes = [
            commune(1, "Aeugst am Albis", 0, "restricted"),
            commune(121, "Wetzikon", 3, "restricted"),
            commune(2, "Affoltern am Albis", 0, "rate_limited"),
            commune(3, "Bonstetten", 0, "restricted", True),
        ]
        path = self.path.split("?")[0]
        if path == "/api/archive/communes":
            body = communes
        elif path.startswith("/api/archive/communes/"):
            body = next(c for c in communes if str(c["bfs_id"]) == path.rsplit("/", 1)[1])
        elif path.startswith("/api/dataset/"):
            self.send_response(404)
            self.end_headers()
            return
        else:
            body = dict(total=0, years=[], items=[])
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass


HTTPServer(("127.0.0.1", 8002), Handler).serve_forever()
