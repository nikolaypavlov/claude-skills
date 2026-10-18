# Run contract

A run directory is the unit of evidence. It must be readable years later by
someone who has only the directory.

## Contents

```
runs/<run_id>/
  request.json        every input: params, model settings, solver settings
  params.json         the design parameters alone (convenience, same values)
  mesh.json           the discretisation PLAN (see the warning below)
  manifest.json       spec_hash, git_sha / code_version, solver version, host
  metrics.json        post-processed results, the only numbers quoted anywhere
  <raw>               port data, field dumps, whatever post-processing reads
  log.txt             solver stdout
  wall_time_s         and the solver's own reported time, if they differ
  run_id              the id as a file, so a copied directory stays identifiable
```

Rules:

- Immutable. Nothing rewrites a run. A corrected post-processing pass writes a
  new run or a separate regrade file that names the source run.
- Self-describing. A reader must not need the repository to know what ran.
- `metrics.json` is the only source of quotable numbers, and the run directory
  name is the only reliable identity (see below).

## run_id and the cache

`run_id` is a short hash of everything that changes the result: parameters,
model settings, solver settings, code version. If the directory exists with
valid results, reuse it.

Three traps, all measured:

1. **Do not fold the working-tree state into the id.** A provenance hash built
   from `git status --porcelain` lists the run artifacts the solver itself
   writes under a tracked `runs/` tree. Every completed run then changes the
   code version, so every later request gets a new id: 23 runs produced 23
   distinct ids, the cache never hit once, and nine bit-identical solves ran.
   Exclude `runs/` from the provenance hash, resolve the id once per request
   and reuse it.
2. **An id that is a property recomputed on access is not an identity.** If the
   id is recomputed when a report is written, it is the id of a later state,
   so published ids name directories that do not exist. Write the id into the
   directory and cite `run_dir`.
3. **A cache hit must re-validate under the same rules as a fresh run.** If the
   hit path omits checks (exact stopping criterion, expected cell count,
   expected timestep), re-validation can only ever loosen a verdict. Check the
   argument list of the cache-hit path against the fresh path.

Also: untracked file names are visible to `git status` but their contents are
not in `git diff HEAD`, so a provenance hash over the diff does not pin a
script that was present at run time. To verify "commit X is the tree that
ran", rebuild the tree in a scratch clone and hash it the same way the
manifest does.

## The discretisation plan is not the discretisation

If the model builder calls solver-side helpers after serialising the mesh plan,
the solver re-adds lines the plan dropped. Measured: a plan of 62x66x18 cells
ran as 68x72x18, and the plan's timestep was 4.7 times the solver's actual
timestep, because the realised minimum cell was 0.0103 mm against a declared
floor of 0.05 mm.

Ground truth is the solver's own log (dimensions line) and its stats file
(timestep). Record the realised minimum cell and the achieved grading ratio in
`mesh.json` next to the planned ones, and treat a deviation as a recorded
deviation with a decision entry, not as a silent one.

## Traceability recipe

For every headline number in `VALIDATION.md`, `DECISIONS.md` or a report:

1. Open the `metrics.json` of the run that the text cites, not of whatever run
   is open.
2. Recompute at least two numbers from raw data, not from `metrics.json`.
3. Check mutual consistency of related quantities. For an RF port, reported
   `Zin` and `s11_min_db` must agree through `|(Z - Z0)/(Z + Z0)|`; that single
   check catches a transcription instantly.
4. Check the whole paragraph, not one number. The recurring failure mode is a
   paragraph rewritten to fix one stale number while three others stay stale.
5. Grep every sentence attributed to the brief or the spec. A decision resting
   on a quotation that does not exist in the source has been found more than
   once.

## Reporting a run that must not be trusted

Runs are excluded, never deleted: list the run id and the reason in the review
or in `VALIDATION.md`. Common exclusions are a run that hit the timestep limit
instead of its stopping criterion, a run whose declared settings do not match
the solver log, and a run whose directory identity cannot be established.
