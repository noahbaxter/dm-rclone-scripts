"""
Shared color definitions for terminal output.
"""


class Colors:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    PURPLE = "\x1b[38;2;138;43;226m"
    INDIGO = "\x1b[38;2;99;102;241m"
    PINK = "\x1b[38;2;244;114;182m"
    PINK_DIM = "\x1b[38;2;150;70;110m"
    DIM_HOVER = "\x1b[38;2;140;150;160m"
    HOTKEY = "\x1b[38;2;167;139;250m"
    MUTED = "\x1b[38;2;148;163;184m"
    MUTED_DIM = "\x1b[38;2;90;100;110m"
    RED = "\x1b[38;2;239;68;68m"  # For excess/purgeable content


def rgb(r: int, g: int, b: int) -> str:
    return f"\x1b[38;2;{r};{g};{b}m"


def lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


# Gemini-style purple/blue/red gradient for header
GRADIENT_COLORS = [
    (138, 43, 226),   # Blue-violet
    (123, 44, 191),   # Purple
    (108, 45, 156),   # Deep purple
    (93, 63, 211),    # Slate blue
    (79, 70, 229),    # Indigo
    (99, 102, 241),   # Light indigo
    (129, 140, 248),  # Periwinkle
    (167, 139, 250),  # Light purple
    (196, 118, 232),  # Orchid
    (232, 121, 197),  # Pink
    (244, 114, 182),  # Hot pink
    (251, 113, 133),  # Rose
]


def get_gradient_color(pos: float) -> tuple:
    """Get interpolated color at position 0.0-1.0."""
    pos = max(0.0, min(1.0, pos))
    scaled = pos * (len(GRADIENT_COLORS) - 1)
    idx = int(scaled)
    if idx >= len(GRADIENT_COLORS) - 1:
        return GRADIENT_COLORS[-1]
    return lerp_color(GRADIENT_COLORS[idx], GRADIENT_COLORS[idx + 1], scaled - idx)
