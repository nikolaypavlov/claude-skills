# Pre-order checklist

An order is irreversible and slow to correct. The gate is not "DRC passes".

## Artifact and profile agreement

- [ ] Gerbers, drill files and stackup drawing match the fab profile that the
      simulation runs declared. A board optimized under one profile and ordered
      from another fab is an unverified design.
- [ ] The tolerance Monte Carlo used that profile's tolerances, sampled every
      term the process actually varies, and the yield is reported against the
      acceptance criteria.
- [ ] The round-trip gate passed on the exact artifact being sent.
- [ ] Fab notes state what the fab would otherwise decide for you: mask
      keep-out on RF copper, finish, foil type, laminate and core thickness,
      no plated vias where the design forbids them.
- [ ] Panelization, board outline, fiducials, and clearance for the connector
      body where it overhangs the board edge.
- [ ] Archive of exactly what was sent, with the profile name and the date.

## Assembly and parts

- [ ] Every part has a source, a price with a date, and a second source or an
      explicit note that it has none.
- [ ] Parts near end of life flagged with a drop-in alternate.
- [ ] Footprints checked against datasheet land patterns, not against a
      library's guess. Pin numbering checked against the datasheet pinout.
- [ ] Test points for every rail and every lock or status signal that the test
      plan says must be logged.
- [ ] If the board must ship bare (no assembled RF parts), the order says so.

## Cost and scaling

Report cost at 1, 10 and 100 units: bare boards, parts, shipping, customs,
assembly. Mark every price with its source and date, or write "not verified".
Quote-only materials (Rogers laminate is usually quote-only) get a quote request
list instead of an invented number: fab, laminate, thickness, copper weight,
finish, foil type, quantity, lead time.

What changes at 100 units, stated explicitly: assembly house instead of hand
assembly, a test fixture, enclosure tooling, and the first order that justifies
a panel layout rather than individual boards.

## Supply risk register

```
part | sources | risk | alternate
```

Risks worth listing separately from price: single source, long lead time,
export restriction at the seller, refusal to ship to the destination country,
and a part whose footprint cannot be hand-soldered if local assembly is the
fallback.
