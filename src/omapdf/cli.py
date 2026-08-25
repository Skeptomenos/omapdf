"""omapdf command-line interface.

Designed to be equally pleasant for humans and agents: every command that
reports state supports --json, errors are one actionable line on stderr, and
all edits go through the same op engine the MCP server uses.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import __version__, engine, read, signature
from .ops import OpError


def _point(value: str) -> list[float]:
    try:
        x, y = value.split(",")
        return [float(x), float(y)]
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected X,Y — got {value!r}")


def _rect(value: str) -> list[float]:
    parts = value.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"expected X0,Y0,X1,Y1 — got {value!r}")
    return [float(p) for p in parts]


def _emit(data, as_json: bool):
    if as_json:
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _emit_human(data)


def _emit_human(data):
    if isinstance(data, dict) and "applied" in data:
        for op in data["applied"]:
            label = op["op"]
            where = f"p{op['page']}" if "page" in op else ""
            detail = op.get("match") or op.get("field") or op.get("text") or op.get("signature") or ""
            print(f"  ✓ {label} {where} {detail}".rstrip())
        if data.get("output"):
            print(f"saved: {data['output']}")
        else:
            print("(dry run — nothing written)")
    else:
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write("\n")


def _out_args(p: argparse.ArgumentParser):
    p.add_argument("-o", "--output", help="write result here (default: edit in place)")
    p.add_argument("--dry-run", action="store_true", help="resolve and report, write nothing")
    p.add_argument("--json", action="store_true", help="machine-readable report")


def _run_edit(args, op_list):
    result = engine.apply(args.pdf, op_list, output=args.output, dry_run=args.dry_run)
    _emit(result, args.json)


def cmd_read(args):
    pages = [int(p) for p in args.page] if args.page else None
    data = read.extract(args.pdf, pages=pages, text_only=args.text_only)
    if args.text_only and not args.json:
        for page in data["pages"]:
            print(page["text"])
    else:
        _emit(data, True)


def cmd_fields(args):
    _emit(read.form_fields(args.pdf), True)


def cmd_apply(args):
    payload = json.load(sys.stdin) if args.ops == "-" else json.loads(Path(args.ops).read_text())
    _run_edit(args, payload)


def cmd_annotate(args):
    op = {"op": "highlight", "page": args.page, "style": args.style}
    if args.match:
        op["match"] = args.match
    else:
        op["rect"] = args.rect
    _run_edit(args, [op])


def cmd_note(args):
    _run_edit(args, [{"op": "note", "page": args.page, "at": args.at, "text": args.text}])


def cmd_fill(args):
    op_list = [{"op": "fill_field", "field": name, "value": value} for name, value in args.field]
    _run_edit(args, op_list)


def cmd_sign(args):
    op = {
        "op": "place_signature",
        "page": args.page,
        "at": args.at,
        "width": args.width,
        "signature": args.sig,
        "date": args.date,
    }
    _run_edit(args, [op])


def cmd_flatten(args):
    result = engine.flatten(args.pdf, output=args.output)
    _emit(result, args.json)


def cmd_sig(args):
    if args.sig_cmd == "add":
        dest = signature.add(args.image, args.name)
        print(f"saved signature {args.name!r} -> {dest}")
    elif args.sig_cmd == "list":
        names = signature.list_names()
        print("\n".join(names) if names else "(no signatures saved — omapdf sig add <image.png>)")
    elif args.sig_cmd == "remove":
        signature.remove(args.name)
        print(f"removed signature {args.name!r}")


def cmd_open(args):
    # Until the omapdf GUI lands, hand off to the desktop's PDF viewer.
    subprocess.Popen(["xdg-open", args.pdf], start_new_session=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omapdf",
        description="Agent-native PDF annotation and signing.",
    )
    parser.add_argument("--version", action="version", version=f"omapdf {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("read", help="structured document read (JSON)")
    p.add_argument("pdf")
    p.add_argument("--page", action="append", help="limit to page N (repeatable)")
    p.add_argument("--text-only", action="store_true", help="plain text instead of layout")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_read)

    p = sub.add_parser("fields", help="list form fields (JSON)")
    p.add_argument("pdf")
    p.set_defaults(func=cmd_fields)

    p = sub.add_parser("apply", help="apply an ops JSON file (or - for stdin)")
    p.add_argument("pdf")
    p.add_argument("--ops", required=True, help="path to ops JSON, or - for stdin")
    _out_args(p)
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("annotate", help="highlight/underline/strikeout text")
    p.add_argument("pdf")
    p.add_argument("--page", type=int, required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--match", help="highlight every occurrence of this text")
    group.add_argument("--rect", type=_rect, help="X0,Y0,X1,Y1 in points, top-left origin")
    p.add_argument("--style", choices=["highlight", "underline", "strikeout", "squiggly"], default="highlight")
    _out_args(p)
    p.set_defaults(func=cmd_annotate)

    p = sub.add_parser("note", help="attach a sticky-note comment")
    p.add_argument("pdf")
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--at", type=_point, required=True, help="X,Y in points")
    p.add_argument("--text", required=True)
    _out_args(p)
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("fill", help="fill form fields")
    p.add_argument("pdf")
    p.add_argument("--field", nargs=2, action="append", metavar=("NAME", "VALUE"), required=True)
    _out_args(p)
    p.set_defaults(func=cmd_fill)

    p = sub.add_parser("sign", help="place a saved signature image")
    p.add_argument("pdf")
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--at", type=_point, required=True, help="top-left X,Y in points")
    p.add_argument("--width", type=float, default=180)
    p.add_argument("--sig", default="default", help="saved signature name")
    p.add_argument("--date", action="store_true", help="stamp today's date below")
    _out_args(p)
    p.set_defaults(func=cmd_sign)

    p = sub.add_parser("flatten", help="bake annotations and form fields into the page")
    p.add_argument("pdf")
    p.add_argument("-o", "--output")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_flatten)

    p = sub.add_parser("sig", help="manage saved signatures")
    sig_sub = p.add_subparsers(dest="sig_cmd", required=True)
    sp = sig_sub.add_parser("add", help="save a signature image")
    sp.add_argument("image")
    sp.add_argument("--name", default="default")
    sig_sub.add_parser("list", help="list saved signatures")
    sp = sig_sub.add_parser("remove", help="delete a saved signature")
    sp.add_argument("name")
    p.set_defaults(func=cmd_sig)

    p = sub.add_parser("open", help="open in the desktop PDF viewer")
    p.add_argument("pdf")
    p.set_defaults(func=cmd_open)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (OpError, FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"omapdf: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
