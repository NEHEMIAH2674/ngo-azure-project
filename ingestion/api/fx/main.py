"""CLI entrypoint for the FX rates fetch/cache job.

    python ingestion/api/fx/main.py

See hook.py for the exchangerate-api.com client (auth, retry/backoff) and
fx_operator.py for the BigQuery-facing task logic (which dates are missing,
idempotent upsert, historical-endpoint fallback).

Note: the task-logic module is named fx_operator.py, not operator.py --
naming it exactly "operator.py" shadows Python's own stdlib `operator`
module the instant this directory ends up on sys.path, which it always
does when main.py is run directly (Python auto-prepends a directly-executed
script's own directory to sys.path before any of its code runs). That
shadow breaks deep in the standard library's own startup (enum.py imports
`operator`) with a confusing circular-import error -- confirmed by hitting
it directly during development.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # ingestion/

from common import get_logger  # noqa: E402

from api.fx.fx_operator import FxRatesOperator  # noqa: E402
from api.fx.hook import ExchangeRateApiHook, FxPermanentError  # noqa: E402

log = get_logger("fx.main")


def main() -> None:
    try:
        hook = ExchangeRateApiHook()
    except FxPermanentError as exc:
        log.error("FX fetch aborted: %s. Downstream USD figures will be NULL until this is fixed.", exc)
        hook = None

    fx_operator = FxRatesOperator(hook)
    result = fx_operator.execute()
    log.info("fx: run summary: %s", result)


if __name__ == "__main__":
    main()
