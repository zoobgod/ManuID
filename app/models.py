from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CompanyType(str, enum.Enum):
    MANUFACTURER = "MANUFACTURER"
    DISTRIBUTOR = "DISTRIBUTOR"
    BOTH = "BOTH"


class CompanyStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    LIMITED = "LIMITED"
    INACTIVE = "INACTIVE"


class ContactType(str, enum.Enum):
    SALES = "SALES"
    PROCUREMENT = "PROCUREMENT"
    SUPPORT = "SUPPORT"
    GENERAL = "GENERAL"
    QA = "QA"
    REGULATORY = "REGULATORY"


class LinkRole(str, enum.Enum):
    PRIMARY_MANUFACTURER = "PRIMARY_MANUFACTURER"
    AUTHORIZED_DISTRIBUTOR = "AUTHORIZED_DISTRIBUTOR"
    RESELLER = "RESELLER"


class VerificationState(str, enum.Enum):
    UNVERIFIED = "UNVERIFIED"
    AUTO_VERIFIED = "AUTO_VERIFIED"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"


class ProductType(Base):
    __tablename__ = "product_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    pharmacopeia: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    companies: Mapped[list["CompanyProductType"]] = relationship(back_populates="product_type")


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    company_type: Mapped[CompanyType] = mapped_column(Enum(CompanyType), default=CompanyType.BOTH)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hq_country: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    locations: Mapped[list[dict]] = mapped_column(JSON, default=list)
    certifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    compliance: Mapped[dict] = mapped_column(JSON, default=dict)
    regions_served: Mapped[list[str]] = mapped_column(JSON, default=list)
    export_countries_blacklist: Mapped[list[str]] = mapped_column(JSON, default=list)
    lead_time_days_range: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    moq_range: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_source: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[CompanyStatus] = mapped_column(Enum(CompanyStatus), default=CompanyStatus.ACTIVE)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.5)
    verification_state: Mapped[VerificationState] = mapped_column(
        Enum(VerificationState), default=VerificationState.UNVERIFIED
    )
    is_authorized_distributor: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    contacts: Mapped[list["Contact"]] = relationship(back_populates="company", cascade="all, delete-orphan")
    product_links: Mapped[list["CompanyProductType"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    evidences: Mapped[list["CompanyEvidence"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    type: Mapped[ContactType] = mapped_column(Enum(ContactType), default=ContactType.GENERAL)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    telegram: Mapped[str | None] = mapped_column(String(120), nullable=True)

    company: Mapped[Company] = relationship(back_populates="contacts")


class CompanyProductType(Base):
    __tablename__ = "company_product_types"
    __table_args__ = (UniqueConstraint("product_type_id", "company_id", name="uq_pt_company"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_type_id: Mapped[int] = mapped_column(
        ForeignKey("product_types.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    role: Mapped[LinkRole] = mapped_column(Enum(LinkRole), default=LinkRole.PRIMARY_MANUFACTURER)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    product_type: Mapped[ProductType] = relationship(back_populates="companies")
    company: Mapped[Company] = relationship(back_populates="product_links")


class SourceRecord(Base):
    __tablename__ = "source_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(String(1024), index=True)
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    parser_version: Mapped[str] = mapped_column(String(40), default="1.0")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    evidences: Mapped[list["CompanyEvidence"]] = relationship(back_populates="source_record")


class CompanyEvidence(Base):
    __tablename__ = "company_evidences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"), index=True)
    source_record_id: Mapped[int] = mapped_column(
        ForeignKey("source_records.id", ondelete="CASCADE"), index=True
    )
    field_name: Mapped[str] = mapped_column(String(100))
    field_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)

    company: Mapped[Company] = relationship(back_populates="evidences")
    source_record: Mapped[SourceRecord] = relationship(back_populates="evidences")
