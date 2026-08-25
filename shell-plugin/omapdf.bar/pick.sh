#!/bin/bash
# Pick a recent PDF and open it. Bundled with the omapdf.bar Omarchy plugin
# so the widget works standalone: prefers the omapdf editor when installed,
# falls back to the system PDF handler otherwise.

set -uo pipefail

dirs="${OMAPDF_PICK_DIRS:-$HOME/Downloads:$HOME/Documents:$HOME/Desktop}"

existing=()
IFS=':' read -ra parts <<<"$dirs"
for d in "${parts[@]}"; do
  [[ -d $d ]] && existing+=("$d")
done

files=()
if (( ${#existing[@]} > 0 )); then
  mapfile -t files < <(
    find "${existing[@]}" -maxdepth 4 \( -type d -name '.*' -prune \) -o \
      -type f -iname '*.pdf' -printf '%T@\t%p\n' 2>/dev/null |
      sort -rn | cut -f2- | head -40
  )
fi

if (( ${#files[@]} == 0 )); then
  notify-send "omapdf" "No PDFs found in ${dirs//:/, }"
  exit 0
fi

# Menu rows as "<glyph>\t<label>\t<subtext>"; the menu returns "label\tsubtext",
# and the subtext (the full path) is the stable key.
choice="$(
  for f in "${files[@]}"; do
    printf '\t%s\t%s\n' "$(basename "$f" .pdf)" "$f"
  done | omarchy-menu-select "Open PDF" -- --width 800 --maxheight 500
)" || exit 0
[[ -n $choice ]] || exit 0

path="${choice#*$'\t'}"

if command -v omapdf >/dev/null 2>&1; then
  exec omapdf open "$path"
else
  exec xdg-open "$path"
fi
