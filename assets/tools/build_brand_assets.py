#!/usr/bin/env python3
"""Regenerate the Firefly Agentic README brand assets — assets/banner.svg and
the seven diagram SVGs — from the shared visual kit.

Firefly Agentic is the **GenAI / "intelligence" member** of the Firefly Framework
family (the Java/Spring-Boot, .NET, PyFly and Rust siblings share one firefly-in-
the-dark language). This script ports the PyFly brand kit, recolored to a violet
"intelligence" palette, and embeds the family master wordmark ("firefly", from
assets/tools/wordmark.py) recolored — no web fonts, no raster, fully offline.

Requirements: Python 3.13+, fontTools (Arial metrics → guaranteed text fit). The
repo .venv has it (plus cairosvg to render/verify):
    .venv/bin/python assets/tools/build_brand_assets.py
    .venv/bin/python -c "import cairosvg; cairosvg.svg2png(url='assets/banner.svg', write_to='/tmp/b.png', output_width=1280)"

Every diagram registers its card rectangles and runs check(); the build prints
"WARNINGS: none" when nothing overlaps.
"""
from __future__ import annotations
import math, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ASSETS = REPO / "assets"
sys.path.insert(0, str(HERE))
from fontTools.ttLib import TTFont
from wordmark import FIREFLY_PATH, DOT_CX, DOT_CY, DOT_R
try:
    from icons import ICONS
except Exception:
    ICONS = {}

# --------------------------------------------------------------------------- palette
WHITE="#ffffff"
VIOLET="#8b5cf6"; VIOLET2="#7c3aed"; VIOLETD="#6d28d9"
MID="#5b21b6"; DARK="#4c1d95"
INK="#1e1633"; BODY="#322b45"; MUTED="#8b82a3"
SUB="#f5f2fe"; STROKE="#e4def5"
INDIGO="#6366f1"
AMBER="#c2722a"; DOT_HOT="#F68000"; DOT_WARM="#FFF9C1"
MONO="ui-monospace,'SF Mono',Menlo,Consolas,monospace"
SANS="-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"

# --------------------------------------------------------------------------- text metrics
# Arial metrics ≈ system sans, for guaranteed-fit box sizing.
_AR={}
def _arial(bold):
    k="b" if bold else "r"
    if k not in _AR:
        p=f"/System/Library/Fonts/Supplemental/Arial{' Bold' if bold else ''}.ttf"
        try: _AR[k]=(lambda f:(f["head"].unitsPerEm,f.getBestCmap(),f.getGlyphSet()))(TTFont(p))
        except Exception: _AR[k]=None
    return _AR[k]
def tw(s,size,bold=False):
    m=_arial(bold)
    if not m: return 0.56*size*len(str(s))
    upm,cmap,gs=m; w=0
    for ch in str(s):
        g=cmap.get(ord(ch)); w+= gs[g].width if g else upm*0.5
    return w/upm*size
def mw(s,size): return 0.602*size*len(str(s))
def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

# --------------------------------------------------------------------------- kit
def defs(cx,cy,r=520):
    return f'''<defs>
    <linearGradient id="hdr" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{VIOLET}"/><stop offset="1" stop-color="{VIOLETD}"/></linearGradient>
    <linearGradient id="door" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#a78bfa"/><stop offset="1" stop-color="#7c3aed"/></linearGradient>
    <linearGradient id="bed" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#241a3a"/><stop offset="1" stop-color="#150f26"/></linearGradient>
    <radialGradient id="amb" cx="{cx}" cy="{cy}" r="{r}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{VIOLET}" stop-opacity="0.12"/><stop offset="1" stop-color="{VIOLET}" stop-opacity="0"/></radialGradient>
    <filter id="sh" x="-25%" y="-25%" width="150%" height="170%"><feDropShadow dx="0" dy="2" stdDeviation="3.2" flood-color="#4c1d95" flood-opacity="0.16"/></filter>
    <marker id="arr" markerWidth="9" markerHeight="9" refX="6.2" refY="3.2" orient="auto"><path d="M0 0L7 3.2L0 6.4Z" fill="{VIOLETD}"/></marker>
    <marker id="arrb" markerWidth="9" markerHeight="9" refX="6.2" refY="3.2" orient="auto"><path d="M0 0L7 3.2L0 6.4Z" fill="{INDIGO}"/></marker>
    <marker id="arra" markerWidth="9" markerHeight="9" refX="6.2" refY="3.2" orient="auto"><path d="M0 0L7 3.2L0 6.4Z" fill="{AMBER}"/></marker>
    <g id="fly"><circle r="8.5" fill="#a78bfa" opacity="0.10"/><circle r="4.6" fill="#c4b5fd" opacity="0.22"/><circle r="2.4" fill="#ddd6fe" opacity="0.75"/><circle r="1.2" fill="#f5f3ff"/></g>
    <g id="ffly"><circle r="8.5" fill="#f6a821" opacity="0.10"/><circle r="4.6" fill="#ffc24a" opacity="0.22"/><circle r="2.4" fill="#ffd980" opacity="0.78"/><circle r="1.2" fill="#fff6e0"/></g>
  </defs>'''
