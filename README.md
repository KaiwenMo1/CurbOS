# CurbOS

CurbOS is an evidence-aware, street-parking-first application under active development. This PR-01 foundation contains no parking inventory, legal recommendations, occupancy claims, map tiles, or user location collection.

## Current capability

- A compilable Go API entrypoint placeholder. It intentionally exposes no HTTP endpoints yet.
- A React/TypeScript/Vite web shell with an explicit **No verified parking data available** state.
- Reproducible formatting, linting, testing, type-checking, build, and CI commands.

PostGIS begins in PR-02, operational health endpoints in PR-03, and MapLibre in PR-04.

## Prerequisites

- Git 2.43 or newer
- Go 1.27.4
- Node.js 24.22.3
- npm 11.19.1 (bundled with the pinned Node release)
- GNU Make
- A C compiler on `PATH` (such as GCC or Clang) and CGO enabled for `go test -race`, which runs in `make test` and `make check`. Confirm `go env CGO_ENABLED` prints `1`.

Toolchain pins are recorded in `.go-version`, `.nvmrc`, `backend/go.mod`, and `apps/web/package.json`.

## Clean-checkout setup

Until PR-01 is merged, reviewers must switch to `m1/pr-01-foundation` after the branch is pushed. After merge, use `main`.

```bash
git clone https://github.com/KaiwenMo1/CurbOS.git
cd CurbOS
git switch m1/pr-01-foundation

if command -v nvm >/dev/null 2>&1; then
  nvm use
fi
npm --prefix apps/web ci
make check
```

If you use NVM, load it in your shell before running the setup commands. With the default NVM install location, run `source "$HOME/.nvm/nvm.sh"`. Other Node installations work if they provide the pinned versions. Confirm `go version`, `node --version`, and `npm --version` match the prerequisites before running the quality gate.

The checked-in `.env.example` documents the configuration surface. PR-01 requires no environment variables or secrets.

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
docs/           Architecture, milestones, research, and handoff documents
tools/m0/       Research-only M0 audit utilities and synthetic fixtures
tracking/       Planning-bundle status and manifest
```

Research fixtures under `tools/m0/fixtures` are synthetic. They are not Los Angeles measurements and must never support production claims.
