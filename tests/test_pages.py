"""Page-operation tests — preview-parity spec §6.1 items 1–8."""

import json
import subprocess
import sys

import pymupdf
import pytest

from omepreview import engine, pages as pages_mod
from omepreview.mcp_server import delete_pages, extract_pages, insert_pages, list_pages, rotate_pages
from omepreview.ops import OpError
from tests.data.make_docs import make_image_asset, make_labeled_pdf


@pytest.fixture()
def six_page_pdf(tmp_path):
    return make_labeled_pdf(tmp_path / "six.pdf", page_count=6)


@pytest.fixture()
def five_page_pdf(tmp_path):
    return make_labeled_pdf(tmp_path / "five.pdf", page_count=5)


def _page_texts(pdf):
    doc = pymupdf.open(str(pdf))
    texts = []
    for page in doc:
        texts.append(page.get_text("text").strip())
    doc.close()
    return texts


def test_delete_pages_compacts(five_page_pdf, tmp_path):
    """§6.1.1 — delete 2,4 leaves 3 pages; old page 3 becomes new page 2."""
    out = tmp_path / "out.pdf"
    engine.apply(
        five_page_pdf,
        [{"op": "delete_pages", "pages": [2, 4]}],
        output=out,
    )
    assert pages_mod.list_pages(out)["page_count"] == 3
    texts = _page_texts(out)
    assert texts[0].startswith("PAGE 1")
    assert texts[1].startswith("PAGE 3")
    assert texts[2].startswith("PAGE 5")


def test_rotate_page_90(six_page_pdf, tmp_path):
    """§6.1.2 — rotate page 1 changes stored rotation."""
    out = tmp_path / "rot.pdf"
    engine.apply(
        six_page_pdf,
        [{"op": "rotate_pages", "pages": [1], "degrees": 90}],
        output=out,
    )
    doc = pymupdf.open(str(out))
    assert doc[0].rotation in (90, 270)
    doc.close()


def test_move_pages_after(six_page_pdf, tmp_path):
    """§6.1.3 — move [5,6] after 1 → order 1,5,6,2,3,4."""
    out = tmp_path / "moved.pdf"
    engine.apply(
        six_page_pdf,
        [{"op": "move_pages", "pages": [5, 6], "after": 1}],
        output=out,
    )
    texts = _page_texts(out)
    assert [t.split()[1] for t in texts] == ["1", "5", "6", "2", "3", "4"]


def test_move_pages_after_in_selection_raises(six_page_pdf, tmp_path):
    """Engine still rejects after-page-in-selection; GUI must no-op instead."""
    with pytest.raises(OpError, match="among the pages being moved"):
        engine.apply(
            six_page_pdf,
            [{"op": "move_pages", "pages": [3], "after": 3}],
            output=tmp_path / "nope.pdf",
        )


def test_insert_pdf_pages(five_page_pdf, tmp_path):
    """§6.1.4 — insert pages 1–2 of B after page 1 of A."""
    src = make_labeled_pdf(tmp_path / "src.pdf", page_count=3, label_prefix="SRC")
    out = tmp_path / "merged.pdf"
    engine.apply(
        five_page_pdf,
        [
            {
                "op": "insert_pages",
                "after": 1,
                "source": str(src),
                "source_pages": [1, 2],
            }
        ],
        output=out,
    )
    assert pages_mod.list_pages(out)["page_count"] == 7
    texts = _page_texts(out)
    assert texts[0].startswith("PAGE 1")
    assert texts[1].startswith("SRC 1")
    assert texts[2].startswith("SRC 2")
    assert texts[3].startswith("PAGE 2")


def test_insert_blank_after_zero(five_page_pdf, tmp_path):
    """§6.1.5 — blank after 0 makes an empty first page."""
    out = tmp_path / "blank.pdf"
    engine.apply(
        five_page_pdf,
        [{"op": "insert_pages", "after": 0, "blank": {"count": 1, "width": 595, "height": 842}}],
        output=out,
    )
    assert pages_mod.list_pages(out)["page_count"] == 6
    texts = _page_texts(out)
    assert texts[0] == ""
    assert texts[1].startswith("PAGE 1")


def test_insert_image_page(five_page_pdf, tmp_path):
    """§6.1.6 — image insert adds a raster page."""
    image = make_image_asset(tmp_path / "photo.png")
    out = tmp_path / "with_image.pdf"
    engine.apply(
        five_page_pdf,
        [{"op": "insert_pages", "after": 2, "image": str(image)}],
        output=out,
    )
    assert pages_mod.list_pages(out)["page_count"] == 6
    doc = pymupdf.open(str(out))
    images = doc[2].get_images()
    assert images
    doc.close()


