class BaseOutput:
    def __init__(self):
        pass

    def output(self, domains: list[str]) -> list[str]:
        raise NotImplementedError()
