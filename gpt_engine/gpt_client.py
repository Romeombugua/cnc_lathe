import re

from openai import OpenAI


def _build_profile_prompt(
    d_stock: float,
    l_stickout: float,
    d_target: float,
    l_cut: float,
    x_limit: float,
) -> str:
    r_stock  = d_stock  / 2.0
    r_target = d_target / 2.0
    x_approach = r_stock + 6.0

    return (
        f"You are a G-code programmer for a hobbyist GRBL-based CNC lathe.\n\n"
        f"MACHINE HARDWARE:\n"
        f"- 2-axis (X and Y only) — X is radial (cross-slide), Y is longitudinal (carriage)\n"
        f"- NEMA 17 stepper motors, GRBL firmware on Arduino\n"
        f"- DC spindle with PWM speed control, operational range S500–S1000 (below S500 the motor stalls)\n"
        f"- No coolant, no tool changer\n"
        f"- X-axis limit: {x_limit:.1f} mm (radius)\n\n"
        f"CRITICAL — DIAMETER vs RADIUS:\n"
        f"- All operator measurements below are DIAMETERS.\n"
        f"- All X coordinates you emit must be RADII (divide diameter by 2).\n"
        f"- Emitting a diameter as an X coordinate doubles the cut depth and crashes the machine.\n\n"
        f"WORKPIECE MEASUREMENTS (operator-supplied):\n"
        f"- Stock diameter   : {d_stock:.3f} mm  →  stock radius   = {r_stock:.3f} mm\n"
        f"- Target diameter  : {d_target:.3f} mm  →  target radius  = {r_target:.3f} mm\n"
        f"- Stickout length  : {l_stickout:.3f} mm  (total bar overhang from chuck face)\n"
        f"- Turning length   : {l_cut:.3f} mm  (length of section to be turned)\n\n"
        f"DERIVED VALUES (already computed — use these exactly):\n"
        f"- Approach clearance X : {x_approach:.3f} mm  (6 mm beyond stock radius; rapid to here first)\n"
        f"- G54 work coordinate system is already active — Y=0 is the front face of the stock.\n"
        f"- Cutting depth end    : Y={-l_cut:.3f} mm  (move in the NEGATIVE Y direction to cut along the stock)\n\n"
        f"CRITICAL — PER-PASS MOTION PATTERN (follow this exactly for every pass):\n"
        f"  Step 1: G00 X<radius>          ; rapid to this pass's cutting X radius (never use G01 to approach in X)\n"
        f"  Step 2: G00 Y0.500             ; rapid to 0.5 mm in front of the stock face — DO NOT use G01 here\n"
        f"  Step 3: G01 Y{-l_cut:.3f} F<feed> ; feed cut along the full length\n"
        f"  Step 4: G00 X{x_approach:.3f}  ; rapid retract in X to clearance\n"
        f"  Step 5: G00 Y5.000             ; rapid back to safe Y\n"
        f"NEVER use G01 to travel from Y=5 to Y=0 — that creates an unintended facing cut on the stock end.\n\n"
        f"MATERIAL: Engineering wax (Ferris File-A-Wax or equivalent, Shore D 55-70).\n\n"
        f"REQUIRED PASS STRATEGY (generate all three stages):\n"
        f"1. ROUGHING PASSES — feedrate 150-250 mm/min, 0.5-1.0 mm radial depth per pass.\n"
        f"   Leave ~0.3 mm radial stock for finishing.\n"
        f"   Spindle: choose S500–S700 (slower = more torque for bulk removal in wax).\n"
        f"2. FINISHING PASSES — feedrate 50-100 mm/min, 0.1-0.2 mm radial depth.\n"
        f"   Make at least two finishing passes down to the target radius.\n"
        f"   Spindle: choose S700–S900 (higher speed for a cleaner surface finish).\n"
        f"3. SPRING CUT — feedrate 50 mm/min, zero radial advance.\n"
        f"   Repeat the finishing pass at the same X without moving in X first.\n"
        f"   Spindle: choose S900–S1000 (maximum speed for a polished final pass).\n"
        f"   This removes the micro-ridge that wax leaves due to spring-back under cutting force.\n\n"
        f"ALLOWED G-CODES (use only these):\n"
        f"  G00, G01, G02, G03 — motion\n"
        f"  G04                — dwell\n"
        f"  G20, G21           — units (use G21 mm)\n"
        f"  G28                — home\n"
        f"  G90, G91           — positioning (use G90 absolute)\n"
        f"  G92                — coordinate offset\n\n"
        f"ALLOWED M-CODES (use only these):\n"
        f"  M03 S<value>       — spindle on (always include S word, range S500–S1000)\n"
        f"  M05                — spindle off\n"
        f"  M30                — program end\n\n"
        f"FORBIDDEN (never include):\n"
        f"  G40/G41/G42  G94/G95/G96/G97  G17/G18/G19\n"
        f"  M06/M07/M08/M09  T words  Z words (this machine has no Z axis)\n\n"
        f"OUTPUT RULES:\n"
        f"- Start program with: G21 G90\n"
        f"- Turn spindle on immediately after using the speed appropriate for the first pass (M03 S<value>, S500–S1000).\n"
        f"- Change spindle speed with a new M03 S<value> line before each new pass stage.\n"
        f"- Rapid to safe approach position first: G00 X{x_approach:.3f} Y5.000\n"
        f"- Every pass must approach Y=0.500 with G00 (rapid), never with G01.\n"
        f"- Use Y (not Z) for the longitudinal axis throughout.\n"
        f"- End with M05 then M30.\n"
        f"- Feed rates must be 10-500 mm/min.\n"
        f"- Add a brief G-code comment (semicolon) before each stage.\n"
        f"- Output raw G-code ONLY — no markdown, no code fences, no explanations."
    )


