---
title: START HERE
type: index
status: canonical
updated: 2026-08-12
---

# GeoVision — START HERE

> [!important] Rule for every AI/agent session and every human contributor
> **Read this vault BEFORE creating, editing, or generating any file in `GeoVision-Project/`.**
> The vault is the *single source of truth* for architecture, naming, schema, and module scope.
> Code follows the vault. If code and vault disagree, the vault is corrected first (via an ADR),
> then the code is changed. Never invent a table, endpoint, enum, or filename that is not defined here.

> 👉 **Wondering what to do next? Open [[PENDING]]** — the master priority board.

## Reading order (first session)

1. [[Master-Architecture]] — the finalized end-to-end design. **Read fully.**
2. [[Repository-Structure]] — where every file belongs.
3. [[Tech-Stack]] — pinned technologies and hard constraints (e.g. **no TensorFlow**).
4. [[Naming-Conventions]] — project codes, image filenames, device names, DB/API casing.
5. [[Domain-Model]] — entities and the PostgreSQL schema.
6. [[Construction-Stages]] and [[Progress-Calculation]] — the core thesis contribution.
7. [[API-Contract]] — every endpoint, request, response.
8. [[Build-Order]] — the module sequence. **Build one module at a time.**

## Before you write code (checklist)

- [ ] I opened [[Master-Architecture]] and the note for the module I am building.
- [ ] The module I am about to build is the next one in [[Build-Order]] (or the user explicitly chose otherwise).
- [ ] I checked [[Naming-Conventions]] for any identifier I am creating.
- [ ] I checked [[Domain-Model]] before touching the database or any model class.
- [ ] I checked [[API-Contract]] before adding or changing an endpoint.
- [ ] Anything I decide that is *not* already written down gets appended to [[Open-Questions]] or a new ADR in [[ADR-Index]].

## After you finish a module

- [ ] Update the module note's `status:` frontmatter (`planned` → `in-progress` → `done`).
- [ ] Record deviations in [[ADR-Index]].
- [ ] Update [[Progress-Log]] with one line: date, module, what shipped.

## Map of the vault

| Folder | Contains |
|---|---|
| *(root)* | [[PENDING]] — **what to do next, ranked by urgency** |
| `01-Architecture/` | [[Master-Architecture]], [[Repository-Structure]], [[Tech-Stack]], [[Naming-Conventions]], [[Local-Environment-Setup]] |
| `02-Domain/` | [[Domain-Model]], [[Roles-and-Permissions]], [[Construction-Stages]], [[Progress-Calculation]], [[Project-Status-Rules]] |
| `03-Modules/` | One build-spec note per module — see [[Build-Order]] |
| `04-API/` | [[API-Contract]], [[Realtime-Events]] |
| `05-Hardware/` | [[ESP32-CAM-Node]], [[Device-Pairing-Protocol]], [[Capture-Schedule-and-Power]] |
| `06-Dataset/` | [[Dataset-Spec]], [[Annotation-Guide]] |
| `07-Thesis/` | [[Thesis-Mapping]], [[Evaluation-Plan]] |
| `99-Decisions/` | [[ADR-Index]], [[Open-Questions]], [[Progress-Log]] |

## One-paragraph summary of the system

An ESP32-CAM node mounted at a fixed angle on a construction site wakes on a schedule, captures a
photo, geotags it (GPS + RTC timestamp), buffers it to microSD, and uploads it over Wi-Fi to the
GeoVision backend. The backend authenticates the device, resolves which **project folder** it is
paired to, names and stores the image, and runs an AI pipeline: OpenCV preprocessing (perspective
rectification against the camera's reference homography, resize, brightness normalization, denoise)
→ **ResNet18** stage classification (10 fine-grained classes) → mapping to 4 macro construction
stages + a manual approval stage → temporally smoothed progress percentage → optional **YOLOv8**
object detection for corroboration and object counts. Results are written to PostgreSQL and pushed
live to a React dashboard over WebSocket. The dashboard has a **public** face (anyone can browse
public projects, their progress, timeline, GPS location, and public owner profiles) and an
**authenticated** face (owners create project folders, pair cameras, collaborate with other users,
and export PDF/CSV reports).
