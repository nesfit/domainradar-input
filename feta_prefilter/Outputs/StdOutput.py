import logging
from datetime import datetime

from feta_prefilter.Outputs.BaseOutput import BaseOutput

class StdOutput(BaseOutput):
    def __init__(self):
        # cache for already outputted domains with timestamps for clearing
        self._cache = {}

    def output(self, domains: list[dict]) -> list[str]:
        ret = []
        logging.info("START stdoutput")
        for domain_info in domains:
            domain = domain_info["domain"]
            domain_data = domain_info["f_results"]
            if domain not in self._cache:
                self._cache[domain] = datetime.utcnow()
                ret.append(domain)
                print(domain, domain_data)
        logging.info("FINISH stdoutput")
        return ret

