#!/bin/sh
# Runs as root only long enough to make the data folder writable, then drops to PUID:PGID
# (568:568 = the TrueNAS "apps" user by default).
set -e
mkdir -p "$DATA_DIR/uploads"
if [ "$(id -u)" = "0" ]; then
  chown "$PUID:$PGID" "$DATA_DIR" "$DATA_DIR/uploads" 2>/dev/null || true
  # Fix ownership of files from older runs, without walking big trees every start.
  find "$DATA_DIR" -maxdepth 2 ! -user "$PUID" -exec chown "$PUID:$PGID" {} + 2>/dev/null || true
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi
exec "$@"
