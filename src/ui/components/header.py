"""
Application header component.

ASCII art header with gradient coloring.
"""

from ..primitives import Colors, rgb, get_gradient_color


ASCII_HEADER = r"""
 ██████╗ ███╗   ███╗    ███████╗██╗   ██╗███╗   ██╗ ██████╗
 ██╔══██╗████╗ ████║    ██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝
 ██║  ██║██╔████╔██║    ███████╗ ╚████╔╝ ██╔██╗ ██║██║
 ██║  ██║██║╚██╔╝██║    ╚════██║  ╚██╔╝  ██║╚██╗██║██║
 ██████╔╝██║ ╚═╝ ██║    ███████║   ██║   ██║ ╚████║╚██████╗
 ╚═════╝ ╚═╝     ╚═╝    ╚══════╝   ╚═╝   ╚═╝  ╚═══╝ ╚═════╝
""".strip('\n')

ASCII_HEADER = r"""
███████╗██╗   ██╗███╗   ██╗ ██████╗██╗  ██╗ ██████╗ ████████╗██╗ ██████╗
██╔════╝╚██╗ ██╔╝████╗  ██║██╔════╝██║  ██║██╔═══██╗╚══██╔══╝██║██╔════╝
███████╗ ╚████╔╝ ██╔██╗ ██║██║     ███████║██║   ██║   ██║   ██║██║     
╚════██║  ╚██╔╝  ██║╚██╗██║██║     ██╔══██║██║   ██║   ██║   ██║██║     
███████║   ██║   ██║ ╚████║╚██████╗██║  ██║╚██████╔╝   ██║   ██║╚██████╗
╚══════╝   ╚═╝   ╚═╝  ╚═══╝ ╚═════╝╚═╝  ╚═╝ ╚═════╝    ╚═╝   ╚═╝ ╚═════╝
""".strip('\n')


def print_header():
    """Print the ASCII header with diagonal gradient and version."""
    from src import __version__

    lines = ASCII_HEADER.split('\n')
    total = len(lines)

    for row, line in enumerate(lines):
        result = []
        for col, char in enumerate(line):
            if char != ' ':
                # Diagonal gradient: combine row and column position
                pos = (row / total) * 0.4 + (col / len(line)) * 0.6
                r, g, b = get_gradient_color(pos)
                result.append(f"{rgb(r, g, b)}{char}")
            else:
                result.append(char)
        print(''.join(result) + Colors.RESET)

    # Print version left-aligned under header
    print(f" {Colors.DIM}v{__version__}{Colors.RESET}")
    print()
