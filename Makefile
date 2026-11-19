.PHONY: bootstrap fmt fmt-check lint typecheck test build check db-migrate db-status db-test api-test

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
