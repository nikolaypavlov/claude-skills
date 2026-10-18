# openEMS / FDTD: measured behaviour

Everything here was confirmed against raw solver logs, port data and field
dumps on openEMS v0.37 during one Ku-band project. Treat it as measured, not
folklore, and re-verify on a different version. Numbers are from that project's
structures; the mechanisms generalise, the magnitudes do not.

## Stopping criterion and energy

- The energy end criterion is evaluated at the progress-report cadence (about
  4 s of wall time), not on a timestep stride. `timesteps_executed` and
  `final_energy_db` are therefore sampling artifacts: the same physics reported
  4.81x to 6.98x the excitation length and -42.15 to -63.34 dB final energy
  across engines. Never quote either as "timesteps needed to converge", and
  never read final-energy differences as engine or mesh quality.
- `--exact-endcriteria` makes the stopping timestep deterministic (evaluation
  at `floor(TS/nyquist)*nyquist`). To prove the flag took effect, group the
  energies printed in progress lines by that expression: every sample collapses
  to one value per evaluation point. Also check `stop_timestep % nyquist == 0`.
- The energy signal is not monotone: the envelope reverses repeatedly, with
  peak-to-trough swings of about 4 dB against a decay of about 3.9 dB per 1000
  timesteps. The uncertainty on "when did it decay N dB" is the swing divided
  by the slope, about +/-1000 timesteps, not the evaluation interval.
- An energy stop does not mean the metrics converged. See the truncation gate
  in `validation-gates.md`.
- Probe output is decimated to Nyquist/4 (for example 148520 timesteps gave 377
  samples, stride 395). Several runs that differ only in stopping criterion are
  bit-identical prefixes of the longest one, so a criterion sweep is one run
  plus truncation, and repeats carry zero information.

## Engines

- All engines (`basic`, `sse`, `sse-compressed`, `fastest`, multithreaded)
  produce bit-identical port time series to the last printed digit. "N engines
  agree" is one physics result, not an independent check. If they ever disagree
  on port data, that is a real bug.
- They do not agree on the global energy sum (0.12 to 0.25 % apart, consistent
  with a different reduction order in single precision), so "numerically exact"
  is defensible for port quantities only.
- `fastest` is an alias for compressed SSE plus multithreading with auto thread
  tuning. It can retune mid-run and stay there, so its end-to-end rate is a
  phase mixture, not a rate. Pass the engine explicitly and read
  `Multithreaded engine using N threads` from the log rather than trusting a
  `threads` field in a manifest.
- Engine-identification regexes fail silently: the log line differs per engine
  (`enabled basic engine`, `enabled compressed sse engine`, `enabled
  multithreading`, and nothing at all for the alias). Identify from
  `Create FDTD operator (...)` instead, and make a missing identification an
  error, not an absent dict key.
- Threading one solve is a poor trade: on one host an 8-thread engine measured
  5x slower than one thread, and aggregate throughput scaled with concurrent
  single-threaded solves instead (efficiency fell from 94 % at one solve to
  32 % at ten). Leave one core for the orchestrator and post-processing.

## Timestep and mesh

- The timestep follows the anisotropic Courant limit
  `dt <= 1/(c*sqrt(1/dx^2 + 1/dy^2 + 1/dz^2))`, not `d_min/(c*sqrt(3))`. On a
  thin-substrate graded mesh the cubic form was 32 % low, and the error is
  row-dependent, so it also distorts ratios between mesh variants. openEMS uses
  the Rennings_2 method, which allows dt at or slightly above the Courant value.
- Useful asymmetry: refining laterally from lambda/20 to lambda/30 cost 7 % of
  the timestep, while refining a metal-edge cell to 0.05 mm cut it by 5.5x.
  Lateral density is nearly free; edge refinement is what buys the step count.
- Set the minimum cell against the manufacturing tolerance, not against the
  solver. A 0.05 mm cell on a process with +/-0.05 mm etch tolerance meshes
  manufacturing noise.
- `AddEdges2Grid` applies the thirds rule with MIRRORED offsets at the two
  edges of a shape: `{a + res/3, a - 2res/3}` at the lower edge and
  `{b - res/3, b + 2res/3}` at the upper. A planner that applies one offset
  pattern to every edge agrees at upper edges only, and the solver then inserts
  its own lines res/3 away from the planner's. Pick one owner of edge lines:
  either the plan owns them all and the solver-side helper is not called, or
  the opposite.
