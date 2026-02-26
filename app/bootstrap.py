from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models

DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_json(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def seed_default_product_types(db: Session) -> None:
    if db.scalar(select(models.ProductType.id).limit(1)):
        return

    for item in _load_json("default_product_types.json"):
        db.add(
            models.ProductType(
                slug=item["slug"],
                name=item["name"],
                description=item.get("description"),
                keywords=item.get("keywords", []),
                pharmacopeia=item.get("pharmacopeia", []),
            )
        )

    db.commit()


def seed_default_companies(db: Session) -> None:
    if db.scalar(select(models.Company.id).limit(1)):
        return

    product_map = {
        p.slug: p
        for p in db.scalars(select(models.ProductType)).all()
    }

    for entry in _load_json("default_companies.json"):
        company = models.Company(
            name=entry["name"],
            company_type=models.CompanyType(entry.get("company_type", "BOTH")),
            website=entry.get("website"),
            hq_country=entry.get("hq_country"),
            certifications=entry.get("certifications", []),
            compliance=entry.get("compliance", {}),
            regions_served=entry.get("regions_served", []),
            lead_time_days_range=entry.get("lead_time_days_range"),
            moq_range=entry.get("moq_range"),
            confidence_score=float(entry.get("confidence_score", 0.5)),
            verification_source=entry.get("verification_source"),
            status=models.CompanyStatus(entry.get("status", "ACTIVE")),
            verification_state=models.VerificationState(entry.get("verification_state", "UNVERIFIED")),
            last_verified_at=datetime.now(timezone.utc),
        )
        db.add(company)
        db.flush()

        for contact in entry.get("contacts", []):
            db.add(
                models.Contact(
                    company_id=company.id,
                    type=models.ContactType(contact.get("type", "GENERAL")),
                    name=contact.get("name"),
                    email=contact.get("email"),
                    phone=contact.get("phone"),
                    whatsapp=contact.get("whatsapp"),
                    telegram=contact.get("telegram"),
                )
            )

        for slug in entry.get("product_type_slugs", []):
            product = product_map.get(slug)
            if not product:
                continue
            db.add(
                models.CompanyProductType(
                    company_id=company.id,
                    product_type_id=product.id,
                    role=models.LinkRole.PRIMARY_MANUFACTURER,
                    notes="Seed data",
                )
            )

    db.commit()


def load_source_catalog() -> list[dict]:
    return _load_json("source_catalog.json")
