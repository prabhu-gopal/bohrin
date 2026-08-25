"""``--target``: declare the intended policy family without a checkpoint (docs/05 §3).

Most users know what they plan to train long before they have a checkpoint to point at.
``--target pi0`` unlocks exactly the checks that depend on the *architecture* rather than
on trained constants — chiefly ``policy_data.missing_proprio``, which catches π0 silently
zero-filling a state the dataset never recorded.

Deliberately narrow: the returned profile carries **only** the family. Shape and
normalization fields stay ``None``, so the detectors that need real constants stay silent
rather than comparing against invented ones.
"""

from __future__ import annotations

from bohrin.ir.schema import PolicyFamily, PolicyProfile

#: Accepted ``--target`` values → family. Aliases included because these names are typed
#: by hand and the hyphenation varies in the wild.
_TARGETS: dict[str, PolicyFamily] = {
    "bc": PolicyFamily.BC_MLP,
    "bc_mlp": PolicyFamily.BC_MLP,
    "act": PolicyFamily.ACT,
    "diffusion": PolicyFamily.DIFFUSION,
    "diffusion_policy": PolicyFamily.DIFFUSION,
    "openvla": PolicyFamily.VLA_OPENVLA,
    "pi0": PolicyFamily.VLA_PI0,
    "pi-0": PolicyFamily.VLA_PI0,
    "octo": PolicyFamily.OCTO,
}


def target_families() -> tuple[str, ...]:
    """Every accepted ``--target`` spelling, for the CLI's help text and validation."""
    return tuple(sorted(_TARGETS))


class UnknownTargetError(ValueError):
    """Raised for a ``--target`` value we do not recognize."""

    def __init__(self, value: str) -> None:
        # List the *accepted spellings*, not the enum names: a user who copied
        # "vla_pi0" out of this message would hit the same error again.
        options = ", ".join(target_families())
        super().__init__(f"unknown --target {value!r}. Accepted values: {options}")


def profile_for_target(value: str) -> PolicyProfile:
    """A family-only :class:`PolicyProfile` for ``value``.

    Raises :class:`UnknownTargetError` rather than falling back to ``UNKNOWN``: a silent
    fallback would make ``--target typo`` behave exactly like passing nothing.
    """
    family = _TARGETS.get(value.strip().lower())
    if family is None:
        raise UnknownTargetError(value)
    return PolicyProfile(family=family)
