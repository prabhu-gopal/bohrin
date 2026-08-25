"""The pipeline orchestrator — wires the six stages (docs/02).

``run_scan`` is the spine: Ingest → Canonicalize → Profile → Analyze → Synthesize →
Report-object. It is format-agnostic and detector-agnostic by construction: it only ever
touches the frozen contracts (adapter/handle, profile, detector, report), never a concrete
format or check. Everything after P0 slots in by adding an adapter or a detector — the
engine does not change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from bohrin.adapters.base import Sampler
from bohrin.adapters.registry import select_adapter
from bohrin.calibrate.corpus import CalibrationCorpus
from bohrin.config import ScanConfig
from bohrin.detectors.base import AnalysisContext
from bohrin.detectors.registry import discover as discover_detectors
from bohrin.ir.schema import PolicyProfile
from bohrin.profile.dataset_profile import ProfileBuilder
from bohrin.profile.episode_reservoir import EpisodeReservoir
from bohrin.report.model import DatasetInfo, Finding, Report
from bohrin.synth.pipeline import synthesize

#: Bound on episodes kept in RAM for detectors that inspect raw trajectories (docs/02 §7).
_RESERVOIR_CAP = 5000

#: A progress sink: ``(stage, done, total)`` where ``total`` is ``None`` when unknown.
#: The engine stays a pure function of its config — it *reports* progress, it never
#: prints. The CLI supplies a Rich sink; the library API supplies none (docs/02 §6).
ProgressFn = Callable[[str, int, int | None], None]


@dataclass(frozen=True, slots=True)
class PreparedScan:
    """Everything stages ⓪–③ produce: the analysis context plus the ingest facts.

    Split out of :func:`run_scan` because ``bohrin calibrate`` needs the identical
    ingest→canonicalize→profile work but then collects reference scores instead of running
    detectors. One code path means a corpus is always collected under the same sampling,
    seeding and canonicalization as the scans it will later calibrate.
    """

    ctx: AnalysisContext
    adapter_name: str
    declared_episodes: int | None
    #: The trajectory working set: how many episodes it retained out of those streamed, and
    #: how many were declined for memory. Reported so a sampled analysis is never implicit.
    reservoir_held: int = 0
    reservoir_seen: int = 0
    reservoir_dropped_for_memory: int = 0


def prepare_scan(config: ScanConfig, *, progress: ProgressFn | None = None) -> PreparedScan:
    """Run stages ⓪–③ (policy → ingest → canonicalize → profile) and build the context."""
    emit: ProgressFn = progress or (lambda stage, done, total: None)

    # ⓪ Resolve the optional policy *first*, before touching any data. Both paths can fail
    # on what the user typed (an unreadable checkpoint, an unknown --target), and an
    # argument error should surface ahead of any downstream I/O error about the dataset —
    # otherwise a typo in --target gets reported as a problem with the path.
    # The checkpoint is parsed for metadata only and never executed (docs/03 §6).
    policy: PolicyProfile | None = None
    if config.policy is not None:
        from bohrin.policy.loader import load_policy_profile

        policy = load_policy_profile(config.policy)
    elif config.target is not None:
        # No checkpoint, but the user named the architecture they intend to train. That is
        # enough for the family-level checks (π0 zero-filling proprio) though not for the
        # shape/normalization ones, which need real constants.
        from bohrin.policy.target import profile_for_target

        policy = profile_for_target(config.target)

    # ① Ingest — pick and open the adapter.
    adapter = select_adapter(config.path, forced_format=config.format)
    handle = adapter.open(Path(config.path), config)
    schema = handle.schema()
    hints = handle.profile_hints()

    # Independent, reproducible RNG streams so profiling and analysis draws never couple
    # (both are still fully determined by config.seed — docs/02 §9).
    profile_seed, detector_seed, reservoir_seed = np.random.SeedSequence(config.seed).spawn(3)

    # ②/③ Canonicalize + Profile — one streaming pass, bounded reservoir.
    sampler = Sampler(max_episodes=config.max_episodes(), seed=config.seed)
    builder = ProfileBuilder(schema, hints, np.random.default_rng(profile_seed))
    reservoir = EpisodeReservoir(
        capacity=_RESERVOIR_CAP,
        budget_bytes=config.max_episode_memory_mb * 1024 * 1024,
        rng=np.random.default_rng(reservoir_seed),
    )
    declared = handle.episode_count()
    for seen, episode in enumerate(handle.iter_episodes(sample=sampler), start=1):
        builder.add(episode)
        reservoir.add(episode)
        emit("profile", seen, declared)
    profile = builder.finalize()

    # ③.5 Calibration — reference bands from known-good data, when the user supplied a
    # corpus. Absent (the default) every gate self-calibrates and says so (docs/07 §4.2).
    ctx = AnalysisContext(
        profile=profile,
        schema=schema,
        episodes=reservoir.episodes,
        config=config,
        rng=np.random.default_rng(detector_seed),
        policy=policy,
        corpus=CalibrationCorpus.load(config.calibration),
    )
    return PreparedScan(
        ctx=ctx,
        adapter_name=adapter.name,
        declared_episodes=declared,
        reservoir_held=len(reservoir.episodes),
        reservoir_seen=reservoir.seen,
        reservoir_dropped_for_memory=reservoir.dropped_for_memory,
    )


def run_scan(config: ScanConfig, *, progress: ProgressFn | None = None) -> Report:
    """Run the full Layer 1 pipeline for ``config`` and return the :class:`Report`.

    ``progress`` is an optional sink called as stages advance; it cannot affect the result,
    so a scan is byte-identical with and without it.
    """
    emit: ProgressFn = progress or (lambda stage, done, total: None)
    prepared = prepare_scan(config, progress=progress)
    ctx = prepared.ctx
    profile, schema, policy = ctx.profile, ctx.schema, ctx.policy
    declared = prepared.declared_episodes

    # ④ Analyze — run every applicable detector over the read-only context.
    findings: list[Finding] = []
    detectors_run: list[str] = []
    selected = list(discover_detectors(only=config.only, disable=config.disable))
    for i, detector in enumerate(selected, start=1):
        emit("detect", i, len(selected))
        if not detector.applicable(profile, policy):
            continue
        detectors_run.append(detector.id)
        findings.extend(detector.run(ctx))

    # ⑤ Synthesize — cluster and rank. No aggregate score: see Report's docstring.
    clusters = synthesize(findings, total_episodes=profile.n_episodes)

    # ⑥ Report object — the renderers consume this; it never leaves the machine.
    # ``declared`` is the dataset's true episode count when the adapter knows it cheaply;
    # fall back to the scanned count so ``sampled`` is never falsely true.
    total_episodes = declared if declared is not None else profile.n_episodes
    dataset = DatasetInfo(
        uri=config.display_uri(),
        format=prepared.adapter_name,
        n_episodes=profile.n_episodes,
        total_episodes=max(total_episodes, profile.n_episodes),
        total_steps=profile.total_steps,
        embodiment=schema.embodiment,
        control_hz=profile.control_hz,
        action_dim=schema.action_dim,
        proprio_dim=schema.proprio_dim,
        cameras=[c.key for c in schema.cameras],
    )
    return Report(
        dataset=dataset,
        clusters=clusters,
        detectors_run=sorted(detectors_run),
    )
