"""Validation schemas for financial accounts."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class AccountCreate(BaseModel):
    """Validate information used to create an account."""

    name: str = Field(min_length=1, max_length=120)
    account_type: Literal["bank", "cash", "credit", "wallet"]
    institution: str | None = Field(default=None, max_length=120)
    currency: Literal["INR"] = "INR"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()

        if not name:
            raise ValueError("Account name cannot be empty")

        return name
