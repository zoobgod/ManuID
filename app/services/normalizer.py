from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app import models


@dataclass
class NormalizationResult:
    product_type: models.ProductType | None
    normalized_query: str


def _tokenize(value: str) -> list[str]:
    return [x for x in re.split(r"[^a-zA-Z0-9]+", value.lower()) if x]


def normalize_product_type_query(db: Session, query: str) -> NormalizationResult:
    clean_query = query.strip()
    if not clean_query:
        return NormalizationResult(product_type=None, normalized_query=query)

    product_types = db.query(models.ProductType).all()
    if not product_types:
        return NormalizationResult(product_type=None, normalized_query=clean_query)

    query_tokens = set(_tokenize(clean_query))

    best_item: models.ProductType | None = None
    best_score = 0.0

    for item in product_types:
        candidates = [item.name, item.slug, *(item.keywords or [])]
        item_score = 0.0

        for candidate in candidates:
            ratio = difflib.SequenceMatcher(a=clean_query.lower(), b=candidate.lower()).ratio()
            candidate_tokens = set(_tokenize(candidate))
            overlap = len(query_tokens & candidate_tokens) / max(len(query_tokens), 1)
            item_score = max(item_score, 0.55 * ratio + 0.45 * overlap)

        if item_score > best_score:
            best_score = item_score
            best_item = item

    if best_item and best_score >= 0.45:
        return NormalizationResult(product_type=best_item, normalized_query=best_item.name)

    return NormalizationResult(product_type=None, normalized_query=clean_query)
