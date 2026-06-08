import re

# G-codes supported by GRBL on this hobbyist 2-axis lathe
_VALID_G_CODES = {
    'G00', 'G01', 'G02', 'G03', 'G04',
    'G10',                          # Coordinate system set (Phase II sync)
    'G20', 'G21',
    'G28',
    'G49',                          # Cancel tool length offset (init)
    'G54',                          # Activate WCS 1 (Phase II sync)
    'G90', 'G91', 'G92',
}

# M-codes supported (DC spindle on/off + program end only)
_VALID_M_CODES = {
    'M03', 'M05', 'M30',
}

_MAX_FEED_RATE = 1000.0  # mm/min hard ceiling


def _normalise_code(letter: str, number: str) -> str:
    """Return zero-padded code, e.g. 'G0' → 'G00', 'G21' → 'G21'."""
    return f'{letter}{int(number):02d}'


def validate_gcode(
    gcode_text: str,
    x_limit: float = 100.0,
    y_limit: float = 200.0,
    max_feed_rate: float = _MAX_FEED_RATE,
) -> dict:
    """
    Validate G-code text for syntax correctness and safety against machine limits.

    Returns a dict with keys:
        valid       (bool)
        errors      (list[str])
        warnings    (list[str])
        line_count  (int)  – executable lines only
    """
    errors: list[str] = []
    warnings: list[str] = []
    executable_lines = 0

    for line_num, raw_line in enumerate(gcode_text.splitlines(), start=1):
        line = raw_line.strip()

        # Skip blank lines and pure comments
        if not line or line.startswith(';') or line.startswith('('):
            continue

        # Detect non-G-code content (markdown, plain text)
        if line.startswith(('#', '`', '*', '-', '>')):
            errors.append(
                f'Line {line_num}: Non-G-code content detected — "{line[:40]}"'
            )
            continue

        # Remove inline comments before parsing
        line_clean = re.sub(r';.*$', '', line)
        line_clean = re.sub(r'\(.*?\)', '', line_clean).strip()
        # Strip T-words (tool selection) — hardware not present
        line_clean = re.sub(r'\bT\d+\b', '', line_clean, flags=re.IGNORECASE).strip()
        if not line_clean:
            continue

        executable_lines += 1

        # --- G-code validation ---
        for num in re.findall(r'[Gg](\d+(?:\.\d+)?)', line_clean):
            code = _normalise_code('G', num.split('.')[0])
            if code not in _VALID_G_CODES:
                errors.append(f'Line {line_num}: Unknown G-code G{num}')

        # --- M-code validation ---
        for num in re.findall(r'[Mm](\d+)', line_clean):
            code = _normalise_code('M', num)
            if code not in _VALID_M_CODES:
                errors.append(f'Line {line_num}: Unknown M-code M{num}')

        # --- Axis limit checks ---
        for val in re.findall(r'[Xx](-?\d+(?:\.\d+)?)', line_clean):
            if abs(float(val)) > x_limit:
                errors.append(
                    f'Line {line_num}: X{val} exceeds machine X limit of {x_limit} mm'
                )

        for val in re.findall(r'[Yy](-?\d+(?:\.\d+)?)', line_clean):
            if abs(float(val)) > y_limit:
                errors.append(
                    f'Line {line_num}: Y{val} exceeds machine Y limit of {y_limit} mm'
                )

        # --- Spindle speed checks ---
        for val in re.findall(r'[Ss](\d+(?:\.\d+)?)', line_clean):
            if float(val) > 1000:
                errors.append(
                    f'Line {line_num}: Spindle speed S{val} exceeds maximum of 1000'
                )

        # --- Feed rate checks ---
        for val in re.findall(r'[Ff](-?\d+(?:\.\d+)?)', line_clean):
            feed = float(val)
            if feed < 0:
                errors.append(
                    f'Line {line_num}: Negative feed rate F{val} is not allowed'
                )
            elif feed > max_feed_rate:
                warnings.append(
                    f'Line {line_num}: Feed rate F{val} mm/min exceeds recommended '
                    f'maximum of {max_feed_rate} mm/min'
                )

    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings,
        'line_count': executable_lines,
    }