def generate_gcode_from_profile(
    d_stock: float,
    l_stickout: float,
    d_target: float,
    l_cut: float,
    api_key: str,
    model: str = 'gpt-4o',
    x_limit: float = 100.0,
) -> str:
    """Call the OpenAI API to generate a multi-pass turning program from profile parameters."""
    if not api_key:
        raise ValueError(
            'OpenAI API key is not configured. Please set it in the Settings page.'
        )

    client = OpenAI(api_key=api_key)
    prompt = _build_profile_prompt(d_stock, l_stickout, d_target, l_cut, x_limit)

    response = client.responses.create(
        model=model,
        instructions=(
            'You are a CNC lathe G-code generator. '
            'Output only raw G-code — no markdown, no explanations.'
        ),
        input=prompt,
    )

    import logging
    logger = logging.getLogger(__name__)
    logger.warning('GPT profile response: %s', repr(response))

    gcode = response.output_text.strip()

    if not gcode:
        try:
            for item in response.output:
                if getattr(item, 'type', None) == 'message':
                    for part in item.content:
                        text = getattr(part, 'text', None)
                        if text:
                            gcode = text.strip()
                            break
                if gcode:
                    break
        except Exception:
            pass

    if not gcode:
        raise ValueError('GPT returned an empty response.')

    # Strip accidental markdown fences
    if gcode.startswith('```'):
        lines = gcode.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == '```' else len(lines)
        gcode = '\n'.join(lines[start:end]).strip()

    # Clamp spindle speed to S500–S1000 (motor stalls below 500)
    def _clamp_speed(m):
        val = min(max(int(float(m.group(1))), 500), 1000)
        return f'S{val}'
    gcode = re.sub(r'\bS(\d+(?:\.\d+)?)\b', _clamp_speed, gcode, flags=re.IGNORECASE)

    return gcode


def _build_prompt(command: str, x_limit: float, y_limit: float) -> str:
    return (
        f"You are a G-code generator for a hobbyist GRBL-based CNC lathe.\n\n"
        f"Machine hardware:\n"
        f"- 2-axis (X and Y only) driven by NEMA 17 stepper motors\n"
        f"- DC motor spindle with PWM speed control (max spindle speed S1000)\n"
        f"- No coolant system\n"
        f"- No tool changer\n"
        f"- Controller: GRBL firmware on Arduino\n\n"
        f"Axis limits:\n"
        f"- X-axis maximum: {x_limit} mm (radial axis)\n"
        f"- Y-axis maximum: {y_limit} mm (longitudinal axis)\n\n"
        f"ALLOWED G-codes only (do not use any others):\n"
        f"  G00, G01, G02, G03  — motion\n"
        f"  G04                 — dwell\n"
        f"  G20, G21            — units (use G21 for mm)\n"
        f"  G28                 — home\n"
        f"  G90, G91            — positioning mode (use G90 absolute)\n"
        f"  G92                 — coordinate offset\n\n"
        f"ALLOWED M-codes only (do not use any others):\n"
        f"  M03 S<speed> — spindle on with speed (1–1000)\n"
        f"  M05 — spindle off\n"
        f"  M30 — program end\n\n"
        f"FORBIDDEN (never include these):\n"
        f"  G40, G41, G42       — cutter compensation (not supported)\n"
        f"  G94, G95, G96, G97  — feed/speed mode (not supported)\n"
        f"  G17, G18, G19       — plane selection (not needed)\n"
        f"  M06, M07, M08, M09  — tool change / coolant (no hardware)\n"
        f"  T words             — tool selection (no tool changer)\n\n"
        f"Rules:\n"
        f"- Start with G21 G90.\n"
        f"- Use M03 S1000 to turn spindle on (always include S word, max 1000), M05 to turn it off.\n"
        f"- Use Y for the longitudinal axis, not Z.\n"
        f"- End with M05 then M30.\n"
        f"- Keep feed rates between 10 and 500 mm/min.\n"
        f"- Output raw G-code only — no explanations, no markdown, no code fences.\n\n"
        f"Command:\n{command}"
    )


