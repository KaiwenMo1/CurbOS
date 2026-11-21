#!/usr/bin/env bash
set -euo pipefail
set +x

case "${1:-db}" in
  db|api|e2e|cds) mode=${1:-db} ;;
  *) printf 'Usage: %s [db|api|e2e|cds]\n' "$0" >&2; exit 2 ;;
esac

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
COMPOSE_PROJECT_NAME="curbos-db-test-$(openssl rand -hex 8)"
POSTGRES_PASSWORD="$(openssl rand -hex 24)"
export COMPOSE_PROJECT_NAME POSTGRES_PASSWORD
export CURBOS_DB_PORT=0
export COMPOSE_DISABLE_ENV_FILE=1
unset COMPOSE_ENV_FILES
compose=(docker compose -f compose.yaml --project-name "$COMPOSE_PROJECT_NAME")
e2e_container=
e2e_pid=
cds_socket_root=

cleanup() {
  local result=$?
  trap - EXIT
  trap '' INT TERM
  if [[ -n "$e2e_pid" ]]; then
    kill -TERM "$e2e_pid" 2>/dev/null || true
    wait "$e2e_pid" || true
  fi
  if [[ -n "$e2e_container" ]] &&
    [[ "$(docker inspect --format '{{.State.Paused}}' "$e2e_container" 2>/dev/null)" == true ]]; then
    docker unpause "$e2e_container" >/dev/null || result=1
  fi
  if (( result != 0 )); then
    "${compose[@]}" ps -a >&2 || true
    "${compose[@]}" logs --tail 50 db >&2 || true
  fi
  # This project is generated above and owns only the disposable test volume.
  if ! "${compose[@]}" down --volumes; then
    result=1
  fi
  if [[ -n "$cds_socket_root" ]] && ! rm -rf -- "$cds_socket_root"; then
    result=1
  fi
  exit "$result"
}

sql() {
  "${compose[@]}" exec -T db sh -ec '
    PGPASSWORD="$POSTGRES_PASSWORD" exec psql -X -w -h 127.0.0.1 \
      -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -Atq "$@"
  ' sh "$@"
}

require_equal() {
  if [[ "$1" != "$2" ]]; then
    printf 'Expected %s, found %s\n' "$1" "$2" >&2
    exit 1
  fi
}

docker info --format '{{.ServerVersion}}' >/dev/null
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ "$mode" == cds ]]; then
  # The namespace test shares only the disposable database's Unix socket.
  cds_socket_root=$(mktemp -d /tmp/curbos-cds-socket.XXXXXXXX)
  mkdir "$cds_socket_root/socket"
  cat > "$cds_socket_root/compose.yaml" <<EOF
services:
  db:
    volumes:
      - "$cds_socket_root/socket:/var/run/postgresql"
EOF
  compose+=(-f "$cds_socket_root/compose.yaml")
fi
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
if [[ "$mode" == cds ]]; then
  bash db/goose.sh up
  endpoint=$("${compose[@]}" port db 5432)
  require_equal 127.0.0.1 "${endpoint%:*}"
  CURBOS_TEST_DB_CONTAINER=$("${compose[@]}" ps -q db)
  export CURBOS_TEST_DB_CONTAINER
  export CURBOS_TEST_DB_SOCKET="$cds_socket_root/socket"
  export CURBOS_CAPTURE_DB_PORT="${endpoint##*:}" PGPASSWORD="$POSTGRES_PASSWORD"
  export PGUSER=curbos PGDATABASE=curbos PYTHONDONTWRITEBYTECODE=1
  unset PGSERVICE PGSERVICEFILE PGOPTIONS PGHOSTADDR
  "${CURBOS_TEST_PYTHON:-python3}" -m unittest discover -s tests/cds -v
  exit 0
fi
require_equal 1 "$(sql -c 'SELECT 1;')"
if auth_error=$("${compose[@]}" exec -T -e PGPASSWORD=invalid db \
  psql -X -w -h 127.0.0.1 -U curbos -d curbos -Atqc 'SELECT 1;' 2>&1) ||
  [[ "$auth_error" != *'password authentication failed'* ]]; then
  printf 'Expected PostgreSQL to reject an incorrect password over TCP.\n%s\n' "$auth_error" >&2
  exit 1
