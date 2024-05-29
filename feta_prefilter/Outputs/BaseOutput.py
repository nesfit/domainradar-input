class BaseOutput:
    def __init__(self):
        pass

    def output(self, domains: list[dict]) -> list[str]:
        raise NotImplementedError()
