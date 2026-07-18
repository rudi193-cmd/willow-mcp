"""Spike: willow-gate x willow-mcp seam — find the holes before the full build.

Not production. Composes willow-gate's identity/trust with willow-mcp's
gate.permitted + PERMISSION_GROUPS the way docs/design/willow-gate-seam.md
proposes, then attacks it. Prints SAFE (the check holds) or HOLE (a weakness the
full build must close). A "naive" bridge is included next to the "intended" one
to show what each check actually buys.
"""
import hashlib, hmac, json, os, tempfile

# ── temp env, marker-free paths (before importing willow_mcp) ────────────────
HOME = tempfile.mkdtemp(prefix="spike_home_")
APPS = tempfile.mkdtemp(prefix="spike_apps_")          # no "mcp_apps" in the name
os.environ["WILLOW_HOME"] = HOME
os.environ["WILLOW_MCP_APPS_ROOT"] = APPS

from willow_mcp import gate as wmcp                      # noqa: E402
from willow_gate import WillowGate, GateError, TRUST_LEVELS  # noqa: E402

WG = WillowGate(base_dir=tempfile.mkdtemp(prefix="wg_"), require_pgp=False)

def manifest(app, permissions, deny=None):
    d = os.path.join(APPS, app)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.json"), "w") as f:
        json.dump({"app_id": app, "permissions": permissions, "deny_tools": deny or []}, f)

# willow-mcp apps (fine-grained manifests). The seam ties agent_id == app_id, so
# these names double as willow-gate agent ids where a scenario tests the manifest.
manifest("operator", ["full_access"])
manifest("scribe", ["store_read"])                        # read-only MANIFEST
manifest("vet_no_egress", ["task_queue"])                 # execute but NOT integration_call

# willow-gate registered agents (secret + trust CEILING), operator-side
SECRETS = {"operator": b"o" * 32, "rookie": b"r" * 32, "scribe": b"s" * 32,
           "vet_no_egress": b"v" * 32, "reader_only": b"R" * 32}
WG.register_agent("operator",      SECRETS["operator"],      max_trust=4)
WG.register_agent("rookie",        SECRETS["rookie"],        max_trust=1)
WG.register_agent("scribe",        SECRETS["scribe"],        max_trust=2)  # writable tier
WG.register_agent("vet_no_egress", SECRETS["vet_no_egress"], max_trust=3)
WG.register_agent("reader_only",   SECRETS["reader_only"],   max_trust=1)

_N = [0]
def nonce():
    _N[0] += 1
    return f"{_N[0]:032x}"

