from __future__ import annotations

from datetime import datetime, timezone

from app import models
from app.schemas import SearchVendorsRequest


def _freshness_score(last_verified_at: datetime | None) -> tuple[float, str]:
    if not last_verified_at:
        return 0.2, "No recent verification timestamp"

    timestamp = last_verified_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    age_days = (datetime.now(timezone.utc) - timestamp).days
    if age_days <= 30:
        return 1.0, "Verified in last 30 days"
    if age_days <= 90:
        return 0.8, "Verified in last 90 days"
    if age_days <= 180:
        return 0.6, "Verified in last 180 days"
    if age_days <= 365:
        return 0.4, "Verified in last 1 year"
    return 0.2, "Verification is older than 1 year"


def _compliance_coverage(company: models.Company) -> tuple[float, str]:
    supported = (company.compliance or {}).get("pharmacopeia_supported", [])
    if not supported:
        return 0.3, "No pharmacopeia support listed"
    return min(1.0, 0.35 + 0.1 * len(supported)), f"Supports {len(supported)} pharmacopeia standard(s)"


def _certification_match(company: models.Company, filters: list[str]) -> tuple[float, str]:
    if not filters:
        return 0.7, "No certification filter requested"

    company_certs = {x.lower() for x in company.certifications or []}
    requested = {x.lower() for x in filters}
    matched = company_certs & requested
    if not matched:
        return 0.0, "Certification filter not matched"

    ratio = len(matched) / len(requested)
    return ratio, f"Matched certifications: {', '.join(sorted(matched))}"


def score_company(
    company: models.Company,
    request: SearchVendorsRequest,
    matched_role: models.LinkRole | None,
) -> tuple[float, list[str]]:
    reasons: list[str] = []

    freshness, freshness_reason = _freshness_score(company.last_verified_at)
    reasons.append(freshness_reason)

    compliance, compliance_reason = _compliance_coverage(company)
    reasons.append(compliance_reason)

    cert_score, cert_reason = _certification_match(company, request.certifications)
    reasons.append(cert_reason)

    confidence = max(0.0, min(company.confidence_score, 1.0))
    reasons.append(f"Confidence score {confidence:.2f}")

    role_bonus = 0.0
    if request.role and matched_role == request.role:
        role_bonus = 1.0
        reasons.append(f"Role matched requested: {request.role.value}")
    elif request.role:
        reasons.append("Role differs from requested")

    status_score = 1.0 if company.status == models.CompanyStatus.ACTIVE else 0.5
    if company.status == models.CompanyStatus.INACTIVE:
        status_score = 0.1

    total = (
        0.32 * confidence
        + 0.24 * freshness
        + 0.2 * compliance
        + 0.14 * cert_score
        + 0.06 * role_bonus
        + 0.04 * status_score
    )

    return round(total, 4), reasons
