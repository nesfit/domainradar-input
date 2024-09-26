from feta_prefilter.Filters.BaseFilter import FilterAction
from feta_prefilter.Filters.BaseFilter import BaseFilter


class FileBlockListFilter(BaseFilter):
    def __init__(self, filter_name:str, filter_result_action=FilterAction.DROP, filename=""):
        super().__init__(filter_name, filter_result_action)

        with open(filename) as f:
            for domain in f.readlines():
                reversed_domain = '.'.join(reversed(domain.strip().split('.')))
                self.suffix_trie.add(reversed_domain.lower())
