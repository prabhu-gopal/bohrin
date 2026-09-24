# How to add or change a weakness class

A weakness class is a permanent name for one kind of grader defect. Probes, findings, registry
records and fix guidance all point at it, so its ID must never change meaning. Read the rules
below before editing `src/bohrin/spec/weaknesses.toml`.

## Does it need a new class?

An ID is permanent, so a new one needs a **mechanism no existing class describes**. Before adding
one, check whether the defect is:

- an instance of an existing class (add a source to that class instead);
- a combination of existing classes (a finding can name the class that paid, and cite the other);
- about what an agent *said* rather than what the grader did wrong (not a grader weakness at all).

## Add a class

1. Take the next unused number. Numbers carry no meaning: do not choose one to sit near a
   similar class, and never reuse a number, even a deprecated one.
2. Add a `[[weakness]]` entry with every field:

   ```toml
   [[weakness]]
   id = "BGW-139"
   name = "Short name"
   family = "harness_tampering"          # one of [families]
   mechanism = "How a grader with this defect pays for the wrong thing."
   shapes = ["workspace", "container"]
   grounds = ["structural"]              # empty if the evidence is a statistic or a risk
   evidence = ["reproduction"]           # see EVIDENCE in bohrin/spec/weaknesses.py
   provides = ["template"]               # template, fact, statistic, or [] for definition only
   fix = "Static guidance that is true of any grader with this defect."
   sources = ["https://..."]
   ```

3. **Every source must show the technique itself**, not only where it could happen. Open each link
   and find the passage that supports the class before citing it.
4. **Describe the mechanism, never whose grader has it.** No project, benchmark or grader is named
   as defective in the mechanism or the fix.
5. Add the ID and name to `PUBLISHED` in `tests/test_weaknesses.py`. That list only ever grows.
6. If an existing crosswalk category now maps to the new class, update the crosswalk.
7. Regenerate the page and run the tests:

   ```console
   $ uv run python -m bohrin.spec > docs/WEAKNESSES.md
   $ uv run pytest
   ```

## Change a class

- **Allowed:** clarify the mechanism or fix, add or correct sources, add shapes, move the class to
  another family (families are views, not part of the ID).
- **Not allowed:** change what the class means, rename it, renumber it, or delete it. To retire a
  class, set `status = "deprecated"` and keep it in the list.
