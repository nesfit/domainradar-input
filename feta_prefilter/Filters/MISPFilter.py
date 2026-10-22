from urllib.parse import urlparse

from feta_prefilter.Filters.BaseFilter import FilterAction
from feta_prefilter.Filters.BaseFilter import BaseFilter
from feta_prefilter.utils import misp_client

class MISPFilter(BaseFilter):
    def __init__(
        self,
        filter_name: str,
        misp_url: str,
        misp_key: str,
        misp_feed_eventids: list[int],
        misp_ssl: bool | str = True,
        misp_timeout_s: float = 30.0,
        filter_result_action=FilterAction.DROP,
    ):
        super().__init__(filter_name, filter_result_action)

        # a hanging instance must not block the block initialisation forever
        self.misp = misp_client(misp_url, misp_key, misp_ssl, timeout=misp_timeout_s)
        attributes = self.misp.search(
            controller="attributes", to_ids=True, eventid=misp_feed_eventids, pythonify=True
        )

        for attr in attributes:
            if attr.type == "domain":
                reversed_domain = '.'.join(reversed(attr.value.strip().split('.')))
            elif attr.type == "url":
                domain = urlparse(attr.value).netloc
                reversed_domain = '.'.join(reversed(domain.strip().split('.')))
            else:
                continue

            self.suffix_trie.add(reversed_domain.lower())
