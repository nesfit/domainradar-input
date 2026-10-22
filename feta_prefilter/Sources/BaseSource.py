from collections.abc import Iterable


class BaseSource:
    # Optional provenance of everything this source yields. It is a block-level key of the
    # source configuration (``{"type": ..., "args": [], "kwargs": {}, "origin": {...}}``)
    # and is attached by ``main.create_app`` after the constructor, so constructors do not
    # have to change and existing configurations keep working without it.
    origin: dict | None = None

    def __init__(self):
        pass

    def collect(self) -> Iterable[str]:
        raise NotImplementedError()

    def collect_with_origin(self) -> Iterable[tuple[str, dict | None]]:
        """Yield ``(domain, origin)`` pairs; origin may be ``None`` when unknown."""
        for domain in self.collect() or []:
            yield domain, self.origin
