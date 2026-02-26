from __future__ import annotations

from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session, joinedload

from app import models
from app.schemas import SearchVendorsRequest, VerifyVendorRequest
from app.services.normalizer import normalize_product_type_query
from app.services.scoring import score_company


def list_product_types(
    db: Session,
    q: str | None = None,
    pharmacopeia: str | None = None,
    limit: int = 25,
) -> list[models.ProductType]:
    stmt = select(models.ProductType)

    if q:
        pattern = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(models.ProductType.name).like(pattern)
            | func.lower(models.ProductType.slug).like(pattern)
        )

    if pharmacopeia:
        marker = pharmacopeia.strip().upper()
        # SQLite JSON does not support contains uniformly without extension.
        # Filter in-memory after query for portable behavior.
        results = db.scalars(stmt.limit(limit * 3)).all()
        return [x for x in results if marker in {p.upper() for p in (x.pharmacopeia or [])}][:limit]

    return db.scalars(stmt.order_by(models.ProductType.name.asc()).limit(limit)).all()


def search_vendors(
    db: Session,
    payload: SearchVendorsRequest,
) -> tuple[models.ProductType | None, str, list[tuple[models.Company, float, list[str]]]]:
    normalization = normalize_product_type_query(db, payload.product_type_query)

    stmt = (
        select(models.Company, models.CompanyProductType.role)
        .join(models.CompanyProductType, models.CompanyProductType.company_id == models.Company.id)
        .join(models.ProductType, models.ProductType.id == models.CompanyProductType.product_type_id)
        .options(joinedload(models.Company.contacts))
    )

    if normalization.product_type:
        stmt = stmt.where(models.CompanyProductType.product_type_id == normalization.product_type.id)
    else:
        search_pattern = f"%{payload.product_type_query.strip().lower()}%"
        stmt = stmt.where(
            func.lower(models.ProductType.name).like(search_pattern)
            | func.lower(models.ProductType.slug).like(search_pattern)
        )

    if payload.country:
        stmt = stmt.where(func.lower(models.Company.hq_country) == payload.country.lower())

    if payload.company_type:
        stmt = stmt.where(models.Company.company_type == payload.company_type)

    if payload.status:
        stmt = stmt.where(models.Company.status == payload.status)

    if payload.min_confidence > 0:
        stmt = stmt.where(models.Company.confidence_score >= payload.min_confidence)

    rows = db.execute(stmt).unique().all()

    filtered: list[tuple[models.Company, models.LinkRole | None, float, list[str]]] = []
    for company, role in rows:
        if payload.region and payload.region not in (company.regions_served or []):
            continue

        if payload.role and role != payload.role:
            continue

        if payload.certifications:
            company_certs = {x.lower() for x in company.certifications or []}
            req_certs = {x.lower() for x in payload.certifications}
            if not req_certs.issubset(company_certs):
                continue

        score, reasons = score_company(company, payload, role)
        filtered.append((company, role, score, reasons))

    filtered.sort(key=lambda item: item[2], reverse=True)

    results = [(company, score, reasons) for company, _role, score, reasons in filtered[: payload.limit]]
    return normalization.product_type, normalization.normalized_query, results


def get_vendor_detail(db: Session, vendor_id: int) -> tuple[models.Company | None, list[models.ProductType], list[str]]:
    company = db.scalar(
        select(models.Company)
        .where(models.Company.id == vendor_id)
        .options(joinedload(models.Company.contacts), joinedload(models.Company.product_links))
    )
    if not company:
        return None, [], []

    product_types = db.scalars(
        select(models.ProductType)
        .join(models.CompanyProductType, models.CompanyProductType.product_type_id == models.ProductType.id)
        .where(models.CompanyProductType.company_id == vendor_id)
    ).all()

    evidence_urls = db.scalars(
        select(distinct(models.SourceRecord.source_url))
        .join(models.CompanyEvidence, models.CompanyEvidence.source_record_id == models.SourceRecord.id)
        .where(models.CompanyEvidence.company_id == vendor_id)
    ).all()

    return company, product_types, evidence_urls


def verify_vendor(
    db: Session,
    vendor_id: int,
    payload: VerifyVendorRequest,
) -> models.Company | None:
    company = db.get(models.Company, vendor_id)
    if not company:
        return None

    company.verification_state = payload.verification_state
    company.confidence_score = payload.confidence_score
    if payload.notes:
        company.verification_source = (company.verification_source or "") + f" | review: {payload.notes}"

    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def seed_source_catalog(db: Session, sources: list[dict[str, Any]]) -> None:
    if not sources:
        return

    existing = set(db.scalars(select(models.SourceRecord.source_url)).all())
    for source in sources:
        url = str(source.get("url", "")).strip()
        if not url or url in existing:
            continue
        db.add(
            models.SourceRecord(
                source_name=source.get("name", "Catalog Source"),
                source_url=url,
                parser_version="catalog",
            )
        )
    db.commit()
