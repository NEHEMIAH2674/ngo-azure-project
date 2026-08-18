#!/usr/bin/env bash
# Wraps `dagster dev` with a bounded retry for a confirmed transient
# Windows subprocess-spawn flake: dagster dev's webserver child process
# occasionally exits immediately with STATUS_DLL_INIT_FAILED (0xC0000142)
# -- an OS-level hiccup in how Windows spawns the gRPC-backed webserver
# subprocess, not a bug in this project. Confirmed non-deterministic: the
# identical command, with no code or config change, succeeds on retry.
#
# The crash happens late in startup -- after `dbt deps`/`dbt parse` finish
# and the webserver subprocess actually spawns (observed 45-65s in, not at
# t=0) -- so this polls for either signal every second rather than trusting
# a single fixed-delay check: the webserver responding (healthy, attach)
# or the process dying first (crashed, retry). Requires `curl` (bundled
# with Git for Windows, so already on PATH in the same shell used to run
# the rest of this project).

set -uo pipefail
cd "$(dirname "$0")"

MAX_ATTEMPTS=3
GRACE_PERIOD_SECONDS=90
PORT=3000

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    echo "[run_dagster_dev] attempt $attempt/$MAX_ATTEMPTS"
    dagster dev -w workspace.yaml &
    pid=$!

    trap 'kill "$pid" 2>/dev/null; exit 130' INT TERM

    healthy=0
    elapsed=0
    while [ "$elapsed" -lt "$GRACE_PERIOD_SECONDS" ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            break # process died -- not healthy, fall through to retry
        fi
        if curl -sf "http://127.0.0.1:$PORT" >/dev/null 2>&1; then
            healthy=1
            break
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done

    if [ "$healthy" = "1" ]; then
        echo "[run_dagster_dev] webserver responding after ${elapsed}s -- attaching (Ctrl-C to stop)"
        wait "$pid"
        exit $?
    fi

    if kill -0 "$pid" 2>/dev/null; then
        # Still alive but slow (e.g. a cold `dbt deps` package download) --
        # not the crash we're guarding against. Attach rather than kill a
        # perfectly fine, just-slow startup.
        echo "[run_dagster_dev] still starting after ${GRACE_PERIOD_SECONDS}s without responding -- attaching anyway (Ctrl-C to stop)"
        wait "$pid"
        exit $?
    fi

    echo "[run_dagster_dev] exited before becoming healthy -- likely the known transient crash, retrying"
done

echo "[run_dagster_dev] failed $MAX_ATTEMPTS times in a row -- this is no longer the known flake, check the log above"
exit 1
