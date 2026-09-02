import sys

from cold_chain.observability import telemetry as _mod

sys.modules[__name__] = _mod
