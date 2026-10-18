---
name: sim-loop
description: |
  This skill should be used when a design project puts a numerical solver in
  the loop and every reported number must trace to a stored run: FDTD/EM
  simulation, SPICE, FEM, CFD, or any optimizer-driven search over a simulated
  design. It supplies the run contract, the validation gates that must pass
  before an optimizer is allowed to run, the inner/outer loop split, and the
  anti-overfit rules.
  Triggers (English or Ukrainian):
  - "set up a simulation loop", "closed simulation loop", "solver in the loop"
  - "can I trust this optimization result", "validation gates", "mesh convergence"
  - "run contract", "make runs reproducible", "resumable study"
  - "налаштуй цикл симуляції", "чи можна довіряти результату"
  - "гейти валідації", "збіжність сітки", "контракт прогону"
allowed-tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Agent"]
---

# Simulation loop discipline

A design driven by simulation fails in one of two ways: the solver answers a
different question from the one asked, or the answer is real but nobody can
say which run produced it. This skill is the set of rules that make both
visible. It is solver-agnostic; `references/openems.md` holds the measured
specifics for openEMS/FDTD.

Project-specific numbers (band, materials, acceptance thresholds, mesh rules)
never live in this skill. They live in the project's `spec/*.yaml`, which is
the authority. Run `/pcb-design:init` to scaffold that layout.

## The one rule everything else serves

Every number reported in prose, a table, a commit message or a review comes
from a run stored on disk, and names it. No estimates, no interpolation
between runs, no "expected" values. If a run did not happen, say so.

This is not bookkeeping. On the project this skill was extracted from, the
single most frequent defect found by review (seven separate occurrences) was a
headline number transcribed from a superseded run while the text cited the
current one. See `references/run-contract.md`.

## Shape of the loop

```
   spec/*.yaml  (typed, authoritative: targets, materials, process limits)
        |
        v
   [geometry/model]  params -> model (pure function, units asserted)
        |
        +-------------------------------+
        v                               v
   [solver model]                  [manufacturable artifact]
   mesh, ports, boundaries         CAD/netlist emitted from the same
        |                          params, verified by a round-trip gate
        v                               |
   [runner] -> runs/<run_id>/           |
        |      immutable, self-describing
        v                               v
   [post]  raw -> metrics        [independent re-read]
        |
        v
   [objective]  metrics -> scalar + constraint flags
        |
        v
   INNER LOOP (no LLM): search, fixed seed, resumable store, coarse model
        |
        v
   top-k -> fine model re-sim -> tolerance Monte Carlo -> report
        |
        v
   OUTER LOOP (you): read the report, write ONE decision to DECISIONS.md
   (narrow bounds, widen bounds, change topology, change material, stop)
```

The inner loop never calls a model. The outer loop never tunes parameters by
hand. Mixing them produces a search nobody can reproduce and decisions nobody
can audit.

## Before the optimizer runs

The optimizer is forbidden until the validation gates pass, because an
unvalidated model optimizes its own artifacts. `references/validation-gates.md`
gives the gate families, the one-variable-per-leg rule and the
`VALIDATION.md` table format. Short version:

1. Smoke: reproduce a published or known-answer case with the same pipeline.
2. Independent model: an analytic or closed-form cross-check of one quantity.
3. Discretisation convergence, one variable per leg (bulk, through-thickness,
   edge/feature refinement are three different legs).
4. Truncation: the stopping criterion converges the metric you are judged on,
   not a proxy.
5. Domain/boundary: moving the boundary does not move the answer.
6. Convention sanity: signs, handedness, units, reference impedance, tested
   non-circularly (a test fed by the formula it checks proves nothing).
7. Round trip: the emitted manufacturable artifact still matches the model.

Each gate records a run id. If the model or post-processing code changes after
a gate passed, rerun the affected gates.

## Rules that earn their keep

- Units in the key name (`f_center_hz`, `thickness_mm`), asserted at module
  boundaries. Never convert silently.
- Parameter bounds live in the schema, not in a comment and not in hope.
- `runs/` is immutable. Nothing edits a run after it is written, nothing
  deletes runs without asking the owner.
- A result that beats a physical bound (aperture limit, efficiency above 100 %,
  passivity) is a bug. Investigate before reporting.
- Interpolate before quoting a minimum, a resonance or a shift. A difference at
  or below one sample of the grid is not a measurement.
- A pass/fail gate that both candidates fail does not rank them. Say so.
- One change per decision. Never change the objective and the acceptance
  criteria in the same step, or the next study is uncomparable to every
  previous one.

## Decision log

`DECISIONS.md`, append-only, one entry per decision: date, what changed, why,
which run ids support it, what was rejected. Entries are numbered (`D-0001`)
so reviews and spec comments can cite them. When a criterion itself is found
infeasible, the amended criterion goes in `spec/`, and the arithmetic that
forced the amendment goes in the log. The spec wins over any prose brief; say
so once, in the brief.

## Review gate

Call the numerical auditor before trusting any optimization result, after
changes to the model, post-processing, objective or mesh rules, and when
results look too good:

```
Agent: pcb-design:sim-auditor
Blocking verdict: NOT TRUSTED
```

The auditor is read-only. It recomputes headline numbers from raw run data and
returns a verdict; the main session applies fixes and reruns it.

## References

- `references/run-contract.md` - run directory contract, run_id hashing traps,
  cache correctness, traceability recipe.
- `references/validation-gates.md` - gate families, legs, VALIDATION.md format.
- `references/optimizer.md` - inner-loop setup, objective-rule stamping,
  anti-overfit, tolerance Monte Carlo, outer-loop decisions.
- `references/openems.md` - measured openEMS/FDTD behaviour: energy criterion,
  Courant limit, plan-vs-realised mesh, nf2ff surfaces, angular-grid bias,
  raw-field recompute recipes.
