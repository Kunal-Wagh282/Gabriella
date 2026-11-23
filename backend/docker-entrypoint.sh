#!/bin/sh
set -e

# Apply migrations, then seed the catalogue on first boot (no-op once products exist).
alembic upgrade head
python -m seed --if-empty --workers "${SEED_WORKERS:-4}"

exec "$@"
