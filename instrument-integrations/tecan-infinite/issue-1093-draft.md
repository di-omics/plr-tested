# DRAFT - upstream issue #1093 comment + PR scaffold

> DO NOT POST any of this until we have a real read result from the instrument.
> Every claim about the read is a `<FILL ...>` placeholder. We have not run a read yet;
> the reader was USB-identified only. Fill the placeholders from the actual
> `06_tecan_read_absorbance_debug.py` output, then post. No claim we have not verified.

Issue: https://github.com/pylabrobot/pylabrobot/issues/1093
Upstream backend: `pylabrobot/plate_reading/tecan/infinite_backend.py`
`ExperimentalTecanInfinite200ProBackend`, added in #797.

---

## 1. Comment to post on #1093 (fill, then post)

Hi @isaacguerreir @rickwierenga - we have an Infinite `<FILL: 200 PRO / Nano+>` on a
Raspberry Pi (Linux) and ran the same read path. Setup notes that may help others:

- On the Pi, no Zadig step: `lsusb` shows `0c47:8007` and no kernel driver is bound to the
  interface, so libusb claims it without a detach. Non-root access via a udev rule for
  `0c47:8007` (or the `plugdev` group).
- PyLabRobot `<FILL: version / commit>`, pyusb + libusb.

What we ran (instrumented read that logs each command and the raw USB reads, and tags the
reads after `SCANX`):

```
<FILL: paste the 06_tecan_read_absorbance_debug.py trace, especially the lines
around "SCANX sent" and the DIAGNOSIS block>
```

Result: `<FILL: exactly one of the following, from the real run>`

- If it READ: absorbance completed; OD matrix `<FILL>`. Happy to share the working
  settings; if it fails on the M200 specifically we can help narrow the difference.
- If it TIMED OUT like yours: SCANX was sent and the reader returned `<FILL: N>` bytes /
  reads before the timeout. So the connection is fine and the hang is in the
  measurement-frame stream after `SCANX` (in `_await_measurements`). `<FILL: whatever the
  trace shows - e.g. reads return empty, or a TimeoutError on the first 512 B read>`.

`<FILL: only if we actually found and tested a fix - describe it; otherwise say we are
still investigating and will follow up.>`

---

## 2. PR scaffold (open only after a fix is validated on hardware)

- **Target:** upstream classic backend `pylabrobot/plate_reading/tecan/infinite_backend.py`
  (NOT the di-omics capabilities refactor - that is a separate conversation, and upstream is
  mid its own v1 Device/Driver/Backend migration).
- **Title:** `Fix Tecan Infinite absorbance read: <FILL one-line summary of the fix>`
- **Body:**
  - Closes #1093.
  - Background: the Infinite backend (from #797) connects and moves the drawer, but
    `read_absorbance` timed out at the `SCANX` scan step on `<FILL: hardware>`.
  - Root cause: `<FILL: what the trace showed>`.
  - Fix: `<FILL: the actual change>`.
  - Hardware: validated on an Infinite `<FILL>` on a Raspberry Pi (Linux), `<FILL: date>`.
- **Tests:** extend `pylabrobot/plate_reading/tecan/infinite_backend_tests.py` to cover the
  fixed path with a mocked USB transport (no device). Keep the existing tests green.
- **CHANGELOG:** add under `## Unreleased` -> `### Fixed` (Keep a Changelog format):
  `- Tecan Infinite absorbance read <FILL: fix> (#1093)`
- **Before opening:** run the repo's pre-commit (ruff), `pytest` on the reader tests, and
  keep the diff minimal and scoped to the read path.

---

## 3. Pre-post checklist

- [ ] Ran `06_tecan_read_absorbance_debug.py` on the instrument and captured the trace.
- [ ] Filled every `<FILL ...>` from that real output. No unverified claims remain.
- [ ] If claiming a fix: the fix was actually run on the instrument and read a plate.
- [ ] Comment posted on #1093 first (engage before the PR).
- [ ] PR only after a fix is validated; follows CONTRIBUTING (ruff, tests, CHANGELOG).
