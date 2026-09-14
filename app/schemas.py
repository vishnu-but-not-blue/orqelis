from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginInput(Input):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    name: str = Field(default="", max_length=120)


class VerifyInput(Input):
    token: str = Field(min_length=20, max_length=200)


class OrgInput(Input):
    name: str = Field(min_length=2, max_length=160)


class Profile(Input):
    country: str = Field(default="", max_length=3)
    operating_countries: list[str] = Field(default_factory=list, max_length=50)
    languages: list[str] = Field(default_factory=list, max_length=30)
    services: str = Field(default="", max_length=5000)
    products: str = Field(default="", max_length=5000)
    industries: list[str] = Field(default_factory=list, max_length=50)
    employee_band: str = Field(default="5–25", max_length=40)
    revenue_band: str = Field(default="Not supplied", max_length=80)
    cpv_interests: list[str] = Field(default_factory=list, max_length=100)
    currencies: list[str] = Field(default_factory=lambda: ["EUR"], max_length=20)
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    certifications: list[str] = Field(default_factory=list, max_length=100)
    delivery_model: str = Field(default="", max_length=1000)
    regions_served: list[str] = Field(default_factory=list, max_length=100)
    staff_capabilities: str = Field(default="", max_length=5000)
    previous_customers: str = Field(default="", max_length=5000)
    past_projects: str = Field(default="", max_length=10000)
    insurance: str = Field(default="", max_length=1000)
    security_clearances: str = Field(default="", max_length=1000)
    partner_willingness: bool = False
    min_contract: float = Field(default=0, ge=0, le=1e12)
    max_contract: float = Field(default=1000000, gt=0, le=1e12)
    preferred_contract: float = Field(default=250000, ge=0, le=1e12)
    bid_hours_per_day: float = Field(default=2, ge=0, le=1000)
    availability_factor: float = Field(default=0.8, ge=0, le=1)
    hourly_cost: float = Field(default=60, ge=0, le=100000)
    external_bid_cost: float = Field(default=0, ge=0, le=1e9)
    expected_margin: float | None = Field(default=None, ge=0, le=100)
    strategic_fit: int = Field(default=50, ge=0, le=100)
    effort_multiplier: float = Field(default=1, ge=0.25, le=5)

    @field_validator("operating_countries", "languages", "currencies", "cpv_interests")
    @classmethod
    def normalized_list(cls, value):
        if any(len(v) > 20 for v in value):
            raise ValueError("Classification codes must be at most 20 characters")
        return list(dict.fromkeys(v.upper().strip() for v in value if v.strip()))


class EvidenceInput(Input):
    document_id: str | None = None
    capability: str = Field(min_length=2, max_length=160)
    value: float | None = Field(default=None, ge=0, le=1e15)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    annual_values: dict[str, float] = Field(default_factory=dict, max_length=20)
    issuer: str = Field(default="", max_length=250)
    jurisdiction: str = Field(default="", max_length=100)
    valid_from: date | None = None
    valid_until: date | None = None
    locator: str = Field(default="", max_length=500)
    source_excerpt: str = Field(default="", max_length=2000)
    state: Literal["UNVERIFIED", "USER_CONFIRMED", "REJECTED"] = "UNVERIFIED"

    @field_validator("annual_values")
    @classmethod
    def annual(cls, value):
        if any(not k.isdigit() or len(k) != 4 or v < 0 or v > 1e15 for k, v in value.items()):
            raise ValueError("Annual values require a four-digit year and nonnegative amount")
        return value


class WatchInput(Input):
    state: Literal["WATCH", "SAVED", "DISMISSED", "NONE"] = "WATCH"
    reason: str = Field(default="", max_length=500)
    assigned_to: str | None = None
    preference: Literal["CRITICAL", "MATERIAL", "MINOR"] = "MATERIAL"


class CorrectionInput(Input):
    requirement_id: str
    hard_gate: bool
    reason: str = Field(min_length=10, max_length=2000)


class InviteInput(LoginInput):
    role: Literal["ADMIN", "MEMBER", "VIEWER"] = "MEMBER"


class OutcomeInput(Input):
    status: Literal["NOT_SUBMITTED", "SUBMITTED", "SHORTLISTED", "WON", "LOST"]
    actual_hours: float | None = Field(default=None, ge=0, le=100000)
    actual_cost: float | None = Field(default=None, ge=0, le=1e12)
    award_value: float | None = Field(default=None, ge=0, le=1e12)
