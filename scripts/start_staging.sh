#!/bin/sh
set -eu

log_stage() {
  printf "[staging-start] %s %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >&2
}

log_stage "container start command entered"
log_stage "starting alembic upgrade head"
alembic upgrade head
log_stage "alembic upgrade head completed"
log_stage "starting uvicorn on port ${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
