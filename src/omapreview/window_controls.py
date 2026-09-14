"""Detect Omarchy/Hyprland and decide whether to show GTK window controls."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def detect_omarchy_environment() -> bool:
    """True when running under Omarchy or Hyprland (compositor owns the frame)."""
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return True
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    if "omarchy" in desktop.lower():
        return True
    if shutil.which("omarchy"):
        return True
    if Path("/usr/share/omarchy").is_dir():
        return True
    return False


def window_controls_enabled() -> bool:
    """Whether omapreview should show a thin HeaderBar with min/max/close only."""
    override = os.environ.get("OMAPDF_WINDOW_CONTROLS")
    if override == "1":
        return True
    if override == "0":
        return False
    return not detect_omarchy_environment()
