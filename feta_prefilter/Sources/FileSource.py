from feta_prefilter.Sources.BaseSource import BaseSource

class FileSource(BaseSource):
    def __init__(self, filename=''):
        with open(filename) as f:
            self.domains = [l.strip() for l in f.readlines()]

    def collect(self) -> list[str]:
        return self.domains
