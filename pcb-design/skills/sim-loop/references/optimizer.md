# Optimizer: inner loop, anti-overfit, outer loop

## Inner loop

- No model in the loop. A search driven by an LLM is not reproducible.
- Fixed seed, persistent store (for example Optuna with SQLite), resumable.
- Coarse model only. The coarse rule is frozen by the convergence gate, not
  chosen for speed after the fact.
- Prune early on a cheap, monotone signal, and record the pruning rule.
- Per-run wall-time limit and per-study trial limit, both logged. Compute the
  wall-time limit from the CONTENDED solve rate if several solves run at once:
  measured, a solve under ten-way contention ran 3.0 times slower than a lone
  solve, so a limit set from the solo rate kills healthy runs.
- The objective lives in one file with unit tests. Constraint penalties are
  part of it and are tested the same way.

## The objective is versioned state

An objective-rule change leaves every existing study graded under the old rule
with nothing in the study saying so. Measured: resuming a study after a rule
change mixed rules inside one study, and regrading the stored trials under the
new rule reshuffled every top-5 (none of the five previously verified
candidates stayed in the top five).

Stamp it:

- Write a hash of the objective rule into the study's user attributes.
- Refuse to resume or to re-verify a study whose stamp differs.
- Regrade stored trials from their stored raw results instead of re-solving.
  Regrading is cheap and exact if the run directories hold the raw data; verify
  the regrade script reproduces the stored objective for one trial to 1e-6
  before trusting its ranking.

## Anti-overfit

- Re-simulate the top k on the fine rule. A candidate that passes only on the
  coarse rule is rejected, not reported with a caveat.
- Report the coarse-to-fine delta per candidate. Winner's curse is visible
  there: in one study the two coarse winners lost 0.08 to 0.11 dB on the fine
  mesh while three others lost under 0.003 dB.
- Split a coarse-to-fine delta into model error and sampling error by regrading
  both runs on their COMMON frequencies and angles. If the sampling delta is
  zero, the gap is real discretisation error.
- Watch for exploitation of artifacts: an optimum sitting on a parameter bound,
  features smaller than two cells, results that jump between neighbouring
  parameter values, a metric that improves as the mesh gets worse.
- Check every result against a physical bound before reporting it.

## Tolerance Monte Carlo

- Mandatory for finalists, n >= 30, drawn from the declared process profile's
  tolerances (see the pcb-design skill's `references/fab-profiles.md`).
- Draw every term the process actually varies. A Monte Carlo that samples only
  two of five declared tolerance terms reports a yield for a process that does
  not exist; check which terms the code samples against the profile, not
  against the profile's comments.
- Add known systematic bias as a model-uncertainty term. If a convergence study
  measured the production rule to sit 0.35 % low against the extrapolated
  answer, that bias belongs in the draw, with its source decision cited.
- Prefer higher yield over higher nominal performance, and say which candidate
  wins under each rule.
- A mesh or model that tracks a geometric edge at a fraction of its motion
  attenuates the sensitivity the Monte Carlo is measuring. Sweep one tolerance
  term across its range once and confirm the model responds smoothly before
  trusting a yield number.

## Outer loop

After each study, read the report and write exactly one decision:

- narrow bounds, widen bounds, change topology, change material, stop.
- Justify it with run ids.
- Never change the objective and the acceptance criteria in the same step.
- If the study's best candidate fails a criterion, the decision is about the
  design or about the criterion, and either is legitimate. Changing the
  criterion requires the arithmetic that shows it was infeasible, in the log,
  and the amended value in `spec/`.
