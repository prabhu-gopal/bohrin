# How Bohrin thinks

This page explains what Bohrin is for, the idea it is built on, and every term it uses. It is
for understanding, not for looking things up: the exact rules are in [SPEC.md](SPEC.md). If you
would rather learn by doing, start with the [tutorial](tutorial.md).

## The problem: the checker is trusted, and nobody checks it

When a model learns to write code by reinforcement learning, it writes a solution, a **grader**
decides whether the solution is right, and the model is rewarded when the grader says yes. The
grader is usually a test suite, a script that compares outputs, or a check on the state of a
container after the model has worked in it.

The model never sees the task's intent. It sees only the reward. So if a grader can be passed
without doing the task, a model trained against it learns to pass it that way. This is called
**reward hacking**, and it is common. Published work has shown models that:

- return an object whose `==` is always true, so every assertion passes;
- call `sys.exit(0)` before any test runs, so the test process reports success;
- add a `conftest.py` that rewrites every pytest result to "passed";
- write the expected reward straight into the file the grader reads;
- read the solution from the repository's future git history.

Each of these works only because the **grader** has a gap. Bohrin checks the grader, before
anyone trains on it or publishes a score from it.

## The idea: send submissions whose right answer is known

You cannot tell whether a grader is correct by reading its score. You can tell by giving it
submissions where you already know what a correct grader must say:

- a **negative control** is a submission that is wrong *by construction* (the reference solution
  with every function body replaced by `pass`, for example). A correct grader must reject it.
- a **positive control** is a submission that is right by construction (the reference solution,
  reformatted). A correct grader must accept it.

If the grader pays for a negative control, it has a gap, and the submission itself is the proof.
Bohrin's job is to build those controls, to be sure they really are what they claim to be, and
to score the results.

## The one rule: proof before accusation

A tool that checks graders is only useful if it is believed. One false accusation (calling a
correct grader broken) costs more than many missed defects, so every Bohrin claim follows one
rule:

> A submission is called wrong only when its wrongness is established **without asking the
> grader under test**.

How it was established is called its **ground**:

| Ground | Wrong because | Example |
|---|---|---|
| structural | it provably does no work | every function body replaced by `pass` |
| differential | it provably behaves differently from the reference | an input where the two give different outputs |
| invariant | it breaks a property the task itself declares | a "sort" whose output is not in order |

A submission without a ground is a **lead**. It is still tried, and if a grader accepts it you are
shown it, because it may be worth a look. It is never counted in a score and never called a
defect. Every rule that runs after a submission is generated can only *remove* a ground, never add
one: if a submission turns out to be the reference solution written another way, it is dropped.

## How the pieces fit

```
weakness list  ──►  probe  ──►  battery  ──►  (you run your grader)  ──►  Coverage Score
  what can go        how to       every          which submissions          how much of it
  wrong, by ID       try it       submission     it accepted                the grader caught
                                  for a task
```

1. The **weakness list** names every published way a coding grader can be cheated or be wrong.
2. A **probe** is one concrete way of trying a weakness, such as "empty every function body".
3. The **battery** runs every probe that fits a task and returns the submissions, each with its
   ground, after the rules that stop a false accusation have been applied.
4. **You run your grader** on those submissions. Bohrin never runs it for you: this library
   generates, checks and scores, and has no code that calls a grader.
5. The **Coverage Score** says what share of the negative controls your grader rejected, with its
   uncertainty and the list of what was not measured.

## Glossary

**Grader.** Whatever decides whether a submission solved a task: a reward function, a test suite,
an output checker, a script in a container. Also called a verifier.

**Task.** One unit of work: an ID, the prompt, and usually a **reference**, a known-good solution
(`bohrin.ir.task.Task`).

**Shape.** How a task's grader is called. `program`: the grader takes source code and returns a
reward. `io`: it runs a program on inputs and compares outputs. `workspace`: it applies a patch to
a repository and runs the tests. `container`: the agent works in a container and a script there
writes the reward. `history`: a change in a git repository, read from its history. Probes declare
the shapes they apply to.

**Submission (payload).** What is sent to the grader. Either `Source` (program text) or
`Workspace` (file changes and commands for a repository or container).

**Template.** A workspace that names parameters instead of real paths, such as
`{test_root}/conftest.py`. It is the same for every environment, so anyone can read exactly what
is tried. Filling in a real path needs knowledge of one particular environment, and this library
never does it.

**Weakness (class).** One kind of grader defect, with a permanent ID such as `BGW-108`
("test-framework hook"). The number means nothing and is never reused, like a CWE number for
software security. The 38 classes are grouped into **families** (hollow programs, harness
tampering, answer access, weak or wrong tests, grader logic, isolation, measurement adequacy).
See [WEAKNESSES.md](WEAKNESSES.md).

**Probe.** One way of trying a weakness, with an ID such as `bohrin/empty-implementation@1`. The
`@1` changes when what the probe tries changes. A probe is code (an **operator**) plus a
**manifest** that describes it as data.

**Operator.** The code that generates a probe's submissions for a task
(`bohrin.mutate.base.MutationOperator`). Third parties can add their own through a Python entry
point.

**Battery.** Every submission the operators propose for a task, after the rules have been applied
(`bohrin.mutate.battery.battery`). The **battery version** changes whenever a category is added,
removed or redefined, because scores are comparable only within one version.

**Ground, lead.** See [the one rule](#the-one-rule-proof-before-accusation) above.

**Category.** A family of the weakness list that a correct grader must reject. The Coverage Score
is counted per task and category.

**Coverage Score.** Of the negative controls tried, the share the grader rejected, 0 to 100, with
a 95% Wilson interval and the categories measured. A score over nothing is "not measured", never
100.

**Verification Gap.** A second number: how often a grader paid for wrong work or disagreed with
itself, over the checks that ran.

**Finding.** One result, in a fixed record format with a stable ID such as `BF-W6YDC0TBE4`. The
same defect gets the same ID on every run. Its **level** says how far the evidence goes:
`proven`, `proven-experimental`, `suspected`, `lead`, `observation` or `excluded`.

**Reproduction script.** A plain Python script attached to a proven finding. It applies the exact
submission to your environment, runs your grader on the reference and on the submission three
times each, and prints one line saying whether the finding was reproduced. It needs nothing from
Bohrin, so anyone can check a finding themselves. A finding whose script does not reproduce it
stops being proven. See [SPEC.md](SPEC.md#reproduction-scripts) and the
[example](examples/reproduce_BF-GZW6R2M9CJ.py).

**Differentiating input.** An input on which the reference and the submission give different
outputs. It proves a program wrong without asking the grader.

**Differentiating observation.** The same idea for environments: a read-only check of the end
state, tied to a sentence of the task, that the reference passes and the submission fails. It
counts only if at least three other solutions believed correct also pass it, so the check cannot
be one that only the reference could pass.

**Maturity.** Every probe starts `experimental`. It becomes `stable` only after a public sample
has shown no false accusations, with a measured precision.

## What Bohrin does not claim

- A clean result means *these probes found nothing*, not that the grader is safe.
- A check that could not run is reported as not measured, never as passed.
- The techniques are not new: mutation testing and metamorphic testing are decades old, and every
  weakness here was published by someone else first. What Bohrin adds is the discipline of proof
  before accusation, and a standard that any tool can be measured against.
