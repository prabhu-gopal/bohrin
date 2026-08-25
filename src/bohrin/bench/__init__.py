"""The fault-injection benchmark — validate-the-validator (docs/06 P4, docs/08 §4).

Turns "we detect X" from an assertion into a *measured, regression-tested* property. The
harness runs each detector over matched clean/faulted dataset pairs across many seeds and
reports precision, recall, F1 and ROC-AUC per detector. The scenarios (which use the
test-only synthetic generators) and the CI quality gate live in the test suite; this package
ships the generic, reusable measurement machinery.
"""

from bohrin.bench.harness import (
    DetectorMetrics,
    Scenario,
    Trial,
    run_benchmark,
    run_scenario,
)

__all__ = ["DetectorMetrics", "Scenario", "Trial", "run_benchmark", "run_scenario"]
