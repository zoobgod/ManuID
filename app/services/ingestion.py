from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import phonenumbers
from bs4 import BeautifulSoup, Tag
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.config import Settings
from app.schemas import IngestURLRequest, IngestURLResponse
from app.services.enrichment import maybe_enrich_with_openai
from app.services.normalizer import normalize_product_type_query
from app.services.scraper import ScrapeError, fetch_html

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"\+?[0-9][0-9\s().-]{6,}[0-9]")

COMMON_COUNTRIES = {
    "usa": "United States",
    "united states": "United States",
    "uk": "United Kingdom",
    "united kingdom": "United Kingdom",
    "germany": "Germany",
    "france": "France",
    "italy": "Italy",
    "spain": "Spain",
    "india": "India",
    "china": "China",
    "japan": "Japan",
    "switzerland": "Switzerland",
    "netherlands": "Netherlands",
    "belgium": "Belgium",
    "singapore": "Singapore",
    "south korea": "South Korea",
    "korea": "South Korea",
}


@dataclass
class ParsedCompany:
    name: str
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    country: str | None = None
    raw_text: str = ""


@dataclass
class ParseSummary:
    companies: list[ParsedCompany]
    skipped_rows: int


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _extract_first_email(text: str) -> str | None:
    found = EMAIL_RE.findall(text)
    return found[0].lower() if found else None


def _extract_first_phone(text: str) -> str | None:
    for candidate in PHONE_RE.findall(text):
        raw = _clean_text(candidate)
        try:
            parsed = phonenumbers.parse(raw, None)
            if phonenumbers.is_possible_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException:
            continue
    return None


def _extract_country(text: str) -> str | None:
    lower = text.lower()
    for key, value in COMMON_COUNTRIES.items():
        if re.search(rf"\b{re.escape(key)}\b", lower):
            return value
    return None


def _best_website_from_tag(tag: Tag, base_url: str) -> str | None:
    anchors = tag.find_all("a", href=True)
    for a in anchors:
        href = a["href"].strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            return absolute
    return None


def _collect_candidate_from_tag(tag: Tag, base_url: str) -> ParsedCompany | None:
    if tag.name == "tr" and tag.find("th") and not tag.find("td"):
        return None

    text = _clean_text(tag.get_text(" ", strip=True))
    if len(text) < 5:
        return None

    website = _best_website_from_tag(tag, base_url)
    email = _extract_first_email(text)
    phone = _extract_first_phone(text)
    country = _extract_country(text)
    if len(text.split()) > 60 and not (website or email or phone):
        return None

    # Heuristic for company name: first segment before a separator.
    first_piece = re.split(r"\||-|,|;|\u2022", text)[0].strip()
    name = first_piece if len(first_piece) >= 3 else text[:120]
    generic_header_tokens = {"vendor", "vendors", "supplier", "suppliers", "name", "email", "country", "phone"}
    name_words = {w.lower() for w in name.split()}
    if name_words and name_words.issubset(generic_header_tokens):
        return None

    if not re.search(r"[A-Za-z]", name):
        return None

    if len(name.split()) > 12:
        name = " ".join(name.split()[:12])

    return ParsedCompany(
        name=name,
        website=website,
        email=email,
        phone=phone,
        country=country,
        raw_text=text[:5000],
    )


def _extract_from_json_ld(soup: BeautifulSoup, base_url: str) -> list[ParsedCompany]:
    items: list[ParsedCompany] = []
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts:
        content = script.string or script.get_text(strip=True)
        if not content:
            continue
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            continue

        if isinstance(payload, dict):
            payloads = [payload]
        elif isinstance(payload, list):
            payloads = payload
        else:
            continue

        for obj in payloads:
            if not isinstance(obj, dict):
                continue
            item_type = str(obj.get("@type", "")).lower()
            if "organization" not in item_type and "corporation" not in item_type:
                continue

            name = _clean_text(obj.get("name"))
            if not name:
                continue

            website = obj.get("url") or obj.get("sameAs")
            if isinstance(website, list):
                website = website[0] if website else None
            if isinstance(website, str):
                website = urljoin(base_url, website)
            else:
                website = None

            email = _clean_text(obj.get("email")) or None
            phone = _clean_text(obj.get("telephone")) or None
            country = None
            address = obj.get("address")
            if isinstance(address, dict):
                country = _clean_text(address.get("addressCountry")) or None

            items.append(
                ParsedCompany(
                    name=name,
                    website=website,
                    email=email,
                    phone=phone,
                    country=country,
                    raw_text=_clean_text(json.dumps(obj)),
                )
            )
    return items


