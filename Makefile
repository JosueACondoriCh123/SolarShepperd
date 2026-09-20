.PHONY: up down test lint migrate seed

up:
	docker compose up --build

down:
	docker compose down

test:
	docker compose run --rm api pytest

lint:
	docker compose run --rm api ruff check app tests
	docker compose run --rm frontend pnpm lint

migrate:
	docker compose run --rm migrate

seed:
	docker compose exec api python -m app.cli bootstrap
