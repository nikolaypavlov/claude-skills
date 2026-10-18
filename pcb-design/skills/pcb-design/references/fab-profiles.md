# Fab profiles

One file per fab in `spec/fab_profiles/<name>.yaml`. The point of the format is
that an unverified capability is visible in the file rather than assumed in
someone's head.

## Schema

```yaml
schema_version: 1
name: conservative
description: <one line: which fab, which advertised process>
confirmed_by_fab: false        # true only with a written quote or datasheet
status: placeholder_unverified  # omit once confirmed

design_rules:
  min_trace_mm: 0.20
  min_space_mm: 0.20
  min_drill_mm: 0.30
  min_annular_ring_mm: 0.15
  board_outline_tolerance_mm: 0.10
  min_copper_to_edge_mm: 0.30

tolerances:                 # the Monte Carlo draws from here
  etch_mm: 0.05             # +/- on every etched dimension
  dk_abs: 0.05              # +/- on design Dk
  thickness_pct: 10.0       # +/- on core thickness
  registration_mm: 0.075    # layer to layer, matters for stacked topologies
  bow_twist_pct: 0.75       # % of board diagonal; IPC-6012 default acceptance

stackup:
  max_cores: 1
  bondply_available: false
  copper_weight_um: [35]
  laminates: [RO4003C, RO4350B]   # or unknown

constraints:
  plated_vias_inside_radiating_patches: false
  blind_buried_vias: false

finishes: [immersion_silver, immersion_tin]

copper_foil_type: unknown   # reverse_treated | standard_ed | unknown
max_feed_impedance_ohm: 100.0
max_feed_impedance_note: >
  Derived from min_trace_mm on the default stackup. Quarter-wave transformers
  above this impedance are not available from this fab.

open_questions:
  - "<what must be asked before an order>"
```

## The three starting profiles

`assets/spec/fab_profiles/` in this plugin ships them; `/pcb-design:init`
copies them into a project.

- **conservative** - the default. Deliberately pessimistic: assume it until a
  specific fab confirms better in writing. Single core, no bondply, 0.20 mm
  trace and space, 0.05 mm etch tolerance, no plated vias in radiating copper.
- **prototype_cn** - a Chinese prototype house at its advertised process:
  0.15 mm trace and space, 0.04 mm etch, two cores, bondply available, ENIG
  offered. Bare boards only if RF parts must not be assembled abroad.
- **ua_local** - a local fab whose capability is not established. Every
  capability field is `unknown` on purpose, so a run declaring this profile is
  visibly unverified. The manufacturing reviewer fills it from a real quote.

Keep the pessimistic profile as the default and treat any better number as a
decision with a source.

## How a profile reaches the results

```
  profile.design_rules  -> parameter schema bounds (refuse, do not clamp)
  profile.tolerances    -> tolerance Monte Carlo draws
  profile.copper_foil   -> surface roughness -> conductor loss
  profile.stackup       -> which topologies are even buildable
  profile.finishes      -> conductivity of exposed copper in the model
  profile.name          -> recorded in every run manifest and every report
```

Two failure modes seen in practice:

1. **Declared tolerances that nothing samples.** A profile listed five
   tolerance terms while the Monte Carlo code sampled two. The reported yield
   belonged to a process that does not exist. Check which terms the code reads,
   not which terms the file declares.
2. **A capability assumed from the best case.** A substrate spec assumed the
   best copper foil available while no profile committed any fab to a foil
   type. The spread between the best and worst foil was worth about 1.5 dB of
   conductor loss. If the foil is unknown, the roughness model must use the
   worst value.

## Derived limits worth writing down

- Narrowest realisable line on the chosen stackup -> maximum synthesisable
  impedance. On 0.508 mm RO4003C: 0.20 mm minimum trace gives about 100 ohm,
  0.15 mm gives about 120 ohm. A 120 ohm transformer is simply not available at
  the 0.20 mm rule.
- Minimum feature size versus etch tolerance -> the finest mesh or model
  resolution that means anything. A model resolved finer than the etch
  tolerance is modelling noise.
- Registration tolerance -> whether a stacked or bonded topology can hold its
  alignment at all, and what the Monte Carlo must draw for lateral offset.
