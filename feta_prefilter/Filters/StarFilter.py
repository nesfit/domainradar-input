from feta_prefilter.Filters.BaseFilter import FilterAction
from feta_prefilter.Filters.BaseFilter import BaseFilter


class StarFilter(BaseFilter):
    def __init__(self, filter_name:str, filter_result_action=FilterAction.DROP):
        super().__init__(filter_name, filter_result_action)

    def filter(self, domains: list[str]) -> list[FilterAction]:
        res = []
        for domain in domains:
            if '*' in domain:
                res.append(self.filter_result_action)
            else:
                res.append(FilterAction.PASS)
        return res
