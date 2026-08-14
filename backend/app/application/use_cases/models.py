"""What the system is currently running, and what it has ever run.

Two audiences. ``GET /model/status`` answers an operator's question — is a model
loaded, on what device, how fast, and is anything backed up? ``GET /models``
answers the thesis's question: here is every registered model with its metrics,
which is the ResNet18-vs-MobileNetV3-vs-YOLOv8 comparison table.

The status endpoint reads from **two** sources and reconciles them. PostgreSQL
holds the registry — what was trained, when, and how well it scored. The worker
holds the live facts — which weights are actually in memory, on which device,
and how long recent images have taken. Neither alone is the truth: a registry
row proves nothing is loaded, and a worker cannot report the metrics from a
training run it never saw.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.enums import ModelKind

if TYPE_CHECKING:
    from app.application.ports.inference_gateway import InferenceGateway, WorkerStatus
    from app.domain.entities import AIModel
    from app.domain.repositories import AIModelRepository

__all__ = ["GetModelStatus", "ListModels", "ModelStatus"]


@dataclass(frozen=True, slots=True)
class ModelStatus:
    """The reconciled view of what is running.

    Attributes:
        worker_reachable: Whether a worker answered the probe. When ``False``
            every live field is ``None`` and only the registry is reported —
            which is the honest shape of "the models are registered but nothing
            is serving them right now".
        preprocessing_matches: Whether the pipeline the worker is running is the
            one the loaded weights were trained through (ADR-025). ``False``
            means predictions are still being produced and are quietly less
            accurate than the metrics claim — the failure this fingerprint
            exists to make visible.
    """

    worker_reachable: bool
    classifier: AIModel | None = None
    detector: AIModel | None = None
    live: WorkerStatus | None = None
    queue_depth: dict[str, int] = field(default_factory=dict)
    preprocessing_matches: bool | None = None

    @property
    def using_stubs(self) -> bool:
        """Whether a placeholder is answering, rather than trained weights."""
        return self.live.using_stubs if self.live is not None else True


class GetModelStatus:
    """Reconcile the model registry with a live worker probe."""

    def __init__(self, models: AIModelRepository, gateway: InferenceGateway) -> None:
        """Bind the registry and the channel to the worker."""
        self._models = models
        self._gateway = gateway

    async def execute(self) -> ModelStatus:
        """Report what is registered and what is actually loaded.

        Never raises for an unreachable worker. This endpoint is how somebody
        finds out the worker is down; failing when the worker is down would make
        it useless at the only moment it matters.
        """
        classifier = await self._models.get_active(ModelKind.CLASSIFIER)
        detector = await self._models.get_active(ModelKind.DETECTOR)
        live = await self._gateway.status()
        if live is None:
            return ModelStatus(worker_reachable=False, classifier=classifier, detector=detector)

        return ModelStatus(
            worker_reachable=True,
            classifier=classifier,
            detector=detector,
            live=live,
            queue_depth=await self._gateway.queue_depth(),
            preprocessing_matches=_fingerprints_agree(live),
        )


class ListModels:
    """Every registered model — the thesis comparison table."""

    def __init__(self, models: AIModelRepository) -> None:
        """Bind the registry."""
        self._models = models

    async def execute(self) -> tuple[AIModel, ...]:
        """Return all registered models, trained and stub alike.

        Stubs are included rather than filtered out. A comparison table that
        silently omitted the placeholder would make it impossible to tell, from
        the table alone, whether a run used real weights.
        """
        return await self._models.list_all()


def _fingerprints_agree(live: WorkerStatus) -> bool | None:
    """Whether the running pipeline matches the one the weights were trained on.

    Returns ``None`` when the loaded model carries no fingerprint — true of the
    stub, and of any checkpoint produced before Module 07 started stamping it.
    Unknown and mismatched are deliberately different answers: reporting an
    unstamped model as a mismatch would cry wolf on every stub run.
    """
    trained = live.classifier.preprocessing_fingerprint
    if not trained:
        return None
    return trained == live.preprocessing_fingerprint
