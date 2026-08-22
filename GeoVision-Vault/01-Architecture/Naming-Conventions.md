---
title: Naming Conventions
type: architecture
status: canonical
updated: 2026-08-18
---

# Naming Conventions

> ⚖ There are **two image namespaces**. Confusing them is the most likely bug in this project.
> See ADR-002 in [[ADR-Index]].

---

## 1. Project Code

Set by the owner at project creation. Immutable afterwards (it is baked into filenames and
device names).

```
<INITIALS>_<NUMBER>
```

- `INITIALS` — 2–5 uppercase letters `[A-Z]{2,5}`, owner's choice (building, client, or
  personal initials). Examples: `NG`, `BM`, `AYU`, `JOLLI`.
- `NUMBER` — zero-padded 2 digits `[0-9]{2}`, the owner's project counter.
- Examples: `NG_00`, `BM_01`, `AYU_05`.
- **Uniqueness:** globally unique across GeoVision (enforced by a unique index). If the code
  is taken, the API returns `409` with 3 suggested alternatives.
- Regex: `^[A-Z]{2,5}_[0-9]{2}$`

## 2. Device (Camera) Name

Auto-generated at pairing. Never user-typed.

```
ESP_<PROJECT_CODE>_<FACE>
```

| Face | Code | Faces captured | Notes |
|---|---|---|---|
| Front | `F` | 1 | |
| Front Diagonal | `FD` | 2 | **default / recommended** |
| Back | `B` | 1 | |
| Back Diagonal | `BD` | 2 | |

- Examples: `ESP_NG_00_FD`, `ESP_BM_01_B`.
- Multiple devices per project allowed; `(project_id, face)` is unique — one device per face.
  A second camera on the same face must be added as `FD2`… only via an explicit override
  flag (documented in [[Device-Pairing-Protocol]]).
- Regex: `^ESP_[A-Z]{2,5}_[0-9]{2}_(F|FD|B|BD)[0-9]?$`

## 3. Runtime Capture Filename (production images)

Assigned **by the server** on ingest — the device proposes, the server decides.

```
<PROJECT_CODE>_<CAPTURED_AT_UTC>_<SEQ>.jpg
```

- `CAPTURED_AT_UTC` — compact ISO-8601 basic UTC: `YYYYMMDDTHHMMSSZ`.
- `SEQ` — 3-digit zero-padded sequence within that project **for that UTC day**, `001`-based.
- Examples:
  - `NG_00_20260812T070000Z_001.jpg`
  - `AYU_05_20260812T161500Z_003.jpg`
- The **face** is not in the filename (it is a DB column, `images.device_id → devices.face`)
  to keep names short; the storage key carries it for human browsing:
  `projects/{project_id}/images/{yyyy}/{mm}/{dd}/{face}/{filename}`.
- Stage is **absent by design** — the stage is what the AI predicts. Never put a predicted
  label into a filename.

## 4. Dataset / Training Filename

Used only in `dataset/`, where the stage is a **ground-truth label**.

```
GV_<PROJECT>_<STAGE>_<NUMBER>.jpg
```

- Examples: `GV_CB01_FDN_0001.jpg`, `GV_CB01_STR_0045.jpg`.
- `NUMBER` is 4-digit zero-padded, unique within `(PROJECT, STAGE)`.
- Stage tokens: see [[Construction-Stages]] (`FDN, STR, ROF, FIN` — narrowed from the retired
  10-token list by [[ADR-Index#ADR-036|ADR-036]], 2026-08-18).
- A production capture that gets human-labelled and promoted into the dataset is **renamed**
  into this namespace, and `dataset/metadata/metadata.csv` records its original runtime name.

## 5. Storage Keys (object store)

```
projects/{project_id}/images/{yyyy}/{mm}/{dd}/{face}/{filename}
projects/{project_id}/preprocessed/{image_id}.jpg
projects/{project_id}/thumbs/{image_id}.webp
projects/{project_id}/assets/{asset_id}_{safe_original_name}
projects/{project_id}/reports/{report_id}.{pdf|csv}
models/{kind}/{architecture}/{version}/best.pt
```

## 6. Code Conventions

| Layer | Convention | Example |
|---|---|---|
| Python modules/functions/vars | `snake_case` | `compute_window_progress` |
| Python classes | `PascalCase` | `ProjectRepository` |
| Python constants/enums | `UPPER_SNAKE` | `MIN_CONFIDENCE` |
| DB tables | `snake_case`, **plural** | `project_members` |
| DB columns | `snake_case` | `captured_at` |
| DB PK | `id` (UUID v4) | |
| DB FK | `<singular_table>_id` | `project_id` |
| Timestamps | `*_at`, `TIMESTAMPTZ`, **always UTC** | `uploaded_at` |
| Booleans | `is_*` / `has_*` | `is_active` |
| API paths | `/api/v1/<plural-kebab>` | `/api/v1/project-members` |
| API JSON fields | `snake_case` (matches Pydantic; no transform layer) | `progress_pct` |
| TS types/components | `PascalCase` | `ProjectFolderPage` |
| TS vars/functions | `camelCase` | `useProjectProgress` |
| React files | `PascalCase.tsx` for components, `camelCase.ts` otherwise | |
| Enum values in DB | lowercase `snake_case` strings | `front_diagonal` |
| Celery tasks | `<domain>.<verb>` | `inference.process_image` |
| WS events | `<entity>.<event>` | `project.progress.updated` |
| Git branches | `feat/mXX-slug`, `fix/slug` | `feat/m05-device-pairing` |

## 7. Percentages

- Stored as **numeric(5,2)**, range `0.00`–`100.00`, field name always ends `_pct`.
- Confidences stored as `numeric(4,3)` in `0.000`–`1.000`, field ends `_confidence`.
- Never store a percentage as a 0–1 float and a confidence as 0–100. Ever.

## Related
[[Master-Architecture]] · [[Construction-Stages]] · [[Domain-Model]] · [[Device-Pairing-Protocol]]
