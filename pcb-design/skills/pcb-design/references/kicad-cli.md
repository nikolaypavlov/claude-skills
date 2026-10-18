# KiCad from a headless pipeline

`kicad-cli` ships with KiCad 9 and 10. On macOS it lives in the app bundle, so
look it up rather than assuming it is on PATH:

```
kicad-cli
/opt/homebrew/bin/kicad-cli
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
/usr/bin/kicad-cli
```

## The commands the flow needs

```bash
# electrical rules on the schematic
kicad-cli sch erc --format json -o build/erc.json board.kicad_sch

# design rules on the board: zero errors is the deliverable
kicad-cli pcb drc --format json \
  --severity-error --severity-warning --exit-code-violations \
  -o build/drc.json board.kicad_pcb

# fabrication outputs
kicad-cli pcb export gerbers -o build/gerbers board.kicad_pcb
kicad-cli pcb export drill   -o build/gerbers board.kicad_pcb

# does KiCad itself accept the emitted footprint? fp works on a library dir,
# so copy the .kicad_mod into a temporary <name>.pretty first
kicad-cli fp export svg --output build/svg tmp/roundtrip.pretty
```

Parse the JSON report rather than keeping a bare pass/fail: a reviewer is not
allowed to accept a waiver without a written reason, which needs the violation
list. `--exit-code-violations` makes the exit code usable in CI, and the
report path is where the detail is.

If `kicad-cli` is absent, report the check as skipped with a reason. Never
report a skipped check as a pass.

## Emitting a footprint or board

Write the s-expression yourself when the output is a handful of polygons. The
reasons, from a project that tried the alternatives: an antenna-CAD library may
not support the topology at all, an IPC-based API needs a running KiCad while
the pipeline is headless, and a dependency's intermediate representation is one
more thing to keep aligned with the geometry.

Mechanics that matter:

- **Coordinates.** A mathematical geometry (x right, y up, mm, centred) emitted
  into KiCad's screen frame (x right, y down) means negating every y on the way
  out and negating back on the way in.
- **Precision.** KiCad's own coordinate resolution is 1 nm. Emitting six
  decimal places in mm (1 pm) makes the round trip limited by the format rather
  than by the emitter, with four orders of magnitude of headroom against a
  1 um gate tolerance.
- **Layers.** Name them explicitly (`F.Cu`, `B.Cu`); a single-core board uses
  the two outer layers.

## The round-trip gate

```
geometry -> emitted footprint -> re-read polygons -> compare to geometry
                                                     within 1 um
```

What the gate proves: the footprint the fab will build from is the same shape
the solver simulated. What it does not prove: that the file is valid KiCad, or
that the geometry is right. Pair it with `fp export svg` for validity and with
the design review for correctness.

Keep the reader independent of the writer (see the skill), and keep the
tolerance in the project's spec so it can be tightened without touching code.

## Build directory

Emitted artifacts are derived files: `build/` or `runs/<id>/`, not the
repository root, and not tracked unless an order was placed from them. If a
board was ordered, archive exactly what was sent, with the profile name and the
date, because that is the only thing a failure analysis can compare against.
