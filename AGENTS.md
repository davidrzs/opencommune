# OpenCommune: notes for contributors and coding agents

`README.md` describes the project and how to run it. This file holds the rules for changing it.

## Layout

1. `server/`: the Rust web server (JSON API, MCP, static front end). It reads the database only.
2. `frontend/`: the SvelteKit site, built to static files.
3. `deploy/server/`: the systemd unit and Caddy configuration for the public server.

The crawler and the processing stages (Python) are being moved in.

## Privacy

1. Records never name private individuals.
2. Lists never carry a commune's document URL or an unreviewed title.
3. Test fixtures are real data; check new ones for personal data before adding them.

## Engineering

1. The smallest design that does the job: no framework, layer or option without a present use.
2. Rust: logging through `tracing`.
3. Every change keeps `cargo fmt --check`, `cargo clippy` and `cargo test` green for the server, and
   `npm run check` and `npm run format:check` for the front end. Behaviour changes get a test.
4. Tests never touch the network.
