"""Editorial 18×18 cairo glyphs used on the overlay rail.

Undo / redo are open circular arrows with the head at the top: undo
points up-left (counterclockwise), redo points up-right.
"""

from __future__ import annotations

import cairo


def _ink(ctx, fg, width: float = 1.65) -> None:
    if len(fg) == 4:
        ctx.set_source_rgba(*fg)
    else:
        ctx.set_source_rgba(*fg, 1.0)
    ctx.set_line_width(width)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)


def paint_undo(ctx, fg) -> None:
    """Counterclockwise open arrow; head at the upper-left, pointing up-left."""
    _ink(ctx, fg)
    # Tail on the right, curve under, rise up the left side.
    ctx.move_to(14.0, 10.6)
    ctx.curve_to(14.0, 15.4, 3.6, 15.4, 3.8, 8.0)
    ctx.stroke()
    # Chevron pointing up-left.
    ctx.move_to(7.6, 7.0)
    ctx.line_to(3.2, 4.2)
    ctx.line_to(3.4, 8.6)
    ctx.stroke()


def paint_redo(ctx, fg) -> None:
    """Clockwise open arrow; head at the upper-right, pointing up-right."""
    _ink(ctx, fg)
    ctx.move_to(4.0, 10.6)
    ctx.curve_to(4.0, 15.4, 14.4, 15.4, 14.2, 8.0)
    ctx.stroke()
    ctx.move_to(10.4, 7.0)
    ctx.line_to(14.8, 4.2)
    ctx.line_to(14.6, 8.6)
    ctx.stroke()
