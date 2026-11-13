.PHONY: setup fetch catalog build test lint server frontend

setup:
	uv sync
	uv run opencommune init-db

fetch:
	uv run opencommune fetch

catalog:
	uv run opencommune catalog

build:
	uv run opencommune build

test:
	uv run pytest -q

lint:
	uv run pre-commit run --all-files

server:
	cd server && cargo build --release

frontend:
	cd frontend && npm ci && npm run build
