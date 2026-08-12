# `ai/` — GeoVision AI package

Standalone PyTorch package: OpenCV preprocessing, construction-stage
classification, object detection, and the progress aggregation algorithm.

**The backend imports this package. This package never imports the backend.**
(ADR-011)

## Layout

`src`-layout, so the import path is `ai.*` while the working directory can
never shadow the installed package:

```
ai/
├── pyproject.toml
├── src/ai/
│   ├── preprocessing/   Module 06 — OpenCV pipeline + quality gate
│   ├── data/            Module 07 — dataset, transforms, grouped split
│   ├── models/          Modules 07-08 — ResNet18 · MobileNetV3 · YOLOv8 · Stub
│   ├── training/        Modules 07-08 — trainer, callbacks, CLIs
│   ├── progress/        Module 09 — mapping + aggregator (PURE, no I/O)
│   ├── inference/       Module 09 — InferenceService
│   ├── evaluation/      Module 15 — metrics, benchmarks, thesis figures
│   └── configs/         YAML: classes, training, preprocessing
└── tests/
```

## Install

```bash
cd ai
uv sync --extra dev              # CPU torch (default)
uv sync --extra dev --extra detect   # + ultralytics for YOLOv8
```

### GPU training

Torch resolves to **CPU wheels by default** — the CUDA build is ~2.5 GB and
useless without an NVIDIA GPU. To train on a local GPU, comment out the
`[tool.uv.sources]` block in `pyproject.toml` and re-run `uv sync`. No code
changes are needed: every entrypoint already does
`"cuda" if torch.cuda.is_available() else "cpu"`.

## Run

```bash
uv run pytest                                   # tests
uv run python -m ai.training.train_classifier   # Module 07
uv run python -m ai.evaluation.run_all          # Module 15
```

## Hard constraints

- **No TensorFlow or Keras**, including transitively (`make guard` enforces it).
- `ai/progress/` stays pure — no I/O, no ORM, no torch imports.
- Type hints on every function; docstrings on every public one.
- CPU fallback must always work.

Full specs live in the vault: `GeoVision-Vault/03-Modules/`.
