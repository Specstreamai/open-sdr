import logging
import re
from typing import Any
import httpx

from opensdr.enrichment.waterfall import BaseEnrichmentProvider
from opensdr.models import EmailStatus, EnrichmentResult, Lead

logger = logging.getLogger(__name__)

EMAIL_PATTERN = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"


class SpecStreamProvider(BaseEnrichmentProvider):
    """Enrichment provider that finds a lead's public email via the SpecStream Search API."""

    def __init__(self, api_key: str | None = None, timeout_seconds: float = 10.0):
        self.api_key = api_key
        self.timeout = timeout_seconds

    @property
    def name(self) -> str:
        return "specstream"

    async def enrich_lead(self, lead: Lead) -> EnrichmentResult:
        """Search the web for the lead's address on their company domain if an API key is set."""
        if not self.api_key:
            return EnrichmentResult(provider_name=self.name, found=False)

        if not lead.domain or not lead.first_name:
            return EnrichmentResult(provider_name=self.name, found=False)

        url = "https://api.specstream.ai/v1/web-search"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {
            "q": f"\"{lead.first_name} {lead.last_name}\" \"@{lead.domain}\"",
            "speed": "fast",
            "num": 10
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.get(url, params=params, headers=headers)
                if res.status_code != 200:
                    return EnrichmentResult(provider_name=self.name, found=False)

                sources = (res.json().get("data") or {}).get("sources") or []
                return self._match_lead_email(lead, sources)
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("SpecStream search failed for domain %s: %s", lead.domain, error)
            return EnrichmentResult(provider_name=self.name, found=False)

    def _match_lead_email(self, lead: Lead, sources: list[dict[str, Any]]) -> EnrichmentResult:
        """Pick the first address on the lead's domain that carries their first or last name."""
        domain = lead.domain.lower()
        first = lead.first_name.lower()
        last = lead.last_name.lower()

        for source in sources:
            text = f"{source.get('title') or ''} {source.get('snippet') or ''}"
            for candidate in re.findall(EMAIL_PATTERN, text):
                local, _, host = candidate.lower().partition("@")
                if host != domain:
                    continue
                if first in local or (last and last in local):
                    return EnrichmentResult(
                        provider_name=self.name,
                        found=True,
                        email=candidate.lower(),
                        status=EmailStatus.RISKY,
                        confidence=0.65,
                        extra_details={"source_url": source.get("url")}
                    )

        return EnrichmentResult(provider_name=self.name, found=False)
