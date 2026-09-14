#!/bin/bash
# Pick a recent PDF and open it. Bundled with the omapdf.bar Omarchy plugin
# so the widget works standalone: prefers the omepreview editor when installed,
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
  # Bounded scan: a deadline on find and a candidate cap ahead of the sort,
  # so attacker-influenced folder contents cannot drive unbounded work.
  mapfile -t files < <(
    timeout 2 find "${existing[@]}" -maxdepth 4 \( -type d -name '.*' -prune \) -o \
      -type f -iname '*.pdf' -printf '%T@\t%p\n' 2>/dev/null |
      head -n 1000 | sort -rn | cut -f2- | head -40
  )
fi

if (( ${#files[@]} == 0 )); then
  notify-send "omepreview" "No PDFs found in ${dirs//:/, }"
  exit 0
fi

# Filenames are attacker-influenced input. Strip control characters (so a
# crafted name cannot forge tab/newline-delimited menu rows) and replace
# angle brackets (so the menu's AutoText labels can never parse a name as
# rich text). Selection maps back through the row index — the displayed
# string is never trusted as a path.
sanitize() {
  local s
  s=$(printf '%s' "$1" | tr -d '\000-\037')
  s=${s//</(}
  s=${s//>/)}
  printf '%s' "$s"
}

rows=""
for i in "${!files[@]}"; do
  f=${files[$i]}
  name=$(sanitize "$(basename "$f" .pdf)")
  dir=$(sanitize "$(dirname "$f")")
  dir=${dir/#"$HOME"/\~}
  rows+=$'\t'"$name"$'\t'"$((i + 1)) · $dir"$'\n'
done

choice="$(printf '%s' "$rows" |
  omarchy-menu-select "Open PDF" -- --width 800 --maxheight 500)" || exit 0
[[ -n $choice ]] || exit 0

# The menu returns "label\tsubtext"; the subtext leads with the row index.
subtext="${choice#*$'\t'}"
index="${subtext%% *}"
[[ $index =~ ^[0-9]+$ ]] || exit 1
path="${files[$((index - 1))]:-}"
[[ -n $path && -f $path ]] || exit 1

if command -v omepreview >/dev/null 2>&1; then
  exec omepreview open "$path"
else
  exec xdg-open "$path"
fi
