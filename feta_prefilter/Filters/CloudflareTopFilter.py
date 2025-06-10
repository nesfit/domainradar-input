import logging
import time
from validators import country_code

import requests

from feta_prefilter.Filters.BaseFilter import BaseFilter, FilterAction

logger = logging.getLogger(__name__)


class CloudflareTopFilter(BaseFilter):
    """Filter using Cloudflare Radar Top domains."""

    def __init__(
            self,
            filter_name: str,
            api_token: str,  # Cloudflare API token for authentication
            top_n: int = 50,  # Number of top domains to filter, defaults to top 50
            cache_time_s: int = 86400,  # How often to refresh the top N list, defaults to 1 day
            location: str | None = None,  # ISO Alpha-2 code of the target country, defaults to None = worldwide
            filter_result_action: FilterAction = FilterAction.DROP,
    ):
        super().__init__(filter_name, filter_result_action)
        assert api_token != "", "api_token must not be empty"
        assert top_n > 0, "top_n must be greater than 0"
        assert cache_time_s >= 0, "cache_time_s must be a non-negative time in seconds"
        if location is not None:
            assert country_code(location, iso_format='alpha2',
                                ignore_case=True), "location must be a valid ISO 3166 alpha-2 country code"

        self.api_token = api_token
        self.top_n = top_n
        self.cache_time = cache_time_s
        self.location = location
        self._last_fetch = 0.0
        self._fetch_domains()

    def _fetch_domains(self) -> None:
        """Fetch top domains from Cloudflare Radar API and populate the trie."""
        headers = {"Authorization": f"Bearer {self.api_token}"}
        url = "https://api.cloudflare.com/client/v4/radar/ranking/top"
        params = {"limit": self.top_n}
        if self.location:
            params["location"] = self.location
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            domains = []
            result = data.get("result", {})
            top_domains = result.get("top_0", [])
            for item in top_domains:
                domain = item.get("domain")
                if domain:
                    domains.append(domain)
            if domains:
                self.suffix_trie.clear()
                for domain in domains:
                    reversed_domain = ".".join(reversed(domain.strip().split(".")))
                    self.suffix_trie.add(reversed_domain.lower())
                self._last_fetch = time.time()
                logger.info("Loaded %d domains from Cloudflare Radar", len(domains))
        except Exception as e:  # pylint: disable=broad-except
            logger.exception("Failed to fetch domains from Cloudflare Radar", exc_info=e)

    def _ensure_fresh(self) -> None:
        if time.time() - self._last_fetch > self.cache_time:
            self._fetch_domains()

    def filter(self, domains: list[str]) -> list[FilterAction]:
        self._ensure_fresh()
        return super().filter(domains)