def frame(w,h):
    return (f'<rect width="{w}" height="{h}" fill="{WHITE}"/>'
            f'<rect x="3" y="3" width="{w-6}" height="{h-6}" rx="18" fill="{WHITE}" stroke="{STROKE}" stroke-width="1.5"/>'
            f'<rect x="3" y="3" width="{w-6}" height="{h-6}" rx="18" fill="url(#amb)"/>')
def mote(x,y,s=1.0,k="fly"): return f'<use href="#{k}" transform="translate({x},{y}) scale({s})"/>'
def firefly_mark(x,y,s=1.0):
    """The family firefly — a warm amber glow dot, used as the diagram header mark."""
    return (f'<g transform="translate({x},{y}) scale({s})">'
            f'<circle r="11" fill="#f6a821" opacity="0.16"/><circle r="6.5" fill="#ffc24a" opacity="0.30"/>'
            f'<circle r="3.4" fill="url(#dot)"/><circle r="1.5" fill="#fff6e0"/></g>')
def badge(x,y,n,r=10.5):
    return (f'<circle cx="{x}" cy="{y}" r="{r}" fill="{DARK}"/>'
            f'<text x="{x}" y="{y+3.6}" text-anchor="middle" fill="#fff" font-size="{r}" font-weight="700" font-family="{SANS}">{n}</text>')
def icon(name,cx,cy,size,color=None):
    ic=ICONS.get(name)
    if not ic: return ""
    vb=[float(v) for v in ic["vb"].split()]; vw,vh=vb[2],vb[3]; s=size/max(vw,vh)
    return (f'<g transform="translate({cx:.1f},{cy:.1f}) scale({s:.4f}) translate({-vw/2:.1f},{-vh/2:.1f})">'
            f'<path d="{ic["d"]}" fill="{color or ic["color"]}"/></g>')
def title(w,t,sub=None,repo="fireflyframework-agentic"):
    s=[firefly_mark(40,30,1.25),
       f'<text x="64" y="45" font-size="21" font-weight="800" fill="{INK}" font-family="{SANS}" letter-spacing="0.2">{esc(t)}</text>',
       f'<text x="{w-26}" y="42" text-anchor="end" font-size="12" font-weight="600" fill="#b29ddb" font-family="{MONO}">{repo}</text>',
       f'<line x1="26" y1="62" x2="{w-26}" y2="62" stroke="{VIOLET2}" stroke-width="1.4" opacity="0.42"/>']
    if sub: s.append(f'<text x="26" y="84" font-size="12.5" font-style="italic" fill="{MUTED}" font-family="{SANS}">{esc(sub)}</text>')
    return "\n  ".join(s)
def svgdoc(w,h,label,body,amb=None):
    cx,cy=amb or (w-60,40)
    dot=('<radialGradient id="dot" cx="42%" cy="34%" r="72%"><stop offset="0" stop-color="'+DOT_WARM+'"/>'
         '<stop offset="1" stop-color="'+DOT_HOT+'"/></radialGradient>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'role="img" aria-label="{esc(label)}" font-family="{SANS}">\n  '
            +defs(cx,cy).replace("</defs>", dot+"</defs>")+"\n  "+frame(w,h)+"\n  "+body+"\n</svg>\n")

WARN=[]
def need(header,lines,mono=True,icon=False,pad=30):
    hw=tw(header,11,True)+(22 if icon else 0)
    lw=max([(mw(l,10) if mono else tw(l,10)) for l in lines]+[0]); return max(hw,lw)+pad
def fbox(x,y,w,h,header,lines,mono=True,hdrfill="url(#hdr)",stroke=VIOLET2,hc="#fff",icon_name=None,rects=None):
    fam=MONO if mono else SANS
    s=[f'<g filter="url(#sh)"><rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h}" rx="10" fill="{WHITE}" stroke="{stroke}" stroke-width="1.8"/>'
       f'<path d="M{x:.1f} {y+10}a10 10 0 0 1 10 -10h{w-20:.1f}a10 10 0 0 1 10 10v13H{x:.1f}Z" fill="{hdrfill}"/></g>',
       f'<text x="{x+12:.1f}" y="{y+15}" font-size="11" font-weight="700" fill="{hc}" font-family="{SANS}">{esc(header)}</text>']
    if icon_name: s.append(icon(icon_name,x+w-16,y+11,15,"#ffffff"))
    for i,ln in enumerate(lines):
        s.append(f'<text x="{x+12:.1f}" y="{y+39+i*15}" font-size="10" fill="{BODY}" font-family="{fam}">{esc(ln)}</text>')
    if rects is not None: rects.append((x,y,x+w,y+h))
    return "".join(s)
def edge(cx,cy,w,h,fx,fy):
    dx,dy=fx-cx,fy-cy
    if dx==0 and dy==0: return cx,cy
    s=min((w/2)/abs(dx) if dx else 9e9,(h/2)/abs(dy) if dy else 9e9); return cx+dx*s,cy+dy*s
