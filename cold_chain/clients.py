import sys

from cold_chain.adapters import clients as _mod

sys.modules[__name__] = _mod
