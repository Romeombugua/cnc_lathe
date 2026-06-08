# CNC Lathe Control System — Software Documentation

**Project:** Final Year Project (FYP) — Natural Language CNC Lathe Interface  
**Date:** June 2026  

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Technology Stack](#2-technology-stack)
3. [Architecture](#3-architecture)
4. [Module Descriptions](#4-module-descriptions)
   - 4.1 [cnc_system — Project Core](#41-cnc_system--project-core)
   - 4.2 [dashboard — Main Control Interface](#42-dashboard--main-control-interface)
   - 4.3 [machine — Configuration & Logging](#43-machine--configuration--logging)
   - 4.4 [gpt_engine — AI / G-code Engine](#44-gpt_engine--ai--g-code-engine)
   - 4.5 [jobs — Job Management](#45-jobs--job-management)
   - 4.6 [serial_comm — Hardware Communication](#46-serial_comm--hardware-communication)
5. [Database Schema](#5-database-schema)
6. [REST API Reference](#6-rest-api-reference)
7. [User Interface Walkthrough](#7-user-interface-walkthrough)
8. [Operating Workflow (Step-by-Step)](#8-operating-workflow-step-by-step)
9. [Natural Language Feature](#9-natural-language-feature)
10. [G-code Generation Pipeline](#10-g-code-generation-pipeline)
11. [G-code Validation](#11-g-code-validation)
12. [Serial Communication & GRBL Protocol](#12-serial-communication--grbl-protocol)
13. [Safety Mechanisms](#13-safety-mechanisms)
14. [Configuration Reference](#14-configuration-reference)
15. [File & Directory Structure](#15-file--directory-structure)

---

## 1. System Overview

The CNC Lathe Control System is a web-based operator interface that allows a user to control a hobbyist GRBL-based CNC lathe using **plain English descriptions** of machining operations rather than hand-written G-code. The operator types a description such as:

> *"I have a 40 mm diameter bar sticking out 60 mm. Turn it down to 25 mm for a 40 mm length."*

The system extracts the machining parameters from that text using an OpenAI language model, generates a validated multi-pass G-code program (roughing, finishing, and spring-cut passes), and streams it to the machine over a USB serial connection.

The software runs entirely on the operator's local PC. The machine (an Arduino running GRBL firmware) is connected via USB. No cloud connectivity is required during execution — only the G-code generation step contacts the OpenAI API.

---

## 2. Technology Stack

| Layer | Technology | Version |
|---|---|---|
| Web framework | Django | ≥ 5.0 |
| Database | SQLite 3 | (bundled with Python) |
| AI / LLM API | OpenAI Python SDK | ≥ 1.0 |
| Hardware serial | PySerial | ≥ 3.5 |
| Environment config | python-dotenv | ≥ 1.0 |
| Frontend CSS | Bootstrap 5.3 + Bootstrap Icons 1.11 | CDN |
| Frontend JS | Vanilla ES5 JavaScript | — |
| Machine firmware | GRBL | Arduino Uno/Nano |
| Python version | Python 3.11+ | — |

The application is a classic **server-side rendered Django app** with a thin JavaScript layer for real-time UI updates (AJAX polling, progress bars). There is no separate frontend framework (no React, Vue, etc.).

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Operator Browser                     │
│  Bootstrap 5 UI  ←→  Vanilla JS (fetch / postJson)     │
└───────────────────────────┬─────────────────────────────┘
                            │  HTTP (localhost)
┌───────────────────────────▼─────────────────────────────┐
│                    Django Application                   │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌────────┐  ┌──────────┐  │
│  │dashboard │  │  jobs    │  │machine │  │  serial  │  │
│  │  views   │  │  views   │  │ views  │  │  views   │  │
│  └──────────┘  └────┬─────┘  └────────┘  └────┬─────┘  │
│                     │                          │         │
│              ┌──────▼──────┐          ┌────────▼──────┐  │
│              │ gpt_engine  │          │ serial_comm   │  │
│              │ gpt_client  │          │  controller   │  │
│              │  validator  │          │  (singleton)  │  │
│              └──────┬──────┘          └────────┬──────┘  │
│                     │                          │         │
│              ┌──────▼──────┐          ┌────────▼──────┐  │
│              │  OpenAI API │          │  Arduino/GRBL │  │
│              │  (HTTPS)    │          │  (USB Serial) │  │
│              └─────────────┘          └───────────────┘  │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │           SQLite Database (db.sqlite3)           │   │
│  │   Job | MachineConfig | MachineLog               │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

The Django development server (`manage.py runserver`) handles all HTTP traffic. The serial controller is a **thread-safe singleton** that persists across HTTP requests — it holds the open serial port, the GRBL state polling thread, and the job execution thread.

---

## 4. Module Descriptions

### 4.1 `cnc_system` — Project Core

The root Django project package.

| File | Purpose |
|---|---|
| `settings.py` | Django settings: installed apps, database (SQLite), static files, logging, environment variable loading via `python-dotenv` |
| `urls.py` | Root URL dispatcher — routes `/`, `/jobs/`, `/machine/`, `/serial/` to their respective app URL configs |
| `wsgi.py` | WSGI entry point for production deployment |

**Key settings:**
- `SECRET_KEY` — read from environment variable `SECRET_KEY`, falls back to a dev placeholder
- `DEBUG` — controlled by environment variable `DEBUG` (default `True`)
- `ALLOWED_HOSTS = ['*']` — suitable for local LAN use; tighten before public deployment
- Database engine: `django.db.backends.sqlite3`, stored at project root as `db.sqlite3`

---

### 4.2 `dashboard` — Main Control Interface

The dashboard is the primary page the operator uses. It combines every step of the workflow onto a single page.

| File | Purpose |
|---|---|
| `views.py` | Single `index` view — passes the 5 most recent jobs and 10 most recent machine log entries to the template |
| `urls.py` | Maps `/` → `dashboard:index` |
| `templates/dashboard/index.html` | Full single-page control panel (see §7) |

The dashboard template contains approximately 800 lines of HTML + JavaScript. It implements a guided **4-step workflow**: connect → home → sync → generate & execute (see §8).

---

### 4.3 `machine` — Configuration & Logging

Manages persistent machine settings and an audit log of machine events.

**Models:**

| Model | Fields | Description |
|---|---|---|
| `MachineConfig` | `x_limit`, `z_limit`, `baud_rate`, `com_port`, `api_key`, `api_model` | Singleton config record (always `id=1`). Retrieved via `MachineConfig.get_config()` class method |
| `MachineLog` | `event_type`, `message`, `timestamp` | Append-only audit log. Event types: `connection`, `disconnection`, `job_start`, `job_complete`, `job_error`, `emergency_stop`, `validation_error` |

**Views:**

| URL | Method | Description |
|---|---|---|
| `/machine/settings/` | GET / POST | Settings page. GET renders the form; POST validates and saves the config |
| `/machine/status/` | GET | Returns JSON snapshot of the current serial controller state |

**Settings form fields:** OpenAI API key, AI model selection, COM port, baud rate, X-axis limit (mm, radial), Z-axis limit (mm, longitudinal).

---

### 4.4 `gpt_engine` — AI / G-code Engine

The AI layer. No Django models — pure Python logic called by the `jobs` views.

#### `gpt_client.py`

Contains three public functions:

---

**`extract_machining_params(user_text, api_key, model)`**

Introduced to support the natural language input feature. Sends the operator's free-text description to the AI with a structured system prompt that instructs the model to return a JSON object only.

Extracted fields:
- `d_stock` — stock (raw bar) diameter in mm
- `l_stickout` — stickout length in mm *(note: this value is overridden to 30 mm by the server)*
- `d_target` — target (finished) diameter in mm
- `l_cut` — length of the section to be turned in mm

Any field the AI cannot confidently determine is returned as `null`. The function also returns:
- `missing` — list of parameter names that are `null`
- `clarification` — a human-readable note if the AI needs the user to supply more information

Unit conversion (inches → mm) and radius-to-diameter conversion are handled by the AI prompt instructions.

---

**`generate_gcode_from_profile(d_stock, l_stickout, d_target, l_cut, api_key, model, x_limit)`**

The primary G-code generation function. Builds a detailed engineering prompt (`_build_profile_prompt`) that encodes:

- Machine hardware constraints (2-axis NEMA 17, GRBL, DC spindle S500–S1000)
- Workpiece measurements and all pre-computed derived values (radii, approach clearance, cut depth)
- The exact per-pass motion pattern the AI must follow (G00 approach → G00 to Y0.5 → G01 feed cut → G00 retract)
- Required pass strategy:
  1. **Roughing passes** — 0.5–1.0 mm radial depth, feed 150–250 mm/min, S500–S700
  2. **Finishing passes** — 0.1–0.2 mm radial depth, feed 50–100 mm/min, S700–S900
  3. **Spring cut** — zero radial advance, feed 50 mm/min, S900–S1000
- Allowed G-codes and M-codes (strict whitelist)
- Forbidden codes (G40/41/42, Z words, T words, tool change M-codes, etc.)

Post-processing: spindle speeds are clamped to S500–S1000 via regex after the API response is received, and any accidental markdown fences are stripped.

---

**`generate_gcode(command, api_key, model, x_limit, y_limit)`**

Legacy free-text G-code generator used by the `/jobs/generate/` endpoint (the Command page). Accepts a raw machining instruction as text and returns G-code. Less structured than `generate_gcode_from_profile` — used for ad-hoc commands.

---

#### `validator.py`

**`validate_gcode(gcode_text, x_limit, y_limit, max_feed_rate)`**

A pure-Python static analysis pass that checks AI-generated G-code before it is sent to hardware. Returns a dict:

```json
{
  "valid": true,
  "errors": [],
  "warnings": ["Line 4: Feed rate 480 is close to the 500 mm/min limit"],
  "line_count": 42
}
```

Checks performed:
- **Syntax detection** — rejects lines starting with markdown or comment characters
- **G-code whitelist** — only `G00, G01, G02, G03, G04, G10, G20, G21, G28, G49, G54, G90, G91, G92` are allowed
- **M-code whitelist** — only `M03, M05, M30` are allowed
- **Axis limit enforcement** — X and Y coordinates must not exceed `x_limit` and `y_limit`
- **Spindle speed limit** — S-words must not exceed 1000
- **Feed rate limit** — F-words must not exceed `max_feed_rate` (default 1000 mm/min)

Validation is always run before execution. Jobs that fail validation are rejected with an error message and never sent to the serial port.

---

### 4.5 `jobs` — Job Management

Manages the lifecycle of machining jobs: creation, G-code storage, execution status, and history.

**Model — `Job`:**

| Field | Type | Description |
|---|---|---|
| `command` | `TextField` | The natural language command or profile description that originated the job |
| `generated_gcode` | `TextField` | The full G-code program stored after generation |
| `execution_status` | `CharField` | `pending` / `running` / `completed` / `failed` / `stopped` |
| `created_at` | `DateTimeField` | Auto-set on creation |
| `completed_at` | `DateTimeField` | Set by the serial controller when execution finishes |
| `error_message` | `TextField` | Populated if execution fails or is stopped |

**Views / Endpoints:**

| URL | Method | Description |
|---|---|---|
| `/jobs/command/` | GET | Renders the manual G-code command page |
| `/jobs/generate/` | POST | Calls `generate_gcode()`, creates a Job record, returns `{gcode, job_id}` |
| `/jobs/validate/` | POST | Runs `validate_gcode()` on submitted G-code, returns validation result |
| `/jobs/execute/` | POST | Validates then streams G-code to the machine via the serial controller |
| `/jobs/generate-profile/` | POST | Calls `generate_gcode_from_profile()` with the four profile parameters (stickout hardcoded to 30 mm server-side) |
| `/jobs/parse-nl/` | POST | Calls `extract_machining_params()`, returns extracted JSON parameters |
| `/jobs/history/` | GET | Renders the job history page |
| `/jobs/<id>/detail/` | GET | Returns JSON detail of a single job (used for progress polling) |
| `/jobs/cycle/` | GET | Legacy redirect → dashboard |

---

### 4.6 `serial_comm` — Hardware Communication

The most complex module. Contains the `SerialController` singleton and the HTTP views that expose it to the frontend.

#### `controller.py` — `SerialController`

A **thread-safe singleton** implemented with a double-checked locking pattern. One instance persists for the entire server lifetime and is shared across all HTTP request threads.

**Internal state:**

| Attribute | Description |
|---|---|
| `_serial` | The open `serial.Serial` object |
| `_status` | `disconnected` / `connected` / `running` / `error` |
| `_grbl_state` | Last GRBL state string from `?` poll: `Idle`, `Run`, `Hold`, `Alarm`, etc. |
| `_mpos` / `_wpos` | Machine position and work position `{X, Y}` |
| `_feed` / `_speed` | Current feed rate and spindle speed from status reports |
| `_dry_run` | Boolean — when `True`, all `M03` spindle-on commands are suppressed before sending |
| `_homed` / `_synced` | Phase completion flags (survive page refreshes) |
| `_poll_thread` | Background daemon thread sending `?` every 200 ms to GRBL |
| `_job_thread` | Background daemon thread streaming G-code lines |
| `_stop_event` | `threading.Event` used to interrupt the job thread on emergency stop or cancel |

**Key methods:**

| Method | Description |
|---|---|
| `connect(port, baud_rate)` | Opens the serial port, waits 2 s for the Arduino bootloader, resets coordinate offsets, starts the poll thread |
| `disconnect()` | Stops the poll thread, closes the port, resets all state |
| `emergency_stop()` | Sets stop event, sends GRBL soft-reset byte `0x18` (Ctrl-X) |
| `cancel_job()` | Sets stop event, waits for job thread, marks DB record as `stopped` |
| `home()` | Sends GRBL homing command `$H`, sets `_homed = True` on success |
| `sync_workpiece(l_stickout)` | Sets G54 work coordinate origin at the stock face, moves tool to safe staging position |
| `send_gcode(lines, job_id)` | Launches `_execute_gcode` in a background thread |
| `set_dry_run(enabled)` | Toggles spindle suppression |
| `get_status()` | Returns a JSON-serialisable dict of all live state for the frontend to poll |
| `get_available_ports()` | Lists all COM ports visible to the OS |

**G-code execution (`_execute_gcode`):**

The job thread iterates over the G-code lines. For each non-blank, non-comment line:
1. If `_dry_run` is active and the line contains `M03`, the `M03` is replaced with a comment
2. The line is written to the serial port followed by `\n`
3. The thread blocks waiting for `ok` or `error:` from GRBL
4. On `error:`, execution halts and the job is marked `failed`
5. On `_stop_event`, execution halts and the job is marked `stopped`
6. Progress counters (`_current_line`, `_total_lines`) are updated after each line for real-time UI display

**GRBL status polling (`_poll_loop`):**

Runs every 200 ms. Sends `?` to GRBL and parses the `<State|MPos:x,y|WPos:x,y|FS:f,s>` response to update `_grbl_state`, `_mpos`, `_wpos`, `_feed`, and `_speed`.

#### `views.py` — Serial HTTP Endpoints

| URL | Method | Description |
|---|---|---|
| `/serial/connect/` | POST | `{port, baud_rate}` → connects to machine |
| `/serial/disconnect/` | POST | Disconnects and resets |
| `/serial/emergency-stop/` | POST | Triggers `emergency_stop()` |
| `/serial/ports/` | GET | Returns list of available COM ports |
| `/serial/home/` | POST | Initiates GRBL homing cycle |
| `/serial/sync/` | POST | `{l_stickout}` → sets work origin and moves to safe position |
| `/serial/dry-run/` | POST | `{enabled: bool}` → toggles dry-run mode |
| `/serial/cancel-job/` | POST | Cancels the running job |

The machine status is also available at `/machine/status/` (GET), which the frontend polls every second to update the live position display and connection indicator.

---

## 5. Database Schema

The application uses three database tables managed by Django's ORM and stored in `db.sqlite3`.

### `jobs_job`

```
id               INTEGER PRIMARY KEY AUTOINCREMENT
command          TEXT
generated_gcode  TEXT
execution_status VARCHAR(20)   -- pending | running | completed | failed | stopped
created_at       DATETIME
completed_at     DATETIME (nullable)
error_message    TEXT
```

### `machine_machineconfig`

```
id         INTEGER PRIMARY KEY  -- always 1 (singleton)
x_limit    REAL   DEFAULT 100.0
z_limit    REAL   DEFAULT 200.0
baud_rate  INTEGER DEFAULT 115200
com_port   VARCHAR(20) DEFAULT 'COM3'
api_key    VARCHAR(300)
api_model  VARCHAR(50) DEFAULT 'gpt-5'
```

### `machine_machinelog`

```
id          INTEGER PRIMARY KEY AUTOINCREMENT
event_type  VARCHAR(50)   -- connection | disconnection | job_start | job_complete | job_error | emergency_stop | validation_error
message     TEXT
timestamp   DATETIME AUTO
```

---

## 6. REST API Reference

All POST endpoints accept and return `application/json`. Django CSRF protection is active on all form-based views; the JavaScript frontend sends the CSRF token in the `X-CSRFToken` header.

### Jobs

**POST `/jobs/parse-nl/`** — Extract parameters from natural language

Request:
```json
{ "text": "Turn a 40mm bar down to 25mm for 40mm length" }
```
Response:
```json
{
  "success": true,
  "d_stock": 40.0,
  "l_stickout": null,
  "d_target": 25.0,
  "l_cut": 40.0,
  "missing": ["l_stickout"],
  "clarification": ""
}
```

**POST `/jobs/generate-profile/`** — Generate multi-pass G-code

Request:
```json
{ "d_stock": 40.0, "d_target": 25.0, "l_cut": 40.0 }
```
*(Note: `l_stickout` is ignored by the server — hardcoded to 30 mm)*

Response:
```json
{ "success": true, "gcode": "G21 G90\nM03 S600\n...", "job_id": 7 }
```

**POST `/jobs/execute/`** — Execute G-code on machine

Request:
```json
{ "gcode": "G21 G90\n...", "job_id": 7, "command": "Profile turn" }
```
Response:
```json
{ "success": true, "job_id": 7, "message": "Job started" }
```

**GET `/jobs/<id>/detail/`** — Poll job progress

Response:
```json
{
  "id": 7,
  "command": "Profile turn: Ø40→25 mm, L_stickout=30 mm, L_cut=40 mm",
  "execution_status": "running",
  "generated_gcode": "...",
  "created_at": "2026-06-08T14:23:00Z",
  "error_message": ""
}
```

### Serial / Machine

**GET `/machine/status/`** — Live machine state

Response:
```json
{
  "status": "connected",
  "grbl_state": "Idle",
  "mpos": {"X": 12.5, "Y": 0.0},
  "wpos": {"X": 6.5, "Y": 0.0},
  "feed": 0,
  "speed": 0,
  "dry_run": true,
  "homed": true,
  "synced": false,
  "current_line": 0,
  "total_lines": 0,
  "error_message": ""
}
```

---

## 7. User Interface Walkthrough

The UI is a **dark-themed single-page dashboard** with a fixed sidebar and a top status bar.

### Sidebar Navigation

- **Dashboard** — main workflow page (default landing page at `/`)
- **History** — table of all past jobs with G-code viewer modal
- **Settings** — AI and machine configuration form

### Top Bar

Always visible. Shows:
- A coloured status dot (grey = disconnected, green = connected/idle, amber = running, red = error/alarm)
- A text label for the current state
- A red **EMERGENCY STOP** button that sends `0x18` to GRBL and kills the running job immediately

### Dashboard — Step Cards

The main area is divided into four numbered step cards that unlock sequentially:

**Step 1 — Connect to Machine**  
Dropdown to select the COM port (auto-populated by polling `/serial/ports/`), baud rate selector, and a Connect button. Disconnect is also available once connected.

**Step 2 — Initialize & Home Machine**  
Single "Initialize & Home" button that triggers `$H` (GRBL homing cycle). Step 3 unlocks only after homing completes.

**Step 3 — Measure & Sync Workpiece**  
Contains:
- A **natural language input panel** (plain English description → AI parameter extraction)
- Four parameter input fields: Stock Diameter, Stickout Length (read-only, 30 mm), Target Diameter, Turning Length
- Derived value display: X approach clearance, G54 Y offset
- Spindle speed and feed rate reference inputs (informational)
- "Sync & Move to Safe Zone" button

**Step 4 — Generate & Execute Cutting Cycle**  
- "Generate with AI" button — calls `/jobs/generate-profile/`, displays G-code in a code preview
- Dry-run toggle (spindle suppression)
- "Execute" button — validates then streams G-code to the machine
- Live progress bar showing lines sent / total lines
- Cancel Job button (visible during execution)

### Right Column (Dashboard)

- Live position panel: MPos X/Y, WPos X/Y, feed, speed, GRBL state badge
- Recent jobs summary panel (last 5 jobs)
- Machine log panel (last 10 events)

### History Page

Full table of all jobs. Each row shows job ID, truncated command, G-code preview, status badge, and timestamp. An eye button opens a modal with the full G-code in a monospace terminal-style viewer.

### Settings Page

Form with three sections: AI Configuration (API key, model), Serial / Arduino (COM port, baud rate), Machine Axis Limits (X and Z mm limits). Changes are saved with a standard Django POST form.

---

## 8. Operating Workflow (Step-by-Step)

The following is the intended end-to-end procedure for a turning operation:

1. **Configure** — visit Settings, enter the OpenAI API key and confirm the correct COM port.

2. **Connect** — on the Dashboard, select the COM port from the dropdown and click Connect. The system opens the serial port, waits for the Arduino bootloader (2 s), sends coordinate reset commands, and starts the 200 ms GRBL status poll thread.

3. **Home** — click "Initialize & Home Machine". GRBL executes `$H`, driving the axes to their limit switches to establish a repeatable machine origin. The Homed flag is set once GRBL reports `Idle` after the homing sequence.

4. **Measure** — physically measure the workpiece and enter (or speak) the dimensions:
   - Optionally type a plain English description and click the AI extract button (✨)
   - Stock Diameter (D_stock)
   - Stickout Length (fixed at 30 mm — do not overshoot)
   - Target Diameter (D_target)
   - Turning Length (L_cut)

5. **Sync** — click "Sync & Move to Safe Zone". The system sends G-code to GRBL that:
   - Sets G54 work coordinates so Y=0 is the front face of the stock
   - Moves the tool to a safe approach position outside the workpiece

6. **Generate** — click "Generate with AI". The profile parameters are sent to the OpenAI API with a structured engineering prompt. The API returns a complete multi-pass G-code program. The G-code is displayed in the preview panel.

7. **Review** — optionally scroll through the G-code preview. The code can be manually edited before execution.

8. **Dry Run** — the dry-run toggle is ON by default. Execute the job in dry-run mode first: the machine moves through all programmed paths but the spindle does not engage (`M03` commands are suppressed).

9. **Execute** — disable dry run, then click Execute. The system validates the G-code, creates/updates the Job record, and begins streaming lines to GRBL. A progress bar updates in real time.

10. **Monitor** — the live position panel updates every second. The GRBL state badge shows `Run` during cutting and `Idle` when complete.

11. **Stop if needed** — the Cancel Job button gracefully stops execution. The EMERGENCY STOP button sends an immediate hardware reset.

---

## 9. Natural Language Feature

### Purpose

Instead of requiring the operator to know exact field names and measurement units, they can describe the operation in plain English. The AI extracts the four numerical parameters needed to generate the G-code program.

### Implementation

**Frontend (`templates/dashboard/index.html`):**

A textarea and a sparkle button (✨) sit above the profile input fields in Step 3. When clicked:
1. The text is POSTed to `/jobs/parse-nl/`
2. On success, extracted values are written into the corresponding number inputs
3. `updateDerived()` is called to refresh dependent hints and limits
4. A feedback line below the textarea shows which fields were filled and which are still missing

**Backend (`jobs/views.py` → `parse_natural_language`):**

Validates that the API key is configured, then calls `extract_machining_params()`.

**AI layer (`gpt_engine/gpt_client.py` → `extract_machining_params`):**

Sends the user text to the OpenAI API with this system instruction (abbreviated):

> *"Extract d_stock, l_stickout, d_target, l_cut in mm and return ONLY a JSON object. Use null for missing values. Convert inches to mm. Return a clarification string if more information is needed."*

The function:
- Strips any markdown fences from the response
- Parses the JSON
- Builds the `missing` list
- Returns the full dict to the view

### Safety Note

`l_stickout` is hardcoded to **30 mm** both in the frontend (read-only field) and in the `generate_profile` view (server-side override). Even if the AI extracts a different stickout value from the natural language input, it is ignored. This prevents the operator from accidentally programming a longer tool path than the machine's safe travel allows.

---

## 10. G-code Generation Pipeline

```
Operator input
     │
     ▼
extract_machining_params()   ← /jobs/parse-nl/    (NL path)
     │   OR
     ▼
Manual number entry                                (direct path)
     │
     ▼
generate_gcode_from_profile()  ← /jobs/generate-profile/
     │
     │  1. Build engineering prompt (_build_profile_prompt)
     │     - Machine constraints
     │     - Workpiece measurements & derived values
     │     - Per-pass motion pattern specification
     │     - Pass strategy (rough / finish / spring)
     │     - G-code / M-code whitelist
     │
     │  2. Call OpenAI responses.create()
     │
     │  3. Extract output_text; traverse output[] on fallback
     │
     │  4. Strip markdown fences
     │
     │  5. Clamp spindle speeds to S500–S1000
     │
     ▼
validate_gcode()  ← /jobs/validate/  (also called inside /jobs/execute/)
     │
     ▼
Job record created in DB (status: pending)
     │
     ▼
serial_controller.send_gcode()  ← /jobs/execute/
     │
     ▼
_execute_gcode() background thread
  - Line-by-line GRBL streaming
  - ok / error: acknowledgement
  - Dry-run spindle suppression
  - Progress counter updates
     │
     ▼
Job record updated (status: completed / failed / stopped)
MachineLog event created
```

---

## 11. G-code Validation

Validation (`gpt_engine/validator.py`) is performed in two places:
1. On demand from the UI via `POST /jobs/validate/`
2. Automatically inside `POST /jobs/execute/` before any G-code is sent to hardware

The validator processes each line independently:

1. **Skip** blank lines and pure comments (`;` or `(` prefixes)
2. **Reject** non-G-code content (markdown markers: `#`, `` ` ``, `*`, `-`, `>`)
3. Strip inline comments and T-words (tool selection — not present on this machine)
4. Check every `G` word against the whitelist
5. Check every `M` word against the whitelist
6. Check every `X` and `Y` coordinate against axis limits
7. Check every `S` value against the spindle maximum (1000)
8. Check every `F` value against the feed rate ceiling (1000 mm/min)

Errors block execution. Warnings (close to limits) are advisory only.

---

## 12. Serial Communication & GRBL Protocol

GRBL is a CNC firmware that runs on Arduino and speaks a subset of RS274/NGC G-code over a serial port.

### Connection

The system opens the serial port at 115200 baud (configurable). After opening, it waits 2 seconds for the Arduino bootloader to finish, then sends:
- `G92.1\n` — cancel any residual coordinate offsets
- `G49\n` — cancel tool length offset

### Status Polling

A background thread sends `?` to GRBL every 200 ms. GRBL responds with:
```
<Idle|MPos:0.000,0.000|WPos:0.000,0.000|FS:0,0>
```
The controller parses this with a regex to extract state, machine position, work position, feed, and speed.

### Streaming Protocol

G-code is sent one line at a time. After each line, the thread blocks reading until GRBL returns `ok` or `error:<code>`. This **synchronous line-by-line** protocol ensures that the machine never receives more commands than it can process and provides precise progress tracking.

### Emergency Stop

Sending the byte `0x18` (ASCII Ctrl-X) to GRBL triggers an immediate soft reset. GRBL halts all motion, disengages the spindle, and returns to alarm state. The operator must re-home before cutting again.

### Dry Run Mode

When dry run is active (`_dry_run = True`), the execution thread intercepts any line containing `M03` (spindle on) and replaces it with a comment before sending. All motion commands execute normally, allowing the operator to verify the tool path without engaging the cutting spindle.

---

## 13. Safety Mechanisms

The system implements multiple layers of protection:

| Mechanism | Where | Description |
|---|---|---|
| **G-code validation** | `validator.py` | Whitelist checking, axis limit enforcement, feed/speed caps — always runs before execution |
| **Dry run mode** | `SerialController` | Spindle commands suppressed; ON by default after every connection |
| **Emergency stop** | UI top bar + `controller.py` | Sends GRBL `0x18` soft-reset immediately; kills the job thread |
| **Cancel job** | Dashboard UI | Graceful stop; waits for job thread; marks DB record `stopped` |
| **Stickout hardcode** | `views.py` + frontend | `l_stickout` fixed at 30 mm server-side regardless of user or AI input |
| **Spindle speed clamp** | `gpt_client.py` | Post-processing regex clamps all S-words to 500–1000 after AI generation |
| **Axis limit rejection** | `validator.py` | Any X/Y value exceeding configured machine limits causes the job to be rejected |
| **Pre-execution validation** | `jobs/views.py` → `execute` | Validation is always re-run at the execute endpoint, even if the UI already validated |
| **Singleton serial controller** | `controller.py` | Only one serial connection and one job thread can exist at a time; concurrent execute calls are rejected |
| **Phase locking** | Frontend JS | Step 3 (sync) is disabled until homing completes; Step 4 (generate/execute) is disabled until sync completes |

---

## 14. Configuration Reference

### Environment Variables (`.env` file at project root)

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | Dev placeholder | Django secret key — must be changed in production |
| `DEBUG` | `True` | Set to `False` in production |

### Database Settings (`MachineConfig`, via Settings page)

| Field | Default | Description |
|---|---|---|
| `api_key` | *(empty)* | OpenAI API key — required for all AI features |
| `api_model` | `gpt-5` | OpenAI model name. `gpt-4o` recommended for accuracy |
| `com_port` | `COM3` | Serial port of the Arduino (Windows: `COM3`, Linux: `/dev/ttyUSB0`) |
| `baud_rate` | `115200` | Must match GRBL firmware setting |
| `x_limit` | `100.0` | Maximum X axis travel in mm (radial/cross-slide) |
| `z_limit` | `200.0` | Maximum Y axis travel in mm (longitudinal/carriage) |

### Hardcoded Constants

| Constant | Value | Location | Description |
|---|---|---|---|
| `L_STICKOUT` | `30` mm | `dashboard/index.html` (JS) + `jobs/views.py` | Fixed stickout length |
| Spindle min | `500` RPM | `gpt_client.py` | Motor stalls below this value |
| Spindle max | `1000` RPM | `gpt_client.py`, `validator.py` | DC motor PWM ceiling |
| Feed rate max | `1000` mm/min | `validator.py` | Hard rejection ceiling |
| GRBL poll interval | `200` ms | `controller.py` | `?` status query frequency |
| Arduino boot wait | `2` s | `controller.py` | Delay after serial open |

---

## 15. File & Directory Structure

```
cnc_lathe/
│
├── manage.py                   # Django management entry point
├── requirements.txt            # Python dependencies
├── db.sqlite3                  # SQLite database (auto-created)
│
├── cnc_system/                 # Django project package
│   ├── settings.py
│   ├── urls.py                 # Root URL dispatcher
│   └── wsgi.py
│
├── dashboard/                  # Main control UI app
│   ├── views.py
│   └── urls.py
│
├── machine/                    # Config & logging app
│   ├── models.py               # MachineConfig, MachineLog
│   ├── views.py                # Settings page, status endpoint
│   ├── admin.py                # Django admin registration
│   └── urls.py
│
├── gpt_engine/                 # AI / G-code engine (no models)
│   ├── gpt_client.py           # extract_machining_params, generate_gcode_from_profile, generate_gcode
│   └── validator.py            # validate_gcode
│
├── jobs/                       # Job lifecycle management app
│   ├── models.py               # Job model
│   ├── views.py                # All job endpoints incl. parse-nl
│   ├── urls.py
│   └── migrations/
│
├── serial_comm/                # Hardware communication app
│   ├── controller.py           # SerialController singleton
│   ├── views.py                # HTTP endpoints wrapping the controller
│   └── urls.py
│
├── templates/
│   ├── base.html               # Sidebar, top bar, emergency stop
│   ├── dashboard/
│   │   └── index.html          # Main 4-step workflow page (~850 lines)
│   ├── jobs/
│   │   ├── command.html        # Manual G-code command page
│   │   ├── history.html        # Job history table
│   │   └── cycle.html          # Legacy cycle page (redirects to dashboard)
│   └── machine/
│       └── settings.html       # Settings form
│
└── static/
    ├── css/
    │   └── style.css           # Custom dark theme styles
    └── js/
        └── cnc.js              # Shared utilities (postJson, showToast, etc.)
```
