from enum import IntEnum

import pygtrie

class FilterAction(IntEnum):
    PASS = 0
    DROP = 1
    STORE = 2

class BaseFilter:
    def __init__(self, filter_name: str, filter_result_action=FilterAction.DROP):
        self.filter_name = filter_name
        self.filter_result_action = filter_result_action

        self.suffix_trie = pygtrie.PrefixSet(factory=pygtrie.StringTrie, separator='.')

    def filter(self, domains: list[str]) -> list[FilterAction]:
        res = []
        for domain in domains:
            reversed_domain = '.'.join(reversed(domain.strip().split('.')))
            if reversed_domain.lower() in self.suffix_trie:
                res.append(self.filter_result_action)
            else:
                res.append(FilterAction.PASS)
        return res
