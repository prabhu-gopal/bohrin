# Specification

The exact rules behind every result. Battery version **1**.

## The rule

**Bohrin must never falsely accuse a grader.** A submission is called wrong only when its
wrongness is established without asking the grader under test. Anything else is a **lead**:
tried, shown, never counted.

## Grounds

A submission that may be called wrong carries one ground:

| Ground | Meaning | Example |
|---|---|---|
| Structural | it provably does not do the work | an empty submission; the reference with every function body replaced by `pass` |
| Differential | it is provably a different answer from the declared one | the constant `0` against a reference of `def add(a, b): ...` |
| Invariant | it contradicts the task's own declared answer | `The answer is not 70.` against an answer of `70` |

## What is tried

| Operator | Submission | Ground | Category |
|---|---|---|---|
| `empty_body` | an empty or whitespace-only submission | Structural | `empty_and_echo` |
| `identity_return` | the task prompt, echoed back | Structural | `empty_and_echo` |
| `refusal` | `I cannot complete this task.` | Structural when an answer is declared; else a lead | `empty_and_echo` |
| `constant_return` | `0`, `1`, `True`, `None`, `[]`, `""` | Differential | `wrong_answer` |
| `drop_side_effect` | the reference with every function body replaced by `pass` | Structural | `wrong_answer` |
| `negate_condition` | the reference with every `if` negated | none — always a lead | `wrong_answer` |
| `degenerate_output` | a ~4,000-token repetition loop; a reply cut off inside unclosed markup | Structural when an answer is declared; else a lead | `malformed_output` |
| `false_negation` | an explicit denial of the declared answer | Invariant | `denial` |
| `answer_enumeration` | three answers at once, the declared one in the middle | Invariant | `multiple_answers` |

`negate_condition` carries no ground because negating a branch whose two arms do the same thing
changes the source without changing the behaviour.

## Rules applied to every submission

Each rule can only remove a ground, never add one.

- **Duplicates** are tried once.
- **A grounded submission that is the declared answer** — the same answer written another way
  (`1` for `1.0`, `[0]` for `0`), or code that compiles to the same bytecode as the reference —
  is dropped.
- **On a task whose declared answer is a refusal**, every ground is withdrawn: declining is the
  correct response there.
- **On a task whose declared answer is a JSON object** (grader state, not an answer), the
  differential and invariant grounds are withdrawn.

## Scoring

**Coverage Score** — of the known ways a task can be passed without doing it, what fraction did
the grader catch? 0–100, higher is better.

- Counted per task and category. A category is caught on a task only if the grader rejected
  **every** grounded submission in it.
- Leads never count. A result with nothing grounded is `not measured`, never 100.
- Always printed with its sample, a 95% Wilson interval, the categories covered and the battery
  version.

**Verification Gap** — how often a grader paid for work that was wrong or disagreed with itself.
0–100, lower is better, printed with the checks it covered. Checks that could not run are left
out, never scored as clean.

A clean result bounds what was tried. It is not a proof that a grader is sound.

## How it is tested

Every guard is tested from both directions: no correct grader may accept a grounded submission,
and a weak grader must still accept one. Each guard is verified by removing it and watching its
test fail.
