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


def rgb(r: int, g: int, b: int) -> str:
    return f"\x1b[38;2;{r};{g};{b}m"


def lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )
