from .SimpleFileSource import SimpleFileSource
from .StreamingFileSource import StreamingFileSource
from .ELKSource import ELKSource

source_classes = {
    'SimpleFileSource': SimpleFileSource,
    'StreamingFileSource': StreamingFileSource,
    'ELKSource': ELKSource,
}
