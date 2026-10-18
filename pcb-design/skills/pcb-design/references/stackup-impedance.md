# Stackup, impedance, loss

Numbers below are for Rogers RO4003C / RO4350B at Ku band because that is where
they were measured. The models and their validity limits are general; recompute
for your own stackup and band.

## Materials

| laminate | Dk design | Df | note |
|---|---|---|---|
| RO4003C | 3.55 +/-0.05 | 0.0027 | preferred; cores 0.203 to 1.524 mm |
| RO4350B | 3.66 +/-0.05 | 0.0037 | fallback; 37 % more loss, costs efficiency |
| RO4450F bondply | 3.52 | 0.0040 | 0.038 to 0.102 mm, for bonded stacks |

Use the DESIGN Dk, not the process Dk, and never change it silently: a Dk
change goes through the spec and the decision log. Dk tolerance is a Monte
Carlo term, not a nominal.

Copper: sigma 5.8e7 S/m, 35 um standard, 17 um where finer features matter.
State the conductor model explicitly - a finite-conductivity sheet in the
optimization loop, thick metal in final verification - and quantify the
difference on one candidate instead of assuming it is negligible. At Ku, 35 um
is about 7 % of a 0.508 mm substrate, which is not nothing.

## Impedance and geometry

- Compute line width and gap from the actual stackup, not from a default
  calculator preset, and recompute when the core thickness or Dk changes.
  `scikit-rf` or a closed-form microstrip/GCPW model is enough for a review.
- The narrowest line the fab can etch sets the highest impedance available.
  Enforce it in the parameter schema so the optimizer cannot ask for a
  transformer that cannot be built.
- Continuous reference plane under every controlled-impedance trace. A plane
  break is a series inductance and a radiator.
- Via fence pitch and ground stitching: under lambda/10 in the dielectric at
  the highest frequency present in the system, not at the operating band. A
  board receiving at 11 GHz next to a 14 GHz transmitter is stitched for
  14 GHz.
- Bends mitered, T-junctions compensated, impedance steps deliberate. In a
  corporate feed the feed lines themselves radiate and couple to the elements;
  that is part of the design, not an afterthought.
- Edge-launch connector: model the transition explicitly in final verification,
  not inside the optimization loop. The footprint must match the exact
  connector part number, including whether the part suits the board thickness.

## Surface roughness

Roughness raises effective conductor loss above the bulk-sigma value, and for a
microstrip the side that matters is the SUBSTRATE-FACING one, which no finish
ever plates.

```
  foil type         Rq (um)   Hammerstad-Jensen K   added conductor loss
  reverse treated     0.4           1.335                  +33.5 %
  standard ED         2.0           1.956                  saturated
  unknown             2.0           1.956                  assume the worst
```

Validity, signed: Hammerstad-Jensen saturates at K = 2 and is normally
recommended below about 6 to 10 GHz. Above 10 GHz it UNDER-predicts loss, so
using it at 11 GHz is an optimistic error, not a neutral one. Record that, and
turn the assumption into a bounded range with a sensitivity run at
Rq = 0.4 / 1.0 / 2.0 um rather than quoting one number. The Huray cannonball
model is the alternative when measurements justify it.

## Surface finishes

A finish plates only exposed faces, so its penalty is smaller than a bare
surface-resistance ratio suggests. Skin depth in copper at 11.3 GHz is 0.62 um,
so 35 um copper is 56 skin depths.

- **Immersion silver** - preferred. Model it AS COPPER: the layer is 0.1 to
  0.3 um against a 0.60 um skin depth in silver, so it carries almost none of
  the current. Modelling it with silver's conductivity makes the design
  slightly better than physical, which is the wrong direction.
- **Immersion tin** - allowed. 0.8 to 1.2 um against a 1.60 um skin depth, so
  about 0.6 skin depths: small, but not negligible.
- **ENIG** - disqualified by default. Nickel is lossy AND ferromagnetic at
  microwave; published mu_r scatters between 1 and 600. At mu_r = 1 the surface
  resistance is 2x copper, at mu_r = 100 it is 20x and the nickel fully shields
  the copper beneath it. Modelled with mu_r = 1 the penalty is understated by
  roughly a factor of ten, and it lands directly on radiation efficiency. Allow
  it only with a measured permeability for the actual process.
- **HASL** - forbidden on radiating and feed copper: uncontrolled thickness and
  surface profile.

## Solder mask

A fab masks everything unless told otherwise. Over RF copper, mask both detunes
and adds loss (Dk about 3.3, Df 0.02 to 0.03 at 20 to 40 um). Either keep it
off radiating and feed copper explicitly in the fab notes, or model it. An
unmodelled mask is an unaccounted error on the quantity the design is judged on.

## Bonded and stacked topologies

- A bonded stack needs the bondply in the spec, or the middle layer cannot be
  modelled at all.
- Registration and bow/twist become live tolerance terms. IPC-6012's default
  acceptance for bow and twist is 0.75 % of the diagonal; a tighter number on
  the fab drawing is a quote item, not an assumption.
- Air-gap stacks on spacers: the gap, lateral offset, tilt and bow are all
  Monte Carlo terms. Leave physical room for the hardware - a ground margin
  sized only for electrical reasons may leave nowhere to put a standoff.
- Literature bandwidth figures for stacked patches are for other stacks. Quote
  the expected range for YOUR stack thickness and laminate, and mark it as a
  reference, never as a result.
