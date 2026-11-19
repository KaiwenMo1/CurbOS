# CurbOS

CurbOS is an evidence-aware, street-parking-first application under active development. The current foundation contains no parking inventory, legal recommendations, occupancy claims, map tiles, or user location collection.

## Current capability

- A Go HTTP API with liveness and PostgreSQL readiness endpoints.
- A React/TypeScript/Vite web shell with an explicit **No verified parking data available** state.
- A local PostgreSQL/PostGIS service with a Goose migration baseline.
- Reproducible formatting, linting, testing, type-checking, build, and CI commands.

MapLibre is planned for PR-04.

## Prerequisites

- Git 2.43 or newer
- Go 1.27.4
- Node.js 24.22.3
- npm 11.19.1 (bundled with the pinned Node release)
- GNU Make
- A C compiler on `PATH` (such as GCC or Clang) and CGO enabled for `go test -race`, which runs in `make test` and `make check`. Confirm `go env CGO_ENABLED` prints `1`.

Toolchain pins are recorded in `.go-version`, `.nvmrc`, `backend/go.mod`, and `apps/web/package.json`.

## Clean-checkout setup

```bash
git clone https://github.com/KaiwenMo1/CurbOS.git
cd CurbOS

if command -v nvm >/dev/null 2>&1; then
  nvm use
fi
npm --prefix apps/web ci
make check
```

If you use NVM, load it in your shell before running the setup commands. With the default NVM install location, run `source "$HOME/.nvm/nvm.sh"`. Other Node installations work if they provide the pinned versions. Confirm `go version`, `node --version`, and `npm --version` match the prerequisites before running the quality gate.

The web shell can run independently. Start and migrate the database below to exercise the API's ready state.

## Run the foundation

