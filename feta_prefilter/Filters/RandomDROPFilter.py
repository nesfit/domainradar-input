import random

from feta_prefilter.Filters.BaseFilter import FilterAction
from feta_prefilter.Filters.BaseFilter import BaseFilter


class RandomDROPFilter(BaseFilter):
    def __init__(self, filter_name:str, filter_result_action=FilterAction.DROP, drop_rate: float=50.0):
        super().__init__(filter_name, filter_result_action)
        self.drop_rate = drop_rate
        random.seed()

    def filter(self, domains: list[str]) -> list[FilterAction]:
        res = []
        for domain in domains:
            if random.random()*100 <= self.drop_rate:
                res.append(self.filter_result_action)
            else:
                res.append(FilterAction.PASS)
        return res