def arrow(x1,y1,x2,y2,color=VIOLETD,dash=None,mk="arr",sw=1.8):
    d=f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{sw}"{d} marker-end="url(#{mk})"/>'
def spark(cx,cy,r,color):
    return (f'<path d="M{cx} {cy-r}L{cx+r*0.28} {cy-r*0.28}L{cx+r} {cy}L{cx+r*0.28} {cy+r*0.28}'
            f'L{cx} {cy+r}L{cx-r*0.28} {cy+r*0.28}L{cx-r} {cy}L{cx-r*0.28} {cy-r*0.28}Z" fill="{color}"/>')
def check(name,rects,pad=2):
    for i in range(len(rects)):
        for j in range(i+1,len(rects)):
            a,b=rects[i],rects[j]
            if a[0]<b[2]-pad and b[0]<a[2]-pad and a[1]<b[3]-pad and b[1]<a[3]-pad:
                WARN.append(f"{name}: overlap {i}&{j}")

# --------------------------------------------------------------------------- banner
def build_banner():
    W,H=1280,320
    # firefly wordmark transform (upright, like the Rust sibling)
    wx,wy,ws=80,118,0.72
    dot_x,dot_y=wx+ws*DOT_CX, wy+ws*DOT_CY
    wm_right=wx+ws*469
    # agent-network constellation (nodes joined by faint violet edges = a reasoning graph)
    nodes=[(742,150,"a",1.5),(858,96,"v",1.1),(960,182,"a",1.25),(1058,118,"v",1.4),
           (1150,72,"a",1.0),(1118,210,"v",1.15),(1232,150,"a",1.05),(820,238,"v",0.95),(1000,260,"a",0.9)]
    edges=[(0,1),(0,2),(1,3),(2,3),(3,4),(2,5),(3,6),(0,7),(2,8),(5,6)]
    bg=[(700,60,1.2,.45),(792,118,1.0,.4),(905,52,1.4,.46),(1192,108,1.0,.36),
        (690,200,1.1,.4),(1210,238,1.0,.34),(940,70,0.9,.32),(1080,168,1.0,.36)]
    nx=lambda i:nodes[i][0]; ny=lambda i:nodes[i][1]
    fly=lambda x,y,s,k:f'<use href="#fb{k}" transform="translate({x},{y}) scale({s})"/>'
    svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="Firefly Agentic — the production GenAI metaframework built on Pydantic AI">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="{W}" y2="{H}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#0b0a14"/><stop offset="0.5" stop-color="#120d1c"/><stop offset="1" stop-color="#140f1e"/></linearGradient>
    <radialGradient id="ambient" cx="980" cy="120" r="520" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#7c5cff" stop-opacity="0.24"/><stop offset="0.5" stop-color="#8b5cf6" stop-opacity="0.07"/><stop offset="1" stop-color="#8b5cf6" stop-opacity="0"/></radialGradient>
    <linearGradient id="wm" x1="0" y1="{wy+ws*36}" x2="0" y2="{wy+ws*174}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#d6c6ff"/><stop offset="0.5" stop-color="#a78bfa"/><stop offset="1" stop-color="#7c3aed"/></linearGradient>
    <radialGradient id="dotg" cx="42%" cy="34%" r="72%"><stop offset="0" stop-color="{DOT_WARM}"/><stop offset="1" stop-color="{DOT_HOT}"/></radialGradient>
    <linearGradient id="agw" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c4b5fd"/><stop offset="1" stop-color="#8b5cf6"/></linearGradient>
    <g id="fbv"><circle r="13" fill="#7c5cff" opacity="0.09"/><circle r="7.5" fill="#a78bfa" opacity="0.18"/><circle r="3.6" fill="#cbb8ff" opacity="0.6"/><circle r="1.9" fill="#f3efff"/></g>
    <g id="fba"><circle r="13" fill="#f6a821" opacity="0.09"/><circle r="7.5" fill="#ffc24a" opacity="0.17"/><circle r="3.6" fill="#ffd980" opacity="0.62"/><circle r="1.9" fill="#fff6e0"/></g>
  </defs>
  <rect width="{W}" height="{H}" fill="url(#sky)"/>
  <rect width="{W}" height="{H}" fill="url(#ambient)"/>
  <g fill="#b9a6f0">{"".join(f'<circle cx="{x}" cy="{y}" r="{r}" opacity="{o}"/>' for x,y,r,o in bg)}</g>
  <g stroke="#7c5cff" stroke-width="1" fill="none" opacity="0.5">{"".join(f'<line x1="{nx(a)}" y1="{ny(a)}" x2="{nx(b)}" y2="{ny(b)}" opacity="{0.10+0.06*((a+b)%3)}"/>' for a,b in edges)}</g>
  <g fill="none" stroke="#8b6cff" stroke-linecap="round">
    <path d="M812,250 C876,196 918,170 960,182" stroke-width="2" opacity="0.10"/>
    <path d="M1190,250 C1150,210 1110,150 1058,118" stroke-width="1.6" opacity="0.09"/>
  </g>
  {"".join(fly(x,y,s,k) for x,y,k,s in nodes)}
  <g transform="translate({wx},{wy}) scale({ws})" fill="url(#wm)" stroke="#2e1065" stroke-width="5" stroke-linejoin="round" paint-order="stroke"><path d="{FIREFLY_PATH}"/></g>
  <circle cx="{dot_x:.1f}" cy="{dot_y:.1f}" r="{ws*27:.1f}" fill="#f6a821" opacity="0.18"/>
  <circle cx="{dot_x:.1f}" cy="{dot_y:.1f}" r="{ws*DOT_R:.1f}" fill="url(#dotg)"/>
  <g transform="translate({wm_right+28:.0f},0)">
    <line x1="0" y1="148" x2="0" y2="236" stroke="url(#agw)" stroke-width="2.2" opacity="0.65"/>
    <text x="26" y="206" font-size="55" font-weight="800" fill="url(#agw)" font-family="{SANS}" letter-spacing="-1.6">agentic</text>
  </g>
  <rect x="84" y="250" width="320" height="2.4" rx="1.2" fill="url(#agw)" opacity="0.75"/>
  <text x="84" y="280" fill="#ece3ff" font-size="22" font-weight="600" font-family="{SANS}">Production-grade agents, reasoning &amp; pipelines</text>
  <text x="84" y="305" fill="#9d8fc4" font-size="16" font-weight="500" font-family="{SANS}" letter-spacing="0.3">type-safe · model-agnostic · built on Pydantic AI · async-native</text>
  <text x="{W-26}" y="34" text-anchor="end" font-family="{MONO}" font-size="12" fill="#7c6aa6" opacity="0.9" letter-spacing="0.4">fireflyframework-agentic</text>
</svg>'''
    (ASSETS/"banner.svg").write_text(svg)

# --------------------------------------------------------------------------- architecture
def architecture():
    W,H=864,628; X,WD=66,726
    layers=[("1","Orchestration","6","pipeline · DAG · 9 step types · checkpointer · audit-log · reducers"),
            ("2","Experimentation","2","experiments · lab   —   optional leaf modules"),
            ("3","Intelligence","4","reasoning · validation/QoS · observability · explainability"),
            ("4","Agent","5","agents · tools · prompts · memory · content"),
            ("5","Core","7","config · protocols · exceptions · plugins · resilience · storage · security")]
    b=[title(W,"Architecture at a glance","One install, one decorator — five cohesive layers on the Pydantic AI engine.")]
    fy=100
    b.append(f'<rect x="{X}" y="{fy}" width="{WD}" height="50" rx="12" fill="url(#door)" stroke="#6d28d9" stroke-width="1.2" filter="url(#sh)"/>')
    b.append(f'<rect x="{X+14}" y="{fy+6}" width="{WD-28}" height="2" rx="1" fill="#fbf8ff" opacity="0.3"/>')
    b.append(f'<text x="{X+22}" y="{fy+20}" font-size="10.5" font-weight="800" fill="#1c0e3a" letter-spacing="1.4">THE FRONT DOOR</text>')
    b.append(f'<text x="{X+22}" y="{fy+39}" font-size="15" font-weight="800" fill="#190a35" font-family="{MONO}">pip install fireflyframework-agentic · @firefly_agent</text>')
    b.append(f'<text x="{X+WD-16}" y="{fy+20}" text-anchor="end" font-size="11" fill="#1c0e3a" font-weight="700">one install</text>')
    b.append(f'<text x="{X+WD-16}" y="{fy+39}" text-anchor="end" font-size="11" fill="#1c0e3a" font-weight="700">one decorator</text>')
    b.append(f'<g stroke="{VIOLET2}" stroke-width="1.4" stroke-dasharray="2 3" opacity="0.7">'+"".join(f'<line x1="{X+WD*f:.0f}" y1="{fy+50}" x2="{X+WD*f:.0f}" y2="170"/>' for f in (.18,.45,.72))+'</g>')
    b.append(f'<line x1="46" y1="174" x2="46" y2="520" stroke="{VIOLETD}" stroke-width="2.2" marker-end="url(#arr)"/>')
    b.append(f'<text x="28" y="350" text-anchor="middle" font-size="10.5" font-weight="700" fill="{MID}" letter-spacing="0.08em" transform="rotate(-90,28,350)">DEPENDS ON</text>')
    by=170; BH=66; GAP=5.5
    for i,(n,name,cnt,mods) in enumerate(layers):
        y=by+i*(BH+GAP)
        b.append(f'<g filter="url(#sh)"><rect x="{X}" y="{y:.1f}" width="{WD}" height="{BH}" rx="11" fill="{WHITE}" stroke="{VIOLET2}" stroke-width="2"/>'
                 f'<path d="M{X} {y+11:.1f}a11 11 0 0 1 11 -11h{WD-22}a11 11 0 0 1 11 11v15H{X}Z" fill="url(#hdr)"/></g>')
        b.append(badge(X+20,y+13,n))
        b.append(f'<text x="{X+38}" y="{y+18:.1f}" fill="#fff" font-size="13" font-weight="700">{name}</text>')
        b.append(f'<text x="{X+44+tw(name,13,True):.0f}" y="{y+18:.1f}" fill="#ede7fb" font-size="10" font-weight="600">({cnt} modules)</text>')
        if i==4: b.append(f'<text x="{X+WD-14}" y="{y+18:.1f}" text-anchor="end" fill="#e7ddff" font-size="9.5" font-weight="700" letter-spacing="0.06em">BASE LAYER</text>')
        b.append(f'<text x="{X+22}" y="{y+49:.1f}" fill="{BODY}" font-size="11" font-family="{MONO}">{esc(mods)}</text>')
    yb=by+5*(BH+GAP)+4
    b.append(f'<rect x="{X}" y="{yb:.1f}" width="{WD}" height="46" rx="12" fill="url(#bed)"/>')
    b.append(firefly_mark(X+30,yb+23,1.25))
    b.append(f'<text x="{X+56}" y="{yb+20:.1f}" font-size="13" font-weight="800" fill="#efe8ff" font-family="{MONO}">Pydantic AI engine</text>')
    b.append(f'<text x="{X+56}" y="{yb+36:.1f}" font-size="10.5" fill="#c3b6e6">pydantic-ai · pydantic — the type-safe agent core every layer builds on</text>')
    b.append(f'<text x="{X+WD-14}" y="{yb+27:.1f}" text-anchor="end" font-size="10.5" fill="#a896d6" font-weight="600">Agent · Tool · RunContext</text>')
    b.append(f'<text x="{X+26}" y="{H-20}" font-size="9.5" font-style="italic" fill="{MUTED}">Embeddings (8 providers) · Vector Stores (6 backends) — a cross-cutting RAG capability wired into the Agent &amp; Orchestration layers.</text>')
    (ASSETS/"architecture.svg").write_text(svgdoc(W,H,"Firefly Agentic architecture: one front door over five layers on the Pydantic AI engine.","\n  ".join(b),amb=(720,72)))

# --------------------------------------------------------------------------- protocols
def protocols():
    W,H=980,612; R=[]
    b=[title(W,"Protocol-driven contracts — twelve ports, swap any part","Every extension point is a @runtime_checkable Protocol; implement it and the framework discovers you by duck typing.")]
    cards=[("AgentLike","FireflyAgent","pydantic_ai.Agent"),
           ("ToolProtocol","BaseTool","Sequential/Fallback/","  Conditional composer"),
           ("GuardProtocol","Validation · RateLimit","Approval · Sandbox","Composite"),
           ("ReasoningPattern","AbstractPattern","ReasoningPipeline"),
           ("StepExecutor","Agent · Reasoning","Callable · FanOut · FanIn"),
           ("DelegationStrategy","RoundRobin · Capability","ContentBased · CostAware","Chain · Fallback · Weighted"),
           ("CompressionStrategy","Truncation","Summarization · MapReduce"),
           ("MemoryStore","InMemoryStore · FileStore","SQLiteStore"),
           ("ValidationRule","Regex · Format · Range","Enum · Custom"),
           ("Chunker","TextChunker","MarkdownChunker","DocumentSplitter"),
           ("EmbeddingProtocol","BaseEmbedder","8 providers"),
           ("VectorStoreProtocol","BaseVectorStore","6 backends")]
    cols=3; cw=288; ch=96; gx=14; gy=14; x0=(W-(cols*cw+(cols-1)*gx))/2; y0=100
    for i,(hdr,*lines) in enumerate(cards):
        cx=x0+(i%cols)*(cw+gx); cy=y0+(i//cols)*(ch+gy)
        b.append(fbox(cx,cy,cw,ch,hdr,lines,rects=R))
    check("protocols",R)
    (ASSETS/"protocols.svg").write_text(svgdoc(W,H,"Firefly Agentic protocols: twelve runtime-checkable ports, each with its swappable implementations.","\n  ".join(b),amb=(820,64)))

# --------------------------------------------------------------------------- reasoning
def reasoning():
    W,H=980,486; R=[]
    b=[title(W,"Six reasoning patterns on one pluggable loop","Every pattern fills the same template-method loop; ReasoningPipeline chains them and OutputReviewer validates.")]
    # the loop
    ly=128; steps=["_reason","_act","_observe","_should_continue"]; sw=150; gap=22
    total=len(steps)*sw+(len(steps)-1)*gap; x=(W-total)/2-20
    first_x=x
    for i,st in enumerate(steps):
        b.append(f'<g filter="url(#sh)"><rect x="{x:.1f}" y="{ly}" width="{sw}" height="44" rx="10" fill="{SUB}" stroke="{VIOLET2}" stroke-width="1.8"/></g>'
                 f'<text x="{x+sw/2:.1f}" y="{ly+27}" text-anchor="middle" font-size="13" font-weight="700" fill="{MID}" font-family="{MONO}">{st}</text>')
        R.append((x,ly,x+sw,ly+44))
        if i<len(steps)-1: b.append(arrow(x+sw,ly+22,x+sw+gap,ly+22))
        x+=sw+gap
    # dashed loop-back arrow from the last box to the first
    rx=first_x+(len(steps)-1)*(sw+gap)+sw/2; lx=first_x+sw/2
    b.append(f'<path d="M{rx:.1f} {ly+44} C {rx:.1f} {ly+84}, {lx:.1f} {ly+84}, {lx:.1f} {ly+46}" fill="none" stroke="{AMBER}" stroke-width="1.6" stroke-dasharray="5 3" marker-end="url(#arra)"/>')
    cap="loops until done  ->  ReasoningResult + ReasoningTrace"; capw=tw(cap,10.5)+18
    b.append(f'<rect x="{W/2-capw/2:.1f}" y="{ly+92}" width="{capw:.1f}" height="19" rx="9.5" fill="{WHITE}"/>')
    b.append(f'<text x="{W/2:.0f}" y="{ly+105}" text-anchor="middle" font-size="10.5" fill="#a85d22" font-weight="600">{esc(cap)}</text>')
    # six pattern cards
    py=ly+118; pw=300; ph=92; gpx=14; gpy=14; px0=(W-(3*pw+2*gpx))/2
    pats=[("ReAct","observe -> think -> act","interleaved tool use"),
          ("Chain of Thought","step-by-step reasoning","explicit intermediate steps"),
          ("Plan-and-Execute","goal -> plan -> steps","optional replanning"),
          ("Reflexion","execute -> critique -> retry","self-correcting loop"),
          ("Tree of Thoughts","branch -> evaluate -> select","search over thoughts"),
          ("Goal Decomposition","goal -> phases -> tasks","hierarchical breakdown")]
    for i,(hdr,a,c) in enumerate(pats):
        cx=px0+(i%3)*(pw+gpx); cy=py+(i//3)*(ph+gpy)
        b.append(fbox(cx,cy,pw,ph,hdr,[a,c],mono=False,rects=R))
    check("reasoning",R)
    (ASSETS/"reasoning.svg").write_text(svgdoc(W,H,"Firefly Agentic reasoning: a reason/act/observe loop feeding six pluggable patterns.","\n  ".join(b),amb=(150,64)))

# --------------------------------------------------------------------------- pipeline
def pipeline():
    W,H=1000,470; R=[]
    b=[title(W,"Pipelines — a typed DAG your agents run on","PipelineEngine runs nodes level-by-level via asyncio.gather; per-node conditions, retries and timeouts.")]
    phases=[("ingest","BinaryNormalizer"),("split","DocumentSplitter"),("classify","AgentStep"),
            ("extract","AgentStep × N"),("validate","OutputReviewer"),("assemble","FanInStep"),("explain","ReportBuilder")]
    widths=[max(need(h,[l],mono=True),118) for h,l in phases]
    gap=10; total=sum(widths)+gap*(len(phases)-1); x=(W-total)/2; y=156; bh=70; centers=[]
    for (h,l),w in zip(phases,widths):
        hf="url(#hdr)"
        b.append(fbox(x,y,w,bh,h,[l],hdrfill=hf,rects=R)); centers.append(x+w/2); x+=w
        if (h,l)!=phases[-1]: b.append(arrow(x,y+bh/2,x+gap,y+bh/2)); x+=gap
    # fan-out / fan-in annotation over extract (index 3)
    ex=centers[3]
    b.append(f'<text x="{ex:.0f}" y="{y-14}" text-anchor="middle" font-size="10" fill="{INDIGO}" font-weight="600">FanOutStep  -&gt;  parallel  -&gt;  FanInStep</text>')
    b.append(arrow(ex,y-8,ex,y-2,INDIGO,mk="arrb",sw=1.3))
    # human-in-the-loop pause under validate (index 4)
    vx=centers[4]
    b.append(arrow(vx,y+bh,vx,y+bh+24,AMBER,dash="4 3",mk="arra",sw=1.4))
    plabel="human-in-the-loop · Pause / Send"; iw=11; pw=iw+8+tw(plabel,10)+24; bx=vx-pw/2; byy=y+bh+24
    b.append(f'<rect x="{bx:.1f}" y="{byy}" width="{pw:.1f}" height="26" rx="8" fill="{SUB}" stroke="{AMBER}" stroke-dasharray="4 3"/>')
    b.append(f'<rect x="{bx+13:.1f}" y="{byy+7}" width="3" height="12" rx="1" fill="#a85d22"/><rect x="{bx+18:.1f}" y="{byy+7}" width="3" height="12" rx="1" fill="#a85d22"/>')
    b.append(f'<text x="{bx+13+iw+6:.1f}" y="{byy+17}" font-size="10" fill="#a85d22" font-family="{MONO}">{plabel}</text>')
    # checkpointer + audit sidecars
    cy2=y+bh+86
    b.append(fbox(120,cy2,360,52,"Checkpointer · FileCheckpointer",["persist & resume long runs · CheckpointRecord"],mono=False,hdrfill="url(#door)",rects=R))
    b.append(fbox(520,cy2,360,52,"AuditLog family",["File · Logging · Otel · Queryable (AuditEntry)"],mono=False,hdrfill="url(#door)",rects=R))
    b.append(f'<text x="{W/2:.0f}" y="{H-22}" text-anchor="middle" font-size="10.5" font-style="italic" fill="{MUTED}">PipelineBuilder.chain(...) wires the DAG · AgentStep · ReasoningStep · CallableStep · BranchStep · BatchLLMStep · EmbeddingStep · RetrievalStep</text>')
    check("pipeline",R)
    (ASSETS/"pipeline.svg").write_text(svgdoc(W,H,"Firefly Agentic pipeline: a seven-phase IDP DAG with fan-out/fan-in, a human-in-the-loop pause, checkpointing and an audit log.","\n  ".join(b),amb=(860,64)))

# --------------------------------------------------------------------------- rag
def rag():
    W,H=1000,452; R=[]
    b=[title(W,"Retrieval-augmented — eight embedders × six vector stores, one API","EmbeddingProtocol and VectorStoreProtocol make providers and backends fully swappable.")]
    embs=["OpenAI","Azure OpenAI","Cohere","Google","Mistral","Voyage AI","AWS Bedrock","Ollama"]
    stores=["InMemory","ChromaDB","Pinecone","Qdrant","pgvector","sqlite-vec"]
    rh=24; rg=6; ey=112; lw=212; cardh=8*(rh+rg)+38
    def column(x,header,items,proto):
        b.append(fbox(x,ey,lw,cardh,header,[],rects=R))
        for i,it in enumerate(items):
            yy=ey+40+i*(rh+rg)
            b.append(f'<rect x="{x+12}" y="{yy-15}" width="{lw-24}" height="{rh}" rx="6" fill="{SUB}" stroke="{STROKE}"/>')
            b.append(f'<text x="{x+22}" y="{yy+1}" font-size="10.5" fill="{BODY}" font-family="{MONO}">{it}</text>')
        b.append(f'<text x="{x+lw/2:.0f}" y="{ey+cardh+16}" text-anchor="middle" font-size="9.5" fill="{MUTED}" font-family="{MONO}">{proto}</text>')
    lx=44; sx=W-44-lw
    column(lx,"EMBEDDERS",embs,"EmbeddingProtocol · BaseEmbedder")
    column(sx,"VECTOR STORES",stores,"VectorStoreProtocol · BaseVectorStore")
    # centre flow
    flow=[("text","raw documents"),("embed","BaseEmbedder"),("upsert","auto-embed"),("search_text","query · top_k"),("SearchResult","scored hits")]
    fw=156; fbh=40; fgap=12; fx=(W-fw)/2; cen=[]
    for i,(hdr,sub) in enumerate(flow):
        yy=ey+i*(fbh+fgap)
        b.append(fbox(fx,yy,fw,fbh,hdr,[sub],mono=False,rects=R)); cen.append(yy+fbh/2)
        if i<len(flow)-1: b.append(arrow(fx+fw/2,yy+fbh,fx+fw/2,yy+fbh+fgap,VIOLETD))
    b.append(arrow(lx+lw,ey+cardh/2,fx-3,cen[1],VIOLETD,dash="4 3"))         # embedders -> embed
    b.append(arrow(sx,ey+cardh/2,fx+fw+3,cen[3],INDIGO,dash="4 3",mk="arrb")) # stores -> search_text
    b.append(f'<text x="{W/2:.0f}" y="{H-18}" text-anchor="middle" font-size="10" font-style="italic" fill="{MUTED}">ScopedVectorStore / TenantScopedVectorStore isolate per tenant · EmbeddingStep / RetrievalStep drop straight into pipelines</text>')
    check("rag",R)
    (ASSETS/"rag.svg").write_text(svgdoc(W,H,"Firefly Agentic retrieval: eight embedding providers and six vector-store backends behind one API.","\n  ".join(b),amb=(500,64)))

# --------------------------------------------------------------------------- agent anatomy
def agent_anatomy():
    W,H=1000,500; R=[]
    b=[title(W,"Anatomy of an agent run — middleware all the way down","FireflyAgent wraps pydantic_ai.Agent; a composable MiddlewareChain wraps every run.")]
    # middleware chain wrapping the model call
    mids=["Logging","Observability","PromptGuard","OutputGuard","CostGuard","Cache","PromptCache","Explainability","Validation","Retry / CircuitBreaker"]
    cols=5; cw=176; cg=10; rgy=12; x0=(W-(cols*cw+(cols-1)*cg))/2; y0=170
    b.append(f'<text x="{W/2:.0f}" y="152" text-anchor="middle" font-size="11" font-weight="700" fill="{MID}" letter-spacing="0.06em">MiddlewareChain — wraps every agent.run()</text>')
    for i,m in enumerate(mids):
        cx=x0+(i%cols)*(cw+cg); cy=y0+(i//cols)*(46+rgy)
        b.append(f'<g filter="url(#sh)"><rect x="{cx:.1f}" y="{cy}" width="{cw}" height="46" rx="9" fill="{WHITE}" stroke="{VIOLET2}" stroke-width="1.6"/>'
                 f'<rect x="{cx:.1f}" y="{cy}" width="6" height="46" rx="3" fill="url(#hdr)"/></g>')
        b.append(f'<text x="{cx+18:.1f}" y="{cy+28}" font-size="11" font-weight="600" fill="{BODY}" font-family="{SANS}">{m}</text>')
        R.append((cx,cy,cx+cw,cy+46))
    # the wrapped core
    coy=y0+2*(46+rgy)+8; cwd=420; cox=(W-cwd)/2
    b.append(f'<g filter="url(#sh)"><rect x="{cox}" y="{coy}" width="{cwd}" height="58" rx="11" fill="url(#bed)"/></g>')
    b.append(firefly_mark(cox+30,coy+29,1.2))
    b.append(f'<text x="{cox+54}" y="{coy+25}" font-size="13" font-weight="800" fill="#efe8ff" font-family="{MONO}">FireflyAgent  -&gt;  pydantic_ai.Agent</text>')
    b.append(f'<text x="{cox+54}" y="{coy+43}" font-size="10.5" fill="#c3b6e6">the model call — tools, structured output, streaming</text>')
    b.append(arrow(W/2,y0+2*(46+rgy)-4,W/2,coy-2,VIOLETD))
    # side modules
    sy=coy+86; sw=300; sg=20; sx0=(W-(3*sw+2*sg))/2
    side=[("DelegationRouter","7 strategies route across an agent pool"),
          ("FallbackModelWrapper · ResultCache","automatic failover + response caching"),
          ("MemoryManager · AgentLifecycle","conversation + working memory · hooks")]
    for i,(hdr,sub) in enumerate(side):
        b.append(fbox(sx0+i*(sw+sg),sy,sw,52,hdr,[sub],mono=False,hdrfill="url(#door)",rects=R))
    check("agent-anatomy",R)
    (ASSETS/"agent-anatomy.svg").write_text(svgdoc(W,H,"Firefly Agentic agent anatomy: a FireflyAgent wrapping pydantic_ai.Agent inside a ten-stage middleware chain.","\n  ".join(b),amb=(840,64)))

# --------------------------------------------------------------------------- ecosystem
def ecosystem():
    W,H=1000,672; cx,cy=500,382; R=[]
    b=[title(W,"One framework, every runtime — the Firefly family","Firefly Agentic is the agentic member of a polyglot platform that shares one programming model.")]
    members=[("Java / Spring Boot","40+ modules · Production","springboot",False),(".NET","CalVer · Beta","dotnet",False),
             ("PyFly","Python · 39 modules","python",False),("Rust","tokio + axum · Active","rust",False),
             ("Go","CLI · Active","go",False),("Frontend","Angular · flyfront","angular",False),
             ("Agentic","agents · reasoning · RAG","__spark__",True)]
    n=len(members); rx,ry=372,240; angles=[-90+i*360/n for i in range(n)]; nodes=[]
    for (name,meta,ic,me),a in zip(members,angles):
        ar=math.radians(a); x=cx+rx*math.cos(ar); y=cy+ry*math.sin(ar)
        w=max(tw(name,12.5,True)+(34 if ic else 14),tw(meta,9)+(34 if ic else 14))+22; h=58 if not me else 62
        nodes.append([name,meta,ic,me,x,y,w,h])
    for name,meta,ic,me,x,y,w,h in nodes:
        b.append(f'<path d="M{cx+(x-cx)*0.16:.0f} {cy+(y-cy)*0.16:.0f} Q {(cx+x)/2:.0f} {(cy+y)/2-18:.0f} {x:.0f} {y:.0f}" fill="none" stroke="{VIOLET2}" stroke-width="1.2" stroke-dasharray="3 4" opacity="0.45"/>')
    b.append(f'<circle cx="{cx}" cy="{cy}" r="96" fill="url(#amb)"/>')
    b.append(f'<circle cx="{cx}" cy="{cy}" r="62" fill="{SUB}" stroke="{VIOLET2}" stroke-width="2"/>')
    b.append(firefly_mark(cx,cy-22,1.2))
    b.append(f'<text x="{cx}" y="{cy+4}" text-anchor="middle" font-size="13" font-weight="800" fill="{MID}">Firefly</text>')
    b.append(f'<text x="{cx}" y="{cy+21}" text-anchor="middle" font-size="13" font-weight="800" fill="{MID}">Framework</text>')
    b.append(f'<text x="{cx}" y="{cy+39}" text-anchor="middle" font-size="9" font-style="italic" fill="{MUTED}">one model · many runtimes</text>')
    for name,meta,ic,me,x,y,w,h in nodes:
        fill="url(#hdr)" if me else WHITE; tcol="#fff" if me else INK; scol="#ede7fb" if me else MUTED
        b.append(f'<g filter="url(#sh)"><rect x="{x-w/2:.1f}" y="{y-h/2:.1f}" width="{w:.1f}" height="{h}" rx="13" fill="{fill}" stroke="{VIOLET2}" stroke-width="{2.6 if me else 1.6}"/></g>')
        ix=x-w/2+22
        if ic=="__spark__": b.append(spark(ix,y,11,"#e0a528"))
        elif ic: b.append(icon(ic,ix,y,22))
        txt=x-w/2+(40 if ic else 16)
        b.append(f'<text x="{txt:.1f}" y="{y-3:.1f}" font-size="12.5" font-weight="800" fill="{tcol}">{name}</text>')
        b.append(f'<text x="{txt:.1f}" y="{y+13:.1f}" font-size="9" fill="{scol}" font-family="{MONO}">{meta}</text>')
        if me:
            lbl="you are here"; lw=tw(lbl,9.5,True); ytxt=y+h/2+15
            b.append(spark(x-lw/2-7,ytxt-3,5,"#e0a528"))
            b.append(f'<text x="{x:.1f}" y="{ytxt:.1f}" text-anchor="middle" font-size="9.5" font-weight="700" fill="{MID}">{lbl}</text>')
        R.append((x-w/2,y-h/2,x+w/2,y+h/2))
    check("ecosystem",R)
    (ASSETS/"ecosystem.svg").write_text(svgdoc(W,H,"The Firefly family: Java/Spring Boot, .NET, PyFly, Rust, Go, Angular frontend, and GenAI/Agentic (highlighted) around a shared core.","\n  ".join(b),amb=(cx,cy)))

def main():
    build_banner()
    for fn in (architecture,protocols,reasoning,pipeline,rag,agent_anatomy,ecosystem): fn()
    print("banner + 7 diagrams written to", ASSETS)
    print("WARNINGS:", *(WARN or ["none"]))

if __name__ == "__main__":
    main()
