# Rejection and filter budgets

## A rejection number belongs to a chain

Write every rejection requirement as a requirement on the path from the antenna
port to the stage being protected, then apportion it:

```yaml
rejection:
  nearby_transmitter_min_db: 30.0
  image_min_db: 40.0
  reference_to_if_isolation_min_db: 40.0
  chain_split:
    antenna_contribution_db: null    # from simulation, once it exists
    filter_contribution_db: null     # designed against what is left
    status: to_be_apportioned
```

Leaving the split explicitly null is the point: it keeps the filter stage from
being designed against a number nobody checked, and it keeps the antenna's own
roll-off from being assumed.

## Report the antenna out of band

Simulate and report the response at every frequency that matters outside the
design band, not just inside it:

- Nearby transmit bands. A receive array has real response above its
  fundamental (higher-order modes appear, and a corporate feed is broadband),
  so "it is out of band" is not an argument.
- The mixer image, once the LO is fixed.
- Any harmonic of a reference or clock that lands in the IF.

These frequencies belong in the spec as a list that the reporting code reads,
so a new design cannot forget them.

## Filter placement

- The protecting filter goes ahead of the mixer, and the first amplifier ahead
  of the filter unless the interferer is strong enough to compress it. State
  which case the design assumes and what interferer level it survives.
- A filter in front of the amplifier costs noise directly (see
  `noise-budget.md`), so its insertion loss is part of the figure of merit, not
  a detail.
- Verify the realised rejection against the component values, not against the
  datasheet curve of an idealised part: layout parasitics at microwave move a
  filter response more than tolerance does.

## Isolation on a shared cable

Where power, a reference and the IF share one coax, the isolation between paths
is a design requirement with a number, and the DC path must not load the RF.
Measure or simulate it; an assumed isolation is the usual reason a reference
harmonic appears in the IF.
