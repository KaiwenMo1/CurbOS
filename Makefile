PYTHON ?= python3
RUFF ?= ruff

.PHONY: bootstrap fmt fmt-check lint typecheck test build check db-migrate db-status db-test api-test e2e-test cds-unit cds-lint cds-test

bootstrap:
	npm --prefix apps/web ci

fmt:
	cd backend && gofmt -w .

fmt-check:
	@files="$$(gofmt -l backend)" || exit $$?; \
	if [ -n "$$files" ]; then \
		echo "Go files require formatting:"; \
		echo "$$files"; \
		exit 1; \
	fi

lint:
	cd backend && go vet ./...
	npm --prefix apps/web run lint

typecheck:
	npm --prefix apps/web run typecheck

test:
	cd backend && go test -race ./...
	npm --prefix apps/web run test -- --run

build:
	mkdir -p backend/bin
	cd backend && go build -trimpath -o bin/curbos-api ./cmd/api
	npm --prefix apps/web run build

check: fmt-check lint typecheck test build

db-migrate:
	bash db/goose.sh up

db-status:
	bash db/goose.sh status

db-test:
	bash tests/db/smoke.sh

api-test:
	bash tests/db/smoke.sh api

e2e-test:
	bash tests/db/smoke.sh e2e

cds-unit:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests/cds -p 'test_*unit.py' -v

cds-lint:
	$(RUFF) check data/cds_capture data/cds_validate data/cds_publish data/cds_readiness tests/cds
	$(RUFF) format --check data/cds_capture data/cds_validate data/cds_publish data/cds_readiness tests/cds

cds-test:
	CURBOS_TEST_PYTHON="$(PYTHON)" bash tests/db/smoke.sh cds
