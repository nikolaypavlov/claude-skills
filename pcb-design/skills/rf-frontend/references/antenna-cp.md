# Circular polarization, arrays, feasibility

## Handedness: derive it, never quote it

Axial ratio is symmetric in the two circular magnitudes, so a swapped
convention never shows up in axial ratio. It shows up in the hand label, in
cross-polarization, and in sequential-rotation phasing - that is, in the
places that decide whether the antenna works at all. Re-derive the sign every
time. The derivation is ten lines:

1. **Fix the phasor convention from the transform.** A DFT kernel
   `sum x(t) exp(-j*2*pi*f*t)` stores the phasor `X` for which
   `x(t) = Re{X e^{+j*omega*t}}`: feed it `cos(wt)` and you get a positive
   real, feed it `sin(wt)` and you get `-j`.
2. **IEEE right-hand sense.** Right thumb along the propagation direction,
   fingers curl the way E rotates. A right-handed rotation about `+z` maps
   `+x_hat -> +y_hat`, and `Re{(x_hat - j y_hat) e^{jwt}} = x_hat cos(wt) +
   y_hat sin(wt)`. So RHCP along `+z` is proportional to `(x_hat - j y_hat)`
   under `e^{+j*omega*t}`.
3. **Far-field basis.** At boresight with phi = 0,
   `(theta_hat, phi_hat, r_hat) = (x_hat, y_hat, z_hat)`, so a pure RHCP field
   has `E_phi = -j*E_theta`.
4. **Project onto the CONJUGATE unit vector**, which is the step that gets
   dropped:

```
E_RHCP = (E_theta + 1j*E_phi)/sqrt(2)
E_LHCP = (E_theta - 1j*E_phi)/sqrt(2)
```

Sanity: feeding `(1, -1j)` gives `|E_RHCP| = sqrt(2)` and `E_LHCP = 0`.

A test that feeds the field which the formula itself declares to be RHCP is a
tautology and passes either way. The non-circular test builds the time-domain
field from the phasor and asserts the rotation sense, or asserts that
`E_phi = -j*E_theta` is RHCP. Cross-check against the solver's own circular
components if it exposes them.

## Axial ratio and bandwidth

- Report axial ratio over the full graded band and at the graded direction, not
  only at the design frequency: a single-feed circularly polarized element
  rarely holds a tight axial ratio across a wide channel, and that is a design
  limit to state, not a number to average away.
- Separate the axial-ratio bandwidth from the match bandwidth. They have
  different centres, and a design centred on one can fail the other.
- A cone criterion (axial ratio within N degrees of boresight) is a different
  quantity from boresight axial ratio and usually the binding one. Say which
  one a number refers to.

## Sequential rotation and feed networks

- Verify the phases the network actually delivers by probing each branch in a
  feed-only simulation BEFORE adding the elements. A network that is supposed
  to deliver 0/90/180/270 degrees and delivers something else produces a
  plausible-looking pattern with the wrong polarization.
- The long branch of a sequential-rotation network sets the dispersion, and the
  resulting phase error grows across the band; the cone metric feels it first.
- Feed-line radiation and coupling between the feed and the elements are part
  of the result. A weighted model that ignores them accounts for power
  correctly and still misses off-boresight metrics by several dB.

## Array geometry

- Element spacing against grating lobes: `d < lambda / (1 + sin(theta_max))`
  at the HIGHEST frequency in the band, with theta_max the edge of the
  coverage cone.
- Ground-plane size and edge treatment are optimization parameters for a
  receive design, because the back lobe costs twice (see `noise-budget.md`).
- Check any reported gain against the aperture limit
  `10*log10(4*pi*A*eta/lambda^2)` with A the physical area. A gain above it is
  a bug, not a result.

## Is the criterion even achievable?

Before accepting a gain-versus-coverage criterion as a gate, run three checks,
in increasing strictness:

1. **Pattern energy budget.** The integral of gain over the sphere cannot
   exceed `4*pi*eta_rad`, and a single-polarization criterion is stricter
   still. This is necessary, not sufficient.
2. **Minimum-energy admissible pattern.** A flat pedestal at the coverage floor
   over the cone plus a narrow spike at boresight is the real conservation
   bound.
3. **Realizable array factor.** An array factor for the actual element count
   times an element pattern, normalised over the sphere. Small arrays have very
   few degrees of freedom, so criteria that pass the energy budget are
   routinely array-infeasible.

Two cautions from implementing this: the answer is sweep-grid dependent, so
recompute it on the grid you intend to defend, and constrain element
directivity against element spacing (`D_el <= 4*pi*d^2`), or the model picks an
unphysically directive element in a small cell and returns a boresight
directivity above the aperture limit.

Interpolation convention matters too: interpolating gain in dB linearly in
`(1 - cos theta)` (that is, linearly in solid angle) is the most pessimistic
plausible choice and is safe for declaring a criterion infeasible, but it is
not a bound. Write the convention down wherever such numbers are quoted; an
independent re-derivation under a different convention can differ by several dB.
