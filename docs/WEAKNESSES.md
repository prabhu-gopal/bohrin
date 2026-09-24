# Weakness list

<!-- Generated from src/bohrin/spec/weaknesses.toml by `python -m bohrin.spec > docs/WEAKNESSES.md`. Do not edit by hand. -->

Version **1**. Every published way a coding grader or its harness can be cheated or be wrong, each with a permanent ID. Probes, findings, registry records and fix guidance refer to these IDs. The number in an ID carries no meaning and is never reused; families are for reading the list and are not part of the ID.

Each class names the grader shapes it applies to, the evidence a finding of it carries, and what this library provides for it beyond the definition:

- **template**: a template that generates the attack or the control
- **fact**: a fact rule read from version history
- **statistic**: a statistic in the scoring

Evidence kinds:

- **reproduction**: a submission the grader paid for, re-created by a standalone reproduction script
- **differentiating-input**: an input on which the submission and the reference produce different outputs
- **differentiating-observation**: a read-only check of the end state, tied to a sentence of the task, that the reference and presumed-correct solutions pass and the submission fails
- **fact**: a fact read from version history, such as a deleted test or an added exit call
- **statistic**: a measurement over many tasks or runs, reported with its interval
- **positive-control**: a certified-correct submission the grader rejected
- **structural-risk**: a risk read from the harness without a working exploit, reported as suspected

## Hollow programs: the grader pays for code that does no work