def extract_machining_params(
    user_text: str,
    api_key: str,
    model: str = 'gpt-4o',
) -> dict:
    """
    Use the AI to extract machining profile parameters from a natural language description.

    Returns a dict with any of:
        d_stock    (float) — stock diameter in mm
        l_stickout (float) — stickout length in mm
        d_target   (float) — target diameter in mm
        l_cut      (float) — turning length in mm
        missing    (list[str]) — parameter names that could not be extracted
        clarification (str) — human-readable note if the AI needs more info
    """
    if not api_key:
        raise ValueError(
            'OpenAI API key is not configured. Please set it in the Settings page.'
        )

    system_instructions = (
        'You are a CNC parameter extraction assistant. '
        'The user will describe a turning operation in natural language. '
        'Extract these four machining parameters and respond with ONLY a JSON object — no prose:\n'
        '  d_stock    : stock (raw) diameter in mm (number or null)\n'
        '  l_stickout : bar stickout length in mm (number or null)\n'
        '  d_target   : target (finished) diameter in mm (number or null)\n'
        '  l_cut      : length of material to be turned in mm (number or null)\n'
        'Use null for any parameter not mentioned. '
        'If a diameter is given as a radius, double it. '
        'If units are inches, convert to mm (1 in = 25.4 mm). '
        'Also include a "clarification" string (or empty string) if you need the user to provide missing values.'
    )

    import json as _json

    client = OpenAI(api_key=api_key)
    response = client.responses.create(
        model=model,
        instructions=system_instructions,
        input=user_text,
    )

    # Extract text — try convenience property first, then traverse output[]
    raw = (response.output_text or '').strip()
    if not raw:
        try:
            for item in response.output:
                if getattr(item, 'type', None) == 'message':
                    for part in item.content:
                        text = getattr(part, 'text', None)
                        if text:
                            raw = text.strip()
                            break
                if raw:
                    break
        except Exception:
            pass

    if not raw:
        raise ValueError('AI returned an empty response. Try rephrasing your description.')

    # Strip accidental markdown fences
    if raw.startswith('```'):
        lines = raw.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip().startswith('```') else len(lines)
        raw = '\n'.join(lines[start:end]).strip()

    try:
        params = _json.loads(raw)
    except _json.JSONDecodeError:
        # Try to find a JSON object embedded in any surrounding text
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            params = _json.loads(m.group())
        else:
            raise ValueError(f'AI returned unexpected format: {raw[:200]}')

    # Identify which params are missing
    keys = ['d_stock', 'l_stickout', 'd_target', 'l_cut']
    missing = [k for k in keys if params.get(k) is None]
    params['missing'] = missing

    return params


def generate_gcode(
    command: str,
    api_key: str,
    model: str = 'gpt-5',
    x_limit: float = 100.0,
    y_limit: float = 200.0,
) -> str:
    """Call the OpenAI API and return raw G-code for the given machining command."""
    if not api_key:
        raise ValueError(
            'OpenAI API key is not configured. Please set it in the Settings page.'
        )

    client = OpenAI(api_key=api_key)
    prompt = _build_prompt(command, x_limit, y_limit)

    response = client.responses.create(
        model=model,
        instructions=(
            'You are a CNC lathe G-code generator. '
            'Output only raw G-code — no markdown, no explanations.'
        ),
        input=prompt,
        # max_output_tokens=1000,
    )

    import logging
    logger = logging.getLogger(__name__)
    logger.warning('GPT raw response: %s', repr(response))

    # output_text is a convenience property; fall back to manual traversal
    # if it returns empty (can happen when content type differs across SDK versions)
    gcode = response.output_text.strip()

    if not gcode:
        try:
            for item in response.output:
                if getattr(item, 'type', None) == 'message':
                    for part in item.content:
                        text = getattr(part, 'text', None)
                        if text:
                            gcode = text.strip()
                            break
                if gcode:
                    break
        except Exception:
            pass

    if not gcode:
        raise ValueError('GPT returned an empty response. Try rephrasing the command.')

    # Strip any accidental markdown code fences
    if gcode.startswith('```'):
        lines = gcode.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == '```' else len(lines)
        gcode = '\n'.join(lines[start:end]).strip()

    # Cap any spindle speed S-word to 1000
    def _cap_speed(m):
        speed = float(m.group(1))
        return f'S{min(int(speed), 1000)}'
    gcode = re.sub(r'\bS(\d+(?:\.\d+)?)\b', _cap_speed, gcode, flags=re.IGNORECASE)

    return gcode
