"""Spike: H1 — bind an MCP call to an HMAC-verified check-in session.

The hole: a willow-mcp tool call carries `app_id` (a plaintext string). check_in
binds a SESSION (agent_id + trust, HMAC-verified), but nothing ties a given call
to that session, so `app_id=operator` rides the live operator session.

This prototypes the missing binder — what each call must ALSO carry — across
three modes, and attacks each with: a legit call, a RIDE (know the app_id, not
the credential), a REPLAY (capture a credential, reuse it), and a TAMPER (reuse a
credential for a different tool). Prints SAFE / HOLE.

  APPID_ONLY  today: the call carries only app_id.
  BEARER      check_in mints a session token; the call carries it.
  SIGNED      the call carries (session_id, call_nonce, HMAC over the call).
"""
import hashlib, hmac, json, os, secrets, tempfile

os.environ["WILLOW_HOME"] = tempfile.mkdtemp(prefix="h1_home_")
os.environ["WILLOW_MCP_APPS_ROOT"] = tempfile.mkdtemp(prefix="h1_apps_")

from willow_gate import WillowGate                          # noqa: E402

WG = WillowGate(base_dir=tempfile.mkdtemp(prefix="h1_wg_"), require_pgp=False)
SECRETS = {"operator": b"o" * 32, "attacker": b"a" * 32}
WG.register_agent("operator", SECRETS["operator"], max_trust=4)
WG.register_agent("attacker", SECRETS["attacker"], max_trust=4)

_N = [0]
def _nonce():
    _N[0] += 1
    return f"{_N[0]:032x}"

