"""Spike: H2 (willow-gate must BE _gate) + H3 (reconciliation from ReceiptLog).

Reading willow-mcp's _guarded/_gate showed the seam already exists: @_guarded
wraps every @mcp.tool (the sole funnel), _gate already returns an
effective_app_id distinct from the raw arg, and every decision is receipted. So
H2 is: run willow-gate's authorize INSIDE that funnel (composed with the H1
SIGNED binder + permitted() + tier), and H3 is: feed check_out's tools_used from
the real ReceiptLog, not willow-gate's in-session set.

Proves: (1) a denied call's tool body never runs; (2) the receipt log is the
source of truth for reconciliation; (3) reconciliation catches an exit that
claims a tool no receipt ever authorized (out-of-band use).
"""
import hashlib, hmac, json, os, secrets, tempfile

os.environ["WILLOW_HOME"] = tempfile.mkdtemp(prefix="h2_home_")
os.environ["WILLOW_MCP_APPS_ROOT"] = tempfile.mkdtemp(prefix="h2_apps_")

from willow_mcp import gate as wmcp                       # noqa: E402
from willow_mcp.receipts import ReceiptLog                # noqa: E402
from willow_gate import WillowGate                        # noqa: E402

RL = ReceiptLog(db_path=os.path.join(tempfile.mkdtemp(prefix="h2_rl_"), "receipts.db"))
WG = WillowGate(base_dir=tempfile.mkdtemp(prefix="h2_wg_"), require_pgp=False)

SECRETS = {"operator": b"o" * 32, "scribe": b"s" * 32}
WG.register_agent("operator", SECRETS["operator"], max_trust=4)
WG.register_agent("scribe",   SECRETS["scribe"],   max_trust=2)

def manifest(app, perms):
    d = os.path.join(os.environ["WILLOW_MCP_APPS_ROOT"], app)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.json"), "w") as f:
        json.dump({"app_id": app, "permissions": perms, "deny_tools": []}, f)

manifest("operator", ["full_access"])
manifest("scribe", ["store_read"])                        # read-only manifest

TOOL_CLASS = {"store_get": "read", "store_put": "write", "integration_call": "execute"}
EGRESS = {"integration_call"}

_N = [0]
def _nonce():
    _N[0] += 1
    return f"{_N[0]:032x}"

