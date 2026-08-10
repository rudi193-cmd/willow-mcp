#!/usr/bin/env bash
# provision-uids.sh — create the dedicated low-privilege accounts issue #231's
# uid separation needs, so willow-mcp's ownership/mode hardening becomes a real
# OS boundary instead of a no-op on a single-uid host.
#
# This ONLY creates accounts (and, in B2, the WILLOW_HOME dir owned by the
# runtime account). It deliberately does NOT run harden-trust-root, install a
# systemd unit, or flip WILLOW_MCP_STRICT_TRUST_ROOT — those are separate,
# ordered steps in the runbook, which you should read first:
#   docs/deploy/dedicated-uid-deployment.md
#
# Idempotent: existing accounts are left as-is. Requires root (uses useradd).
#
#   sudo deploy/provision-uids.sh                 # B2 (default): operator + runtime
#   sudo deploy/provision-uids.sh --shape b1      # B1: single willow-operator account
#   sudo WILLOW_HOME=/srv/willow deploy/provision-uids.sh
#
# Roles (see the runbook's "three roles" table):
#   willow-operator — trust owner: owns config/, mcp_apps/, the egress key.
#   willow-runtime  — runs the server process (B2 only). Reads manifests/leases,
#                     read/writes store/ & dispatch/; cannot touch the trust root.
# In B1 the runtime IS willow-operator, so no separate runtime account is made.

set -euo pipefail

SHAPE="b2"
OPERATOR="${WILLOW_TRUST_OWNER:-willow-operator}"
RUNTIME="${WILLOW_RUNTIME_USER:-willow-runtime}"
WILLOW_HOME="${WILLOW_HOME:-/var/lib/willow-mcp}"

while [ $# -gt 0 ]; do
    case "$1" in
        --shape) SHAPE="${2:-}"; shift 2 ;;
        --shape=*) SHAPE="${1#*=}"; shift ;;
        -h|--help) sed -n '2,26p' "$0"; exit 0 ;;
        *) echo "provision-uids: unknown argument: $1" >&2; exit 2 ;;
    esac
done

case "$SHAPE" in
    b1|B1) SHAPE="b1" ;;
    b2|B2) SHAPE="b2" ;;
    *) echo "provision-uids: --shape must be b1 or b2, got: $SHAPE" >&2; exit 2 ;;
esac

if [ "$(id -u)" -ne 0 ]; then
    echo "provision-uids: must run as root (useradd needs it); try sudo" >&2
    exit 1
fi

# Create a login-disabled system account if it does not already exist.
ensure_user() {
    local name="$1"
    if id "$name" >/dev/null 2>&1; then
        echo "provision-uids: user '$name' already exists — leaving as-is"
    else
        useradd --system --shell /usr/sbin/nologin "$name"
        echo "provision-uids: created system user '$name'"
    fi
}

ensure_user "$OPERATOR"

if [ "$SHAPE" = "b2" ]; then
    ensure_user "$RUNTIME"
    # WILLOW_HOME is populated and run by the runtime account in B2.
    mkdir -p "$WILLOW_HOME"
    chown "$RUNTIME:$RUNTIME" "$WILLOW_HOME"
    echo "provision-uids: $WILLOW_HOME owned by '$RUNTIME'"
    RUNTIME_HINT="$RUNTIME"
else
    RUNTIME_HINT="$OPERATOR"
fi

cat <<EOF

Accounts ready (shape ${SHAPE^^}). Next, following docs/deploy/dedicated-uid-deployment.md:

  # populate WILLOW_HOME as the runtime account, then move confirm authority
  # to the trust owner:
  sudo -u $OPERATOR env WILLOW_HOME=$WILLOW_HOME \\
      willow-mcp harden-trust-root --runtime-user $RUNTIME_HINT
  sudo -u $OPERATOR env WILLOW_HOME=$WILLOW_HOME \\
      willow-mcp repair-runtime-perms --runtime-user $RUNTIME_HINT

Then install a SYSTEM systemd unit from
deploy/willow-mcp-serve-system.service.template with User=$RUNTIME_HINT
$( [ "$SHAPE" = "b1" ] && echo "(delete its WILLOW_MCP_STRICT_TRUST_ROOT line — B1)" )
and verify with:  sudo -u $RUNTIME_HINT env WILLOW_HOME=$WILLOW_HOME willow-mcp doctor
EOF
