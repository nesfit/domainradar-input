import random
import time

from feta_prefilter.Sources.BaseSource import BaseSource

MS = 1_000_000


class StreamingFileSource(BaseSource):

    def __init__(self, filename: str = '', delay_ms: int = 1000, jitter_ms: int = 100,
                 entries_per_produce: int = 1, entries_per_produce_jitter: int = 0, repeat: bool = False):
        self.file = open(filename, 'r')
        self.delay = delay_ms - jitter_ms // 2
        self.jitter = jitter_ms
        self.repeat = repeat and self.file.seekable()
        self.entries_per_produce = entries_per_produce
        self.entries_per_produce_jitter = entries_per_produce_jitter

        self._rnd = random.Random()
        self._next = 0
        self._make_next()
        self._ended = False

    def __del__(self):
        if hasattr(self, 'file') and self.file is not None and not self.file.closed:
            self.file.close()

    def collect(self) -> list[str]:
        if not self._ended and time.monotonic_ns() > self._next:
            to_produce = []

            if self.entries_per_produce_jitter > 0:
                num_entries = max(1, self.entries_per_produce - (self.entries_per_produce_jitter // 2) +
                                  self._rnd.randint(0, self.entries_per_produce_jitter))
            else:
                num_entries = self.entries_per_produce

            for _ in range(num_entries):
                line = self.file.readline()
                if not line:
                    if self.repeat:
                        self.file.seek(0)
                        line = self.file.readline()
                    else:
                        self._ended = True
                        self.file.close()
                        return []
                to_produce.append(line.strip())

            self._make_next()
            return to_produce

        return []

    def _make_next(self):
        self._next = time.monotonic_ns() + self.delay * MS + self._rnd.randint(0, self.jitter * MS)
