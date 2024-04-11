from feta_prefilter.Filters.BaseFilter import BaseFilter

class FileBlockListFilter(BaseFilter):
    def __init__(self, filename=''):
        with open(filename) as f:
            self.block_domains = [l.strip() for l in f.readlines()]

    def filter(self, domains: list[str]) -> list[bool]:
        return [domain not in self.block_domains for domain in domains]
