from enum import IntEnum

class FilterAction(IntEnum):
    PASS = 0
    DROP = 1
    STORE = 2

class BaseFilter:
    def __init__(self, filter_name: str, filter_result_action=FilterAction.DROP):
        self.filter_name = filter_name
        self.filter_result_action = filter_result_action

    def filter(self, domains: list[str]) -> list[FilterAction]:
        raise NotImplementedError("Doesn't implement filter method")
