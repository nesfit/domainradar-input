import pygtrie

from feta_prefilter.Filters.BaseFilter import FilterAction
from feta_prefilter.Filters.BaseFilter import BaseFilter


class FileBlockListFilter(BaseFilter):
    def __init__(self, filter_name:str, filter_result_action=FilterAction.DROP, filename=""):
        super().__init__(filter_name, filter_result_action)

        self.suffix_trie = pygtrie.PrefixSet(factory=pygtrie.StringTrie, separator='.')

        with open(filename) as f:
            for domain in f.readlines():
                reversed_domain = '.'.join(reversed(domain.strip().split('.')))
                self.suffix_trie.add(reversed_domain)

    def filter(self, domains: list[str]) -> list[FilterAction]:
        res = []
        for domain in domains:
            reversed_domain = '.'.join(reversed(domain.strip().split('.')))
            if reversed_domain in self.suffix_trie:
                res.append(self.filter_result_action)
            else:
                res.append(FilterAction.PASS)
        return res
