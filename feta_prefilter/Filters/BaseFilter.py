class BaseFilter:
    def __init__(self):
        pass

    def filter(self, domains: list[str]) -> list[bool]:
        raise NotImplementedError("Doesn't implement filter method")
