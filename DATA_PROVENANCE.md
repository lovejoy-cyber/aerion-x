# AERION-X — Data Provenance

Every important result in AERION-X can be traced back to what produced it.
This document is the map for doing that trace, not a promise that it's
automated end-to-end in the GUI (it isn't, yet — see bottom).

## Vision event trace

```
EVENT (events table)
  source_id      -> which video/camera stream produced it (e.g. "video:vtest.avi")
  track_ids      -> which tracked object(s) — join against the in-memory
                     Track objects during the run that produced them
                     (tracks are not currently persisted standalone; only
                     the events they produced are — see "Known gap" below)
  provenance     -> REAL | SYNTHETIC | SIMULATION, always explicit
  evidence (JSON) -> the measurable fact that triggered the event
                      (e.g. {"position": [x,y]}, {"distance_px": ..., "threshold_px": ...})

  -> pipeline_runs table, joined by source_id + time window, gives:
       which model (model_name is on the Detection, not currently
       persisted per-event — see "Known gap")
       frame count, wall-clock start/end
```

## Sensor anomaly trace

```
ANOMALY (anomaly_results table)
  stream_id   -> sensor_streams table: signal_name, unit, provenance, asset_id
  algorithm   -> which detector (z-score / rolling-threshold / CUSUM / isolation-forest)
  threshold   -> the exact threshold that was crossed
  score       -> the measured value (e.g. std deviations from mean)
  reason      -> a human-readable restatement of score+threshold, never invented
```

## Inspection trace

```
INSPECTION (inspections table)
  asset_id       -> assets table
  change_score, mean_ssim -> the two real measurements
  anomaly_regions (JSON)  -> bbox + area_px + label ("VISUAL ANOMALY REGION")
                              per real classical-CV region found
  notes          -> states plainly this is not a trained defect classifier
```

Reference/current frame numbers and source video path are accepted as request
parameters (`POST /inspections/run`) but **not currently persisted onto the
inspection record itself** — see "Known gap" below.

## Correlation trace

```
CORRELATED_EVENT
  event_ids       -> the exact events that were grouped (not summarized/lossy)
  event_types     -> the set of distinct types involved
  sources         -> the set of distinct source_ids involved
  provenance_note -> e.g. "MIXED: REAL,SYNTHETIC" — explicit whenever a
                       correlation spans differently-sourced data
```

`CorrelationEngine` groups by time window only — it never computes or exposes
a causation score, confidence-of-causation, or "caused_by" field, by design
(`core/correlation/correlation_engine.py`).

## Model provenance

```
GET /models -> ModelRecord:
  name, version           -> e.g. YOLOv8n, 8.4.0
  weights_source           -> the exact URL weights were fetched from
  license                   -> e.g. AGPL-3.0 (Ultralytics)
  num_parameters             -> extracted from the loaded model object, never hardcoded
  hardware                    -> platform + GPU-or-CPU string, captured at registration time
  registered_at                -> ISO timestamp
```

## Known gaps (real, not hidden)

- **Tracks are not persisted as standalone records.** Only the events a track
  produced are in the database; the full position/velocity/state history of a
  track lives only in memory during a pipeline run. Tracing "this event came
  from this exact frame" beyond the event's own `evidence` JSON currently
  requires re-running the pipeline, not querying history.
- **Inspection records don't store which video/frame numbers produced them**
  — the `POST /inspections/run` request parameters aren't written onto the
  `InspectionRecord`/`InspectionReport` object. A real fix: add
  `source_video_path`, `reference_frame`, `current_frame` columns to the
  `inspections` table.
- **No per-event model-version stamp.** `Detection.model_name` exists on the
  in-memory object but isn't currently carried onto the persisted `Event` —
  `Event.metadata` (a free-form dict already in the schema) is the natural
  place to add it; not done in this pass.

These are the concrete next steps if full click-through provenance
(GUI event -> exact frame -> exact model version) becomes a real requirement.
