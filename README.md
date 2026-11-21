# CurbOS

CurbOS is an evidence-aware, street-parking-first application under active development. The current foundation has no parking inventory, legal recommendations, occupancy claims, or user location collection.

## Current capability

- A Go HTTP API with liveness, PostgreSQL readiness, and release-pinned Discovery endpoints. Ordinary Discovery requests have no authorized public release.
- A responsive React/TypeScript/Vite map shell with Going Home and Going Out modes, optional MapLibre rendering, and a live backend readiness check. **No verified parking data available.** remains visible in every backend state.
- A local PostgreSQL/PostGIS service with a Goose migration baseline.
- Reproducible formatting, linting, testing, type-checking, build, and CI commands.

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

The web shell starts independently and reports the result of its readiness request. Follow the runbook below to exercise the complete local stack.

## Run the foundation

Configure the ignored root `.env` first, then run database startup and migration from the repository root. [Local PostgreSQL and PostGIS](#local-postgresql-and-postgis)

```bash
docker compose -f compose.yaml up -d --wait --wait-timeout 90 db
make db-migrate
```

On a fresh local database, create a dedicated API login from the PostgreSQL administrator console. `\password` prompts for a new password without putting it on the command line. Reuse the login on subsequent starts.

```bash
docker compose -f compose.yaml exec db psql -X -U curbos -d curbos
```

```sql
CREATE ROLE curbos_local_api LOGIN IN ROLE curbos_api_reader;
\password curbos_local_api
\quit
```

Start the Go API in a separate terminal from the repository root and enter that reader password when prompted.

```bash
(
  set -e
  set +x
  unset PGSERVICE PGSERVICEFILE PGOPTIONS
  endpoint=$(docker compose -f compose.yaml port db 5432)
  read -rs -p 'Local API reader password: ' PGPASSWORD
  printf '\n'
  export PGPASSWORD
  export CURBOS_DATABASE_URL="postgres://curbos_local_api@$endpoint/curbos?sslmode=disable"
  export CURBOS_HTTP_ADDR=127.0.0.1:8080
  cd backend
  go run ./cmd/api
)
```

Run the frontend development server in another terminal:

```bash
npm --prefix apps/web run dev -- --host 127.0.0.1
```

Open the local URL printed by Vite. The browser sends one same-origin `GET /readyz` request on load. Vite forwards that path to Go on `http://127.0.0.1:8080`. Go checks the PostgreSQL, PostGIS, and Goose baseline and the panel displays **Backend ready** when the check succeeds. The panel shows **Backend unavailable** for a failed database check or a server error, and **Backend connection error** for a failed connection, timeout, or unexpected response. Use **Check again** after fixing an outage. Each check has a six-second browser deadline.

To use a different Go port, change `CURBOS_HTTP_ADDR` in the API terminal and set the matching `CURBOS_DEV_API_ORIGIN=http://127.0.0.1:<port>` in the frontend terminal or `apps/web/.env.local`. Restart Vite after changing it. Vite validates the origin at startup and keeps it on the server side. The proxy accepts only `127.0.0.1` with an explicit HTTP port. Keep database credentials in the API terminal.

To exercise a database outage, run these steps against your local development project while Go and Vite stay running.

1. Run `docker compose -f compose.yaml stop db` and select **Check again**. Expect **Backend unavailable** with a database message, and **No verified parking data available.** above the map.
2. Run `docker compose -f compose.yaml up -d --wait --wait-timeout 90 db` and select **Check again**. Expect **Backend ready** on the same page.
3. Press Ctrl+C in the Vite and Go terminals to stop them. Run `docker compose -f compose.yaml down` to stop the database and retain its named volume.

For a connection error, first check `curl -i http://127.0.0.1:8080/readyz`, then `/readyz` at the Vite origin. The expected ready response is HTTP 200 with JSON `{"status":"ready"}`. An HTML response usually indicates a missing proxy route. Serve a production build behind a same-origin `/readyz` route to Go if deploying it later. Vite's development and preview proxies are for local use.

### Optional basemap

Leave `VITE_MAP_STYLE_URL` unset for the default **Basemap not configured** view. It starts no MapLibre renderer and makes no external map requests.

To enable a basemap, copy `apps/web/.env.example` to the ignored `apps/web/.env.local` and set `VITE_MAP_STYLE_URL` to an approved MapLibre Style Specification JSON URL. Use an absolute HTTPS URL or a root-relative path on the same origin, such as `/basemap/style.json` if you serve an approved style there. Restart Vite or rebuild the frontend after changing this value. Vite exposes `VITE_` variables to the browser, so keep credentials, private tokens, and signed URLs out of this setting and all style resources.

Review the style and each resource it references before enabling it. The browser fetches the style, source metadata, tiles, sprites, and fonts directly when needed. Provider requests expose the viewer's IP address and can reveal the viewed map area. Confirm that each provider permits this use, ensure its required attribution appears through MapLibre's attribution control, and check CORS and any deployed Content Security Policy for the approved origins, including support for the same-origin MapLibre worker.

If the configured basemap cannot initialize within 15 seconds, fails to load, reports a worker failure, or loses its WebGL2 context, the shell shows **Map rendering unavailable**. Check WebGL2 support, the worker request, the style URL, resource availability, and CORS, then reload. The parking-data notice appears above the map in every basemap state.

## API configuration and health contract

Export the variables for the API process. Compose reads its local `.env` file separately. The Go process reads its environment at startup.

| Variable | Default | Accepted values |
|---|---|---|
| `CURBOS_DATABASE_URL` | Required | A single PostgreSQL TCP URL with an explicit host, user, and database. The port defaults to `5432`. Set a non-empty URL password or omit it and use a pgx credential source such as `PGPASSWORD`. |
| `CURBOS_HTTP_ADDR` | `127.0.0.1:8080` | An IP address, `localhost`, or an empty host with a port from 1 to 65535. An empty host listens on all interfaces. |
| `CURBOS_READY_TIMEOUT` | `1s` | Go duration from `1ms` to `5s`, including pool acquisition and the readiness query. |
| `CURBOS_DISCOVERY_TIMEOUT` | `2s` | Go duration from `1ms` to `5s`, including pool acquisition and the Discovery query. |
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
| Unknown path outside `/v1/parking/` | `404` with `{"status":"not_found"}`. |

Health responses use `Content-Type: application/json` and `Cache-Control: no-store`. [Health OpenAPI contract](contracts/openapi/health.yaml)

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

Run `make api-test` to include the real HTTP lifecycle test in that same disposable setup. The test verifies the connection target before running database checks, checks readiness around migration and a paused database, and verifies pool cleanup after recovery. Additional probes hold a lock in the test database to exercise graceful drain and forced shutdown with an active request.

### M2 evidence schema

`make db-migrate` applies migration `00002` after PostGIS. It creates empty `sources`, `geo`, and `rules` schemas for source provenance, QA, and release-scoped Zones, Policies, and Areas. Composite foreign keys keep their relationships within one release and restrict the nullable active pointer to its own scope. An imported source identifier can be recorded independently of physical resource identity. A valid WGS84 LineString alone gives no evidence of curb placement, side, or parking legality.

`make db-test` checks the empty schema, inserts explicitly synthetic rows in a rolled-back transaction, and tests rejection of invalid relationships, digests, metadata, and geometry. It exercises migration rollback and reapplication in a disposable project while preserving migration `00001` and PostGIS. Migration `00002` Down deletes the M2 tables and is intended for disposable tests.

### Offline CDS capture

M2 PR-02 verifies a local manifest and captures DS13 Zones and DS11 Policies, with DS12 Areas optional. It records provenance in PostgreSQL and writes deterministic private staging and QA files. The test gate uses synthetic fixtures in a disposable database. [Setup, usage and recovery](data/cds_capture/README.md)

### Private release preparation

The offline validator prepares private candidate packages. Apply through migration `00004` for private registration, independent candidate verification and approval, frozen projections, and an audited pointer workflow gated to administrator-enrolled synthetic fixtures. Real releases remain private. The local `curbos` database owner is for administration. Use a separate least-privileged login for the API. [Validation runbook](data/cds_validate/README.md) [Publication runbook](data/cds_publish/README.md)

### Parking Discovery API

Migration `00005` grants a narrow read capability and adds coverage, map, and pinned Zone detail routes under `/v1/parking`. Ordinary mode returns no authorized public release. The disposable `make api-test` harness alone enables synthetic responses and checks release consistency across activation, rollback, and withdrawal. [API behavior and setup](contracts/openapi/DISCOVERY.md) [Discovery OpenAPI](contracts/openapi/discovery.yaml)

### Browser-to-database quality gate

Install dependencies with `make bootstrap`. Then install Chromium for the pinned Playwright version and run the complete local integration path. On Linux, install the browser's system libraries with Playwright's `--with-deps` option if your environment needs them.

```bash
npm --prefix apps/web exec -- playwright install --only-shell chromium
make e2e-test
```

`make e2e-test` starts and migrates an isolated Compose database, runs the Go integration test, starts the Go binary and the built frontend, and opens Chromium through Vite's loopback preview origin. It verifies readiness, a paused database, recovery on the same page, a stopped API, and an offline browser. A temporary synthetic background style exercises real MapLibre without a provider or parking data. The suite checks the no-data notice across states and the canvas identity across trip mode and readiness changes.

The browser test validates the disposable Compose project's label and published port before pausing its database. The harness uses ephemeral loopback ports, a random test password, and temporary build output. The browser receives no database credentials. On success, failure, SIGINT, or SIGTERM, the harness shuts down the test services and removes the temporary build and disposable volume. The GitHub Actions database job runs this combined database, API, and Chromium check.

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
apps/web/       React/TypeScript/Vite frontend and Chromium integration check
backend/        Go modular-monolith foundation
db/             Goose runner and versioned migrations
tests/db/       Isolated Compose database integration check
docs/           Architecture, milestones, research, and handoff documents
tools/m0/       Research-only M0 audit utilities and synthetic fixtures
tracking/       Planning-bundle status and manifest
```

Research fixtures under `tools/m0/fixtures` are synthetic. They are not Los Angeles measurements and must never support production claims.
