from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.models import CompanyStatus, CompanyType, ContactType, LinkRole, VerificationState


class ProductTypeRead(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None
    keywords: list[str]
    pharmacopeia: list[str]
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContactRead(BaseModel):
    type: ContactType
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    telegram: str | None = None

    model_config = {"from_attributes": True}


class CompanyRead(BaseModel):
    id: int
    name: str
    company_type: CompanyType
    website: str | None
    hq_country: str | None
    certifications: list[str]
    compliance: dict
    regions_served: list[str]
    lead_time_days_range: dict | None
    moq_range: dict | None
    last_verified_at: datetime | None
    verification_source: str | None
    status: CompanyStatus
    confidence_score: float
    verification_state: VerificationState
    contacts: list[ContactRead] = []
    score: float | None = None
    score_reasons: list[str] | None = None

    model_config = {"from_attributes": True}


class SearchVendorsRequest(BaseModel):
    product_type_query: str = Field(..., min_length=2, max_length=200)
    country: str | None = None
    region: str | None = None
    certifications: list[str] = []
    role: LinkRole | None = None
    company_type: CompanyType | None = None
    status: CompanyStatus | None = CompanyStatus.ACTIVE
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=25, ge=1, le=100)


class SearchVendorsResponse(BaseModel):
    product_type: ProductTypeRead | None
    normalized_query: str
    data: list[CompanyRead]


class IngestURLRequest(BaseModel):
    source_url: HttpUrl
    source_name: str = Field(default="User Source", min_length=2, max_length=255)
    product_type_query: str = Field(..., min_length=2, max_length=200)
    role: LinkRole = LinkRole.AUTHORIZED_DISTRIBUTOR
    dry_run: bool = False

    @field_validator("source_name")
    @classmethod
    def sanitize_source_name(cls, value: str) -> str:
        return value.strip()


class IngestURLResponse(BaseModel):
    source_id: int | None
    inserted_companies: int
    updated_companies: int
    skipped_rows: int
    message: str


class VendorDetailResponse(BaseModel):
    vendor: CompanyRead
    product_types: list[ProductTypeRead]
    evidence_urls: list[str]


class VerifyVendorRequest(BaseModel):
    verification_state: VerificationState
    confidence_score: float = Field(ge=0.0, le=1.0)
    notes: str | None = Field(default=None, max_length=1000)
