# Validation gates

Gates are the price of admission for an optimizer. Each gate is a run with an
id, a recorded tolerance and a verdict in `VALIDATION.md`. The thresholds
belong in `spec/`, not here: a project graded at 0.2 dB and a project graded at
5 % need the same gate families with different numbers.

## Families

**1. Smoke / known answer.** Reproduce a published case, a tutorial case or an
analytically known result through the same pipeline that will produce the
design numbers. The point is the pipeline, not the physics.

**2. Independent model.** Cross-check one quantity against a model that shares
no code with the solver: a transmission-line model, a closed-form expression, a
hand integral. State the agreement as a percentage and the tolerance claimed.

**3. Discretisation convergence, one variable per leg.** A single "fine vs
extra fine" comparison is not a convergence study. Separate legs:

```
  leg             what changes            what it catches
  -------------   ---------------------   -----------------------------------
  bulk            cells per wavelength    volumetric discretisation error
  through-thick   cells across the thin   reactance / loss at the interface
                  dimension
  edge/feature    minimum cell at         the error that bulk refinement is
                  material edges          blind to
```

Measured consequence of skipping the edge leg: all rules shared one minimum
cell and the same pinned edge sites, so bulk convergence read 0.02 % while the
edge treatment carried 1 to 2 % of resonance. Three points, not two, give an
observed order of convergence and a Richardson estimate; two points cannot say
whether a shift is converging.

**4. Truncation / stopping criterion.** The criterion must converge the metric
the project is graded on. Measured: at a -40 dB energy stop, resonance was
converged but the S11 depth still carried 0.217 dB of truncation error, more
than the entire 0.2 dB tolerance of two other gates, while mismatch efficiency
carried 0.0073 dB. A stopping-criterion study is one long run truncated at
several lengths, not several runs.

**5. Domain and boundary.** Move the absorbing boundary or the domain margin
and require the answer not to move. Watch for confounding: if the integration
surface or the sampling grid is defined relative to the domain, moving the
boundary moves them too and the controlled variable was not controlled.

**6. Convention sanity.** Signs, handedness, polarization basis, reference
impedance, dB versus linear, directivity versus gain. A unit test that feeds
the field which the formula itself declares correct is circular and passes
either way. Build the quantity from first principles in the time domain, or
assert against an independent implementation.

**7. Round trip to the manufacturable artifact.** Re-read the emitted CAD or
netlist with an independent reader and compare it to the model it came from,
within a stated tolerance. This gate is only meaningful if the artifact is
emitted from the parametric model and never edited downstream.

## Rules

- A gate needs a run id. A gate without one is an opinion.
- Rerun gates 2 to 6 after any change to the model builder or post-processing.
- Grade a gate on the quantity the project is judged on. A gain gate evaluated
  at a fixed frequency off resonance is a resonance test in disguise: decompose
  the delta into directivity, efficiency and mismatch before accepting it.
- Interpolate minima and resonances before quoting a shift. A reported spread
  of exactly one grid step is the quantisation floor, not a result.
- Vary one thing per leg. If a leg changes two settings, a failure cannot be
  attributed.
- If both options under comparison fail the gate, the gate does not choose
  between them. Report that explicitly rather than letting the lesser failure
  look like a pass.
- A gate may legitimately end in a recorded deviation (the rule is unreachable
  and the cost of reaching it is worse than the deviation). Record it in
  `DECISIONS.md` with the measured value, and keep the required value in the
  spec next to the achieved one.

## VALIDATION.md format

```markdown
## Gate 3 - discretisation convergence

| leg | rule A | rule B | metric | delta | tolerance | run ids | verdict |
|---|---|---|---|---|---|---|---|
| bulk | fine | extra_fine | f_res | +0.02 % | 0.5 % | abc123 / def456 | PASS |
| edge | 0.15 mm | 0.10 mm | f_res | -1.8 % | 0.5 % | 789abc / 012def | FAIL |

Evidence: metrics.json of each run; resonance interpolated parabolically.
Open items: <what is unresolved, and what run would resolve it>
```

Keep the gate table generated from the reports where possible, so a stale
number cannot survive in prose. Where it is written by hand, re-read the cited
run before every milestone sign-off.
