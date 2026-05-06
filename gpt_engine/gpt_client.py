from openai import OpenAI


def _build_prompt(command: str, x_limit: float, z_limit: float) -> str:
    return (
        f"You are a G-code generator for a hobbyist GRBL-based CNC lathe.\n\n"
        f"Machine hardware:\n"
        f"- 2-axis (X and Z only) driven by NEMA 17 stepper motors\n"
        f"- DC motor spindle with simple on/off control (no speed regulation)\n"
        f"- No coolant system\n"
        f"- No tool changer\n"
        f"- Controller: GRBL firmware on Arduino\n\n"
        f"Axis limits:\n"
        f"- X-axis maximum: {x_limit} mm (radial axis)\n"
        f"- Z-axis maximum: {z_limit} mm (longitudinal axis)\n\n"
        f"ALLOWED G-codes only (do not use any others):\n"
        f"  G00, G01, G02, G03  — motion\n"
        f"  G04                 — dwell\n"
        f"  G20, G21            — units (use G21 for mm)\n"
        f"  G28                 — home\n"
        f"  G90, G91            — positioning mode (use G90 absolute)\n"
        f"  G92                 — coordinate offset\n\n"
        f"ALLOWED M-codes only (do not use any others):\n"
        f"  M03 — spindle on\n"
        f"  M05 — spindle off\n"
        f"  M30 — program end\n\n"
        f"FORBIDDEN (never include these):\n"
        f"  G40, G41, G42       — cutter compensation (not supported)\n"
        f"  G94, G95, G96, G97  — feed/speed mode (not supported)\n"
        f"  G17, G18, G19       — plane selection (not needed)\n"
        f"  M06, M07, M08, M09  — tool change / coolant (no hardware)\n"
        f"  T words             — tool selection (no tool changer)\n"
        f"  S words             — spindle speed (DC motor, no control)\n\n"
        f"Rules:\n"
        f"- Start with G21 G90.\n"
        f"- Use M03 to turn spindle on, M05 to turn it off.\n"
        f"- End with M05 then M30.\n"
        f"- Keep feed rates between 10 and 500 mm/min.\n"
        f"- Output raw G-code only — no explanations, no markdown, no code fences.\n\n"
        f"Command:\n{command}"
    )


def generate_gcode(
    command: str,
    api_key: str,
    model: str = 'gpt-5',
    x_limit: float = 100.0,
    z_limit: float = 200.0,
) -> str:
    """Call the OpenAI API and return raw G-code for the given machining command."""
    if not api_key:
        raise ValueError(
            'OpenAI API key is not configured. Please set it in the Settings page.'
        )

    client = OpenAI(api_key=api_key)
    prompt = _build_prompt(command, x_limit, z_limit)

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

    return gcode
