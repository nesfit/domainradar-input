from feta_prefilter.Filters.BaseFilter import FilterAction
from feta_prefilter.Filters.BaseFilter import BaseFilter


class FileBlockListFilter(BaseFilter):
    def __init__(self, filter_result_action=FilterAction.DROP, filename=""):
        super().__init__(filter_result_action)

        with open(filename) as f:
            self.block_domains = [l.strip() for l in f.readlines()]

    def filter(self, domains: list[str]) -> list[FilterAction]:
        res = []
        for domain in domains:
            if domain in self.block_domains:
                res.append(self.filter_result_action)
            else:
                res.append(FilterAction.PASS)
        return res
