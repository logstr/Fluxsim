#!/bin/sh
set -e

# Alpine bind runs fine as root in containers; ensure runtime dirs exist
mkdir -p /var/cache/bind /var/run/named

echo ">>> /etc/bind listing:"
ls -l /etc/bind || true

echo ">>> Validating named.conf and zones..."
if ! named-checkconf -z /etc/bind/named.conf; then
  echo ">>> named-checkconf FAILED. Sleeping for inspection..."
  sleep 3600
  exit 1
fi

echo ">>> Starting named (foreground, debug=1)..."
# -g = foreground; -c config path; -d 1 = a bit of debug
exec named -g -c /etc/bind/named.conf -d 1
