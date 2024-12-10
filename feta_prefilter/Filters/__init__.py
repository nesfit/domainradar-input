from .FileBlockListFilter import FileBlockListFilter
from .MISPFilter import MISPFilter
from .ValidDomainFilter import ValidDomainFilter
from .RandomDROPFilter import RandomDROPFilter
from .CustomPostgresFilter import CustomPostgresFilter

filter_classes = {
    'FileBlockListFilter': FileBlockListFilter,
    'MISPFilter': MISPFilter,
    'ValidDomainFilter': ValidDomainFilter,
    'RandomDROPFilter': RandomDROPFilter,
    'CustomPostgresFilter': CustomPostgresFilter,
}