def parse_vendor_companies(html: str, base_url: str) -> ParseSummary:
    soup = BeautifulSoup(html, "lxml")

    candidates: list[ParsedCompany] = []
    skipped_rows = 0

    candidates.extend(_extract_from_json_ld(soup, base_url))

    selector_groups = [
        "table tr",
        "ul li",
        "ol li",
        "div.vendor",
        "div.supplier",
    ]

    for selector in selector_groups:
        for tag in soup.select(selector):
            candidate = _collect_candidate_from_tag(tag, base_url)
            if candidate is None:
                skipped_rows += 1
                continue
            candidates.append(candidate)

    deduped: dict[str, ParsedCompany] = {}
    for item in candidates:
        key = (item.website or "").lower().strip()
        if not key:
            key = item.name.lower().strip()

        if not key or len(item.name) < 3:
            skipped_rows += 1
            continue

        existing = deduped.get(key)
        if not existing:
            deduped[key] = item
            continue

        # Keep richer version when duplicates are found.
        existing_fields = sum(bool(getattr(existing, f)) for f in ("website", "email", "phone", "country"))
        item_fields = sum(bool(getattr(item, f)) for f in ("website", "email", "phone", "country"))
        if item_fields > existing_fields:
            deduped[key] = item

    final_items = [x for x in deduped.values() if len(x.name) >= 3]
    return ParseSummary(companies=final_items, skipped_rows=skipped_rows)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:120] or "custom_product_type"


def _upsert_product_type(db: Session, query: str) -> models.ProductType:
    normalized = normalize_product_type_query(db, query)
    if normalized.product_type:
        return normalized.product_type

    slug = _slugify(query)
    existing = db.scalar(select(models.ProductType).where(models.ProductType.slug == slug))
    if existing:
        return existing

    product_type = models.ProductType(
        slug=slug,
        name=query.strip().title(),
        description="User-created product type from ingestion/search query",
        keywords=[query.strip().lower()],
        pharmacopeia=[],
    )
    db.add(product_type)
    db.flush()
    return product_type


def _calculate_auto_confidence(company: ParsedCompany, source_domain: str) -> float:
    score = 0.35
    if company.website:
        score += 0.2
    if company.email:
        score += 0.2
    if company.phone:
        score += 0.1
    if company.country:
        score += 0.1
    if source_domain and company.website:
        if urlparse(company.website).hostname == source_domain:
            score += 0.05
    return round(min(score, 0.95), 3)


def _get_or_create_company(db: Session, parsed: ParsedCompany) -> tuple[models.Company, bool, bool]:
    company: models.Company | None = None
    if parsed.website:
        company = db.scalar(select(models.Company).where(models.Company.website == parsed.website))

    if not company:
        company = db.scalar(select(models.Company).where(models.Company.name == parsed.name))

    created = False
    if not company:
        company = models.Company(
            name=parsed.name,
            company_type=models.CompanyType.BOTH,
            website=parsed.website,
            hq_country=parsed.country,
            certifications=[],
            compliance={"pharmacopeia_supported": []},
            regions_served=[],
            status=models.CompanyStatus.ACTIVE,
            confidence_score=0.4,
            verification_state=models.VerificationState.UNVERIFIED,
        )
        db.add(company)
        db.flush()
        created = True

    changed = False

    if parsed.website and not company.website:
        company.website = parsed.website
        changed = True

    if parsed.country and not company.hq_country:
        company.hq_country = parsed.country
        changed = True

    # Maintain one primary general contact in MVP.
    primary_contact = company.contacts[0] if company.contacts else None
    if not primary_contact and (parsed.email or parsed.phone):
        primary_contact = models.Contact(type=models.ContactType.GENERAL, email=parsed.email, phone=parsed.phone)
        company.contacts.append(primary_contact)
        changed = True
    elif primary_contact:
        if parsed.email and not primary_contact.email:
            primary_contact.email = parsed.email
            changed = True
        if parsed.phone and not primary_contact.phone:
            primary_contact.phone = parsed.phone
            changed = True

    return company, created, changed


