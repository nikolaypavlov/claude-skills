# Building and ordering from Ukraine

Everything in the dated list below was verified on the date given and drifts.
Re-verify with a web search before quoting it, and cite the source with an
access date. Where a claim cannot be verified, write "not verified" instead of
an estimate.

## Standing constraints

- **Fab-agnostic design.** The board must be manufacturable both by a foreign
  prototype house and by a local fab. That is what the per-fab profiles are
  for; the design must survive the conservative one.
- **Bare boards from abroad, RF parts separately.** Ordering an assembled RF
  board across the border invites refusals and customs classification trouble.
  Order bare boards; buy connectors, LNAs, synthesisers and filters from EU
  distributors.
- **Export control and seller refusals are two different risks.** A part can be
  export-controlled at the source, or simply refused by a seller or forwarder
  for the destination. Flag both per line item, and propose equivalents.
- **Power.** Assume outages: the chain runs from a 12 V battery or a USB-PD
  power bank, with filtered boost supplies for anything needing more. No
  mains-only components in the critical path.
- **Outdoor duty.** Winter to -20 C, rain, wet snow on a horizontal panel.
  A radome and a snow-shedding tilt are design parameters with measurable
  penalties, not accessories.
- **Keep spares local.** Connectors, laminate offcuts and standoffs are the
  parts that stop a build for weeks if a parcel is delayed.

## Dated facts (verified 2026-10-16, re-check before use)

Laminate and fabs:

- A large Chinese prototype house's high-frequency page listed only RO4350B,
  2 layers, 0.65 / 0.9 / 1.65 mm. Not usable for RO4003C 0.508 / 0.813 mm.
- Leiton (DE) listed RO4003C in 0.203 / 0.305 / 0.406 / 0.508 / 0.813 /
  1.524 mm, 35 um, 7 to 17 working days; multilayer special stackups on enquiry.
- PCBWay listed RO4003C and RO4350B, 0.2 to 3.2 mm, 7 to 10 days, without a
  per-core list.
- No Ukrainian fab was verified as able to process Rogers. One Kyiv supplier
  sells Rogers laminate generically; one fab claims Rogers capability in a page
  snippet only. Treat local Rogers capability as an open question to be
  answered by a quote.
- Bare-board prices for Rogers are quote-only. Public anchors exist for FR4
  starting prices only; label any Rogers figure as an ESTIMATE with its anchors.

Import:

- Ukrposhta parcel rule for individuals: duty-free to EUR 150, with the excess
  taxed at 10 % duty plus 20 % VAT on excess plus duty. Parcels from the same
  sender on the same day are combined.
- A VAT-from-zero reform was at committee stage on 2026-10-06 with effect no
  earlier than July 2027. Splitting orders to stay under a threshold is a
  logistics decision with its own shipping cost; compute both.

Parts and hardware:

- 18 GHz edge-launch SMA: Amphenol SV 2985-6037 (0.031 in board) and 2985-6035
  (0.063 in); Southwest SuperSMA clamp parts cover up to 0.065 in with a pin
  cover for thin boards. No fixed-slot 0.020 in part was found.
- Connector body height above the board and its overlap onto the board top were
  NOT verified: several distributor pages return 403 or are JavaScript-only.
  That dimension is needed before a stacked board outline is fixed.
- Nylon M2 / M2.5 standoffs and PTFE sheet are available locally on the
  consumer marketplaces. POM rod below 5 mm was not found locally.
- Rohacell 31 HF sheets start at 5 mm in standard stock; 2 mm was found only in
  a different grade from a UK supplier. Foam as a controlled air gap is a
  procurement risk.

## Method for a sourcing review

1. Start from the list above and mark what is still unverified.
2. Lines that matter get a source URL plus an access date; everything else is
   labelled an estimate with its anchors named.
3. Do not retry vendor pages that returned 403 or require JavaScript; record
   them as unreachable and ask for a quote instead.
4. Keep a dated memory of which fabs, connectors and rules were checked, so the
   next review does not repeat the searches.