Start the [local database](#local-postgresql-and-postgis) and apply its migration first. Then run the API from the repository root. This example reads the password from the running local container and passes it through the environment.

```bash
(
  set -e
  endpoint=$(docker compose -f compose.yaml port db 5432)
  PGPASSWORD=$(docker compose -f compose.yaml exec -T db printenv POSTGRES_PASSWORD)
  export PGPASSWORD
  export CURBOS_DATABASE_URL="postgres://curbos@$endpoint/curbos?sslmode=disable"
  cd backend
  go run ./cmd/api
)
```

Run the frontend development server in another terminal:

```bash
npm --prefix apps/web run dev
```

Vite prints the local URL. The page must state that no verified parking data is available; it must not display parking pins or imply coverage.

## API configuration and health contract

Export the variables for the API process. Compose reads its local `.env` file separately. The Go process reads its environment at startup.

| Variable | Default | Accepted values |
|---|---|---|
| `CURBOS_DATABASE_URL` | Required | A single PostgreSQL TCP URL with an explicit host, user, and database. The port defaults to `5432`. Set a non-empty URL password or omit it and use a pgx credential source such as `PGPASSWORD`. |
| `CURBOS_HTTP_ADDR` | `127.0.0.1:8080` | An IP address, `localhost`, or an empty host with a port from 1 to 65535. An empty host listens on all interfaces. |
| `CURBOS_READY_TIMEOUT` | `1s` | Go duration from `1ms` to `5s`, including pool acquisition and the readiness query. |
| `CURBOS_SHUTDOWN_TIMEOUT` | `10s` | Go duration from `1ms` to `30s` for HTTP drain and pool cleanup combined. |

The database URL defaults to `sslmode=verify-full` when the mode is omitted. Set `sslmode=disable` only for a loopback database such as the Compose service. Explicit `verify-ca` and `require` modes are also supported. Keep credentials out of command history, version control, and logs. Use a dedicated runtime role with access to the installed extension and Goose history in deployments.

```bash
curl -i http://127.0.0.1:8080/healthz
curl -i http://127.0.0.1:8080/readyz
```

| Request | Status and JSON |
|---|---|
| `GET /healthz` | `200` with `{"status":"ok"}` whenever the process can serve HTTP. |
| `GET /readyz` | `200` with `{"status":"ready"}` when PostgreSQL answers the baseline check. |
| `GET /readyz` during an outage, timeout, or missing baseline | `503` with `{"status":"not_ready"}`. |
| Unsupported method on a health route | `405` with `Allow: GET` and `{"status":"method_not_allowed"}`. HTTP suppresses the body for HEAD requests. |
| Unknown path | `404` with `{"status":"not_found"}`. |

Application responses use `Content-Type: application/json` and `Cache-Control: no-store`. See the [OpenAPI contract](contracts/openapi/health.yaml).

The API validates configuration and creates one lazy connection pool at startup. Each readiness request uses one bounded SQL query to check that the PostGIS function works, the extension is installed, and the latest record for Goose migration 1 is applied. This lets an API that starts before migration or during an outage become ready on a subsequent request. M1 readiness covers the database baseline. Parking data coverage and legal recommendations have separate acceptance gates.

The pool allows four connections with a five-second connection setup limit. The HTTP server uses five-second read-header, ten-second read/write, and one-minute idle timeouts. SIGINT and SIGTERM stop new HTTP connections. In-flight requests and PostgreSQL pool cleanup share the shutdown deadline. On expiry, the server cancels remaining requests, force-closes their HTTP connections, and exits with an error. The operating system closes any database sockets still open at process exit.

## Local PostgreSQL and PostGIS

Use Docker with the Compose plugin and Linux containers. On Windows, start Docker Desktop and enable [WSL integration](https://docs.docker.com/desktop/features/wsl/) for the Ubuntu distro. From WSL, confirm both the CLI and the engine respond.

```bash
docker compose version
docker info --format '{{.ServerVersion}} {{.OSType}} {{.OperatingSystem}}'
```

From the repository root, create the ignored `.env` if needed, then set `POSTGRES_PASSWORD` in it to a unique local value. A random hexadecimal value works without dotenv quoting. Keep this password separate from production and simulation credentials.

```bash
test -e .env || (umask 077 && cp .env.example .env)
# Edit .env before continuing.
docker compose -f compose.yaml config --quiet
docker compose -f compose.yaml up -d --wait --wait-timeout 90 db
make db-migrate
make db-status
docker compose -f compose.yaml exec -T db psql -X -U curbos -d curbos -c 'SELECT postgis_full_version();'
```

The service listens on `127.0.0.1:5432` by default. Set `CURBOS_DB_PORT` in `.env` if that port is occupied. The pinned PostgreSQL 17 / PostGIS 3.6 image is for Linux amd64. The first migration installs PostGIS. Compose masks the image's automatic init scripts so Goose records that change explicitly. The container can become healthy before the first migration runs. A healthy container has answered an authenticated SQL query, and `make db-status` confirms the schema version separately.

`go run` builds the pinned Goose CLI on first use and caches the build. The migration command uses the local Docker engine's Unix socket to resolve the loopback port and read the development container's password. It passes the password to the driver through the environment. The `curbos` role initializes and owns this disposable local database. TLS is disabled for the loopback migration connection. Run one migration command at a time.

Use `docker compose -f compose.yaml ps -a` and `docker compose -f compose.yaml logs --tail 50 db` for diagnostics. Keep `config --quiet` when checking configuration because the rendered config includes the database password. An empty password fails Compose configuration. The PostgreSQL image reads the initialization password only when the volume is empty. If you edit it later, the health check will fail until you restore the matching password or rotate the stored role password and recreate the container. If Goose cannot reach a stopped database, start it with `docker compose -f compose.yaml up -d --wait db` and retry.

Checkouts using the default `curbos-dev` project on the same Docker engine share its volume. Set a distinct `COMPOSE_PROJECT_NAME` and `CURBOS_DB_PORT` in each checkout's `.env` if you want separate databases.

- **Restart** with `docker compose -f compose.yaml restart db`, then `docker compose -f compose.yaml up -d --wait db` to wait for health.
- **Shut down and keep data** with `docker compose -f compose.yaml down`. The named volume remains.
- **Destructive reset** of the default project. Confirm the target with `docker compose -f compose.yaml -p curbos-dev ps -a` and `docker volume ls --filter label=com.docker.compose.project=curbos-dev`. If the entire volume can be discarded, run `docker compose -f compose.yaml -p curbos-dev down --volumes`. For a custom project, replace `curbos-dev` in all three commands with that exact project name.

Run the database integration check with `make db-test`. It requires Bash, Go, Docker Compose and OpenSSL. It uses an isolated project with a random local password, an ephemeral loopback port, and a disposable named volume. The script uses the checked-in Compose file explicitly, so local override files cannot redirect its startup or cleanup. It checks clean startup, rejection of empty and incorrect passwords, PostGIS installation by Goose, recorded migration status, repeatable migration, and persistence through restart and container recreation. It removes only its own test project and volume.

Run `make api-test` to include the real HTTP lifecycle test in that same disposable setup. The test verifies the connection target before running database checks, checks readiness around migration and a paused database, and verifies pool cleanup after recovery. Additional probes hold a lock in the test database to exercise graceful drain and forced shutdown with an active request. CI runs the combined database and API check.

## Verification commands

```bash
make fmt-check
make lint
make typecheck
make test
make build
```

Or run the complete local quality gate:

```bash
make check
```

`make bootstrap` performs a clean frontend dependency installation. CI runs the same checks from a clean GitHub checkout.

## Repository layout

```text
apps/web/       React/TypeScript/Vite frontend
backend/        Go modular-monolith foundation
db/             Goose runner and versioned migrations
tests/db/       Isolated Compose database integration check
docs/           Architecture, milestones, research, and handoff documents
tools/m0/       Research-only M0 audit utilities and synthetic fixtures
tracking/       Planning-bundle status and manifest
```

Research fixtures under `tools/m0/fixtures` are synthetic. They are not Los Angeles measurements and must never support production claims.
