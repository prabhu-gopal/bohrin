"""Optional checkpoint parsing — the ``--policy`` seam (docs/03 §6).

Reads checkpoint *metadata* only; never executes a model. Everything here is inert unless
the user passes ``--policy``.
"""

from bohrin.policy.loader import UnreadablePolicyError, load_policy_profile

__all__ = ["UnreadablePolicyError", "load_policy_profile"]
