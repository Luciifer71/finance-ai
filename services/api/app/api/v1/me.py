"""The signed-in user's own identity."""

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.schemas.me import MeResponse

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
def read_me(user: CurrentUser) -> MeResponse:
    return MeResponse.model_validate(user)