fi
require_equal 1 "$(sql -c "SELECT count(*) FROM pg_available_extensions WHERE name = 'postgis';")"
require_equal 0 "$(sql -c "SELECT count(*) FROM pg_extension WHERE extname = 'postgis';")"
bash db/goose.sh validate
if [[ "$mode" != db ]]; then
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
postgis_sql='SELECT public.ST_SRID(public.ST_SetSRID(public.ST_MakePoint(0, 0), 4326));'
baseline_sql='SELECT id, is_applied, tstamp FROM public.goose_db_version WHERE version_id = 1 ORDER BY id DESC LIMIT 1;'
evidence_applied_sql='SELECT COALESCE((SELECT is_applied::int FROM public.goose_db_version WHERE version_id = 2 ORDER BY id DESC LIMIT 1), 0);'
require_equal public "$(sql -c "SELECT extnamespace::regnamespace FROM pg_extension WHERE extname = 'postgis';")"
require_equal 4326 "$(sql -c "$postgis_sql")"
require_equal 1 "$(sql -c 'SELECT count(*) FROM public.goose_db_version WHERE version_id = 1 AND is_applied;')"
require_equal 1 "$(sql -c "$evidence_applied_sql")"
baseline_history=$(sql -c "$baseline_sql")
history_sql="SELECT id, version_id, is_applied, tstamp FROM public.goose_db_version ORDER BY id;"
history=$(sql -c "$history_sql")
printf 'PASS authenticated startup and Goose migration on PostgreSQL %s with PostGIS %s\n' \
  "$(sql -c 'SHOW server_version;')" "$(sql -c 'SELECT public.postgis_lib_version();')"

bash db/goose.sh up
require_equal "$history" "$(sql -c "$history_sql")"
# Test the original PR-01 contract on its own version. PR-04 deliberately
# makes provenance and release transitions stricter.
bash db/goose.sh test-down-to-2
sql -f - < tests/db/evidence_constraints.sql
require_equal 0 "$(sql -c 'SELECT count(*) FROM sources.publication_scope;')"
printf 'PASS clean evidence schema, release and scope constraints, provenance, geometry and synthetic fixture rollback\n'

if rollback_error=$(COMPOSE_PROJECT_NAME=curbos-dev bash db/goose.sh test-down-to-1 2>&1) ||
  [[ "$rollback_error" != *'Rollback requires the disposable CurbOS database test project'* ]]; then
  printf 'Expected rollback to reject the development project.\n%s\n' "$rollback_error" >&2
  exit 1
fi
printf 'PASS rollback rejects the development project\n'
bash db/goose.sh test-down-to-1
require_equal 0 "$(sql -c "$evidence_applied_sql")"
require_equal 0 "$(sql -c "SELECT count(*) FROM pg_catalog.pg_namespace WHERE nspname IN ('sources', 'geo', 'rules');")"
require_equal "$baseline_history" "$(sql -c "$baseline_sql")"
require_equal 4326 "$(sql -c "$postgis_sql")"
bash db/goose.sh up
require_equal 1 "$(sql -c "$evidence_applied_sql")"
require_equal 1 "$(sql -c "SELECT count(*) FROM pg_catalog.pg_namespace WHERE nspname = 'publication';")"
require_equal publication.release_verification "$(sql -c "SELECT to_regclass('publication.release_verification');")"
require_equal 0 "$(sql -c 'SELECT count(*) FROM sources.publication_scope;')"
history=$(sql -c "$history_sql")
bash db/goose.sh up
require_equal "$history" "$(sql -c "$history_sql")"
printf 'PASS evidence migration Down and reapply preserve M1 PostGIS and Goose baseline\n'

"${compose[@]}" restart db
"${compose[@]}" up -d --wait --wait-timeout 90 db
require_equal "$history" "$(sql -c "$history_sql")"
printf 'PASS repeated migration and ordinary restart preserve Goose history\n'

"${compose[@]}" down
if migration_error=$(bash db/goose.sh up 2>&1) ||
  [[ "$migration_error" != *'CurbOS database port unavailable'* ]]; then
  printf 'Expected Goose to fail because the database is stopped.\n%s\n' "$migration_error" >&2
  exit 1
fi
"${compose[@]}" up -d --wait --wait-timeout 90 db
require_equal "$history" "$(sql -c "$history_sql")"
require_equal 4326 "$(sql -c "$postgis_sql")"
bash db/goose.sh up
require_equal "$history" "$(sql -c "$history_sql")"
printf 'PASS stopped DB fails migration and recreated container preserves data\n'

if [[ "$mode" == e2e ]]; then
  # The persistence check recreated the container. Resolve the current identity and port.
  export CURBOS_TEST_DB_ENDPOINT CURBOS_TEST_DB_CONTAINER
  CURBOS_TEST_DB_ENDPOINT=$("${compose[@]}" port db 5432)
  e2e_container=$("${compose[@]}" ps -q db)
  CURBOS_TEST_DB_CONTAINER=$e2e_container
  unset PGSERVICE PGSERVICEFILE PGOPTIONS
  # Bash runs signal traps immediately while waiting on an asynchronous child.
  node apps/web/tests/readiness.e2e.mjs &
  e2e_pid=$!
  result=0
  wait "$e2e_pid" || result=$?
  e2e_pid=
  exit "$result"
fi
