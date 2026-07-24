# WGS preparation + HHS lidded dry validation - 2026-07-21

Operator-attended physical validation on the Hamilton STAR using empty
sacrificial labware, no samples or reagents, returned tips, and no HHS
heating/shaking.

## Git evidence

- staged runner commit: `45b4862`
- continuous single-home runner commit: `d152e1a`
- branch: `codex/wgs_prep-hhs-lidded-dry-run`
- PyLabRobot: `0.2.1`

## Labware and deck

- CellTreat 229195/229196 work plate at rail35 pos0
- empty/dry CellTreat source plate at rail35 pos1
- Corning 3603 lid on its park plate at rail35 pos4
- p10 tips at rail48 pos0, columns 1 and 2
- p50 rack at rail48 pos1, modeled but unused
- HHS at rail27 pos2, empty/open/idle at start

## Individual stage evidence

1. WGS preparation lysis and reaction dry motions used the approved operator
   profile, returned tips, and moved the plate forward to HHS: exit 0,
   physically confirmed.
2. First lid-on attempt: firmware `NoElementError('Plate not found')` at r35p4
   because the physical lid was not seated carefully on the park plate. The
   runner skipped automatic iSWAP parking, disconnected, and no code changed.
3. Lid reseated flat; identical lid-on code retried: exit 0, physically confirmed.
4. Delid at HHS x12/y45.5/z16 to park drop z4: exit 0; only the lid moved and
   the work plate remained seated.
5. Bare plate return at HHS x12/y45.5/z10 to r35p0 drop z8.5: exit 0,
   physically confirmed.

## Continuous single-home evidence

The continuous runner performed, without an operator pause:

1. lysis dry motion
2. reaction dry motion
3. plate forward to corrected HHS target x12/y45.5/z17
4. lid-on from r35p4, pickup z9
5. delid from HHS, pickup z16, park drop z4
6. bare plate return, HHS pickup z10, r35p0 drop z8.5

Result: exit 0 with the success banner and clean USB disconnect. The operator
confirmed work plate square at r35p0, lid flat at r35p4, HHS empty, tips
returned, iSWAP parked, and no scrape, tilt, collision, or unexpected movement.

## Operational control retained

The lid must be seated flat, square, stable, and non-rocking on the r35p4 park
plate before release. A mis-seated lid can produce `Plate not found`. Any setup
or operation failure keeps automatic iSWAP parking disabled and requires
physical-state reconciliation before retry.
