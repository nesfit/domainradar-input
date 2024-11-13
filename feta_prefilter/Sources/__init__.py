from .SimpleFileSource import SimpleFileSource
from .StreamingFileSource import StreamingFileSource
from .ELKSource import ELKSource
from .CesnetELKSource import CesnetELKSource

source_classes = {
    'SimpleFileSource': SimpleFileSource,
    'StreamingFileSource': StreamingFileSource,
    'ELKSource': ELKSource,
    'CesnetELKSource': CesnetELKSource,
}
