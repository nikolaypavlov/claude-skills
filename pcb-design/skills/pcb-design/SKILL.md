---
name: pcb-design
description: |
  This skill should be used when designing, reviewing or ordering a printed
  circuit board where the copper geometry matters electrically: RF and
  microwave boards, controlled-impedance stackups, antennas, and any board
  whose performance was predicted by simulation. It covers the parametric
  geometry to KiCad flow, fab profiles and their tolerances, stackup and
  impedance, surface finish and mask rules, the round-trip gate, and the
  pre-order checklist.
  Triggers (English or Ukrainian):
  - "design a PCB", "RF board", "controlled impedance", "stackup"
  - "emit a KiCad footprint", "run DRC", "export gerbers", "ready to order"
  - "fab rules", "fab profile", "etch tolerance", "surface finish"
  - "спроєктуй плату", "стек плати", "правила фабрики", "готово до замовлення"
  - "виведи KiCad", "перевір DRC", "гербери"
allowed-tools: ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Agent"]
---

# PCB design with the geometry as the source of truth

For a board whose copper is part of the circuit, the CAD file is an output, not
a design. The design is a parametric model; KiCad holds what that model emitted.
This is what makes a round-trip check meaningful and what keeps the simulated
structure and the fabricated structure the same object.

Project-specific values (materials, band, acceptance thresholds, the fab that
will build it) live in the project's `spec/*.yaml`. Run `/pcb-design:init` to
scaffold it. This skill holds the method and the traps.

## Flow

```
   spec/*.yaml  +  params
        |
        v
   geometry(params) -> shapes          pure function, mm, units asserted
        |
        +---------------------------------+
        v                                 v
   solver model                      CAD emitter
   (see the sim-loop skill)          .kicad_mod / .kicad_pcb
        |                                 |
        |                                 +-- kicad-cli sch erc
        |                                 +-- kicad-cli pcb drc
        |                                 +-- kicad-cli pcb export gerbers
        |                                 +-- kicad-cli pcb export drill
        |                                 |
        v                                 v
   metrics                           independent re-read
        |                            (own reader, not the writing library)
        +------------> round-trip gate <---+
                       polygons match within a stated tolerance
```

Rules that make the flow hold:

- The emitter is one-way. Nothing is edited in KiCad and fed back. If a change
  is needed, it is a change to the parametric model.
- The round-trip reader is independent of the writer. A round trip through the
  same library mostly tests that library's own symmetry. A short
  s-expression reader for polygon coordinates has no version-compatibility risk
  and is the honest check; let KiCad itself prove the file is valid KiCad
  (`kicad-cli fp export svg` has to load a footprint to render it).
- Watch the coordinate convention. A geometry with y up emitted into KiCad's y
  down means every y coordinate is negated on the way out and negated back on
  the way in; a missed flip shows up as a mirrored polygon, which is exactly
  what the gate is for.
- Every run and every emitted artifact declares which fab profile it was built
  against.

## Fab profile is an input, not an afterthought

One YAML file per fab, in `spec/fab_profiles/`: design rules, tolerances,
stackup capability, allowed finishes, foil type, derived limits. Every
optimization run declares its profile, and the tolerance Monte Carlo draws from
that profile. A profile that no fab has confirmed says so in the file
(`confirmed_by_fab: false`), so an unverified assumption is visible rather than
quietly optimistic.

The profile also sets what the parameter schema may synthesise: the narrowest
realisable line sets the highest feed impedance available, so quarter-wave
transformers above that impedance do not exist for that fab. Enforce it in the
schema, not in a comment.

Details and the three starting profiles: `references/fab-profiles.md`.

## Electrical rules that bite

- Continuous reference plane under every controlled-impedance trace; a plane
  break is a series inductance and a radiator.
- Via fence and stitching pitch set against the highest frequency present, not
  the operating band, and stated in the dielectric's own wavelength.
- Keep the mask off radiating and feed copper, or model it. An unmodelled mask
  is unaccounted detuning plus loss, and a fab masks everything unless told
  otherwise.
- Surface finish is a conductivity change on the exposed copper, and it plates
  only exposed faces. HASL is unacceptable on RF copper. ENIG needs nickel's
  permeability for the actual process before it can be modelled honestly.
- Copper foil type drives surface roughness, which drives conductor loss. If no
  fab has confirmed the foil, assume the worst one.

`references/stackup-impedance.md` has the numbers, the models and their
validity limits.

## Before ordering

Work through `references/dfm-order.md`. The gate is not "DRC passes": it is
that the ordered artifact matches the simulated geometry, the profile the
simulation used is the profile the fab will run, the tolerance study used that
profile, and every part has a source. For sourcing from Ukraine, see
`references/ua-sourcing.md`.

## Review gates

```
Agent: pcb-design:circuit-reviewer        blocking verdict: FAIL
  after schematic, layout, footprint or power changes; before ordering

Agent: pcb-design:manufacturing-engineer  blocking verdict: NOT READY
  after BOM, fab profile or board changes; before any order

Agent: pcb-design:rf-engineer             blocking verdict: FAIL
  (rf-frontend skill) after geometry, feed, frequency plan or criteria changes
```

All three are read-only reviewers: they return a verdict and findings, never
edit project files. The main session applies fixes and reruns the reviewer that
raised the finding.

## References

- `references/fab-profiles.md` - profile schema, the three starting profiles,
  how tolerances reach the Monte Carlo.
- `references/kicad-cli.md` - the exact commands, emitter and round-trip
  mechanics, DRC and ERC handling.
- `references/stackup-impedance.md` - impedance, roughness, finishes, mask,
  vias, connector transitions.
- `references/dfm-order.md` - pre-order checklist, cost at 1/10/100, what
  changes at volume.
- `references/ua-sourcing.md` - building and ordering from Ukraine.
