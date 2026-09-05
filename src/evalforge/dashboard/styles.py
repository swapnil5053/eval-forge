"""Every colour, size and font the dashboard uses.

The look is an instrument panel: near-black ground, one warm accent, monospace for
anything numeric, and borders instead of shadows. Nothing in the dashboard writes a
colour or a size literal - it comes from here, so retuning the whole panel means
editing this file.
"""

# Ground and surfaces. The background is near-black with a slight cool cast, which
# is what lets a warm accent read as an indicator lamp rather than a brand colour.
BACKGROUND = "hsl(220, 14%, 7%)"
SURFACE = "hsl(220, 13%, 9.5%)"
SURFACE_RAISED = "hsl(220, 12%, 12.5%)"
BORDER = "hsl(220, 10%, 17%)"
BORDER_BRIGHT = "hsl(220, 10%, 27%)"

TEXT = "hsl(0, 0%, 87%)"
TEXT_DIM = "hsl(0, 0%, 55%)"
TEXT_FAINT = "hsl(0, 0%, 36%)"

# One accent, used only for the active nav item, the primary chart series, bars, and
# interactive affordances on hover. Status colours are not the accent.
# Matches the accent on the landing page in docs/, so the product reads as one thing.
ACCENT = "#A8C97F"
ACCENT_MUTED = "#5F7549"

OK = "#A8C97F"
WARN = "#C9A961"
ERROR = "#C97A5A"

# Chart series, dimmest first: p50 is background information, p99 is the alarm.
SERIES = (TEXT_FAINT, TEXT_DIM, ACCENT)

MONO = "'JetBrains Mono', 'SF Mono', 'Menlo', 'Consolas', monospace"
SANS = "'Inter', -apple-system, 'Segoe UI', 'Roboto', sans-serif"

FONT_LABEL = "10px"
FONT_SMALL = "11px"
FONT_BODY = "12px"
FONT_DATA = "12.5px"
FONT_METRIC = "30px"

SPACE_1 = "4px"
SPACE_2 = "8px"
SPACE_3 = "12px"
SPACE_4 = "16px"
SPACE_5 = "24px"

RADIUS = "2px"
SIDEBAR_WIDTH = "200px"
ROW_HEIGHT = "26px"

STYLESHEETS = [
    "https://fonts.googleapis.com/css2?family=Inter:wght@400;500&"
    "family=JetBrains+Mono:wght@400;500&display=swap"
]

# Small, uppercase, letter-spaced and dim: the engraved label under a panel dial.
LABEL = {
    "font_family": SANS,
    "font_size": FONT_LABEL,
    "letter_spacing": "0.11em",
    "text_transform": "uppercase",
    "color": TEXT_FAINT,
    "line_height": "1",
}

METRIC = {
    "font_family": MONO,
    "font_size": FONT_METRIC,
    "font_weight": "500",
    "color": TEXT,
    "line_height": "1",
    "letter_spacing": "-0.02em",
}

DATA = {"font_family": MONO, "font_size": FONT_DATA, "color": TEXT}
DATA_DIM = {"font_family": MONO, "font_size": FONT_DATA, "color": TEXT_DIM}
BODY = {"font_family": SANS, "font_size": FONT_BODY, "color": TEXT}

PANEL = {
    "background": SURFACE,
    "border": f"1px solid {BORDER}",
    "border_radius": RADIUS,
    "padding": SPACE_4,
}

# Data tables get square corners. Rows are separated by a single hairline, never by
# alternating fills.
TABLE = {"width": "100%", "border_collapse": "collapse", "font_family": MONO}
TABLE_HEADER = {
    **LABEL,
    "text_align": "left",
    "padding": f"{SPACE_2} {SPACE_3} {SPACE_2} 0",
    "border_bottom": f"1px solid {BORDER_BRIGHT}",
    "white_space": "nowrap",
    "cursor": "pointer",
}
TABLE_CELL = {
    "font_family": MONO,
    "font_size": FONT_DATA,
    "color": TEXT,
    "padding": f"{SPACE_2} {SPACE_3} {SPACE_2} 0",
    "border_bottom": f"1px solid {BORDER}",
    "white_space": "nowrap",
}

INPUT = {
    "background": BACKGROUND,
    "border": f"1px solid {BORDER}",
    "border_radius": RADIUS,
    "color": TEXT,
    "font_family": MONO,
    "font_size": FONT_DATA,
    "padding": f"{SPACE_1} {SPACE_2}",
    "outline": "none",
    "_focus": {"border_color": ACCENT_MUTED},
    "_placeholder": {"color": TEXT_FAINT},
}

BUTTON = {
    "background": "transparent",
    "border": f"1px solid {BORDER}",
    "border_radius": RADIUS,
    "color": TEXT_DIM,
    "font_family": MONO,
    "font_size": FONT_SMALL,
    "padding": f"{SPACE_1} {SPACE_2}",
    "cursor": "pointer",
    "_hover": {"color": ACCENT, "border_color": ACCENT_MUTED},
}

CODE_BLOCK = {
    "font_family": MONO,
    "font_size": FONT_SMALL,
    "color": TEXT_DIM,
    "background": BACKGROUND,
    "border": f"1px solid {BORDER}",
    "border_radius": RADIUS,
    "padding": SPACE_2,
    "white_space": "pre-wrap",
    "word_break": "break-word",
    "overflow_x": "auto",
    "margin": "0",
}

BASE = {
    "background": BACKGROUND,
    "color": TEXT,
    "font_family": SANS,
    "font_size": FONT_BODY,
    "::selection": {"background": ACCENT_MUTED, "color": TEXT},
    "::-webkit-scrollbar": {"width": "10px", "height": "10px"},
    "::-webkit-scrollbar-track": {"background": BACKGROUND},
    "::-webkit-scrollbar-thumb": {"background": BORDER, "border": f"2px solid {BACKGROUND}"},
    "::-webkit-scrollbar-thumb:hover": {"background": BORDER_BRIGHT},
}


# Claim verdicts, worst last: the audit view colours by severity, not by score.
VERDICT_COLOURS = {
    "SUPPORTED": OK,
    "PARTIALLY_SUPPORTED": WARN,
    "UNSUPPORTED": ERROR,
    "CONTRADICTED": "#E0603C",
}


def status_colour(status: str) -> str:
    return ERROR if status == "error" else OK


def score_colour(value: float, higher_is_better: bool = True) -> str:
    """Green when the score points the good way, amber mid, red when it does not."""
    good = value if higher_is_better else 1.0 - value
    if good >= 0.8:
        return OK
    return WARN if good >= 0.5 else ERROR
