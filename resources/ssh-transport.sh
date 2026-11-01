#!/bin/sh
# Keep scp as the foreground process so its native progress meter is visible.
set -eu
exec "${IPHONE7_SSHPASS:?Missing sshpass executable}" -e ssh "$@"
