# Web server deployment

One Rust binary serves the website, the JSON API and MCP from a read-only SQLite database; Caddy
in front terminates HTTPS. Nothing else runs on the server: no Python, no Node.

Layout:

1. `/opt/opencommune/opencommune-server`: the release binary (`make server`).
2. `/opt/opencommune/site/`: the static front end (`make frontend`, the contents of `frontend/build`).
3. `/opt/opencommune/data/opencommune.db`: a copy of the serving database that `opencommune build`
   writes to `DATA_DIR/serving.db` (out of WAL mode, so the read-only server needs no `-shm` file).
4. `/var/lib/opencommune/usage.sqlite3`: usage statistics, written by the server.

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

Search engines: with `SEARCH_INDEXING=true` the pages may be indexed and `robots.txt` lists the
sitemap; with `false` every response says `noindex`. The commune pages stay `noindex` and out of
the sitemap until `SEARCH_INDEX_COMMUNES=true`. After a change: `systemctl daemon-reload` and a
restart.

MCP registry: `server.json` at the repository root describes the public MCP server for the official
registry (registry.modelcontextprotocol.io), from which many clients and directories read. Publish
or update it with the registry's `mcp-publisher` tool: `mcp-publisher login github`, then
`mcp-publisher publish` from the repository root.
