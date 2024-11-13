from .SimpleFileSource import SimpleFileSource
from .StreamingFileSource import StreamingFileSource
from .ELKSource import ELKSource
from .CesnetELKSource import CesnetELKSource
from .MISPSource import MISPSource

source_classes = {
    'SimpleFileSource': SimpleFileSource,
    'StreamingFileSource': StreamingFileSource,
    'ELKSource': ELKSource,
    'CesnetELKSource': CesnetELKSource,
    'MISPSource': MISPSource,
}
