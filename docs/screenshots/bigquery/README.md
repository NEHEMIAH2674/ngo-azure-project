# BigQuery

Captured from the BigQuery console (project `npd-01`):

1. **`dataset-separation.png`** — the Explorer pane, showing both
   environments at once: `dev_dlight_raw` /
   `dev_dlight_analytics_{staging,intermediate,marts}` alongside the plain,
   unmarked `dlight_raw` / `dlight_analytics_{staging,intermediate,marts}`
   (prod — the ready-for-use one). The naming itself tells the story: no
   caveat on the name means it's ready for use.

Optional extras, not captured (the one shot above already carries the point
this folder exists to make):
- A raw table (e.g. `dlight_raw.payments`) with its schema open, showing
  every column as untyped `STRING` — the "raw is raw" claim, visible rather
  than just asserted.
- A mart table (e.g. `dlight_analytics_marts.fct_paid_post_call`) previewed
  alongside it, showing the typed, modeled output for contrast.