def _header(agent, trust, tools):
    h = {"agent_id": agent, "agent_name": agent, "last_gate": "h1",
         "pass_count": 100, "fail_count": 0, "drift": 0, "nonce": _nonce(),
         "trust_level": trust, "timestamp": 1000, "tools": tools,
         "state_hash": "s0", "reserved": 0, "signature": "0" * 64}
    signed = {k: h[k] for k in sorted(set(h) - {"signature"})}
    h["signature"] = hmac.new(SECRETS[agent], json.dumps(signed, sort_keys=True,
                              separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
    return h

# ── the binder: resolve a CALL -> a verified (agent_id, trust) or None ────────
# A Call is what actually crosses the MCP boundary: an app_id, a tool, and
# whatever credential the mode requires.
_BEARER_TOKENS = {}      # token -> session nonce (bearer mode)
_USED_CALL_NONCES = set()  # signed-mode per-call replay guard

def check_in(agent, trust, tools):
    ok, msg, sess = WG.check_in(_header(agent, trust, tools))
    token = secrets.token_hex(16)
    _BEARER_TOKENS[token] = sess["nonce"]
    return sess, token

def _sig_over(secret, session_id, app_id, tool, call_nonce):
    msg = f"{session_id}|{app_id}|{tool}|{call_nonce}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()

def resolve(mode, call):
    """Return (agent_id, trust) if the call is bound to a live session, else None
    with a reason. This is what _gate must run BEFORE permitted()/tier."""
    app_id = call["app_id"]
    if mode == "APPID_ONLY":
        # today's behaviour: app_id is taken at face value. No binding at all.
        return (app_id, None), "app_id trusted verbatim"
    if mode == "BEARER":
        tok = call.get("session_token")
        nonce = _BEARER_TOKENS.get(tok or "")
        sess = WG.sessions.get(nonce or "")
        if sess is None:
            return None, "no live session for this token"
        if sess["agent_id"] != app_id:
            return None, "token's session is not this app_id"
        return (sess["agent_id"], sess["trust_level"]), "bound by bearer token"
    if mode == "SIGNED":
        sid = call.get("session_id"); cn = call.get("call_nonce"); sig = call.get("sig")
        sess = WG.sessions.get(sid or "")
        if sess is None:
            return None, "no live session for session_id"
        if not cn or cn in _USED_CALL_NONCES:
            return None, "missing or replayed call_nonce"
        rec = WG._registry.get(sess["agent_id"])
        secret = bytes.fromhex(rec["secret"])
        expect = _sig_over(secret, sid, app_id, call["tool"], cn)
        if not (sig and hmac.compare_digest(expect, sig)):
            return None, "call signature mismatch"
        if sess["agent_id"] != app_id:
            return None, "signed session is not this app_id"
        _USED_CALL_NONCES.add(cn)
        return (sess["agent_id"], sess["trust_level"]), "bound by per-call signature"
    raise ValueError(mode)

# ── call builders (what a legit client sends) ────────────────────────────────
def bearer_call(app_id, tool, token):
    return {"app_id": app_id, "tool": tool, "session_token": token}

def signed_call(app_id, tool, agent_secret, session_id):
    cn = secrets.token_hex(16)
    return {"app_id": app_id, "tool": tool, "session_id": session_id,
            "call_nonce": cn, "sig": _sig_over(agent_secret, session_id, app_id, tool, cn)}

R = []
def verdict(mode, attack, hole, note):
    R.append((mode, attack, hole))
    print(f"  [{'HOLE' if hole else 'SAFE'}] {mode:10} / {attack:16} {note}")

# operator legitimately checks in; the attacker knows operator's app_id string.
op_sess, op_token = check_in("operator", 4, ["read", "write"])
SID = op_sess["nonce"]

print("== APPID_ONLY (today) ==")
r, why = resolve("APPID_ONLY", {"app_id": "operator", "tool": "store_put"})
verdict("APPID_ONLY", "ride", r is not None and r[0] == "operator",
        "attacker calls app_id=operator with nothing else and is resolved AS operator")

print("\n== BEARER (session token per call) ==")
r, _ = resolve("BEARER", bearer_call("operator", "store_put", op_token))
verdict("BEARER", "legit", not (r and r[0] == "operator"),
        "operator's own token resolves" if (r and r[0] == "operator") else "legit call REJECTED (bad)")
r, why = resolve("BEARER", bearer_call("operator", "store_put", secrets.token_hex(16)))
verdict("BEARER", "ride", r is not None, f"attacker without the token: {why}")
# residual: a captured bearer token replays for ANY later call
r, _ = resolve("BEARER", bearer_call("operator", "store_delete", op_token))  # different tool!
verdict("BEARER", "replay/tamper", r is not None,
        "captured token reused for a DIFFERENT tool (store_delete) still resolves — bearer is reusable")

print("\n== SIGNED (per-call HMAC) ==")
r, _ = resolve("SIGNED", signed_call("operator", "store_put", SECRETS["operator"], SID))
verdict("SIGNED", "legit", not (r and r[0] == "operator"),
        "operator's signed call resolves" if (r and r[0] == "operator") else "legit REJECTED (bad)")
r, why = resolve("SIGNED", {"app_id": "operator", "tool": "store_put", "session_id": SID,
                            "call_nonce": secrets.token_hex(16),
                            "sig": _sig_over(SECRETS["attacker"], SID, "operator", "store_put", "x")})
verdict("SIGNED", "ride", r is not None, f"attacker signs with own secret: {why}")
captured = signed_call("operator", "store_put", SECRETS["operator"], SID)
resolve("SIGNED", captured)                       # legit use consumes the call_nonce
r, why = resolve("SIGNED", captured)              # verbatim replay
verdict("SIGNED", "replay", r is not None, f"verbatim replay of a captured signed call: {why}")
tampered = dict(captured); tampered["tool"] = "store_delete"   # reuse sig for another tool
r, why = resolve("SIGNED", tampered)
verdict("SIGNED", "tamper", r is not None, f"captured sig reused for a different tool: {why}")

print("\n== SUMMARY ==")
holes = [(m, a) for m, a, h in R if h]
print(f"{len(holes)} holes / {len(R)} probes")
for m, a, h in R:
    if h:
        print(f"  HOLE  {m} / {a}")
