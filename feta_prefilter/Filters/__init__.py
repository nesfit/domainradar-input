from .FileBlockListFilter import FileBlockListFilter
from .MISPFilter import MISPFilter
from .StarFilter import StarFilter
from .RandomDROPFilter import RandomDROPFilter

filter_classes = {
    'FileBlockListFilter': FileBlockListFilter,
    'MISPFilter': MISPFilter,
    'StarFilter': StarFilter,
    'RandomDROPFilter': RandomDROPFilter,
}
