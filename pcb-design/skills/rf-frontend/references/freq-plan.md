# Frequency plan

Write it as code with unit tests, and let it FAIL a plan. A plan that lives in
prose gets violated by the next LO choice.

## What the tool computes, per channel

- IF, and whether it lands inside the IF filter and the receiver's tuning
  range.
- Image frequency `2*LO - RF`, and the rejection available there.
- Mixing products `m*LO +/- n*RF` up to order 5, with their levels.
- LO leakage to the input and to the IF.
- Reference harmonics falling inside the IF channel.

Fail the plan when an image or a product lands in band without the required
margin.

## LO choice

- Use an integer multiple of the reference so no fractional-N spurs appear
  (for example 9.750 GHz is 975 x 10 MHz).
- Check both injection sides against the real interference environment, not
  only against the IF band. A worked example: a high-side LO giving a legal IF
  put the image directly on top of a nearby transmit band, so a neighbour's
  terminal would land inside the IF. The low-side LO moved the image several
  GHz below the design band and was the only acceptable choice.
- Expose the lock-detect signal and log it. A capture taken with the
  synthesiser unlocked is invalid, and without logging you cannot tell.

## Reference harmonics: a level test, not a presence test

Harmonics of a 10 MHz reference are 10 MHz apart, so several always fall inside
a wide receiver window (about 5.6 of them in a 56 MHz window). Presence is
guaranteed; only level matters. Test the level against the required isolation
between the reference path and the IF path, and specify that isolation (40 dB
is a reasonable starting requirement for a shared-coax reference).

## Phase noise

Close-in reference phase noise is multiplied by `20*log10(LO/f_ref)`, which is
about 60 dB for a 9.75 GHz LO from 10 MHz. The master oscillator's phase noise
at 10 Hz to 10 kHz offsets therefore dominates and must be specified, not
assumed. State the LO phase-noise target with its offset and say what it is
derived from.

## Reference transport and coherence

- Carrying DC power, the reference and the IF on one coax needs a triplexer
  with a stated isolation between the reference path and the IF path, and a DC
  path that cannot load the RF.
- A GNSS-disciplined reference must degrade to holdover, never to an unlocked
  jump. Log the reference state (locked / holdover / free-running) with every
  capture; in an environment with GNSS interference this is not optional.
- One reference for the whole chain has a processing consequence: the total
  frequency error is a single fractional offset applied to the RF frequency, so
  a Doppler or offset estimator fits ONE parameter, not separate local and
  receiver offsets. A coherence check before any field test: inject a tone
  locked to the same master and require the output to sit at the predicted IF
  with a residual well under the estimator's resolution, then repeat with the
  reference unplugged to confirm the lock logging flags it.

## Board split

Keep the synthesiser, mixer and IF stage off the antenna board where the
antenna board is a controlled-impedance high-frequency laminate: the array, the
first amplifier and the protecting filter on one board, the rest on a cheaper
multilayer behind the ground plane, connected by the shortest possible link.
Shield the synthesiser and keep the reference and its harmonics away from the
RF input.
