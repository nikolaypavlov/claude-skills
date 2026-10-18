# PCB Design

Three skills and four reviewer agents for hardware projects where the copper is
part of the circuit and the performance was predicted by simulation.

Extracted from a Ku-band receive antenna project, with the band, the materials
and the acceptance thresholds removed: those live in each project's
`spec/*.yaml`, which the skills read and never contain.

## Skills

| skill | use it for |
|---|---|
| `sim-loop` | solver in the loop: run contract, validation gates, optimizer discipline, anti-overfit, tolerance Monte Carlo |
| `pcb-design` | the board: parametric geometry to KiCad, fab profiles, stackup and impedance, finishes, round-trip gate, pre-order checklist |
| `rf-frontend` | the chain: noise budget and G/T, frequency plan, images and products, polarization and arrays, rejection budgets |

`sim-loop` is domain-neutral. It applies to FDTD, SPICE, FEM or any search over
simulated designs; the measured openEMS specifics sit in one of its references.

## Agents

| agent | blocking verdict | when |
|---|---|---|
| `pcb-design:rf-engineer` | FAIL | geometry, feed, frequency plan, noise budget or criteria changed; every milestone |
| `pcb-design:sim-auditor` | NOT TRUSTED | before trusting an optimization result; model, post-processing, objective or mesh rules changed |
| `pcb-design:circuit-reviewer` | FAIL | schematic, layout, footprint or power changed; before ordering |
| `pcb-design:manufacturing-engineer` | NOT READY | BOM, fab profile or board changed; before any order |

All four are read-only. They return a verdict and findings and never edit
project files; the main session applies fixes and reruns the reviewer that
raised the finding.

## Command

```
/pcb-design:init [project name]
```

Scaffolds `spec/` (targets, substrates, mesh rules, three fab profiles),
`runs/`, `reports/`, `DECISIONS.md`, `VALIDATION.md` and a brief skeleton. It
writes placeholders, never guessed numbers.

## The rule the whole plugin exists to enforce

Every number reported in prose, a table, a commit message or a review comes
from a run stored on disk, and names it. If a run did not happen, say so.

## Checks

Documentation-only plugin, so the checks are structural:

```bash
python3 scripts/check-structure.py                        # from this directory
uv run --with pyyaml python scripts/check-structure.py    # adds the YAML leg
```

It verifies that each skill's frontmatter name matches its directory, that no
reference is orphaned or dangling, that agents and the command carry the
frontmatter the harness reads, that each agent keeps its read-only contract,
that the templates parse, and that no file uses em dashes, curly quotes,
ellipsis characters, unicode bullets or non-breaking spaces.

## Layout

```
pcb-design/
├── skills/sim-loop/SKILL.md
│   └── references/{run-contract,validation-gates,optimizer,openems}.md
├── skills/pcb-design/SKILL.md
│   └── references/{fab-profiles,kicad-cli,stackup-impedance,dfm-order,ua-sourcing}.md
├── skills/rf-frontend/SKILL.md
│   └── references/{noise-budget,freq-plan,antenna-cp,filters}.md
├── agents/{rf-engineer,sim-auditor,circuit-reviewer,manufacturing-engineer}.md
├── commands/init.md
├── scripts/check-structure.py
└── assets/spec/{targets,substrates,mesh_rules}.template.yaml
    └── fab_profiles/{conservative,prototype_cn,ua_local}.yaml
```