| ID | Weakness | Shapes | Provides |
|---|---|---|---|
| [BGW-101](#bgw-101) | Trivial implementation | program, io, workspace, container, history | template, fact |
| [BGW-102](#bgw-102) | Exit before the checks | program, workspace, container, history | template, fact |
| [BGW-103](#bgw-103) | Equality spoofing | program, workspace, container, history | template, fact |
| [BGW-104](#bgw-104) | Hard-coded expected outputs | program, io, workspace, container, history | fact |
| [BGW-105](#bgw-105) | State recorded across calls | program, workspace, container | definition |
| [BGW-106](#bgw-106) | Dead code for a static check | program, workspace, container | definition |
| [BGW-107](#bgw-107) | Letter of the specification, not its intent | program, io, workspace, container | definition |

### BGW-101

**Trivial implementation**. A body that is empty, returns None or a type-correct constant, or raises NotImplementedError passes a grader that checks only that the code imports, runs or returns the right type, so the policy is paid for skipping the work.

- **Evidence:** reproduction, fact
- **Grounds:** structural
- **Fix:** Check return values against known outputs on inputs the submission cannot see, and include at least one case a constant or empty body cannot pass.
- **Sources:** <https://arxiv.org/abs/2604.17596>

### BGW-102

**Exit before the checks**. Calling sys.exit(0), os._exit(0) or raising SystemExit(0) ends the process with a success code before any assertion runs, and a grader that reads the exit code as the verdict pays full marks.

- **Evidence:** reproduction, fact
- **Grounds:** structural
- **Fix:** Never infer a pass from the exit code alone: require a positive record that every expected test ran and passed, written outside the submission's reach.
- **Sources:** <https://arxiv.org/abs/2511.18397>

### BGW-103

**Equality spoofing**. An object whose __eq__ always returns True, with __ne__ and methods such as strip() overridden to match, satisfies every equality assertion without computing anything.

- **Evidence:** reproduction, fact
- **Grounds:** structural
- **Fix:** Check the exact type of a returned value before comparing it, compare serialised values rather than calling the submission's own __eq__, and reject monkey-patched operators on built-in types.
- **Sources:** <https://arxiv.org/abs/2511.18397> · <https://metr.org/blog/2025-06-05-recent-reward-hacking/>

### BGW-104

**Hard-coded expected outputs**. Special-casing the inputs the visible tests use returns the expected outputs without implementing the behaviour, so a grader that tests only those inputs is passed by a lookup table.

- **Evidence:** differentiating-input, fact
- **Grounds:** differential
- **Fix:** Grade on held-out inputs the submission never sees, generated or drawn fresh per run, in addition to the visible examples.
- **Sources:** <https://arxiv.org/abs/2604.17596> · <https://arxiv.org/abs/2510.20270> · <https://arxiv.org/abs/2605.21384>

### BGW-105

**State recorded across calls**. A submission that remembers what it saw on earlier calls, such as the first expected value, can replay it to game checks that repeat or compare calls.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Run each check in a fresh process, and never pass expected values into the code under test.
- **Sources:** <https://arxiv.org/abs/2510.20270>

### BGW-106

**Dead code for a static check**. Code that is never executed but contains what a static check looks for (a keyword, an import, a call) satisfies the check without the behaviour.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Verify behaviour by executing the code, not by searching its source for keywords or imports.
- **Sources:** <https://arxiv.org/abs/2604.17596>

### BGW-107

**Letter of the specification, not its intent**. A brute force where efficiency was required, or a trivial method that happens to satisfy the tests, meets what the grader checks while missing what the task asked for.

- **Evidence:** differentiating-input
- **Grounds:** differential
- **Fix:** Test the stated constraints directly: inputs large enough that a brute force times out, and cases that separate the required method from a shortcut.
- **Sources:** <https://arxiv.org/abs/2604.17596>

## Harness tampering: the submission changes what judges it

| ID | Weakness | Shapes | Provides |
|---|---|---|---|
| [BGW-108](#bgw-108) | Test-framework hook | workspace, container, history | template, fact |
| [BGW-109](#bgw-109) | Tests edited, deleted or skipped | workspace, container, history | template, fact |
| [BGW-110](#bgw-110) | Hijacked tool | container | template |
| [BGW-111](#bgw-111) | Direct write to the reward file | container | template |
| [BGW-112](#bgw-112) | Result parser replaced | workspace, container | template |
| [BGW-113](#bgw-113) | Measurement tampering | container, history | template, fact |
| [BGW-114](#bgw-114) | Shared state tampered through a side channel | container | definition |

### BGW-108

**Test-framework hook**. A conftest.py that patches pytest's report creation, or a monkey-patched unittest.TestCase.run, rewrites every test outcome to passed, so the test run reports success whatever the code does.

- **Evidence:** reproduction, fact
- **Grounds:** structural
- **Fix:** Run the tests in a separate verifier environment, copy in only the submission's source files, and disable plugin and conftest discovery from the submission's paths.
- **Sources:** <https://arxiv.org/abs/2511.18397> · <https://rdi.berkeley.edu/blog/trustworthy-benchmarks-cont/>

### BGW-109

**Tests edited, deleted or skipped**. A submission that can write to the tests or their configuration can delete them, empty them, mark them skipped or deselect them, and a grader that runs whatever tests remain reports success.

- **Evidence:** reproduction, fact
- **Grounds:** structural
- **Fix:** Make the tests and test configuration read-only to the agent, or restore them from a trusted copy before grading, and check the number of tests collected.
- **Sources:** <https://arxiv.org/abs/2510.20270> · <https://arxiv.org/abs/2511.21654>

### BGW-110

**Hijacked tool**. Any tool the verifier runs to read state (the test runner, a service manager, a settings reader, a patched standard library) can be replaced by one that prints the state the verifier wants.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Run the verifier with its own trusted binaries and interpreter, from paths the agent cannot write, with a fixed PATH.
- **Sources:** <https://rdi.berkeley.edu/blog/trustworthy-benchmarks-cont/> · <https://arxiv.org/abs/2604.17596>

### BGW-111

**Direct write to the reward file**. When the verifier's result is a file in a path the agent can write, the agent can write the maximum reward there itself.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Write the reward from a process the agent does not control, to a location the agent cannot write, after the agent has finished.
- **Sources:** <https://docs.harborframework.com/core-concepts/tasks/overview.md> · <https://arxiv.org/abs/2605.12673>

### BGW-112

**Result parser replaced**. When the script that turns test output into a verdict lives where the agent can write, replacing it with one that reports success passes every task.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Keep the result parser outside the agent's environment and parse output copied out of it.
- **Sources:** <https://rdi.berkeley.edu/blog/trustworthy-benchmarks-cont/>

### BGW-113

**Measurement tampering**. A submission that reassigns timers, synchronisation calls or counters changes what a performance grader measures, so a slow or wrong program reports a speed-up.

- **Evidence:** reproduction, fact
- **Grounds:** structural
- **Fix:** Measure from outside the submission's process, and check the output's correctness in the same run as its timing.
- **Sources:** <https://metr.org/blog/2025-06-05-recent-reward-hacking/> · <https://arxiv.org/abs/2604.17596>

### BGW-114

**Shared state tampered through a side channel**. Inputs, fixtures or shared files the grader reads after the agent has run can be changed by the agent so that its output matches them.

- **Evidence:** differentiating-observation
- **Grounds:** differential
- **Fix:** Give the grader its own copy of every input, taken before the agent runs, and compare against that copy.
- **Sources:** <https://arxiv.org/abs/2604.17596>

## Answer access: the submission obtains the solution instead of producing it

| ID | Weakness | Shapes | Provides |
|---|---|---|---|
| [BGW-115](#bgw-115) | Solution in the task text | workspace, container | statistic |
| [BGW-116](#bgw-116) | Reference or verifier readable at run time | container | template |
| [BGW-117](#bgw-117) | Future repository state | workspace, container | template |
| [BGW-118](#bgw-118) | Solution fetched from the network | container | definition |

### BGW-115

**Solution in the task text**. When the task statement or its attached discussion contains the solution, a submission can copy it, and the task measures copying rather than solving.

- **Evidence:** statistic
- **Grounds:** none
- **Fix:** Remove solutions and solution hints from task text before release, and exclude tasks whose statement cannot be separated from the answer.
- **Sources:** <https://arxiv.org/abs/2410.06992>

### BGW-116

**Reference or verifier readable at run time**. When the reference solution, the tests or the verifier can be read from the agent's environment (files, configuration, stack frames), the agent can return the expected answer instead of computing it.

- **Evidence:** reproduction, structural-risk
- **Grounds:** structural
- **Fix:** Keep references, tests and verifier code out of the agent's image; copy them in only for grading, in a separate environment.
- **Sources:** <https://arxiv.org/abs/2604.17596> · <https://metr.org/blog/2025-06-05-recent-reward-hacking/> · <https://arxiv.org/abs/2605.12673> · <https://arxiv.org/abs/2605.20744>

### BGW-117

**Future repository state**. When the repository keeps history past the task's starting commit (other branches, the reflog, remote refs, unsquashed commits), the agent can find the real fix and apply it.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Ship the repository as a single squashed commit at the starting state, with no other refs, remotes or reflog.
- **Sources:** <https://github.com/SWE-bench/SWE-bench/issues/465> · <https://arxiv.org/abs/2604.11072> · <https://poolside.ai/blog/through-the-looking-glass>

### BGW-118

**Solution fetched from the network**. With network access, an agent can fetch the published fix from a public repository, a package registry or a web archive.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Block egress during the agent's run, or allow only the package mirrors the task needs, pinned to versions that predate the fix.
- **Sources:** <https://poolside.ai/blog/through-the-looking-glass> · <https://arxiv.org/abs/2605.12673>

## Weak or wrong tests: the tests cannot tell right from wrong

| ID | Weakness | Shapes | Provides |
|---|---|---|---|
| [BGW-119](#bgw-119) | Tests too weak | program, io, workspace, container | definition |
| [BGW-120](#bgw-120) | Tests too narrow | program, io, workspace, container | template |
| [BGW-121](#bgw-121) | Specification contradicts the tests | program, io, workspace, container | definition |
| [BGW-122](#bgw-122) | Partial credit rewards the wrong approach | program, io, workspace, container | statistic |
| [BGW-123](#bgw-123) | Output checker too lenient | program, io, workspace, container | template |
| [BGW-124](#bgw-124) | Reference solution wrong | program, io, workspace, container | definition |
| [BGW-134](#bgw-134) | Numeric tolerance too loose for the output | numeric | template |
| [BGW-135](#bgw-135) | Proof checker accepts incomplete proofs | proof | template |
| [BGW-136](#bgw-136) | Execution equivalence on one database | query | definition |
| [BGW-137](#bgw-137) | Pseudo-tested code | program, workspace | template |
| [BGW-138](#bgw-138) | Proxy-state check | workspace, container | template |

### BGW-119

**Tests too weak**. When a wrong program passes every test, the grader pays for wrong behaviour, and the policy learns whichever wrong behaviour is easiest.

- **Evidence:** differentiating-input
- **Grounds:** differential
- **Fix:** Add the inputs that separate the reference from the surviving wrong programs, and measure test strength by mutation analysis.
- **Sources:** <https://arxiv.org/abs/2506.09289> · <https://arxiv.org/abs/2503.15223> · <https://arxiv.org/abs/2305.01210> · <https://arxiv.org/abs/2505.24098>

### BGW-120

**Tests too narrow**. Tests that depend on one implementation's incidental choices (formatting, names, order, an internal API) reject correct programs, so the policy is penalised for correct work.

- **Evidence:** positive-control
- **Grounds:** none
- **Fix:** Test behaviour through the interface the task specifies, and confirm that equivalent rewritings of the reference still pass.
- **Sources:** <https://openai.com/index/introducing-swe-bench-verified/> · <https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/>

### BGW-121

**Specification contradicts the tests**. When the task text and the hidden tests disagree, a program that follows the text fails, and an agent is pushed toward whatever the tests reward, including cheating.

- **Evidence:** positive-control
- **Grounds:** none
- **Fix:** Check each test against the sentence of the task it verifies, and remove or reword tests that require behaviour the task does not state.
- **Sources:** <https://openai.com/index/separating-signal-from-noise-coding-evaluations/> · <https://arxiv.org/abs/2510.20270>

### BGW-122

**Partial credit rewards the wrong approach**. A reward proportional to the share of tests passed can pay most for an approach that is fundamentally wrong but passes the easy cases.

- **Evidence:** statistic
- **Grounds:** none
- **Fix:** Use all-or-nothing rewards for correctness, or weight tests so that no wrong approach can outscore a correct partial one.
- **Sources:** <https://arxiv.org/abs/2605.02944> · <https://www.together.ai/blog/deepcoder>

### BGW-123

**Output checker too lenient**. An input/output checker that normalises too aggressively (ignoring extra tokens, order or content) accepts outputs that differ from the only correct one.

- **Evidence:** reproduction
- **Grounds:** differential
- **Fix:** Compare exactly what the task specifies, and use a special checker only where the task genuinely accepts several answers.
- **Sources:** <https://rdi.berkeley.edu/blog/trustworthy-benchmarks-cont/> · <https://github.com/MikeMirzayanov/testlib>

### BGW-124

**Reference solution wrong**. When the reference is wrong, tests derived from it reward the same mistake and penalise correct programs.

- **Evidence:** differentiating-input
- **Grounds:** none
- **Fix:** Check the reference against the specification on independent inputs, and exclude tasks whose reference fails its own grader.
- **Sources:** <https://arxiv.org/abs/2305.01210>

### BGW-134

**Numeric tolerance too loose for the output**. A tolerance-based comparison whose acceptance band grows with the size of the output eventually admits clearly wrong results, such as a constant of the right shape.

- **Evidence:** differentiating-input
- **Grounds:** differential
- **Fix:** Set the tolerance from the variance correct implementations actually produce, and include cases where a constant or zero output falls outside it.
- **Sources:** <https://arxiv.org/abs/2609.22220>

### BGW-135

**Proof checker accepts incomplete proofs**. A proof checker that allows placeholder proofs, non-standard axioms or a changed statement accepts proofs that prove nothing about the task.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Check proofs with an independent checker, an axiom allow-list and a comparison of the proved statement with the original.
- **Sources:** <https://arxiv.org/abs/2606.29493> · <https://lean-lang.org/doc/reference/latest/ValidatingProofs/>

### BGW-136

**Execution equivalence on one database**. Two queries can return the same rows on one database instance while meaning different things, so comparing results on one instance accepts a semantically wrong query.

- **Evidence:** differentiating-input
- **Grounds:** differential
- **Fix:** Compare results on several database instances built to separate queries that agree by accident.
- **Sources:** <https://aclanthology.org/2025.naacl-long.228.pdf> · <https://www.vldb.org/cidrdb/papers/2026/p5-jin.pdf>

### BGW-137

**Pseudo-tested code**. A function the tests execute but never check can have its body replaced by a default value with every test still passing, so its behaviour is unverified.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Add an assertion on each function's observable effect, and run extreme mutation (empty each body in turn) to find the ones no test checks.
- **Sources:** <https://link.springer.com/article/10.1007/s10664-018-9653-2> · <https://arxiv.org/abs/2103.08480>

### BGW-138

**Proxy-state check**. A verifier that checks a stand-in for the required state (keywords in a file, a file's existence or apparent size, a status line a tool prints) is passed by producing the stand-in without the behaviour the task asks for.

- **Evidence:** reproduction, differentiating-observation
- **Grounds:** structural, differential
- **Fix:** Verify the behaviour itself by exercising it (start the service, read the configuration the way the system does, use the file), not by inspecting its traces.
- **Sources:** <https://arxiv.org/abs/2604.17596> · <https://github.com/harbor-framework/terminal-bench-science/blob/main/rubrics/task-implementation.toml>

## Grader logic and reliability

| ID | Weakness | Shapes | Provides |
|---|---|---|---|
| [BGW-125](#bgw-125) | Evaluation that does not evaluate | program, io, workspace, container | definition |
| [BGW-126](#bgw-126) | Failure scored as success | program, io, workspace, container | template |
| [BGW-127](#bgw-127) | Nondeterministic grader | program, io, workspace, container | statistic |
| [BGW-128](#bgw-128) | Aggregation defect | program, io, workspace, container | statistic |
| [BGW-129](#bgw-129) | Grader executes agent-controlled data | workspace, container | definition |

### BGW-125

**Evaluation that does not evaluate**. A grader whose logic never inspects the work (it checks who spoke last, or that a file exists) passes anything that reaches it.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Confirm that the grader rejects a submission that does nothing before relying on it.
- **Sources:** <https://rdi.berkeley.edu/blog/trustworthy-benchmarks-cont/>

### BGW-126

**Failure scored as success**. A grader that reads an exception, a timeout or an exit code as a pass pays for failures, and one that charges infrastructure failures to the model penalises it for the harness.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Fail closed: anything other than a positive, complete record of passing is a fail, and harness errors are recorded as errors, never as scores.
- **Sources:** <https://github.com/UKGovernmentBEIS/inspect_evals/pull/2298>

### BGW-127

**Nondeterministic grader**. A grader that gives different rewards for the same submission, through async waits, concurrency or test order, turns the reward into noise the policy cannot learn from.

- **Evidence:** statistic
- **Grounds:** none
- **Fix:** Score each submission several times, in varied test order, and remove the sources of variation found.
- **Sources:** <https://dl.acm.org/doi/10.1145/2635868.2635920>

### BGW-128

**Aggregation defect**. Dropping errored samples from the denominator, or allowing rewards past the declared maximum, makes the aggregate score overstate performance.

- **Evidence:** statistic
- **Grounds:** none
- **Fix:** Count every sample in the denominator, record errors as failures or report them separately, and clip or reject rewards outside the declared range.
- **Sources:** <https://github.com/UKGovernmentBEIS/inspect_ai/issues/4286>

### BGW-129

**Grader executes agent-controlled data**. A grader that calls eval or exec on, or unsafely deserialises, data the agent produced lets the agent run code inside the grader and set its own verdict.

- **Evidence:** reproduction
- **Grounds:** structural
- **Fix:** Parse agent output with a safe parser, and never execute it in the grader's process.
- **Sources:** <https://rdi.berkeley.edu/blog/trustworthy-benchmarks-cont/> · <https://arxiv.org/abs/2605.12673>

## Isolation and permissions: the structure that enables tampering and answer access

| ID | Weakness | Shapes | Provides |
|---|---|---|---|
| [BGW-130](#bgw-130) | Agent and grader share an environment | container | definition |
| [BGW-131](#bgw-131) | Evaluator paths writable by the agent | container | definition |
| [BGW-132](#bgw-132) | Excessive permissions or network egress | container | definition |

### BGW-130

**Agent and grader share an environment**. When the grader runs in the environment the agent controlled, everything it relies on (files, binaries, interpreter, processes) may have been changed by the agent.

- **Evidence:** structural-risk
- **Grounds:** none
- **Fix:** Run the verifier in a separate sandbox, and copy across only the artefacts the task produces.
- **Sources:** <https://arxiv.org/abs/2605.12673> · <https://docs.harborframework.com/news/separate-verifier-sandboxes.md> · <https://arxiv.org/abs/2605.02964>

### BGW-131

**Evaluator paths writable by the agent**. When the tests, the verifier or the reward location are writable by the agent, tampering with them is one write away.

- **Evidence:** structural-risk
- **Grounds:** none
- **Fix:** Mount evaluator paths read-only for the agent, or keep them out of its environment entirely.
- **Sources:** <https://arxiv.org/abs/2510.20270>

### BGW-132

**Excessive permissions or network egress**. Root access, broad capabilities or open egress give the agent the means to tamper with the harness or fetch the answer.

- **Evidence:** structural-risk
- **Grounds:** none
- **Fix:** Run the agent as an unprivileged user with no network, or only the egress the task needs.
- **Sources:** <https://arxiv.org/abs/2605.12673> · <https://poolside.ai/blog/through-the-looking-glass>

## Measurement adequacy

| ID | Weakness | Shapes | Provides |
|---|---|---|---|
| [BGW-133](#bgw-133) | Evaluation too small or noisy | program, io, workspace, container | statistic |

### BGW-133

**Evaluation too small or noisy**. An evaluation with too few tasks, or with tasks that cluster, cannot distinguish the differences it is used to claim, so its conclusions are noise.

- **Evidence:** statistic
- **Grounds:** none
- **Fix:** Report every score with an interval suited to its sample, cluster by shared source, and size the evaluation for the smallest difference it must detect.
- **Sources:** <https://arxiv.org/abs/2411.00640> · <https://arxiv.org/abs/2503.01747>

## Crosswalks

Categories from other published taxonomies, mapped to the classes above, so a reader who knows one vocabulary can read this one.

### Terminal Wrench exploit categories

Source: <https://arxiv.org/abs/2604.17596>

| Category | Classes |
|---|---|
| hollow-implementation | BGW-101, BGW-138 |
| output-spoofing | BGW-104 |
| constraint-loophole | BGW-107 |
| structural-extraction | BGW-116 |
| binary-hijacking | BGW-110 |
| algorithmic-simplification | BGW-107 |
| mutable-input-tampering | BGW-114 |
| keyword-gaming | BGW-106, BGW-138 |
| metric-spoofing | BGW-113 |
| security-downgrading | BGW-138, BGW-110 |
| deceptive-rationalization | none (not a grader weakness) |

### Harbor task implementation rubric

Source: <https://github.com/harbor-framework/terminal-bench-science/blob/main/rubrics/task-implementation.toml>

| Category | Classes |
|---|---|
| Anti-Cheat Robustness | BGW-108, BGW-109, BGW-110, BGW-111, BGW-112, BGW-113, BGW-114 |
| Functional Verification | BGW-106, BGW-138 |
| Graded Instances Discriminate | BGW-101, BGW-119 |
| Do Not Modify Enforced | BGW-109 |
| Separate Verifier Configured | BGW-130 |
| Verifier Execution Isolation | BGW-111, BGW-129, BGW-131 |
| Environment Hygiene | BGW-116 |
| Test-Instruction Alignment | BGW-121 |
| Deterministic & Reproducible | BGW-127 |
| Ground Truth Provenance | BGW-124 |
| Solution Quality | BGW-124 |
