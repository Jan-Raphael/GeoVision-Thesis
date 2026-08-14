"""Model status and the registry.

Both endpoints are readable by any authenticated user rather than by project
members: a model is a property of the *system*, not of any one project, and
"which version scored my images, on what hardware, how well" is a question every
user of an AI system is entitled to ask about the system judging their site.
Neither endpoint exposes project data.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, InferenceGatewayDep, ModelRepoDep
from app.api.route import TransactionalRoute
from app.api.schemas.predictions import ModelListResponse, ModelStatusResponse
from app.api.v1.presenters_ai import present_model, present_model_status
from app.application.use_cases.models import GetModelStatus, ListModels

router = APIRouter(tags=["models"], route_class=TransactionalRoute)


@router.get(
    "/model/status",
    summary="Active models and live worker health",
    response_model=ModelStatusResponse,
)
async def get_model_status(
    user: CurrentUser,
    models: ModelRepoDep,
    gateway: InferenceGatewayDep,
) -> ModelStatusResponse:
    """What is registered, what is actually loaded, and how backed up it is.

    Reconciles two sources that can legitimately disagree: PostgreSQL knows what
    was trained and how it scored; the worker knows what is in memory right now,
    on which device, and how long recent images took.

    **Always 200.** When no worker answers, ``worker_reachable`` is false and the
    live fields are null — this endpoint is how somebody discovers the worker is
    down, so failing when it is down would make it useless exactly then.

    Two fields deserve attention. ``using_stubs`` is true while the placeholder
    models are answering, so a demo can never be mistaken for a trained result.
    ``preprocessing_matches`` is false when the running pipeline is no longer the
    one the weights were trained through (ADR-025) — predictions continue, and
    are quietly worse than the reported metrics claim.
    """
    _ = user
    status = await GetModelStatus(models, gateway).execute()
    return present_model_status(status)


@router.get(
    "/models",
    summary="Every registered model",
    response_model=ModelListResponse,
)
async def list_models(
    user: CurrentUser,
    models: ModelRepoDep,
) -> ModelListResponse:
    """The full registry — the thesis comparison table.

    ResNet18 against MobileNetV3 against YOLOv8, each with the metrics recorded
    at training time. Stub entries are included rather than filtered, so it is
    always possible to tell from the table alone whether a run used real weights.
    """
    _ = user
    registered = await ListModels(models).execute()
    return ModelListResponse(models=[present_model(model) for model in registered])
