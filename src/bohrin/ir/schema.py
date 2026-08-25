"""The frozen, dataset-wide type description and the shared enums (docs/03 §2, §4–§6).

These objects are *contracts*: adapters produce them, detectors and the report consume
them. They are immutable by construction (frozen dataclasses / frozen pydantic models) so
a detector can never mutate what another detector reads. Enums are string-valued so they
serialize into JSON reports as stable, human-readable tokens.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from bohrin._compat import StrEnum


class Severity(StrEnum):
    """Ordered finding severity. Order matters for ranking and ``--fail-on`` gating."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @property
    def rank(self) -> int:
        """Monotonic rank (INFO=0 … HIGH=3) for comparison and sorting."""
        return _SEVERITY_RANK[self]


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
}


class Family(StrEnum):
    """The eleven detector families (docs/02 §4.2)."""

    COVERAGE = "COVERAGE"
    INTEGRITY = "INTEGRITY"
    STATS = "STATS"
    SMOOTHNESS = "SMOOTHNESS"
    TEMPORAL = "TEMPORAL"
    DYNAMICS = "DYNAMICS"
    CAUSAL = "CAUSAL"
    CONSISTENCY = "CONSISTENCY"
    MULTIMODALITY = "MULTIMODALITY"
    VISION = "VISION"
    LABEL = "LABEL"
    POLICY_DATA = "POLICY_DATA"


class ActionSpace(StrEnum):
    """How to interpret the action vector (docs/03 §2)."""

    JOINT_POS = "JOINT_POS"
    JOINT_VEL = "JOINT_VEL"
    EEF_DELTA = "EEF_DELTA"
    EEF_ABS = "EEF_ABS"
    EEF_6D_ROT = "EEF_6D_ROT"
    GRIPPER_MIX = "GRIPPER_MIX"
    UNKNOWN = "UNKNOWN"


class PolicyFamily(StrEnum):
    """Target policy architecture (docs/03 §6)."""

    BC_MLP = "BC_MLP"
    ACT = "ACT"
    DIFFUSION = "DIFFUSION"
    VLA_OPENVLA = "VLA_OPENVLA"
    VLA_PI0 = "VLA_PI0"
    OCTO = "OCTO"
    UNKNOWN = "UNKNOWN"


class NormScheme(StrEnum):
    """Normalization a checkpoint bakes in (docs/03 §6)."""

    QUANTILE_Q01_Q99 = "QUANTILE_Q01_Q99"
    MEANSTD = "MEANSTD"
    MINMAX = "MINMAX"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class FeatureStats:
    """Per-feature summary stats, declared (SchemaHints) or measured (Profile)."""

    mean: float
    std: float
    min: float
    max: float
    q01: float | None = None
    q99: float | None = None


@dataclass(frozen=True, slots=True)
class CameraSpec:
    """One camera stream in the dataset."""

    key: str
    height: int
    width: int
    channels: int = 3
    is_depth: bool = False
    fps: float | None = None


@dataclass(frozen=True, slots=True)
class GripperSpec:
    """Where and how the gripper lives inside the action vector."""

    action_index: int
    is_binary: bool
    closed_value: float
    open_value: float


@dataclass(frozen=True, slots=True)
class DatasetSchema:
    """Frozen, dataset-wide type/shape/units info. Built once in Stage ③ (docs/03 §2)."""

    action_dim: int
    action_space: ActionSpace = ActionSpace.UNKNOWN
    action_names: tuple[str, ...] | None = None
    proprio_dim: int | None = None
    proprio_names: tuple[str, ...] | None = None
    cameras: tuple[CameraSpec, ...] = ()
    control_hz: float | None = None
    embodiment: str | None = None
    gripper: GripperSpec | None = None
    coordinate_frame: str | None = None


@dataclass(frozen=True, slots=True)
class SchemaHints:
    """What the *source* declares — trusted but verified against measurement (docs/03 §5)."""

    declared_stats: dict[str, FeatureStats] | None = None
    declared_dtypes: dict[str, str] | None = None
    declared_shapes: dict[str, tuple[int, ...]] | None = None
    declared_fps: float | None = None

    @staticmethod
    def empty() -> SchemaHints:
        """A hints object for sources that declare nothing."""
        return SchemaHints()


@dataclass(frozen=True, slots=True)
class PolicyProfile:
    """Parsed from an optional checkpoint; unlocks the POLICY↔DATA family (docs/03 §6)."""

    family: PolicyFamily = PolicyFamily.UNKNOWN
    expected_action_dim: int | None = None
    expected_proprio_dim: int | None = None
    expected_cameras: tuple[str, ...] | None = None
    norm_scheme: NormScheme | None = None
    norm_stats: dict[str, FeatureStats] | None = None
    clamps_actions: bool | None = None


class Provenance(BaseModel):
    """Where an IR field / finding came from — traceable to the byte (docs/03 §4).

    A frozen pydantic model (not a dataclass) because it round-trips into every serialized
    :class:`~bohrin.report.model.Finding`; keeping it pydantic means one serializer.
    """

    model_config = ConfigDict(frozen=True)

    adapter: str
    uri: str
    locator: str = ""
    source_keys: dict[str, str] = Field(default_factory=dict)
