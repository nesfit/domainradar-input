from .FileBlockListFilter import FileBlockListFilter
from .MISPFilter import MISPFilter
from .StarFilter import StarFilter

filter_classes = {
    'FileBlockListFilter': FileBlockListFilter,
    'MISPFilter': MISPFilter,
    'StarFilter': StarFilter,
}
