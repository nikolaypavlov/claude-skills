---
description: "Scaffold the spec, run and decision-log layout that the pcb-design, sim-loop and rf-frontend skills expect"
argument-hint: "[project name]"
allowed-tools: ["Bash", "Read", "Write", "Edit", "AskUserQuestion"]
---

You are scaffolding a hardware design project so the `pcb-design`, `sim-loop`
and `rf-frontend` skills have the files they read. The skills hold the method;
this command creates the project-specific files that hold the numbers. Nothing
in the skills is copied into the project except the templates named below.

## Phase 1: Check the target

Work in the current directory. Report what already exists before writing
anything:

```
spec/            spec/fab_profiles/   DESIGN_BRIEF.md
runs/            reports/             DECISIONS.md    VALIDATION.md
```

If any of them exist, list them and ask via AskUserQuestion whether to
**skip existing files** (default), **overwrite** the ones you name, or
**cancel**. Never silently overwrite a spec or a decision log.

## Phase 2: Ask what the project needs

One AskUserQuestion call, multiSelect, offering only what is missing:

- "Typed spec (`spec/targets.yaml`, `spec/substrates.yaml`)" - the
  authoritative targets and materials.
- "Fab profiles (`spec/fab_profiles/`)" - conservative, prototype_cn,
  ua_local.
- "Simulation loop (`spec/mesh_rules.yaml`, `runs/`, `reports/`,
  `VALIDATION.md`)" - only if a solver is in the loop.
- "Decision log (`DECISIONS.md`)" - recommended always.
- "Brief skeleton (`DESIGN_BRIEF.md`)" - the prose brief the reviewer agents
  read first.

Then ask, in the same call, which fab profile is the project default
(conservative unless the user says otherwise).

## Phase 3: Copy the templates

Templates live in this plugin's `assets/spec/`. Resolve that directory from
this command's own path, and copy:

```
assets/spec/targets.template.yaml      -> spec/targets.yaml
assets/spec/substrates.template.yaml   -> spec/substrates.yaml
assets/spec/mesh_rules.template.yaml   -> spec/mesh_rules.yaml
assets/spec/fab_profiles/*.yaml        -> spec/fab_profiles/
```

Copy them verbatim, then fill only what the user has told you: project name,
band edges if known, the default profile name. Leave every unknown value at its
placeholder (`0.0`, `null`, `unknown`). A placeholder is honest; a guessed
number becomes a design assumption nobody remembers making.

Create empty `runs/` and `reports/` with a `.gitkeep`, and add to
`.gitignore`: nothing by default. Run artifacts are evidence, so decide with
the user whether `runs/` is tracked (small metrics and manifests) or ignored
(large field dumps) - if ignored, say in the brief where runs are archived
instead.

## Phase 4: Write the logs and the brief

`DECISIONS.md`:

```markdown
# Decision log

Append-only. One entry per decision, newest at the bottom. Every entry names
the runs that support it. `spec/` wins over this log and over the brief; this
log explains why `spec/` says what it says.

## D-0001: <title>  (<YYYY-MM-DD>)

**Changed:** <what changed, which file>
**Why:** <the argument, with the arithmetic if a number moved>
**Evidence:** <run ids, report paths>
**Rejected:** <what was considered and not chosen>
```

`VALIDATION.md`:

```markdown
# Validation gates

The optimizer is forbidden until every gate below passes. Each row needs a run
id. Rerun gates after any change to the model builder or post-processing.

| gate | what it proves | tolerance | run ids | verdict |
|---|---|---|---|---|
| 1 smoke | the pipeline reproduces a known answer | | | NOT RUN |
| 2 independent model | one quantity cross-checked | | | NOT RUN |
| 3 convergence | one leg per variable | | | NOT RUN |
| 4 truncation | the stopping rule converges the graded metric | | | NOT RUN |
| 5 domain | the boundary does not move the answer | | | NOT RUN |
| 6 conventions | signs and units, tested non-circularly | | | NOT RUN |
| 7 round trip | emitted CAD matches the model | | | NOT RUN |
```

`DESIGN_BRIEF.md` skeleton with these headings and one line of guidance each:
goal and figure of merit; acceptance criteria (pointing at `spec/targets.yaml`
as authoritative); physical and manufacturing constraints; environment and
sourcing constraints; architecture and pipeline; validation gates; review gates
and which agent blocks what; milestones; test plan.

Include in the brief, verbatim, the rule the reviewers enforce:

> Every number reported in prose, a table, a commit message or a review comes
> from a run stored on disk and names it. If a run did not happen, say so.

## Phase 5: Report

Print what was written, what was skipped, and the three things the user must
fill before the skills are useful: the band or operating point in
`spec/targets.yaml`, the acceptance criteria with their rationale, and the fab
profile that will actually build the board. Name the reviewer agents that are
now available (`pcb-design:rf-engineer`, `pcb-design:circuit-reviewer`,
`pcb-design:manufacturing-engineer`, `pcb-design:sim-auditor`) and the
blocking verdict of each.

Do not create source code, a solver model or a KiCad file. This command
scaffolds the contract, not the implementation.