def _header(agent, trust, tools):
    h = {"agent_id": agent, "agent_name": agent, "last_gate": "h2", "pass_count": 100,
         "fail_count": 0, "drift": 0, "nonce": _nonce(), "trust_level": trust,
         "timestamp": 1000, "tools": tools, "state_hash": "s0", "reserved": 0,
         "signature": "0" * 64}
    signed = {k: h[k] for k in sorted(set(h) - {"signature"})}
    h["signature"] = hmac.new(SECRETS[agent], json.dumps(signed, sort_keys=True,
                              separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
    return h

def check_in(agent, trust, tools):
    return WG.check_in(_header(agent, trust, tools))[2]

_USED_CN = set()
def _sig(secret, sid, app, tool, cn):
    return hmac.new(secret, f"{sid}|{app}|{tool}|{cn}".encode(), hashlib.sha256).hexdigest()

def signed_call(agent, app_id, tool, sid):
    cn = secrets.token_hex(16)
    return {"app_id": app_id, "tool": tool, "session_id": sid, "call_nonce": cn,
            "sig": _sig(SECRETS[agent], sid, app_id, tool, cn)}

# ── the composed gate: H1 binder -> willow-gate authorize -> permitted ────────
def _gate_v2(call):
    """Returns (effective_app_id, error|None). This is what belongs INSIDE
    willow-mcp's _gate, replacing the app_id-verbatim step."""
    app_id, tool = call["app_id"], call["tool"]
    sess = WG.sessions.get(call.get("session_id") or "")
    if sess is None:
        return None, "no live session"
    cn = call.get("call_nonce")
    if not cn or cn in _USED_CN:
        return None, "missing/replayed call_nonce"
    secret = bytes.fromhex(WG._registry[sess["agent_id"]]["secret"])
    if not hmac.compare_digest(_sig(secret, call["session_id"], app_id, tool, cn),
                               call.get("sig", "")):
        return None, "signature mismatch"
    if sess["agent_id"] != app_id:
        return None, "signed session is not this app_id"
    _USED_CN.add(cn)
    ok, msg = WG.authorize_tool(sess, TOOL_CLASS[tool], export=(tool in EGRESS))
    if not ok:
        return None, "tier: " + msg
    if not wmcp.permitted(app_id, tool):
        return None, "manifest: not granted"
    return app_id, None

# ── the sole funnel: the raw tool body is reachable ONLY through here ─────────
_RAN = {}                       # tool -> times its body actually executed
def guarded(tool_name):
    def deco(fn):
        def wrapper(call):
            eff, err = _gate_v2(call)          # gate FIRST
            if err:
                RL.record(call["app_id"], tool_name, "denied", err)
                return {"error": err}          # fn body never runs
            result = fn(call)                  # only authorized calls reach the body
            RL.record(eff, tool_name, "ok", None)
            return result
        return wrapper
    return deco

@guarded("store_get")
def store_get(call):
    _RAN["store_get"] = _RAN.get("store_get", 0) + 1
    return {"ok": "read"}

@guarded("store_put")
def store_put(call):
    _RAN["store_put"] = _RAN.get("store_put", 0) + 1
    return {"ok": "wrote"}

# ── H3: reconciliation reads tools_used from the RECEIPT LOG ──────────────────
def tools_used_from_receipts(agent_id):
    return {r["tool"] for r in RL.tail(agent_id, limit=100) if r.get("outcome") == "ok"}

def reconcile(agent_id, exit_declared_tools):
    used = tools_used_from_receipts(agent_id)
    unaccounted = set(exit_declared_tools) - used - {"read"}
    return (not unaccounted), used, unaccounted

R = []
def verdict(tag, ok, note):
    R.append((tag, ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {tag}: {note}")

print("== H2: willow-gate authorize runs INSIDE the funnel ==")
op = check_in("operator", 4, ["read", "write"])
sid_op = op["nonce"]
res = store_get(signed_call("operator", "operator", "store_get", sid_op))
verdict("allowed-runs-body", res.get("ok") == "read" and _RAN.get("store_get") == 1,
        "operator's signed store_get authorized and body executed once")

sc = check_in("scribe", 2, ["read", "write"])
sid_sc = sc["nonce"]
before = _RAN.get("store_put", 0)
res = store_put(signed_call("scribe", "scribe", "store_put", sid_sc))   # read-only manifest
verdict("denied-body-never-runs", "error" in res and _RAN.get("store_put", 0) == before,
        f"scribe store_put denied ({res.get('error')}) and the body did NOT run")

print("\n== H3: reconciliation is fed from the ReceiptLog ==")
# operator legitimately used store_get (and store_put below); the receipt log,
# not willow-gate's session set, is the source of truth.
store_put(signed_call("operator", "operator", "store_put", sid_op))
ok, used, un = reconcile("operator", ["store_get", "store_put"])
verdict("recon-matches-receipts", ok, f"exit tools reconciled against receipts {sorted(used)}")

# out-of-band claim: exit declares a tool that has NO ok receipt for this agent
ok2, used2, un2 = reconcile("operator", ["store_get", "store_put", "integration_call"])
verdict("recon-catches-out-of-band", (not ok2) and un2 == {"integration_call"},
        f"exit claimed integration_call but no receipt authorized it -> flagged {un2}")

print("\n== sole-funnel note ==")
# The raw body is a local captured by the wrapper; the module exposes only the
# guarded callable. In willow-mcp the equivalent is @_guarded wrapping @mcp.tool:
# MCP registers the wrapped fn, and _gate is the only authorizer it calls.
exposed_is_wrapper = store_get.__name__ == "wrapper"
verdict("only-wrapper-exposed", exposed_is_wrapper,
        "the exported tool IS the guard wrapper; the raw body has no un-gated handle")

print("\n== SUMMARY ==")
fails = [t for t, ok in R if not ok]
print(f"{len(R) - len(fails)}/{len(R)} pass" + (f"; FAILS: {fails}" if fails else ""))
