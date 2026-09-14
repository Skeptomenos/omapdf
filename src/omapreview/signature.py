"""Signature store: named signature images kept in the user's config dir.

Signatures are ordinary PNG files (ideally with a transparent background) in
~/.config/omapreview/signatures/. The name "default" is what `place_signature`
uses when no name is given.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def store_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "omapreview" / "signatures"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(name: str) -> Path:
    if "/" in name or name.startswith("."):
        raise ValueError(f"invalid signature name {name!r}")
    return store_dir() / f"{name}.png"


def add(source: str | Path, name: str = "default") -> Path:
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"no such image: {source}")
    if source.suffix.lower() != ".png":
        raise ValueError("signatures must be PNG (transparent background recommended)")
    dest = path_for(name)
    shutil.copyfile(source, dest)
    return dest


def get(name: str = "default") -> Path:
    p = path_for(name)
    if not p.is_file():
        known = ", ".join(list_names()) or "(none saved)"
        raise FileNotFoundError(
            f"no signature named {name!r}. Saved signatures: {known}. "
            f"Add one with: omapreview sig add <image.png> --name {name}"
        )
    return p


def list_names() -> list[str]:
    return sorted(p.stem for p in store_dir().glob("*.png"))


def remove(name: str) -> None:
    path_for(name).unlink(missing_ok=False)
