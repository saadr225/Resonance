PYTHON ?= python
COMPOSE ?= docker compose --env-file .env -f infra/docker-compose.yml
SERVICES := media-server audio-chunker ai-pipeline insight-pusher session-api

.PHONY: proto up up-demo down logs lint test build

.PHONY: lint-docker test-docker

proto:
	$(PYTHON) -m grpc_tools.protoc -I proto --python_out=proto --grpc_python_out=proto proto/resonance.proto

up:
	$(COMPOSE) up --build

up-demo:
	$(COMPOSE) --profile demo up --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

lint:
	ruff check services tests

test:
	pytest -v

lint-docker:
	$(COMPOSE) --profile tooling run --rm lint-runner

test-docker:
	$(COMPOSE) --profile tooling run --rm test-runner

build:
	$(COMPOSE) build
