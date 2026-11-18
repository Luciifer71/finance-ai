"""Mounts every /api/v1 module router.

Authentication is a router-level dependency, so no /api/v1 route can be added
without it: requests without a valid token get 401 before any handler runs.
"""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.v1 import (
    accounts,
    budgets,
    categories,
    exports,
    goals,
    imports,
    jobs,
    me,
    refunds,
    reports,
    scenarios,
    transactions,
    transfers,
)

api_router = APIRouter(dependencies=[Depends(get_current_user)])
for module in (
    me,
    accounts,
    categories,
    transactions,
    imports,
    transfers,
    refunds,
    jobs,
    reports,
    budgets,
    exports,
    goals,
    scenarios,
):
    api_router.include_router(module.router)
