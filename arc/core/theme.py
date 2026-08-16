"""
ARC Color System
-----------------
Literal hex values matching the confirmed UI mockup (arc_full_suite.html) --
ARC's identity color (red) replaces the amber that used to carry no real
meaning, freeing amber up for its actual job: in-progress/running/caution,
paired with SessionBar's existing 5min/1min countdown escalation.

Used by f-string interpolation into each screen's CSS class attribute --
Textual screens in this app define CSS inline rather than via external
.tcss files, so this stays consistent with that pattern rather than
introducing a second styling mechanism.
"""
ARC_RED = "#E8262E"
ARC_RED_DIM = "#7A1418"
ARC_BLUE = "#2E7FE8"
ARC_AMBER = "#E8A32E"
ARC_GREEN = "#2EB56D"
ARC_ROSE = "#C1416B"

BG = "#0A0B0D"
PANEL = "#101216"
PANEL_ALT = "#14161B"
BORDER = "#2A2E35"
TEXT = "#D8DCE2"
TEXT_DIM = "#6B7280"

# Braille-dot spinner frames -- the standard terminal-app "in progress"
# technique (same family npm/cargo/docker use), cycled on a timer to read
# as genuinely spinning within a character grid.
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