def _upsert_product_link(
    db: Session,
    product_type_id: int,
    company_id: int,
    role: models.LinkRole,
) -> None:
    existing = db.scalar(
        select(models.CompanyProductType).where(
            models.CompanyProductType.product_type_id == product_type_id,
            models.CompanyProductType.company_id == company_id,
        )
    )
    if not existing:
        db.add(
            models.CompanyProductType(
                product_type_id=product_type_id,
                company_id=company_id,
                role=role,
                notes="Added by ingestion pipeline",
            )
        )


def _add_evidence(
    db: Session,
    company: models.Company,
    source: models.SourceRecord,
    parsed: ParsedCompany,
    confidence: float,
) -> None:
    evidence_pairs = {
        "name": parsed.name,
        "website": parsed.website,
        "email": parsed.email,
        "phone": parsed.phone,
        "country": parsed.country,
    }

    for field_name, field_value in evidence_pairs.items():
        if not field_value:
            continue
        db.add(
            models.CompanyEvidence(
                company_id=company.id,
                source_record_id=source.id,
                field_name=field_name,
                field_value=str(field_value),
                confidence=confidence,
            )
        )


def _apply_enrichment(company: models.Company, parsed: ParsedCompany, settings: Settings) -> None:
    enrichment = maybe_enrich_with_openai(parsed.raw_text, settings)
    if not enrichment:
        return

    certifications = enrichment.get("certifications")
    if isinstance(certifications, list):
        merged = sorted({*(company.certifications or []), *[str(x).strip() for x in certifications if x]})
        company.certifications = merged

    regions = enrichment.get("regions_served")
    if isinstance(regions, list):
        company.regions_served = sorted({*(company.regions_served or []), *[str(x).strip() for x in regions if x]})

    pharma_supported = enrichment.get("pharmacopeia_supported")
    if isinstance(pharma_supported, list):
        compliance = dict(company.compliance or {})
        compliance["pharmacopeia_supported"] = sorted(
            {*(compliance.get("pharmacopeia_supported", [])), *[str(x).strip() for x in pharma_supported if x]}
        )
        company.compliance = compliance

    lead_time = enrichment.get("lead_time_days_range")
    if isinstance(lead_time, dict):
        company.lead_time_days_range = lead_time

    moq = enrichment.get("moq_range")
    if isinstance(moq, dict):
        company.moq_range = moq


async def ingest_from_url(db: Session, settings: Settings, payload: IngestURLRequest) -> IngestURLResponse:
    try:
        scrape_result = await fetch_html(str(payload.source_url), settings)
    except ScrapeError as exc:
        return IngestURLResponse(
            source_id=None,
            inserted_companies=0,
            updated_companies=0,
            skipped_rows=0,
            message=str(exc),
        )

    parse_summary = parse_vendor_companies(scrape_result.html, scrape_result.final_url)

    if payload.dry_run:
        return IngestURLResponse(
            source_id=None,
            inserted_companies=len(parse_summary.companies),
            updated_companies=0,
            skipped_rows=parse_summary.skipped_rows,
            message="Dry run completed. No database changes were made.",
        )

    source = models.SourceRecord(
        source_name=payload.source_name,
        source_url=scrape_result.final_url,
        http_status=scrape_result.status_code,
        content_hash=scrape_result.content_hash,
        parser_version="1.0",
    )
    db.add(source)
    db.flush()

    product_type = _upsert_product_type(db, payload.product_type_query)

    inserted = 0
    updated = 0
    source_domain = urlparse(scrape_result.final_url).hostname or ""

    for parsed in parse_summary.companies:
        company, created, changed = _get_or_create_company(db, parsed)
        _upsert_product_link(db, product_type.id, company.id, payload.role)

        confidence = _calculate_auto_confidence(parsed, source_domain)
        company.confidence_score = max(company.confidence_score, confidence)
        company.last_verified_at = source.retrieved_at
        company.verification_source = scrape_result.final_url
        company.verification_state = models.VerificationState.AUTO_VERIFIED

        _apply_enrichment(company, parsed, settings)
        _add_evidence(db, company, source, parsed, confidence)

        if created:
            inserted += 1
        elif changed:
            updated += 1

    db.commit()

    return IngestURLResponse(
        source_id=source.id,
        inserted_companies=inserted,
        updated_companies=updated,
        skipped_rows=parse_summary.skipped_rows,
        message=f"Ingestion complete: {inserted + updated} companies processed.",
    )
