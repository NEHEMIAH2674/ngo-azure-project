# BigQuery

Capture from the BigQuery console (project `npd-01`):

1. **`dataset-separation.png`** — the Explorer pane showing `dlight_raw`
   sitting alongside `dlight_analytics_staging` / `_intermediate` / `_marts`
   as visibly separate datasets.
2. **`raw-table-schema.png`** — a raw table (e.g. `dlight_raw.payments`)
   with its schema/preview open, showing every column as untyped `STRING` —
   the "raw is raw" claim, visible rather than just asserted.
3. **`mart-preview.png`** — a mart table (e.g.
   `dlight_analytics_marts.fct_paid_post_call`) previewed side by side,
   showing the typed, modeled output for contrast.
