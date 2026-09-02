import sys

from cold_chain.adapters import agentic_eval as _mod

sys.modules[__name__] = _mod
