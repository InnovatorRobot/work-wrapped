#!/usr/bin/env bash
# Convert dashboard.webm to dashboard.gif (good quality, reasonable size)
# Usage: ./scripts/webm-to-gif.sh [input.webm] [output.gif]
# Default: dashboard.webm -> dashboard.gif (in current dir or script dir)

set -e
INPUT="${1:-dashboard.webm}"
OUTPUT="${2:-dashboard.gif}"
WIDTH="${WIDTH:-960}"   # optional: WIDTH=640 ./scripts/webm-to-gif.sh
FPS="${FPS:-10}"        # optional: FPS=8 ./scripts/webm-to-gif.sh

if [[ ! -f "$INPUT" ]]; then
  echo "Error: $INPUT not found."
  echo "Usage: $0 [input.webm] [output.gif]"
  exit 1
fi

echo "Converting $INPUT -> $OUTPUT (width=${WIDTH}, fps=${FPS})..."
PALETTE="/tmp/palette_$$.png"

ffmpeg -y -i "$INPUT" -vf "fps=${FPS},scale=${WIDTH}:-1:flags=lanczos,palettegen" "$PALETTE"
ffmpeg -y -i "$INPUT" -i "$PALETTE" -lavfi "fps=${FPS},scale=${WIDTH}:-1:flags=lanczos[x];[x][1:v]paletteuse" "$OUTPUT"
rm -f "$PALETTE"
echo "Done: $OUTPUT"
