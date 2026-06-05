# IMPROVE spec — #164 a11y-bus capture robustness (+ #163 absolute firefox path)
**Owner:** taeys-hands (engineering-owner per conductor 2026-06-02). **Implement:** codex IMPROVE lane. **Verify:** taeys-hands production-run + conductor end-to-end re-verify.
**6SIGMA:** root-cause shapes (deterministic capture + live-xprop fallback + absolute binary), NOT guards. Production-run on real displays, NO tests.

## Symptom (Observed)
:6 Perplexity Firefox crashed; systemd `taey-display-6.service` auto-restarted it (NRestarts=1, 18:36) — Firefox came back up on `/usr/lib/firefox/firefox` WITH a window and a HEALTHY live AT-SPI bus (X root `AT_SPI_BUS` set, `/run/user/1000/at-spi/bus_6`), BUT `/tmp/a11y_bus_:6` was MISSING. `core.platforms.get_platform_bus()` reads that file, got `FileNotFoundError`, returned `None` → `core.atspi` find_firefox failed → consultation.py aborted "Firefox not found / Failed to switch to perplexity tab". Conductor's manual `xprop`→file write + clean `systemctl --user restart` fixed it live (current crutch).

## Root cause
The unit ExecStart (see `systemd/user/taey-display-N.service`) writes `/tmp/a11y_bus_:N` only inside an initial `for i in $(seq 1 20)` loop that `break`s ON a matched `unix:path=*|unix:abstract=*` from `xprop AT_SPI_BUS`. If that 20×1s window times out (or races the `ExecStopPost` `rm -f /tmp/a11y_bus_:N` on the prior stop), the file is never (re)written, even though the live bus is healthy. The background change-monitor loop only rewrites on a *changed* address, so it doesn't reliably self-heal a never-written file. Net: any crash→auto-restart can silently leave the display half-broken (FF up, bus file absent).

## Fix — belt + suspenders (either alone fixes it; both = robust). PRIORITIZE the driver fallback.

### (B) Driver-side live-xprop fallback — HIGHER VALUE, LOW RISK, additive
**File:** `core/platforms.py` → `get_platform_bus(platform)` (≈ line 137).
Currently:
```python
bus_file = f'/tmp/a11y_bus_{display}'
try:
    with open(bus_file) as f:
        return f.read().strip() or None
except FileNotFoundError:
    return None
```
**Change:** when the file is absent OR empty, fall back to the live X root property, and (best-effort) write it back so subsequent reads are fast:
```python
addr = None
try:
    addr = (open(bus_file).read().strip() or None)
except FileNotFoundError:
    addr = None
if not addr:
    # live fallback: source the bus from the X root AT_SPI_BUS property
    out = subprocess.run(['xprop','-display',display,'-root','AT_SPI_BUS'],
                         capture_output=True, text=True).stdout
    m = out.split('"')
    cand = m[1].strip() if len(m) >= 2 else ''
    if cand.startswith('unix:'):
        addr = cand
        try:  # best-effort cache; never fatal
            with open(bus_file, 'w') as f: f.write(addr + '\n')
        except OSError:
            pass
return addr
```
Impact (gitnexus, upstream): **LOW — 0 direct callers in the static graph; purely additive** (returns a valid addr instead of None when the file is absent; happy path unchanged). Apply the SAME fallback to `tools/extract.py:30` (it reads the same `/tmp/a11y_bus_{display}` file). Consider a shared helper so both sites stay in sync.

### (A) Unit-side deterministic write — hardens the source
**File:** `systemd/user/taey-display-N.service` (all N; templatize if feasible). In the ExecStart bash:
- The initial capture loop should write the file as soon as a valid `unix:*` address is seen (it does) — but make it robust: if the loop exits WITHOUT a match, do a final unconditional `xprop`-source attempt and write whatever valid address is present before launching Firefox; and have the background monitor loop ALSO create the file when absent (not only on change). Net invariant: **if the live root `AT_SPI_BUS` is a `unix:*` address, `/tmp/a11y_bus_:N` exists with that value within a couple seconds of (re)start, deterministically.**
- Audit the `ExecStopPost` `rm -f /tmp/a11y_bus_:N` vs `Restart=always` ordering so the cleanup can't delete a file the next ExecStart just wrote.

### (#163) Absolute firefox binary — same branch
**Files:** `scripts/restart_display.sh` (≈ line 235) + `scripts/launch_isolated_display.sh` — replace bare `firefox` with absolute `/usr/lib/firefox/firefox` (the snap `/snap/bin/firefox` dies from non-snap cgroups; the working units already use the absolute real binary). Make the path overridable via env (e.g. `${FIREFOX_BIN:-/usr/lib/firefox/firefox}`) for portability.

## PRODUCTION-VERIFY (taeys-hands; the test that proves the loop+fallback fix)
1. Pick an idle display (e.g. :6 when no consult running). `kill` its Firefox PID (simulate crash).
2. Let `Restart=always` auto-restart the unit. Do NOT manually write `/tmp/a11y_bus_:N`.
3. Confirm `core.atspi.find_firefox` returns FOUND for that platform (driver fallback or deterministic unit write — either path) — i.e. a consultation can run with NO manual bus-file write.
4. Also confirm a normal `systemctl --user restart taey-display-N.service` leaves the file present.
Ping conductor when it lands; conductor re-verifies the auto-restart path end-to-end.