def test_refuse_delete_all(five_page_pdf):
    """§6.1.7 — cannot delete every page."""
    with pytest.raises(OpError, match="at least one page"):
        engine.apply(
            five_page_pdf,
            [{"op": "delete_pages", "pages": [1, 2, 3, 4, 5]}],
        )


def test_delete_all_allowed_with_insert(five_page_pdf, tmp_path):
    out = tmp_path / "replaced.pdf"
    engine.apply(
        five_page_pdf,
        [
            {"op": "delete_pages", "pages": [1, 2, 3, 4, 5]},
            {
                "op": "insert_pages",
                "after": 0,
                "blank": {"count": 1, "width": 595, "height": 842},
            },
        ],
        output=out,
    )
    assert pages_mod.list_pages(out)["page_count"] == 1


def test_atomic_fail_bad_page_index(five_page_pdf, tmp_path):
    """§6.1.8 — invalid page index aborts without writing."""
    out = tmp_path / "unchanged.pdf"
    before = five_page_pdf.read_bytes()
    with pytest.raises(OpError, match="out of range"):
        engine.apply(
            five_page_pdf,
            [{"op": "delete_pages", "pages": [99]}],
            output=out,
        )
    assert not out.exists()
    assert five_page_pdf.read_bytes() == before


def test_extract_pages(tmp_path, five_page_pdf):
    excerpt = tmp_path / "excerpt.pdf"
    engine.apply(
        five_page_pdf,
        [{"op": "extract_pages", "pages": [2, 3], "to": str(excerpt)}],
    )
    assert pages_mod.list_pages(excerpt)["page_count"] == 2
    assert pages_mod.list_pages(five_page_pdf)["page_count"] == 5
    texts = _page_texts(excerpt)
    assert texts[0].startswith("PAGE 2")
    assert texts[1].startswith("PAGE 3")


def test_cli_pages_list(six_page_pdf):
    run = subprocess.run(
        [sys.executable, "-m", "omepreview.cli", "pages", str(six_page_pdf), "--list"],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert data["page_count"] == 6


def test_cli_pages_delete_dry_run_json(five_page_pdf):
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "omepreview.cli",
            "pages",
            str(five_page_pdf),
            "--delete",
            "2,4",
            "--dry-run",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert data["output"] is None
    assert data["applied"][0]["applied"] is False


def test_cli_pages_move(six_page_pdf, tmp_path):
    out = tmp_path / "cli_moved.pdf"
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "omepreview.cli",
            "pages",
            str(six_page_pdf),
            "--move",
            "5-6",
            "--after",
            "1",
            "-o",
            str(out),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    texts = _page_texts(out)
    assert [t.split()[1] for t in texts] == ["1", "5", "6", "2", "3", "4"]


def test_mcp_list_pages(six_page_pdf):
    data = list_pages(str(six_page_pdf))
    assert data["page_count"] == 6
    assert len(data["pages"]) == 6


def test_mcp_delete_pages_dry_run_and_apply(five_page_pdf, tmp_path):
    dry = delete_pages(str(five_page_pdf), pages=[2, 4], confirm=False)
    assert dry["output"] is None
    assert dry["needs_confirmation"]
    out = tmp_path / "mcp_out.pdf"
    applied = delete_pages(str(five_page_pdf), pages=[2, 4], output=str(out), confirm=True)
    assert applied["output"] == str(out)
    assert pages_mod.list_pages(out)["page_count"] == 3


def test_mcp_rotate_and_extract(six_page_pdf, tmp_path):
    rotated = rotate_pages(str(six_page_pdf), pages=[1], degrees=90, dry_run=True)
    assert rotated["applied"][0]["applied"] is False
    excerpt = tmp_path / "mcp_excerpt.pdf"
    result = extract_pages(str(six_page_pdf), pages=[2, 3], to=str(excerpt))
    assert pages_mod.list_pages(excerpt)["page_count"] == 2


def test_mcp_insert_blank(five_page_pdf, tmp_path):
    out = tmp_path / "mcp_blank.pdf"
    result = insert_pages(
        str(five_page_pdf),
        after=0,
        blank_count=1,
        output=str(out),
    )
    assert result["output"] == str(out)
    assert pages_mod.list_pages(out)["page_count"] == 6


def test_edit_command_still_available(six_page_pdf):
    """Slice 1 regression — edit subcommand still routes to the GTK editor."""
    import inspect

    from omepreview.cli import build_parser, cmd_edit

    args = build_parser().parse_args(["edit", str(six_page_pdf)])
    assert args.command == "edit"
    assert args.func is cmd_edit
    assert "gui.run" in inspect.getsource(cmd_edit)