def header(agent, trust, tools, *, secret=None, pass_count=100, fail_count=0,
           drift=0, ts=1000, reserved=0, nonce_override=None):
    h = {"agent_id": agent, "agent_name": agent, "last_gate": "spike",
         "pass_count": pass_count, "fail_count": fail_count, "drift": drift,
         "nonce": nonce_override or nonce(), "trust_level": trust, "timestamp": ts,
         "tools": tools, "state_hash": "s0", "reserved": reserved, "signature": "0" * 64}
    sec = secret if secret is not None else SECRETS[agent]
    signed = {k: h[k] for k in sorted(set(h) - {"signature"})}
    h["signature"] = hmac.new(sec, json.dumps(signed, sort_keys=True,
                              separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
    return h

# ── the seam: tool -> abstract class; egress tools ───────────────────────────
TOOL_CLASS = {"store_get": "read", "lineage_why": "read",
              "store_put": "write", "lineage_record": "write",
              "task_submit": "execute", "integration_call": "execute",
              "schema_confirm_mapping": "admin"}
EGRESS = {"integration_call"}

def intended(session, app_id, tool):
    """The proposed seam: identity-bound + manifest + tier ceiling + export gate."""
    if session["agent_id"] != app_id:
        return False, "identity: session not bound to this app_id"
    if not wmcp.permitted(app_id, tool):
        return False, "manifest: app_id not granted this tool"
    ok, msg = WG.authorize_tool(session, TOOL_CLASS[tool], export=(tool in EGRESS))
    return (ok, "tier: " + msg) if not ok else (True, "ALLOWED")

def naive_arg(session, app_id, tool):
    """A tempting shortcut: trust the app_id ARGUMENT, skip the session binding."""
    if not wmcp.permitted(app_id, tool):
        return False, "manifest"
    ok, msg = WG.authorize_tool(session, TOOL_CLASS[tool], export=(tool in EGRESS))
    return ok, msg

def naive_noexport(session, app_id, tool):
    """Another shortcut: forget the manifest ∩, lean only on the trust tier."""
    ok, msg = WG.authorize_tool(session, TOOL_CLASS[tool], export=(tool in EGRESS))
    return ok, msg

R = []
def verdict(tag, hole, note):
    R.append((tag, hole, note))
    print(f"  [{'HOLE' if hole else 'SAFE'}] {tag}: {note}")

def checkin(agent, trust, tools, **kw):
    ok, msg, sess = WG.check_in(header(agent, trust, tools, **kw))
    return sess

print("== willow-gate native protections, exercised THROUGH the bridge ==")
# ceiling
try:
    checkin("rookie", 4, ["read"])                      # claim Elder, ceiling is 1
    verdict("ceiling-cap", True, "rookie claimed trust 4 and check_in accepted it")
except GateError as e:
    verdict("ceiling-cap", False, f"claim>ceiling rejected ({e})")
# forgery
try:
    WG.check_in(header("operator", 4, ["read"], secret=b"x" * 32))
    verdict("forged-sig", True, "wrong secret produced a valid check_in")
except GateError as e:
    verdict("forged-sig", False, f"signature mismatch rejected")
# replay
s = checkin("operator", 4, ["read"], nonce_override="ab" * 16)
try:
    WG.check_in(header("operator", 4, ["read"], nonce_override="ab" * 16))
    verdict("nonce-replay", True, "reused nonce accepted")
except GateError:
    verdict("nonce-replay", False, "reused nonce refused")
# trap
try:
    WG.check_in(header("operator", 4, ["read"], reserved=1))
    verdict("reserved-trap", True, "reserved!=0 accepted")
except GateError:
    verdict("reserved-trap", False, "reserved trap tripped")

print("\n== SEAM hole #1: identity decoupling (session vs app_id argument) ==")
# scribe: a WRITABLE tier (2), but its willow-mcp manifest grants only store_read.
scribe = checkin("scribe", 2, ["read", "write"])
ok_naive, _ = naive_arg(scribe, "operator", "store_put")    # scribe session, operator arg
verdict("naive-trusts-arg", ok_naive,
        "naive bridge let the scribe session (own manifest = read-only) WRITE via "
        "operator's full_access, just by passing app_id=operator" if ok_naive else "n/a")
ok_int, why = intended(scribe, "operator", "store_put")
verdict("intended-binds-session", ok_int,
        "intended bridge STILL allowed it" if ok_int else f"denied — {why}")
ok_own, why_own = intended(scribe, "scribe", "store_put")   # scribe as itself
verdict("intended-manifest-confines", ok_own,
        "scribe wrote despite a read-only manifest" if ok_own else f"denied — {why_own}")
# but over MCP the call carries only app_id. If the bridge maps app_id->live session:
op = checkin("operator", 4, ["read", "write", "query", "execute", "admin"])
LIVE_BY_APPID = {"operator": op}                        # what an app_id-keyed bridge would do
attacker_session = LIVE_BY_APPID.get("operator")        # attacker passes app_id=operator
ok_ride, _ = intended(attacker_session, "operator", "store_put")
verdict("appid-keyed-session-ride", ok_ride,
        "a caller passing app_id=operator rode the LIVE operator session with no auth "
        "of its own — MCP calls carry app_id (a string), not a session credential"
        if ok_ride else "n/a")

print("\n== SEAM hole #2: egress must need BOTH manifest and tier ==")
vet = checkin("vet_no_egress", 3, ["read", "write", "query", "execute"])  # export-allowed tier
ok_naive2, _ = naive_noexport(vet, "vet_no_egress", "integration_call")
verdict("tier-only-egress", ok_naive2,
        "tier-only bridge granted integration_call the manifest never gave"
        if ok_naive2 else "n/a")
ok_int2, why2 = intended(vet, "vet_no_egress", "integration_call")
verdict("intended-egress-double-gate", ok_int2,
        "intended bridge allowed egress" if ok_int2 else f"denied — {why2}")

print("\n== SEAM hole #3: read-universal (willow-gate) vs fail-closed (willow-mcp) ==")
# willow-gate: read is universal, even Exiled. willow-mcp: unmanifested app_id -> deny.
try:
    WG.check_in(header("ghost", 0, ["read"], secret=b"g" * 32))
    verdict("ghost-checkin", True, "unregistered agent got a session")
except GateError:
    verdict("ghost-checkin", False, "unregistered agent cannot even check_in (fail-closed)")
# a REGISTERED but unmanifested reader: willow-gate would grant read; the seam must not
WG.register_agent("reader_only", b"R" * 32, max_trust=1)
rd = checkin("reader_only", 1, ["read"])
ok_read, why3 = intended(rd, "reader_only", "store_get")   # no manifest for reader_only
verdict("read-universal-survives", ok_read,
        "read-universal leaked past willow-mcp scoping" if ok_read
        else f"willow-mcp fail-closed WON over read-universal — {why3} "
             "(POLICY: read-universal does not survive the seam; must be stated)")
# also: Exiled entry — willow-gate defines entry_allowed=False for Exiled...
ex_allowed = TRUST_LEVELS[0].entry_allowed
try:
    checkin("reader_only", 0, ["read"])
    got_session = True
except GateError:
    got_session = False
verdict("exiled-entry-enforced", (got_session and not ex_allowed),
        "Exiled got a session though entry_allowed=False — check_in never enforces "
        "entry_allowed" if (got_session and not ex_allowed) else "consistent")

print("\n== SEAM hole #4: enforcement path — is the bridge the ONLY door? ==")
# willow-mcp tools are framework-dispatched via _guarded/_gate. willow-gate only
# PREVENTS if authorize is the sole path. Simulate a call that reaches the willow-mcp
# tool via gate.permitted alone (bypassing willow-gate):
direct_ok = wmcp.permitted("operator", "store_put")     # what _gate does today
verdict("bypass-around-willow-gate", direct_ok,
        "willow-mcp authorized store_put with willow-gate never consulted — the bridge "
        "must BE _gate, not sit beside it, or prevention+reconciliation are theater"
        if direct_ok else "n/a")
# and check_out reconciliation is blind to that bypass:
blind = "store_put" not in op["tools_used"]
verdict("checkout-recon-blind", blind,
        "check_out's tools_used never saw the bypassed call — reconciliation can't "
        "detect out-of-band use unless tools_used is fed by willow-mcp receipts"
        if blind else "n/a")

print("\n== SUMMARY ==")
holes = [t for t, h, _ in R if h]
print(f"{len(holes)} holes / {len(R)} probes")
for t, h, n in R:
    if h:
        print(f"  HOLE  {t}: {n}")
