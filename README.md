# CurbOS

CurbOS is an evidence-aware, street-parking-first application under active development. The current foundation contains no parking inventory, legal recommendations, occupancy claims, map tiles, or user location collection.

## Current capability

- A compilable Go API entrypoint placeholder. It intentionally exposes no HTTP endpoints yet.
- A React/TypeScript/Vite web shell with an explicit **No verified parking data available** state.
- A local PostgreSQL/PostGIS service with a Goose migration baseline.
- Reproducible formatting, linting, testing, type-checking, build, and CI commands.

Operational health endpoints are planned for PR-03 and MapLibre for PR-04.

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

The Go placeholder and web shell run without a database or environment variables. Use the database setup below to work with PostGIS.

## Run the foundation

The Go command is a buildable placeholder, not an HTTP server:

```bash
cd backend
go run ./cmd/api
```

Run the frontend development server in another terminal:

```bash
npm --prefix apps/web run dev
```

Vite prints the local URL. The page must state that no verified parking data is available; it must not display parking pins or imply coverage.

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
