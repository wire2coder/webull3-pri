#!/bin/bash
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/tradeconfirmation"
DEST="$(cd "$(dirname "$0")" && pwd)/done1"

mkdir -p "$SRC" "$DEST"

count=$(find "$SRC" -maxdepth 1 -type f ! -name '.*' | wc -l | tr -d ' ')
echo "Files in tradeconfirmation: $count"

if [ "$count" -eq 0 ]; then
  echo "Nothing to move."
  exit 0
fi

find "$SRC" -maxdepth 1 -type f ! -name '.*' | while read -r file; do
  filename=$(basename "$file")
  mv "$file" "$DEST"/"$filename"
  echo "Moved: $filename from $SRC to $DEST"
done
echo "Moved $count file(s) to done1."
