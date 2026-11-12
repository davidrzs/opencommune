# Web server deployment

One Rust binary serves the website, the JSON API and MCP from a read-only SQLite database; Caddy
in front terminates HTTPS. Nothing else runs on the server: no Python, no Node.

Layout:

1. `/opt/opencommune/opencommune-server`: the release binary (`make server`).
2. `/opt/opencommune/site/`: the static front end (`make frontend`, the contents of `frontend/build`).
3. `/opt/opencommune/data/opencommune.db`: the database after processing and
   `opencommune build` (out of WAL mode, so the read-only server needs no `-shm` file).
4. `/opt/opencommune/data/dataset.sqlite`: optional, the votes and finance dataset.
5. `/var/lib/opencommune/usage.sqlite3`: usage statistics, written by the server.

Install:

```sh
cp opencommune.service /etc/systemd/system/
cp Caddyfile /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now opencommune
systemctl reload caddy
```

To update, replace the binary, the site or the database and run `systemctl restart opencommune`.
Logs: `journalctl -u opencommune`. Settings: `server/API.md`.
