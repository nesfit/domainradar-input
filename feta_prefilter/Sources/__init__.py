from .FileSource import FileSource
from .ELKSource import ELKSource

source_classes = {
    'FileSource': FileSource,
    'ELKSource': ELKSource,
}
