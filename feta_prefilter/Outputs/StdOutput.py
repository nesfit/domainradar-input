import logging
from datetime import datetime

from feta_prefilter.Outputs.BaseOutput import BaseOutput

class StdOutput(BaseOutput):
    def __init__(self):
        # cache for already outputted domains with timestamps for clearing
        self._cache = {}

    def output(self, domains: list[str]) -> list[str]:
        ret = []
        logging.info("START stdoutput")
        for domain in domains:
            if domain not in self._cache:
                self._cache[domain] = datetime.utcnow()
                ret.append(domain)
                print(domain)
        logging.info("FINISH stdoutput")
        return ret

