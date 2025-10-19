#!/bin/bash
set -euo pipefail

# --- defaults (safe under `set -u`) ---
: "${DOMAIN:=sim.local}"
: "${RECORD_NAME:=flux}"
: "${FLUX_INTERVAL:=5}"        # seconds
: "${FLUX_SELECTOR:=random}"   # random|roundrobin

# --- legacy aliases (if older code paths use them) ---
INTERVAL="$FLUX_INTERVAL"
SELECTOR="$FLUX_SELECTOR"

ZONE_FILE="/etc/bind/db.sim.local.zone"
AGENTS_FILE="/etc/bind/flux_agents.txt"

echo "DNS Updater: domain=${DOMAIN}, record=${RECORD_NAME}, interval=${FLUX_INTERVAL}s, selector=${FLUX_SELECTOR}"

# Ensure runtime dirs exist
mkdir -p /run /var/run || true

# Start named if not already running (some images exec this script directly)
if ! pgrep -x named >/dev/null 2>&1; then
  /usr/sbin/named -g -c /etc/bind/named.conf.local &
  NAMED_PID=$!
  sleep 2
else
  NAMED_PID="$(pgrep -x named | head -1)"
fi

# Resolve tool paths (Alpine packages)
CHECKZONE=""
for p in /usr/sbin/named-checkzone /usr/bin/named-checkzone; do
  [ -x "$p" ] && CHECKZONE="$p" && break
done
RNDC=""
for p in /usr/sbin/rndc /usr/bin/rndc; do
  [ -x "$p" ] && RNDC="$p" && break
done

# --- Helpers ---

# Overwrite target file contents without replacing inode (bind-mount safe)
overwrite_file() {
  # $1 = src tmp, $2 = dest
  # shellcheck disable=SC2094
  cat "$1" > "$2"
  sync
}

# Compute next 10-digit serial YYYYMMDDnn (nn auto-increments)
bump_serial() {
  local cur day today nn
  today="$(date +%Y%m%d)"
  cur="$(awk '/Serial \(dynamically generated\)/ {print $1; exit}' "$ZONE_FILE" || true)"
  if [[ "$cur" =~ ^[0-9]{10}$ ]]; then
    day="${cur:0:8}"
    nn="${cur:8:2}"
    if [ "$day" = "$today" ]; then
      nn=$((10#$nn + 1)); [ $nn -gt 99 ] && nn=1
      printf "%s%02d\n" "$today" "$nn"
    else
      printf "%s01\n" "$today"
    fi
  else
    printf "%s01\n" "$today"
  fi
}

# Pick an agent IP (random|roundrobin)
pick_ip() {
  case "$SELECTOR" in
    roundrobin)
      mapfile -t arr <"$AGENTS_FILE" || true
      local cnt="${#arr[@]}"
      [ "$cnt" -eq 0 ] && return 1
      local idx_file="/run/ff_rr_${RECORD_NAME}.idx"
      local idx=0
      if [ -f "$idx_file" ]; then
        idx=$(cat "$idx_file" 2>/dev/null || echo 0)
      fi
      # choose current index, then advance
      local choice=$(( idx % cnt ))
      echo $(( (idx + 1) % 100000000 )) > "$idx_file"
      printf "%s" "${arr[$choice]}"
      ;;
    random|*)
      shuf -n 1 "$AGENTS_FILE"
      ;;
  esac
}

# --- Main loop ---
while true; do
  # Ensure named is alive
  if ! kill -0 "$NAMED_PID" 2>/dev/null; then
    echo "[dns_updater] ERROR: named not running (pid=$NAMED_PID). Exiting."
    exit 1
  fi

  # Agents list present & non-empty?
  if [ ! -s "$AGENTS_FILE" ]; then
    echo "[dns_updater] waiting: $AGENTS_FILE empty"
    sleep "$FLUX_INTERVAL"
    continue
  fi

  NEW_IP="$(pick_ip || true)"
  if [ -z "${NEW_IP:-}" ]; then
    echo "[dns_updater] no IP picked; sleeping"
    sleep "$FLUX_INTERVAL"
    continue
  fi

  NEW_SERIAL="$(bump_serial)"

  # Rewrite zone to a temp, then OVERWRITE (not mv) to survive bind-mounts
  TMP="$(mktemp -p /tmp db.XXXXXX.zone)"
  awk -v s="$NEW_SERIAL" -v label="$RECORD_NAME" -v ip="$NEW_IP" '
    BEGIN { serial_done=0; added=0 }
    # replace serial line
    /^[ \t]*[0-9]{10}[ \t]*; Serial \(dynamically generated\)[ \t]*$/ {
      printf("                 %s ; Serial (dynamically generated)\n", s);
      serial_done=1; next
    }
    # drop any existing label A lines; we will emit one fresh below
    $0 ~ "^[ \t]*" label "[ \t]+IN[ \t]+A[ \t]+[0-9.]+" { next }
    { print }
    END {
      if (!serial_done) {
        print "                 " s " ; Serial (dynamically generated)"
      }
      print label "  IN A " ip
    }
  ' "$ZONE_FILE" > "$TMP"

  # Validate if possible
  if [ -n "$CHECKZONE" ]; then
    if ! "$CHECKZONE" "$DOMAIN" "$TMP" >/dev/null 2>&1; then
      echo "[dns_updater] zone check FAILED for $NEW_IP (serial $NEW_SERIAL)"
      rm -f "$TMP"
      sleep "$FLUX_INTERVAL"
      continue
    fi
  fi

  overwrite_file "$TMP" "$ZONE_FILE"
  chown named:named "$ZONE_FILE" || true
  rm -f "$TMP" || true

  # Reload
  if [ -n "$RNDC" ] && "$RNDC" reload "$DOMAIN" >/dev/null 2>&1; then
    echo "[dns_updater] reload via rndc OK: $RECORD_NAME.$DOMAIN -> $NEW_IP (serial $NEW_SERIAL)"
  else
    kill -HUP "$NAMED_PID" || true
    echo "[dns_updater] reload via HUP: $RECORD_NAME.$DOMAIN -> $NEW_IP (serial $NEW_SERIAL)"
  fi

  sleep "$FLUX_INTERVAL"
done
