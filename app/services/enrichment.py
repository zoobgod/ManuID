from __future__ import annotations

import json
from typing import Any

from app.config import Settings


def maybe_enrich_with_openai(raw_text: str, settings: Settings) -> dict[str, Any]:
    if not settings.enable_openai_enrichment:
        return {}

    if not settings.openai_api_key:
        return {}

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)

        prompt = (
            "Extract procurement metadata from the company text as JSON with keys: "
            "certifications (string[]), regions_served (string[]), "
            "lead_time_days_range ({min,max} or null), moq_range ({min,max,unit} or null), "
            "pharmacopeia_supported (string[]). Return JSON only.\n\n"
            f"TEXT:\n{raw_text[:4000]}"
        )

        response = client.responses.create(model=settings.openai_model, input=prompt)
        text = getattr(response, "output_text", "") or ""
        payload = json.loads(text)

        if not isinstance(payload, dict):
            return {}

        return payload
    except Exception:
        return {}
