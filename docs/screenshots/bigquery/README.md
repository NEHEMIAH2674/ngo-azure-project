# BigQuery

Capture from the BigQuery console (project `npd-01`):

1. **`dataset-separation.png`** — the Explorer pane filtered to `dlight`,
   showing both environments at once: `dev_dlight_raw` /
   `dev_dlight_analytics_{staging,intermediate,marts}` alongside the plain,
   unmarked `dlight_raw` / `dlight_analytics_{staging,intermediate,marts}`
   (prod — the ready-for-use one). The naming itself tells the story: no
   caveat on the name means it's ready for use.
2. **`raw-table-schema.png`** — a raw table (e.g. `dlight_raw.payments`)
   with its schema/preview open, showing every column as untyped `STRING` —
   the "raw is raw" claim, visible rather than just asserted.
3. **`mart-preview.png`** — a mart table (e.g.
   `dlight_analytics_marts.fct_paid_post_call`) previewed side by side,
   showing the typed, modeled output for contrast.
