# Noise budget and G/T

## The chain, in order

```
T_A    = (1/4pi) * integral of D_tot(theta,phi) * T_B(theta,phi) dOmega
T_A'   = eta * T_A + (1 - eta) * T_phys
T_sys  = T_A'/L + T_phys * (1 - 1/L) + T_LNA  [+ second-stage terms]
T_LNA  = 290 * (10^(NF/10) - 1)               NF in dB
G/T    = G_realized / T_sys                   reported in dB/K
```

`L` is the linear loss factor before the amplifier (>= 1), `T_phys` about
290 K, `eta` the radiation efficiency, `D_tot` the total-power directivity.

Worked magnitudes worth remembering: 0.5 dB of loss ahead of the amplifier adds
about 31 K. An amplifier with 0.8 dB noise figure is about 59 K. So a feed-loss
budget of 0.3 dB is not pedantry when the target temperature is 50 to 60 K.

## Normalisation is a test, not a comment

```
(1/4pi) * integral of D_tot dOmega = 1 exactly
D_tot = 4*pi*(U_co + U_cross)/P_rad
```

Make the implementation refuse a weight that does not integrate to one. That
single assertion catches the gain-versus-directivity trap, a missing
sin(theta) factor, a hemisphere dropped from the integral, and a pattern
normalised to its own peak.

## What the integral is sensitive to

- Both hemispheres. Ground emission below the horizon at about 290 K is usually
  the largest single contribution to a zenith-pointing antenna's temperature.
- Angular grid. A trapezoid sphere integral on a coarse grid biases directivity
  high by a pattern-dependent amount, so it does not cancel between two designs
  (see the sim-loop skill's `references/openems.md`).
- Back-lobe share. Required efficiency scales directly with back radiation: in
  one case the floor moved from 0.726 to 0.781 as the back-hemisphere share
  went from zero to 7 %. An efficiency floor is therefore also a statement
  about how much power may go below the horizon.

## Environment model

Keep the brightness-temperature model in its own spec file and implement it as
a tested function, not as a table pasted into a report. Derive it from stated
assumptions (zenith attenuation, air mass, physical temperature) so the
assumptions are visible and can be varied. Every report quoting a temperature
says the model is a model.

A simple clear-sky starting point at 11 to 12 GHz: about 15 K at zenith rising
to about 100 K near the horizon, ground 290 K below the horizon. Rain and wet
snow are separate cases, not a margin.

## Noise match versus power match

An amplifier's optimum source impedance is usually not exactly 50 ohm. Default
to a return-loss criterion for simplicity, and add an optional mode where the
feed transforms to the amplifier's own optimum reflection coefficient and the
objective uses its noise parameters (minimum noise figure, noise resistance,
optimum reflection coefficient). State which mode produced any reported number.

Physical layout follows from the budget: the first amplifier sits as close to
the feed point as the board allows, any cable between them counts in the loss
budget, and a connector pair that is not in the budget is a defect.

## Cascade arithmetic

- Second and later stages enter divided by the preceding gain; report whether
  they were included.
- A reactive divider or combiner between elements re-scatters element mismatch
  and does not simply weight it. A first-order model (network transmission
  times embedded element patterns) can be optimistic by several dB on
  off-boresight metrics while agreeing to a few hundredths of a dB on
  boresight. When a weighted model and an in-situ simulation disagree, suspect
  the re-scattering term before suspecting radiation from the network.
- Weights expressed as power-wave scattering parameters of a network whose
  ports are at the same impedance as the elements include network loss and
  input mismatch exactly once. Check the reference impedance on both sides
  before accepting any weighted regrade.

## Reporting

State for every figure: which run produced it, at which frequency and
direction, whether gain is realized (mismatch included) or not, and which
assumptions (amplifier noise figure, sky model, loss budget) it carries. A G/T
quoted without its assumed amplifier is not a result.
