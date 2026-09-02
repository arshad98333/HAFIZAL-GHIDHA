import sys

from cold_chain.domain import rules_engine as _mod

sys.modules[__name__] = _mod
