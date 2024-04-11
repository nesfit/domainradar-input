class BaseSource:
    def __init__(self):
        pass

    def collect(self) -> list[str]:
        raise NotImplementedError()
