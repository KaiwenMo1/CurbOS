#!/usr/bin/env bash
set -euo pipefail
set +x

case "${1:-db}" in
  db|api) mode=${1:-db} ;;
  *) printf 'Usage: %s [db|api]\n' "$0" >&2; exit 2 ;;
esac

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
COMPOSE_PROJECT_NAME="curbos-db-test-$(openssl rand -hex 8)"
POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export COMPOSE_PROJECT_NAME POSTGRES_PASSWORD
export CURBOS_DB_PORT=0
export COMPOSE_DISABLE_ENV_FILE=1
unset COMPOSE_ENV_FILES
compose=(docker compose -f compose.yaml --project-name "$COMPOSE_PROJECT_NAME")

cleanup() {
  local result=$?
  trap - EXIT
  if (( result != 0 )); then
    "${compose[@]}" ps -a >&2 || true
    "${compose[@]}" logs --tail 50 db >&2 || true
  fi
  # This project is generated above and owns only the disposable test volume.
  if ! "${compose[@]}" down --volumes; then
    result=1
  fi
  exit "$result"
}

sql() {
  "${compose[@]}" exec -T db sh -ec '
    PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -w -h 127.0.0.1 \
      -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atqc "$1"
  ' sh "$1"
}

require_equal() {
  if [[ "$1" != "$2" ]]; then
    printf 'Expected %s, found %s\n' "$1" "$2" >&2
    exit 1
  fi
}

docker info --format '{{.ServerVersion}}' >/dev/null
trap cleanup EXIT
if config_error=$(POSTGRES_PASSWORD= "${compose[@]}" config --quiet 2>&1) ||
  [[ "$config_error" != *'Set POSTGRES_PASSWORD in the local .env file'* ]]; then
  printf 'Expected Compose to reject an empty database password.\n%s\n' "$config_error" >&2
  exit 1
fi
if startup_error=$("${compose[@]}" run --rm --no-deps -T -e POSTGRES_PASSWORD= \
  --entrypoint timeout db -k 5s 20s docker-entrypoint.sh postgres 2>&1) ||
  [[ "$startup_error" != *'superuser password is not specified'* ]]; then
  printf 'Expected a clean PostgreSQL startup to reject an empty password.\n%s\n' "$startup_error" >&2
  exit 1
fi
printf 'PASS missing password is rejected by Compose and by a clean PostgreSQL startup\n'

"${compose[@]}" up -d --wait --wait-timeout 90 db
require_equal 1 "$(sql 'SELECT 1;')"
if auth_error=$("${compose[@]}" exec -T -e PGPASSWORD=invalid db \
  psql -X -w -h 127.0.0.1 -U curbos -d curbos -Atqc 'SELECT 1;' 2>&1) ||
  [[ "$auth_error" != *'password authentication failed'* ]]; then
  printf 'Expected PostgreSQL to reject an incorrect password over TCP.\n%s\n' "$auth_error" >&2
  exit 1
fi
require_equal 1 "$(sql "SELECT count(*) FROM pg_available_extensions WHERE name = 'postgis';")"
require_equal 0 "$(sql "SELECT count(*) FROM pg_extension WHERE extname = 'postgis';")"
bash db/goose.sh validate
if [[ "$mode" == api ]]; then
  endpoint=$("${compose[@]}" port db 5432)
  require_equal 127.0.0.1 "${endpoint%:*}"
  container=$("${compose[@]}" ps -q db)
  (
    cd backend
    unset PGSERVICE PGSERVICEFILE PGOPTIONS
    export CURBOS_API_INTEGRATION=1 CURBOS_TEST_DB_CONTAINER="$container"
    export CURBOS_DATABASE_URL="postgres://curbos@$endpoint/curbos?sslmode=disable"
    export CURBOS_READY_TIMEOUT=1s CURBOS_SHUTDOWN_TIMEOUT=5s CURBOS_HTTP_ADDR=127.0.0.1:8080
    export PGPASSWORD="$POSTGRES_PASSWORD"
    go test -race -count=1 -v -run '^TestAPIIntegration$' ./cmd/api
  )
fi
PGSERVICE=curbos-missing-service PGSERVICEFILE=/dev/null PGOPTIONS='-c search_path=pg_catalog' bash db/goose.sh up
bash db/goose.sh status
require_equal public "$(sql "SELECT extnamespace::regnamespace FROM pg_extension WHERE extname = 'postgis';")"
require_equal 4326 "$(sql 'SELECT ST_SRID(ST_SetSRID(ST_MakePoint(0, 0), 4326));')"
require_equal 1 "$(sql 'SELECT count(*) FROM public.goose_db_version WHERE version_id = 1 AND is_applied;')"
history_sql="SELECT id, version_id, is_applied, tstamp FROM public.goose_db_version ORDER BY id;"
history=$(sql "$history_sql")
printf 'PASS authenticated startup and Goose migration on PostgreSQL %s with PostGIS %s\n' \
  "$(sql 'SHOW server_version;')" "$(sql 'SELECT postgis_lib_version();')"

bash db/goose.sh up
require_equal "$history" "$(sql "$history_sql")"
"${compose[@]}" restart db
"${compose[@]}" up -d --wait --wait-timeout 90 db
require_equal "$history" "$(sql "$history_sql")"
printf 'PASS repeated migration and ordinary restart preserve Goose history\n'

"${compose[@]}" down
if migration_error=$(bash db/goose.sh up 2>&1) ||
  [[ "$migration_error" != *'CurbOS database port unavailable'* ]]; then
  printf 'Expected Goose to fail because the database is stopped.\n%s\n' "$migration_error" >&2
  exit 1
fi
"${compose[@]}" up -d --wait --wait-timeout 90 db
require_equal "$history" "$(sql "$history_sql")"
require_equal 4326 "$(sql 'SELECT ST_SRID(ST_SetSRID(ST_MakePoint(0, 0), 4326));')"
bash db/goose.sh up
require_equal "$history" "$(sql "$history_sql")"
printf 'PASS stopped DB fails migration and recreated container preserves data\n'
