# EEZ Studio — Live Toast Pattern

Reference for implementing a continuous live-readout shortcut in EEZ Studio 0.28.0.
Developed and tested against the EA-PS2342 bridge extension (v1.0.29).
Apply the same pattern to DMM 34465A, Rigol MHO98, and similar multi-channel instruments.

---

## The Pattern

```javascript
// ── 1. CSS injection — multi-line toast support ───────────────────────────────
// Must run before any notify call that uses \n.
// document is accessible in the EEZ Studio 0.28.0 script sandbox.
// The id guard ensures the style is only injected once per EEZ session.
if (!document.getElementById('my-instrument-toast-fix')) {
    var _s = document.createElement('style');
    _s.id = 'my-instrument-toast-fix';
    _s.textContent = '.Toastify__toast-body{white-space:pre-line}';
    document.head.appendChild(_s);
}

// ── 2. Interval ───────────────────────────────────────────────────────────────
const INTERVAL_MS = 100;   // 100 ms works well; increase if instrument is slow

// ── 3. Acquire connection and open a persistent toast ─────────────────────────
await connection.acquire(true);
var liveToast = notify.info("▶ Live: connecting...", { autoClose: false });

// ── 4. Poll loop ──────────────────────────────────────────────────────────────
try {
    while (!session.isStopped) {
        var raw = await connection.query("YOUR:MEAS:QUERY?");
        // ... parse raw into display string ...
        var line1 = "CH1: " + /* formatted value */;
        var line2 = "CH2: " + /* formatted value */;

        notify.update(liveToast, {
            render: line1 + "\n" + line2,   // \n renders as line break with CSS fix above
            autoClose: false
        });
        await new Promise(r => setTimeout(r, INTERVAL_MS));
    }
    notify.update(liveToast, { render: "Live stopped", autoClose: 2000 });
} catch(e) {
    notify.update(liveToast, { render: "Live failed: " + e.message, autoClose: 5000, type: "error" });
} finally {
    connection.release();
}
```

---

## Key Design Decisions

### notify.update() — not dismiss + recreate

`notify.update(toastId, { render, autoClose })` updates the existing toast **in place**.
Dismiss + recreate causes a new toast to slide in below while the old one slides off —
visible jump on every poll cycle. `notify.update()` has zero animation and zero jump.

`notify.info()` returns a numeric toast ID (e.g. `436`). Pass it directly to `notify.update()`.
This works in EEZ Studio 0.28.0 — it was broken in 0.27.x.

### Single toast only

Two simultaneous toasts (e.g. a hint toast + a data toast) stack and obscure the
Stop button in the Scripts panel. Use one toast for all live data.

### Stop mechanism

`session.isStopped` becomes true when the user clicks Stop. However, the toast
obscures the Stop button while it is visible. Closing the toast reveals the Stop button.
Document this in the shortcut comment:

```javascript
// To stop: close this toast to reveal the Stop button in the Scripts panel.
```

### Interval tuning

| Interval | Behaviour |
|----------|-----------|
| 100 ms | Smooth update, readable at rest |
| 500 ms | Readable while scrolling terminal |
| 1000 ms | Comfortable for slow instruments |

100 ms is the practical minimum for MEAS:BOTH? on the EA bridge (single round-trip).
For instruments that require one query per channel, multiply by channel count.

### Multi-line display with \n

EEZ Studio's toast library (react-toastify) does not set `white-space: pre-line`
on `.Toastify__toast-body` by default, so `\n` in a string is collapsed to a space.

**Fix:** inject the CSS rule from the script (see step 1 above).

A GitHub issue has been filed against `eez-open/studio` requesting the fix upstream
(`packages/eez-studio-ui/_stylesheets/app.less`). Once merged the injection becomes
a harmless no-op.

`\n` in a JavaScript string literal inside the EEZ script sandbox becomes a real
newline character at runtime — this is standard JS behaviour. The CSS fix is the
only thing needed to make it visible in the toast.

Things that do NOT work:
- `<br>` — printed as literal text, not rendered as HTML
- `white-space` override without the CSS injection — no effect

### qts() helper — robust query result extraction

EEZ Studio query responses can be strings, numbers, or binary ArrayBuffers depending
on connection state. Always wrap with:

```javascript
function qts(r) {
    if (r === null || r === undefined) return "";
    if (typeof r === "string") return r.trim();
    if (typeof r === "number") return String(r);
    if (r.data) { var t = new TextDecoder().decode(new Uint8Array(r.data)); return t.trim(); }
    return String(r).trim();
}
```

### console.log() produces no output

`console.log()` in the EEZ Studio 0.28.0 script sandbox produces no visible output.
Use `notify.info()` for debugging during development.

---

## Applying to DMM 34465A / Rigol MHO98

1. **Copy the pattern above** into a new shortcut script for the instrument.
2. **Replace the query** (`YOUR:MEAS:QUERY?`) with the instrument's measurement command.
   - 34465A: `MEAS:VOLT:DC?` / `READ?` / `FETC?` depending on mode
   - MHO98: `MEAS1?` / `MEAS2?` or channel-combined equivalents if available
3. **Format the result** into `line1` / `line2` strings with units and mode.
4. **Tune `INTERVAL_MS`** to the instrument's response time — GPIB/USB instruments
   may need 200–500 ms.
5. **Use the same CSS injection block** (change only the `id` string to avoid
   conflicts if multiple instruments are open simultaneously).
6. **Add the shortcut to the instrument's `package.json`** and rebuild the zip.
