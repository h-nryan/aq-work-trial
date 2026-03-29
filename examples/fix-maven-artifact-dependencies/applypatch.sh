#!/bin/sh
# Minimal applypatch helper for Aider-style patches
# Applies blocks like:
# *** Begin Patch
# *** Update File: path
# @@
# -old
# +new
# *** End Patch

set -e

TMPDIR="$(mktemp -d)"
PATCH_FILE="$TMPDIR/patch.in"
cat > "$PATCH_FILE"

# Process the patch file and apply updates
awk -v tmpdir="$TMPDIR" '
  BEGIN { in_update=0; in_hunk=0; path="" }
  /^\*\*\* Update File: / {
    if (path != "") {
      # flush previous file
      close(out)
    }
    path = substr($0, 20)
    out = tmpdir "/out_" NR
    files[path] = out
    in_update=1; in_hunk=0
    next
  }
  /^\*\*\* End Patch/ {
    in_update=0; in_hunk=0
    next
  }
  /^@@/ {
    if (in_update) { in_hunk=1; next }
  }
  {
    if (in_update) {
      if (in_hunk) {
        if ($0 ~ /^\+/) { print substr($0,2) >> out }
        else if ($0 ~ /^ /) { print substr($0,2) >> out }
        else if ($0 ~ /^-/) { next }
        else { print $0 >> out }
      } else {
        # If no hunks, treat verbatim content as replacement (skip patch headers)
        if ($0 !~ /^\*\*\*/ && $0 !~ /^---/ && $0 !~ /^\+\+\+/) {
          print $0 >> out
        }
      }
    }
  }
  END {
    # Emit list of files
    for (f in files) {
      print f "\t" files[f]
    }
  }
' "$PATCH_FILE" > "$TMPDIR/map.txt"

# Apply generated outputs
while IFS="\t" read -r dst src; do
  if [ -s "$src" ]; then
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
  fi
done < "$TMPDIR/map.txt"

rm -rf "$TMPDIR" 