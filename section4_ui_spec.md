# 4. Application Software Layer & UI Interface Specification

To design an accessible, error-tolerant human-machine interface (HMI) for this setup, developers should follow the architectural criteria and script execution flows mapped out below.

---

## 4.1 Required Operator Data Inputs

The GUI profile screen abstracts all direct hardware interactions by exposing four input fields, each enforcing strict threshold validation:

| Input Field | Unit | Min | Max | Hard Block Condition |
|---|---|---|---|---|
| `D_stock` — Stock Diameter | mm | 1.0 | 185.0 *(radius ≤ 92.5, within `$130` = 100)* | Radius exceeds `$130` soft limit |
| `L_stickout` — Stickout Length | mm | 1.0 | 110.0 *(within `$131` = 115 with pull-off)* | Exceeds Y-axis safe travel |
| `D_target` — Target Profile Diameter | mm | 0.5 | `D_stock` − 0.5 | `D_target` ≥ `D_stock` |
| `L_cut` — Target Turning Depth | mm | 0.5 | `L_stickout` − 0.5 | `L_cut` ≥ `L_stickout` |

**Derived values computed silently by the software layer:**

- Safe approach position: `X_approach = (D_stock / 2) + 6.0 mm`
- Work Y offset: `Work_Y_Offset = MPos_Y_chuck + L_stickout` → `G10 L2 P1 X-69.000 Y{Work_Y_Offset}`

> **Diameter vs Radius — Critical Invariant**
> All operator-facing fields collect values as diameters. The software layer must halve all diameter values before emitting any G-code X coordinate. GRBL operates in Radius Mode on this machine — substituting a diameter directly into an X command doubles the intended cut depth and risks a mechanical crash.

---

## 4.2 Startup and Cycle Execution Logic Flow

The following phases must execute in strict sequence. No phase may be triggered out of order; the UI should disable downstream buttons until each prerequisite phase completes successfully.

### Invariant — Connection Initialisation

Immediately on serial connection, before any other command is sent:

```gcode
G92.1   ; Clear any temporary coordinate shifts
G49     ; Cancel tool length compensation offsets
```

This prevents coordinate translation distortion carried over from a previous session.

---

### Phase I — Hardware Initialisation

**UI Button:** `[Initialize & Home Machine]`

Sends: `$H`

The lathe homes all axes and resets its structural coordinate master map (MPos X:0, Y:0). On completion the UI must confirm the homing cycle finished without alarm before enabling Phase II controls.

---

### Phase II — Coordinate Synchronisation

**UI Button:** `[Sync Workpiece Parameters]`

**Prerequisite:** Phase I complete. Operator has measured and entered `D_stock` and `L_stickout`.

The UI layer processes the offset equation and transmits:

```gcode
G10 L2 P1 X-69.000 Y{Work_Y_Offset}   ; Set G54 origin to spindle centreline / stock front face
G54                                     ; Activate the work coordinate system
```

Where `Work_Y_Offset = -120.000 + L_stickout`.

**Example** for `L_stickout = 30.000 mm`:

```gcode
G10 L2 P1 X-69.000 Y-90.000
G54
```

---

### Phase III — Safe Zone Verification

Immediately after Phase II, the UI automatically fires:

```gcode
G00 X15.000 Y5.000
```

This positions the tool tip 6 mm clear of the stock profile and 5 mm back from the front face, establishing a uniform open-air staging position before any cutting begins.

If **Dry-Run Mode** is active (see §4.4), the spindle remains off throughout this move. The operator should visually verify carriage travel before proceeding.

---



---

## 4.3 Feed Rates and Multi-Pass Cutting Strategy

These parameters are validated for engineering wax substrates (see §4.5). The Phase IV compiler must select feedrates automatically based on pass type.

| Pass Type | Feedrate (mm/min) | Depth of Cut (mm) | Surface Result |
|---|---|---|---|
| Roughing | 150 – 250 | 0.5 – 1.0 | Fast stock removal; minor surface marks acceptable |
| Finishing | 50 – 100 | 0.1 – 0.2 | Smooth, dimensionally accurate surface |
| Spring cut | 50 | 0.0 *(repeat)* | Removes deflection artefacts — wax-specific best practice |

> **Spring cut:** A zero-depth repeat of the finishing pass is strongly recommended for wax. The material springs back slightly under cutting force; the repeat pass removes the resulting micro-ridge without further tool advance.

---

## 4.4 Dry-Run Mode and Live Position Readback

### Dry-Run Mode

The UI must expose a **`[Dry Run]`** toggle, defaulting to **ON** after every homing cycle and on first connection. When active:

- All motion commands execute normally.
- The spindle is not engaged (no `M3` / `M4` command is sent).
- A persistent banner indicates dry-run state so the operator cannot mistake it for a live cut.

Dry-run mode lets the operator verify full carriage travel extents before committing to material.

### Live Position Readback Panel

A persistent status panel must poll GRBL at a minimum interval of **200 ms** using the `?` status query character and display:

| Field | Description |
|---|---|
| **MPos X / Y** | Raw machine coordinates from homing switches |
| **WPos X / Y** | Active work coordinates relative to G54 origin |
| **Machine State** | `Idle`, `Run`, `Hold`, `Alarm`, `Jog`, etc. |
| **Feed / Speed** | Current feedrate and spindle RPM |

The panel should highlight **WPos X** and **WPos Y** in a distinct colour (e.g. green) when both read `0.000` at the expected datum position, confirming the Phase II G54 sync resolved correctly before the operator triggers Phase IV.

---

## 4.5 Engineering Wax Material Specification

The term *engineering wax* throughout this document refers specifically to machinable modelling or carving wax of the Ferris or equivalent grade (e.g. Ferris File-A-Wax Green, Araldite XW396, or equivalent polyethylene-based tooling wax). The following properties informed the parameter choices in §4.3:

- **Hardness:** Shore D 55–70. Cuts cleanly without burring at recommended feeds.
- **Melting onset:** ~65–80 °C. Excessive spindle speed or insufficient feed generates frictional heat that glazes the surface.
- **Chip form:** Produces continuous ribbon chips at finishing feeds. Ensure chip clearance around the tool holder.

> **Other wax grades:** Soft blue injection wax and similar low-durometer materials have significantly lower Shore hardness and require reduced feedrates and RPM. Revise §4.3 tables accordingly before use with non-standard substrates.
