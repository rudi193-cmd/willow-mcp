import json, statistics as st
p="/root/.claude/projects/-home-user-willow-mcp/e62e7dfd-17eb-5686-97cb-14a998884184.jsonl"
rows=[]
for line in open(p):
    line=line.strip()
    if not line: continue
    try: rows.append(json.loads(line))
    except: pass

# walk: for each genuine user turn, find ts, then first assistant text ts (TTFT),
# last assistant event ts (turn end), and count tool calls in the turn.
from datetime import datetime
def ts(r):
    t=r.get("timestamp")
    if not t: return None
    return datetime.fromisoformat(t.replace("Z","+00:00")).timestamp()

def is_user(r):
    if r.get("type")!="user": return False
    m=r.get("message",{})
    c=m.get("content")
    if isinstance(c,str): return True
    if isinstance(c,list):
        # genuine user text, not a tool_result
        return any(isinstance(b,dict) and b.get("type")=="text" for b in c) or \
               all(not(isinstance(b,dict) and b.get("type")=="tool_result") for b in c)
    return False

def user_text(r):
    m=r.get("message",{}); c=m.get("content")
    if isinstance(c,str): return c
    if isinstance(c,list):
        return " ".join(b.get("text","") for b in c if isinstance(b,dict) and b.get("type")=="text")
    return ""

turns=[]
i=0
n=len(rows)
while i<n:
    r=rows[i]
    if is_user(r) and user_text(r).strip():
        ut=ts(r); txt=user_text(r).strip()
        # scan forward to next genuine user turn
        j=i+1; ttft=None; last=ut; tools=0
        while j<n:
            rj=rows[j]
            if is_user(rj) and user_text(rj).strip(): break
            if rj.get("type")=="assistant":
                m=rj.get("message",{}); c=m.get("content",[])
                if isinstance(c,list):
                    for b in c:
                        if isinstance(b,dict):
                            if b.get("type")=="text" and b.get("text","").strip() and ttft is None:
                                ttft=ts(rj)
                            if b.get("type")=="tool_use": tools+=1
                if ts(rj): last=ts(rj)
            j+=1
        turns.append(dict(txt=txt[:48], chars=len(txt), tools=tools,
                          ttft=(ttft-ut) if (ttft and ut) else None,
                          dur=(last-ut) if (last and ut) else None))
        i=j
    else:
        i+=1

BIG=8
for k,t in enumerate(turns):
    t["size"]="BIG" if t["tools"]>=BIG else ("med" if t["tools"]>=3 else "small")

def med(xs):
    xs=[x for x in xs if x is not None]
    return round(st.median(xs),1) if xs else None

small=[t for t in turns if t["size"]=="small"]
# small turns whose PREVIOUS turn was BIG
small_after_big=[t for k,t in enumerate(turns) if t["size"]=="small" and k>0 and turns[k-1]["size"]=="BIG"]
allt=turns

print(f"turns classified: {len(turns)}")
print(f"all TTFT median {med([t['ttft'] for t in allt])}s  (n={sum(1 for t in allt if t['ttft'])})")
print(f"small TTFT median {med([t['ttft'] for t in small])}s  (n={len(small)})")
print(f"small-after-BIG TTFT median {med([t['ttft'] for t in small_after_big])}s  (n={len(small_after_big)})")
tt=[t['ttft'] for t in allt if t['ttft']]
print(f"TTFT min {round(min(tt),1)}s  max {round(max(tt),1)}s")
print()
print("small-after-BIG turns (the actual test):")
print(f"{'prevBIGtools':>12} {'ttft_s':>7} {'dur_s':>7}  prompt")
for k,t in enumerate(turns):
    if t["size"]=="small" and k>0 and turns[k-1]["size"]=="BIG":
        pv=turns[k-1]
        print(f"{pv['tools']:>12} {str(t['ttft']and round(t['ttft'],1)):>7} {str(t['dur']and round(t['dur'],1)):>7}  {t['txt']}")