- `mesh_hint_from_primitive` returns nothing for a POLYGON, so a
  non-rectangular shape gets no solver-side edge refinement at all. On
  polygons, realised grading and minimum cell can be far from the rules while a
  rectangle on the same rules comes out clean.
- Effective metal extent is decided by which field-edge midpoints fall inside
  the copper, and `IsInside` is boundary-inclusive. One missing edge line
  extended a patch by one 0.15 mm cell, worth -2.1 % of resonance (predicted
  -2.07 % measured). Resonance-level claims need the realised edge pattern
  printed, not the planned one.
- Check "every site has a line" on the FINAL line list. A symmetrisation or
  merge stage that runs after the check can drop a kept site with no error and
  report the wrong dropped positions.
- Floating-point hazards seen in meshers: two lines 4.4e-16 mm apart (a sum of
  thicknesses against a stored top coordinate, one ulp apart) gave a planned
  timestep of 1.5e-27 s. Scan any newly plannable input set for a minimum cell
  below 1e-6 mm on all axes. Lexicographic tie-breaking summed in float is not
  mirror invariant, so symmetric geometries can be refused or split
  asymmetrically; quantise the keys or resolve one half and mirror it.

## Far field, nf2ff and quadrature

- `CreateNF2FFBox()` puts the surface two grid lines inside the domain edge, so
  its distance is a function of the air margin, not of the recorded value. With
  explicit bounds it still snaps to grid lines: measured standoffs ran -19 % to
  +16 % off the nominal and were asymmetric by 0.85 mm. Read the surface
  positions from the dump's own `/Mesh/{x,y,z}`, never from a manifest.
- The net real Poynting flux through the box is not conserved across box
  positions: 8.4 % spread on one solve (efficiency reading 0.863 to 0.935)
  because E and H are node-interpolated onto cells capped at about lambda/10.
  That spread, about +/-0.18 dB, is the error floor for any efficiency or gain
  number from such a pipeline. An over-unity efficiency at a larger radius is a
  surface-discretisation artifact, not stored near-field energy.
- A trapezoid sphere integral on a coarse angular grid biases directivity high
  by a pattern-dependent amount: +0.011 dB on isotropic, +0.102 dB on cos^8,
  +0.10 to +0.20 dB with a -15 to -10 dB back lobe, at 10 x 30 degrees. The
  bias does not cancel between two runs with different patterns. Any gate
  graded at 0.2 dB needs 2 x 5 degrees or finer. If a coarse grid reproduces a
  known answer better than a fine one, its quadrature bias is cancelling a real
  surface error.
- `nf2ff_results` exposes both `Prad` (total radiated power per frequency) and
  `P_rad` (the W/sr density over theta/phi). Using the density where the total
  is meant, or the reverse, is a silent factor error; the other one is a free
  cross-check.

## Independent recompute recipes

These are the cheapest independent checks available, and they are what a
numerical audit should run instead of re-reading `metrics.json`.

- **S11 from port data.** Load `port_ut_1` and `port_it_1` with `comments='%'`.
  Each file carries its OWN time column, offset by dt/2; DFT each on its own
  time column, then `S11 = (U - Z0*I)/(U + Z0*I)`. Using the voltage file's
  time for both leaves a 0.1 to 0.2 dB error that looks like solver
  interpolation but is not. dt is in line 2 of `openEMS_stats.txt`, not in the
  solver log (which prints `Timestep (s): 0.00`).
- **Radiated power from the face dumps.** `nf2ff_E_<n>.h5` and `nf2ff_H_<n>.h5`
  hold time-domain E and H on the six faces, H offset by dt/2, `/Mesh` already
  in metres (multiplying by `mesh_scaling` again is a plausible-looking error
  that reads efficiency as zero). DFT with `t = time + ts*dt`, take
  `0.5*Re(E x H*)` with the CYCLIC cross product per face
  (`S_x = EyHz* - EzHy*`, and so on; "the two other axes in index order"
  negates the y faces), integrate each face, sign faces 0/2/4 negative. Compare
  with `0.5*Re(U I*)` from the port files using the same DFT.
- **Realized gain.** With r = 1 m in `nf2ff.h5`,
  `gain = (4*pi*Z_port/eta0) * |E/uf_inc|^2`; `uf_inc` equals twice the probe
  sample spacing times a plain DFT sum, a real factor, so phases agree.
  `nf2ff.h5` may hold only the last frequency the pipeline computed.
