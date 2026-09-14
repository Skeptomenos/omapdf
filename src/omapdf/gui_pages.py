"""GTK thumbnail sidebar with page-operation ghosts."""

from __future__ import annotations

import mimetypes
from pathlib import Path

import pymupdf
from gi.repository import Gdk, Gio, GLib, GObject, Gtk

from .page_clipboard import (
    MIME_PDF,
    extract_pages_bytes,
    push_clipboard,
    read_clipboard_pdf_bytes,
    serialize_pages,
    write_pages_to_file,
    write_temp_pdf,
)
from .page_preview import PagePreviewState


def build_page_sidebar(
    ed,
    on_navigate,
    on_change,
    toast,
):
    """Build the thumbnail sidebar; mutates ``ed`` with page-preview state."""

    preview: PagePreviewState = ed.page_preview

    def touch_preview():
        ed.invalidate_view()

    selected: set[int] = set()
    anchor: int | None = None
    sidebar_focus = {"active": False}
    row_widgets: list[Gtk.Widget] = []

    side_list = Gtk.ListBox()
    side_list.add_css_class("omapdf-thumbs")

    def pages_doc() -> pymupdf.Document:
        return ed.page_doc()

    def refresh_thumbs():
        nonlocal row_widgets
        row_widgets.clear()
        side_list.remove_all()
        doc = pages_doc()
        for n in range(doc.page_count):
                pg = doc[n]
                thumb_w = 84
                scale = (thumb_w * 2) / pg.rect.width
                pix = pg.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale).prerotate(pg.rotation),
                )
                texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(pix.tobytes("png")))
                pic = Gtk.Picture.new_for_paintable(texture)
                pic.add_css_class("omapdf-thumb")
                pic.set_size_request(thumb_w, int(pg.rect.height * thumb_w / pg.rect.width))
                pic.set_content_fit(Gtk.ContentFit.FILL)
                cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                cell.set_margin_top(8)
                cell.set_margin_bottom(4)
                cell.set_margin_start(8)
                cell.set_margin_end(8)
                cell.append(pic)
                label = Gtk.Label(label=str(n + 1))
                label.add_css_class("omapdf-thumb-num")
                if (n + 1) in preview.inserted_pages:
                    label.set_text(f"+ {n + 1}")
                cell.append(label)
                row = Gtk.ListBoxRow()
                row.set_child(cell)
                row.set_activatable(False)
                row.page_index = n
                if n in selected:
                    row.add_css_class("omapdf-thumb-selected")
                if (n + 1) in preview.inserted_pages:
                    row.add_css_class("omapdf-thumb-inserted")
                gesture = Gtk.GestureClick()
                gesture.set_button(0)
                gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

                def on_click(g, _n, _x, _y, idx=n):
                    nonlocal anchor
                    state = g.get_current_event_state()
                    ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
                    shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
                    if shift and anchor is not None:
                        lo, hi = sorted((anchor, idx))
                        selected.clear()
                        selected.update(range(lo, hi + 1))
                    elif ctrl:
                        if idx in selected:
                            selected.discard(idx)
                        else:
                            selected.add(idx)
                    else:
                        selected.clear()
                        selected.add(idx)
                    anchor = idx
                    refresh_selection_style()
                    on_navigate(idx)

                gesture.connect("pressed", on_click)
                row.add_controller(gesture)

                drag = Gtk.DragSource()
                drag.set_actions(Gdk.DragAction.MOVE | Gdk.DragAction.COPY)

                def prepare(g, _x, _y, idx=n):
                    if idx not in selected:
                        selected.clear()
                        selected.add(idx)
                        refresh_selection_style()
                    state = g.get_current_event_state()
                    if state & Gdk.ModifierType.SHIFT_MASK:
                        pages = selected_1based() or [idx + 1]
                        pdf = extract_pages_bytes(pages_doc(), pages)
                        return Gdk.ContentProvider.new_for_bytes(
                            MIME_PDF, GLib.Bytes.new(pdf)
                        )
                    return Gdk.ContentProvider.new_for_value(str(idx))

                drag.connect("prepare", prepare)
                row.add_controller(drag)
                side_list.append(row)
                row_widgets.append(row)

    def refresh_selection_style():
        for row in row_widgets:
            idx = row.page_index
            if idx in selected:
                row.add_css_class("omapdf-thumb-selected")
            else:
                row.remove_css_class("omapdf-thumb-selected")

    def select_pages(indices: set[int]):
        selected.clear()
        selected.update(indices)
        refresh_selection_style()

    def highlight_current(n: int):
        """Keep multi-select; ensure the current page stays selected."""
        nonlocal anchor
        anchor = n
        if not selected:
            selected.add(n)
        refresh_selection_style()

    def selected_1based() -> list[int]:
        return sorted(i + 1 for i in selected)

    def drop_after_for_row(row_index: int) -> int:
        """Map sidebar row index to move_pages ``after`` (0 = beginning)."""
        return 0 if row_index <= 0 else row_index

    drop_target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)

    def on_reorder_drop(_t, value, _x, y):
        try:
            src_idx = int(value)
        except (TypeError, ValueError):
            return False
        row = side_list.get_row_at_y(int(y))
        if row is None:
            after = pages_doc().page_count
        else:
            after = drop_after_for_row(row.page_index)
        pages = selected_1based() or [src_idx + 1]
        ed.checkpoint()
        preview.move_selection_to_after(pages, after)
        touch_preview()
        on_change()
        toast(f"Moved page(s) {pages} after {after}")
        return True

    drop_target.connect("drop", on_reorder_drop)
    side_list.add_controller(drop_target)

    file_target = Gtk.DropTarget.new(GObject.TYPE_NONE, Gdk.DragAction.COPY)
    file_target.set_gtypes([Gdk.FileList.__gtype__])

    def on_file_drop(_t, files, _x, y):
        row = side_list.get_row_at_y(int(y))
        after = drop_after_for_row(row.page_index) if row else pages_doc().page_count
        paths = [Path(f.get_path()) for f in files.get_files() if f.get_path()]
        if not paths:
            return False
        ed.checkpoint()
        for path in paths:
            mime = mimetypes.guess_type(str(path))[0] or ""
            if path.suffix.lower() == ".pdf" or mime == "application/pdf":
                preview.add_insert_pdf(after, str(path))
                after += pymupdf.open(str(path)).page_count
                pymupdf.open(str(path)).close()
            elif mime.startswith("image/") or path.suffix.lower() in (".png", ".jpg", ".jpeg"):
                preview.add_insert_image(after, str(path))
                after += 1
        touch_preview()
        on_change()
        toast(f"Inserted {len(paths)} file(s)")
        return True

    file_target.connect("drop", on_file_drop)
    side_list.add_controller(file_target)

    menu = Gio.Menu()
    menu.append("Rotate right (90°)", "page.rotate_cw")
    menu.append("Rotate left (90°)", "page.rotate_ccw")
    menu.append("Delete", "page.delete")
    menu.append("Insert blank after", "page.blank")
    menu.append("Insert file…", "page.insert_file")
    menu.append("Extract…", "page.extract")
    popover = Gtk.PopoverMenu.new_from_model(menu)

    def show_menu(x, y):
        popover.set_parent(ed.window or side_list)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.popup()

    def act_rotate_cw(_a, _p):
        pages = selected_1based() or [ed.page_no + 1]
        ed.checkpoint()
        preview.add_rotate_pages(pages, 90)
        touch_preview()
        on_change()

    def act_rotate_ccw(_a, _p):
        pages = selected_1based() or [ed.page_no + 1]
        ed.checkpoint()
        preview.add_rotate_pages(pages, -90)
        touch_preview()
        on_change()

    def act_delete(_a, _p):
        pages = selected_1based()
        if not pages:
            return
        ed.checkpoint()
        preview.add_delete_pages(pages)
        selected.clear()
        touch_preview()
        on_change()
        toast(f"Marked page(s) {pages} for deletion")

    def act_blank(_a, _p):
        after = selected_1based()[-1] if selected else ed.page_no + 1
        ed.checkpoint()
        preview.add_insert_blank(after)
        touch_preview()
        on_change()
        toast("Blank page inserted")

    def act_insert_file(_a, _p):
        after = selected_1based()[-1] if selected else ed.page_no + 1
        dialog = Gtk.FileDialog()
        dialog.set_title("Insert pages from file")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        f_pdf = Gtk.FileFilter()
        f_pdf.set_name("PDF")
        f_pdf.add_mime_type("application/pdf")
        f_img = Gtk.FileFilter()
        f_img.set_name("Images")
        f_img.add_mime_type("image/png")
        f_img.add_mime_type("image/jpeg")
        filters.append(f_pdf)
        filters.append(f_img)
        dialog.set_filters(filters)

        def on_pick(_d, result):
            try:
                file = dialog.open_finish(result)
            except GLib.Error:
                return
            path = file.get_path()
            if not path:
                return
            ed.checkpoint()
            try:
                if path.lower().endswith(".pdf"):
                    preview.add_insert_pdf(after, path)
                else:
                    preview.add_insert_image(after, path)
                touch_preview()
                on_change()
                toast(f"Inserted {Path(path).name}")
            except Exception as exc:
                toast(f"Insert failed: {exc}")

        parent = ed.window
        if parent is None:
            toast("Editor window not ready")
            return
        dialog.open(parent, None, on_pick)

    def act_extract(_a, _p):
        pages = selected_1based() or [ed.page_no + 1]
        dialog = Gtk.FileDialog()
        dialog.set_title("Extract selected pages")
        dialog.set_initial_name("excerpt.pdf")

        def on_save(_d, result):
            try:
                dest = dialog.save_finish(result)
            except GLib.Error:
                return
            path = dest.get_path()
            if not path:
                return
            try:
                write_pages_to_file(pages_doc(), pages, path)
                toast(f"Extracted {len(pages)} page(s) to {Path(path).name}")
            except Exception as exc:
                toast(f"Extract failed: {exc}")

        parent = ed.window
        if parent is None:
            toast("Editor window not ready")
            return
        dialog.save(parent, None, on_save)

    action_group = Gio.SimpleActionGroup()
    for name, cb in (
        ("rotate_cw", act_rotate_cw),
        ("rotate_ccw", act_rotate_ccw),
        ("delete", act_delete),
        ("blank", act_blank),
        ("insert_file", act_insert_file),
        ("extract", act_extract),
    ):
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", cb)
        action_group.add_action(action)

    gesture_menu = Gtk.GestureClick()
    gesture_menu.set_button(3)

    def on_right_click(g, _n, x, y):
        show_menu(x, y)

    gesture_menu.connect("pressed", on_right_click)
    side_list.add_controller(gesture_menu)

    focus_ctl = Gtk.EventControllerFocus()

    def on_focus_in(_c):
        sidebar_focus["active"] = True

    def on_focus_out(_c):
        sidebar_focus["active"] = False

    focus_ctl.connect("enter", on_focus_in)
    focus_ctl.connect("leave", on_focus_out)
    side_list.add_controller(focus_ctl)

    def insert_blank_after_current():
        ed.checkpoint()
        preview.add_insert_blank(ed.page_no + 1)
        touch_preview()
        on_change()
        toast("Blank page inserted")

    def delete_selected_pages():
        pages = selected_1based()
        if not pages:
            pages = [ed.page_no + 1]
        ed.checkpoint()
        preview.add_delete_pages(pages)
        selected.clear()
        touch_preview()
        on_change()
        toast(f"Marked page(s) {pages} for deletion")

    def rotate_selected(degrees: int):
        pages = selected_1based() or [ed.page_no + 1]
        ed.checkpoint()
        preview.add_rotate_pages(pages, degrees)
        touch_preview()
        on_change()

    def insert_after_focus() -> int:
        pages = selected_1based()
        if pages:
            return pages[-1]
        return ed.page_no + 1 if ed.page_no + 1 <= pages_doc().page_count else pages_doc().page_count

    def has_page_selection() -> bool:
        return bool(selected)

    def copy_selected_pages() -> bool:
        pages = selected_1based() or [ed.page_no + 1]
        try:
            json_bytes, pdf_bytes = serialize_pages(pages_doc(), pages)
            push_clipboard(json_bytes, pdf_bytes)
        except Exception as exc:
            toast(f"Copy failed: {exc}")
            return False
        toast(f"Copied {len(pages)} page(s)")
        return True

    def paste_pages() -> bool:
        pdf_bytes = read_clipboard_pdf_bytes()
        if not pdf_bytes:
            toast("Clipboard has no omapdf pages")
            return False
        after = insert_after_focus()
        tmp = write_temp_pdf(pdf_bytes)
        try:
            ed.checkpoint()
            preview.add_insert_pdf(after, str(tmp), retain_source=True)
            touch_preview()
            on_change()
            toast(f"Pasted pages after {after}")
            return True
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            toast(f"Paste failed: {exc}")
            return False

    def cut_selected_pages() -> bool:
        if not copy_selected_pages():
            return False
        delete_selected_pages()
        return True

    return {
        "widget": side_list,
        "refresh": refresh_thumbs,
        "highlight_current": highlight_current,
        "select_row": highlight_current,
        "sidebar_focus": sidebar_focus,
        "selected_1based": selected_1based,
        "insert_blank_after_current": insert_blank_after_current,
        "delete_selected_pages": delete_selected_pages,
        "rotate_selected": rotate_selected,
        "has_page_selection": has_page_selection,
        "copy_selected_pages": copy_selected_pages,
        "paste_pages": paste_pages,
        "cut_selected_pages": cut_selected_pages,
        "actions": action_group,
    }
