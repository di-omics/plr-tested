# DRAFT - upstream issue #1093 comment (filled from the real 2026-07-12 hardware session)

> This is filled from actual runs on the instrument, not placeholders. It does NOT claim a
> working read - because we did not get one. It reports exactly what works and what fails.
> Post only with di-omics's explicit OK. Nothing here is published yet.

Issue: https://github.com/pylabrobot/pylabrobot/issues/1093
Upstream backend: `pylabrobot/plate_reading/tecan/infinite_backend.py`
`ExperimentalTecanInfinite200ProBackend` (from #797).

---

## Comment (ready for review, then post)

Hi @isaacguerreir @rickwierenga - we hit this too and can add data. We have a Tecan Infinite
(200 PRO / Nano+ class) on a Raspberry Pi (Linux), driving it through PyLabRobot over USB.

Setup note that may help others: on the Pi there is no Zadig step. `lsusb` shows `0c47:8007`
and no kernel driver is bound to the interface, so libusb claims it directly, no detach.

**What works for us**

- `setup()` (QQ + INIT FORCE), tray open, and tray close all work. One quirk: the `BY#T5000`
  settle response after `ABSOLUTE MTP,IN` times out on our unit even though the drawer
  physically moves in; tolerating that one TimeoutError lets us continue.
- `read_absorbance` gets **past** the `ABSOLUTE MTP` / `SCANX` step and streams measurement
  frames - we decode per-well sample/reference counts (~379 bytes). So on our unit the
  absorbance scan itself runs, unlike the timeout you see there on the M200.

**Where it fails for us**

- After the scan, `read_absorbance` raises `RuntimeError: ABS calibration packet not seen;
  cannot compute calibrated OD`. The `PREPARE REF` reference/calibration packet is not
  captured, so it cannot turn the raw counts into OD. The raw `sample` counts also peg at
  65535 (saturated) even with dye loaded in every well, consistent with the reference not
  being applied.
- `read_fluorescence` **does** time out at the first `ABSOLUTE MTP,Y=`, matching your symptom.
  We traced it to `_configure_fluorescence` issuing its ~19-command config **twice**
  (`for _ in range(2)`) before `PREPARE REF` (sent `read_response=False`); that appears to
  desync the USB stream so the next read hits nothing. Absorbance's shorter, single-pass
  config gets through the same MTP move, which is why absorbance scans and fluorescence hangs.

Corroborating your note: we also see USB read timeouts creep in after operations (same family
as your "device disappears from lsusb"); a fresh connect recovers it here.

Happy to run the smaller sequences you offered - setup+close, absorbance config without scan,
and manual transport commands before `SCANX` - we have the hardware on the bench. Environment:
Raspberry Pi, Linux, no vendor software.

---

## PR scaffold (open only after a fix is validated on hardware)

- **Target:** upstream classic backend `pylabrobot/plate_reading/tecan/infinite_backend.py`.
- **Two candidate fixes to test on the bench:**
  1. Capture the `PREPARE REF` / ABS calibration packet so `read_absorbance` can compute OD
     (right now `decoder.calibration` stays `None`).
  2. Keep the USB stream in sync through `_configure_fluorescence` (the doubled config +
     `read_response=False` on `PREPARE REF` is the prime suspect for the `MTP,Y` desync).
- Tests in `pylabrobot/plate_reading/tecan/infinite_backend_tests.py`; CHANGELOG under
  `## Unreleased` -> `### Fixed`; ruff pre-commit.

## Pre-post checklist

- [ ] di-omics has read this and approves the exact wording.
- [ ] It claims nothing we did not observe (it does not claim a working read).
- [ ] Post the comment on #1093 first; PR only after a fix is validated on hardware.
