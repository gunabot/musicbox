# Power / Corruption Risk Report — Musicbox

## Summary
For Raspberry Pi appliances, abrupt power cuts are the biggest reliability risk on SD storage.

## Three power strategies

### 1) Hard power cut (no shutdown)
- Risk: **high over time**
- Typical failures: fs inconsistencies, partial writes, occasional unbootable state.
- Not recommended for daily use.

### 2) Graceful shutdown then cut power
- Risk: **low**
- Best practical baseline with current hardware.
- Requires user flow discipline (software shutdown first).

### 3) Read-only root + writable data partition (overlay/appliance)
- Root corruption risk: **very low**
- Data partition risk: **medium** (depends on write patterns)
- Best resilience for uncontrolled power loss.

## Current project state
- Overlay tooling exists (`musicbox` helper + runbook)
- System currently in **maintenance mode** (overlay disabled)
- Root currently RW ext4

## Recommendation for Musicbox
Short-term:
1. Keep graceful shutdown flow via UI/buttons
2. Add low-battery warning + auto-shutdown threshold

Mid-term:
3. Re-enable appliance mode (overlay) after validating boot path
4. Keep app writes in `/data` only

Long-term:
5. Add hardware soft-power controller (ATXRaspi path) for clean consumer UX

## Operational safeguards
- Nightly backup of config/mappings
- Boot health checks and automatic service restart
- Clear recovery instructions in docs (`overlayfs-runbook.md`)

## Decision
For production-like kid usage, combine:
- graceful shutdown controls,
- low-battery auto-shutdown,
- overlay/appliance mode once stable,
- and eventually soft-power hardware.
