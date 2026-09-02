import sys

from cold_chain.domain import simulate as _mod

sys.modules[__name__] = _mod
