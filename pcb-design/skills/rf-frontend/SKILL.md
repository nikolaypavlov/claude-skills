---
name: rf-frontend
description: |
  This skill should be used for the RF chain arithmetic of a receive or
  transmit front end: noise budget and G/T, system temperature, frequency plan
  with images and mixing products, LO and reference phase noise, filter
  rejection budgets, antenna polarization and array questions. Use it
  alongside the pcb-design skill when the chain lives on a board.
  Triggers (English or Ukrainian):
  - "noise budget", "G/T", "system temperature", "noise figure cascade"
  - "frequency plan", "image frequency", "mixing products", "LO", "phase noise"
  - "axial ratio", "circular polarization", "RHCP", "array spacing", "grating lobe"
  - "filter rejection", "out of band", "isolation"
  - "шумовий бюджет", "частотний план", "образ", "осьове відношення"
  - "кругова поляризація", "крок решітки", "режекція фільтра"
allowed-tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch", "Agent"]
---

# RF front end

This skill holds the arithmetic and the conventions that decide whether a front
end meets its figure of merit. The project's own band, targets and thresholds
live in `spec/targets.yaml`; the sky or environment model lives in its own spec
file and is a MODEL, which every report quoting it must say.

## Pick the figure of merit first, then design for it

A receive chain is judged on G/T, not on gain. That changes what is worth
optimizing: back lobes and low-elevation side lobes cost twice (less gain where
the signal is, more warm ground noise), loss before the first amplifier adds
noise directly, and a finite ground plane becomes an optimization parameter
rather than a detail.

A receive-only design also removes work: power handling, thermal design of the
radiator, intermodulation under high power, transmit/receive isolation,
emission masks and transmit certification. Do not spend effort there, and do
not import a transmit-oriented material choice for a receive-only board.

```
   antenna  ->  feed loss  ->  LNA  ->  filter  ->  mixer  ->  IF  ->  SDR
      |            |            |         |          |
     T_A          adds        T_LNA    rejection    image,
   pattern-      noise      dominates   budget    products
   weighted      directly    T_sys                 (freq plan)
```

## The three traps that make a noise budget wrong

1. The pattern weight for antenna noise temperature is DIRECTIVITY, not gain.
   Weighting by gain and then applying efficiency downstream counts efficiency
   twice; at 70 % efficiency that understates the temperature by 30 % and makes
   the acceptance gate about 30 % easier than intended.
2. The weight is TOTAL POWER, not the co-polar pattern. Thermal emission is
   unpolarized, so a co-polar weighting understates the temperature by up to
   3 dB, and it does so worst in the back lobe and horizon side lobes, which
   are exactly the directions that matter.
3. Dissipative loss is excluded from the antenna temperature and enters the
   system temperature downstream, so that a failure points at one cause.

Full chain, formulas and the normalisation test: `references/noise-budget.md`.

## Frequency plan is a tool, not a paragraph

Write the plan as unit-tested code that fails a plan rather than as prose: for
each channel compute the IF, the image, mixing products up to order five, LO
leakage and reference harmonics, and fail when anything lands in band without
the required margin. `references/freq-plan.md` has the rules, including the
ones that are counterintuitive (a reference-harmonic test must test LEVEL, not
presence, and a high-side LO can put the image on top of a nearby transmitter).

## Polarization and arrays

Handedness sign errors are the single most repeated defect in circular
polarization code, and axial ratio is blind to them. Derive the convention from
the time-domain rotation sense every time instead of trusting a docstring, and
make sure the test is not fed by the formula it checks.
`references/antenna-cp.md` has the derivation, the sequential-rotation checks,
array spacing limits and the bounds that decide whether a criterion is
achievable at all.

## Rejection is a chain requirement

A rejection number belongs to the chain from the antenna port to the mixer
input, apportioned between the antenna's own roll-off and the filter. Until the
simulated out-of-band response exists, the split is unknown and must be written
as unknown. `references/filters.md`.

## Review gate

```
Agent: pcb-design:rf-engineer
Blocking verdict: FAIL
```

Call it after any change to geometry, feed network, frequency plan, noise
budget or acceptance criteria, and before every milestone sign-off.

## References

- `references/noise-budget.md` - T_A, T_sys, G/T, noise match, sky models.
- `references/freq-plan.md` - LO choice, images, products, phase noise,
  reference transport, coherence.
- `references/antenna-cp.md` - handedness, axial ratio, sequential rotation,
  array spacing, feasibility bounds, in-situ penalties.
- `references/filters.md` - rejection budgets, out-of-band reporting,
  apportionment.
