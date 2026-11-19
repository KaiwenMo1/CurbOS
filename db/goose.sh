#!/usr/bin/env bash
set -euo pipefail
set +x

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
compose=(docker compose -f compose.yaml)
goose=(
  go run -tags no_clickhouse,no_libsql,no_mssql,no_mysql,no_sqlite3,no_vertica,no_ydb
  github.com/pressly/goose/v3/cmd/goose@v3.30.1
  -env=none -dir db/migrations -table public.goose_db_version -timeout 30s
)

case "${1:-}" in
  validate)
    exec "${goose[@]}" validate
    ;;
  up|status|version)
    ;;
  *)
    printf 'Usage: bash db/goose.sh {validate|up|status|version}\n' >&2
    exit 2
    ;;
esac

docker_host=${DOCKER_HOST:-}
if [[ -n "${DOCKER_CONTEXT:-}" || -z "$docker_host" ]]; then
  docker_host=$(docker context inspect --format '{{.Endpoints.docker.Host}}')
fi
if [[ "$docker_host" != unix://* ]]; then
  printf 'CurbOS migrations require a local Docker engine using a Unix socket.\n' >&2
  exit 1
fi

if ! endpoint=$("${compose[@]}" port db 5432) || [[ ! "$endpoint" =~ ^127\.0\.0\.1:([0-9]+)$ ]]; then
  printf 'CurbOS database port unavailable. Start it with docker compose -f compose.yaml up -d --wait db.\n' >&2
  exit 1
fi

port="${BASH_REMATCH[1]}"
# Ignore workstation service presets and session options for this local target.
unset PGSERVICE PGSERVICEFILE PGOPTIONS
password=$("${compose[@]}" exec -T db printenv POSTGRES_PASSWORD)
if [[ -z "$password" ]]; then
  printf 'The CurbOS database container has no migration password.\n' >&2
  exit 1
fi
PGPASSWORD="$password" exec "${goose[@]}" postgres \
  "postgres://curbos@127.0.0.1:$port/curbos?sslmode=disable&connect_timeout=5&search_path=public" "$1"
