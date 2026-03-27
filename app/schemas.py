from typing import Any

from pydantic import BaseModel, Field


class ParseRow(BaseModel):
    date: str = Field(description="ISO date YYYY-MM-DD when possible")
    description: str = ""
    amount: float
    raw: dict[str, Any] | None = None


class ParseResult(BaseModel):
    currency: str = "ARS"
    period: dict[str, str | None] = Field(default_factory=lambda: {"from": None, "to": None})
    rows: list[ParseRow] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    bank_code: str
    file_type: str
