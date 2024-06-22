import logging
from datetime import datetime

from feta_prefilter.Outputs.BaseOutput import BaseOutput

logger = logging.getLogger(__name__)

class StdOutput(BaseOutput):
    def __init__(self):
        # cache for already outputted domains with timestamps for clearing
        # TODO this cache will grow infinitely, fix?
        self._cache = {}

    def output(self, domains: list[dict]) -> list[str]:
        ret = []
        logger.info("START stdoutput")
        for domain_info in domains:
            domain = domain_info["domain"]
            domain_data = domain_info["f_results"]
            if domain not in self._cache:
                self._cache[domain] = datetime.utcnow()
                ret.append(domain)
                print(domain, domain_data)
        logger.info("FINISH stdoutput")
        return ret
