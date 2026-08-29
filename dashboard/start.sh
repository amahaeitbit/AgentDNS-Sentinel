#!/bin/sh
set -eu

nginx
exec reflex run \
    --env dev \
    --frontend-port 3001 \
    --backend-port 8000 \
    --backend-host 0.0.0.0
