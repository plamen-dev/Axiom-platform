"""Axiom Atlas — local-first, read-only visual map of the platform.

Renders existing artifacts (the newest execution-chain self-model, the
capability-evidence intake history, and the tracked evidence summaries under
``artifacts/validation_runs/``) into a single self-contained HTML page with an
interactive module-bubble graph and a capability/evidence panel.

Boundaries:

* read-only — never mutates confidence / readiness / promotion / capability
  state; it only *renders* what other engines already persisted;
* local-first — no external network calls, no CDN assets, no uploads; the
  page is plain vanilla JS/SVG served from disk or a stdlib HTTP server;
* no new evidence framework — the atlas is a viewer, not a producer.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ATLAS_SCHEMA_VERSION = "1.1"

TRAIL_LIMIT = 25


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _git_commit(repo_root: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        return None
    return out or None


def _newest_self_model(artifacts_root: Path) -> tuple[dict[str, Any] | None, str]:
    """Return (self_model dict, run_id) for the newest execution-chain run."""
    chain_dir = artifacts_root / "execution_chain"
    if not chain_dir.is_dir():
        return None, ""
    candidates = sorted(
        (p for p in chain_dir.glob("*/self_model.json") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        model = _load_json(path)
        if model is not None:
            return model, path.parent.name
    return None, ""


def _trail_entry(report: dict[str, Any]) -> dict[str, Any]:
    """Compact, render-ready view of one intake report (read-only)."""
    prior = report.get("prior_state") or {}
    updated = report.get("updated_state") or {}
    quality = report.get("evidence_quality") or {}
    promotion = report.get("promotion") or {}
    return {
        "intake_id": report.get("intake_id"),
        "created_at": report.get("created_at"),
        "decision": report.get("decision"),
        "quality_verdict": quality.get("verdict"),
        "before": {
            "confidence_level": prior.get("confidence_level"),
            "readiness": prior.get("readiness"),
            "score": prior.get("score"),
        },
        "after": {
            "confidence_level": updated.get("confidence_level"),
            "readiness": updated.get("readiness"),
            "score": updated.get("score"),
        },
        "state_changed": report.get("state_changed"),
        "promotion": {
            "raw_level": promotion.get("raw_level"),
            "effective_level": promotion.get("effective_level"),
            "clamped": promotion.get("clamped"),
        }
        if promotion
        else None,
    }


def _capability_states(artifacts_root: Path) -> list[dict[str, Any]]:
    """Latest per-capability state + intake trail from reports (read-only)."""
    intake_dir = artifacts_root / "capability_evidence_intake"
    if not intake_dir.is_dir():
        return []
    reports: dict[str, list[tuple[float, str, dict[str, Any]]]] = {}
    counts: dict[str, dict[str, int]] = {}
    for report_path in intake_dir.glob("*/report.json"):
        report = _load_json(report_path)
        if not report:
            continue
        capability = str(report.get("capability_id") or "unknown")
        decision = str(report.get("decision") or "unknown").lower()
        counts.setdefault(capability, {})
        counts[capability][decision] = counts[capability].get(decision, 0) + 1
        sort_key = (
            report_path.stat().st_mtime,
            str(report.get("created_at") or ""),
        )
        reports.setdefault(capability, []).append((*sort_key, report))

    capabilities: list[dict[str, Any]] = []
    for capability, entries in sorted(reports.items()):
        entries.sort(key=lambda e: (e[0], e[1]))
        latest = entries[-1][2]
        state = latest.get("updated_state") or latest.get("prior_state") or {}
        trail = [_trail_entry(r) for _, _, r in entries[-TRAIL_LIMIT:]]
        trail.reverse()  # newest first for display
        capabilities.append(
            {
                "capability_id": capability,
                "confidence_level": state.get("confidence_level"),
                "readiness": state.get("readiness"),
                "score": state.get("score"),
                "last_decision": latest.get("decision"),
                "last_intake_id": latest.get("intake_id"),
                "decision_counts": counts.get(capability, {}),
                "trail": trail,
            }
        )
    return capabilities


def _evidence_summaries(artifacts_root: Path) -> list[dict[str, Any]]:
    """Tracked evidence summaries (proof objects) under validation_runs."""
    runs_dir = artifacts_root / "validation_runs"
    if not runs_dir.is_dir():
        return []
    entries: list[tuple[float, dict[str, Any]]] = []
    for path in runs_dir.glob("*/evidence_summary.json"):
        summary = _load_json(path)
        if not summary:
            continue
        entries.append(
            (
                path.stat().st_mtime,
                {
                    "summary_id": summary.get("summary_id"),
                    "generated_at_utc": summary.get("generated_at_utc"),
                    "capability_id": summary.get("capability_id"),
                    "run_id": summary.get("run_id"),
                    "chain_status": summary.get("chain_status"),
                    "quality_verdict": summary.get("quality_verdict"),
                    "decision": summary.get("decision"),
                    "git_commit": summary.get("git_commit"),
                    "path": (
                        "artifacts/validation_runs/"
                        f"{path.parent.name}/evidence_summary.json"
                    ),
                },
            )
        )
    entries.sort(key=lambda e: e[0], reverse=True)
    return [entry for _, entry in entries]


def build_atlas_data(repo_root: str | Path) -> dict[str, Any]:
    """Assemble the read-only atlas payload from existing artifacts."""
    root = Path(repo_root)
    artifacts_root = root / "artifacts"

    self_model, run_id = _newest_self_model(artifacts_root)
    modules: list[str] = []
    edges: list[list[str]] = []
    metrics: dict[str, Any] = {}
    if self_model:
        raw_modules = self_model.get("modules") or []
        modules = [str(m) for m in raw_modules]
        raw_edges = self_model.get("edges") or []
        edges = [
            [str(e[0]), str(e[1])]
            for e in raw_edges
            if isinstance(e, (list, tuple)) and len(e) == 2
        ]
        metrics = self_model.get("metrics") or {}

    return {
        "schema_version": ATLAS_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(root),
        "self_model": {
            "source_run_id": run_id,
            "modules": modules,
            "edges": edges,
            "metrics": metrics,
        },
        "capabilities": _capability_states(artifacts_root),
        "evidence_summaries": _evidence_summaries(artifacts_root),
    }


def render_atlas_html(data: dict[str, Any]) -> str:
    """Render the self-contained atlas page (vanilla JS/SVG, no CDN)."""
    payload = json.dumps(data).replace("</", "<\\/")
    return _ATLAS_TEMPLATE.replace("__ATLAS_DATA__", payload)


def write_atlas(repo_root: str | Path) -> tuple[str, str]:
    """Write ``atlas.html`` + ``atlas_data.json``; return relative paths."""
    root = Path(repo_root)
    out_dir = root / "artifacts" / "atlas"
    out_dir.mkdir(parents=True, exist_ok=True)

    data = build_atlas_data(root)
    json_path = out_dir / "atlas_data.json"
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    html_path = out_dir / "atlas.html"
    html_path.write_text(render_atlas_html(data), encoding="utf-8")
    return (
        html_path.relative_to(root).as_posix(),
        json_path.relative_to(root).as_posix(),
    )


def serve_atlas(repo_root: str | Path, port: int = 8763) -> None:
    """Serve the atlas directory on localhost with a stdlib HTTP server.

    Regenerates the page once at startup, then serves static files only —
    artifacts created after startup (e.g. a new evidence summary) appear
    only after restarting the server or re-running ``axiom atlas``.
    Local-first: binds 127.0.0.1, no external calls. Blocks until Ctrl+C.
    """
    import http.server

    root = Path(repo_root)
    write_atlas(root)
    directory = str(root / "artifacts" / "atlas")

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    with http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler) as httpd:
        print(f"Axiom Atlas: http://127.0.0.1:{port}/atlas.html (Ctrl+C to stop)")
        print(
            "Static snapshot generated at startup; restart to pick up "
            "artifacts created after this point."
        )
        httpd.serve_forever()


_ATLAS_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Axiom Atlas</title>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --border: #30363d; --fg: #c9d1d9;
    --dim: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --yellow: #d29922; --red: #f85149; --gray: #6e7681;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 13px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif;
    display: flex; flex-direction: column; height: 100vh;
  }
  header {
    padding: 8px 16px; border-bottom: 1px solid var(--border);
    display: flex; align-items: baseline; gap: 16px; flex-shrink: 0;
  }
  header h1 { font-size: 16px; margin: 0; color: var(--accent); }
  header .meta { color: var(--dim); font-size: 12px; }
  #main { display: flex; flex: 1; min-height: 0; }
  #graph-wrap { flex: 1; position: relative; min-width: 0; }
  #graph { width: 100%; height: 100%; display: block; cursor: grab; }
  #tooltip {
    position: absolute; pointer-events: none; background: var(--panel);
    border: 1px solid var(--border); border-radius: 6px; padding: 6px 10px;
    font-size: 12px; display: none; z-index: 10; max-width: 340px;
  }
  #side {
    width: 380px; border-left: 1px solid var(--border); overflow-y: auto;
    background: var(--panel); padding: 12px; flex-shrink: 0;
  }
  #side h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .05em;
    color: var(--dim); margin: 14px 0 6px; }
  #side h2:first-child { margin-top: 0; }
  .cap, .summary {
    border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px;
    margin-bottom: 6px; background: var(--bg);
  }
  .cap .name { font-weight: 600; }
  .pill {
    display: inline-block; border-radius: 10px; padding: 0 8px; font-size: 11px;
    margin-left: 6px; color: #0d1117; font-weight: 600;
  }
  .pill.green { background: var(--green); } .pill.yellow { background: var(--yellow); }
  .pill.red { background: var(--red); } .pill.gray { background: var(--gray); color: var(--fg); }
  .kv { color: var(--dim); font-size: 12px; margin-top: 2px; }
  .kv b { color: var(--fg); font-weight: 500; }
  .cap { cursor: pointer; }
  .cap .hint { color: var(--dim); font-size: 11px; float: right; }
  .trail { display: none; margin-top: 6px; border-top: 1px solid var(--border); padding-top: 6px; }
  .cap.open .trail { display: block; }
  .trail-item { border-left: 2px solid var(--border); padding: 2px 0 2px 8px; margin-bottom: 4px; font-size: 12px; }
  .trail-item .when { color: var(--dim); font-size: 11px; }
  .arrow { color: var(--accent); }
  .clamp { color: var(--yellow); font-size: 11px; }
  code { color: var(--accent); font-size: 11px; word-break: break-all; }
  #legend { position: absolute; left: 12px; bottom: 12px; background: var(--panel);
    border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 12px; }
  #legend .dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%;
    margin-right: 6px; vertical-align: -1px; }
</style>
</head>
<body>
<header>
  <h1>Axiom Atlas</h1>
  <span class="meta" id="hdr-meta"></span>
</header>
<div id="main">
  <div id="graph-wrap">
    <svg id="graph"></svg>
    <div id="tooltip"></div>
    <div id="legend"></div>
  </div>
  <div id="side">
    <h2>Capabilities</h2>
    <div id="caps"></div>
    <h2>Captured evidence summaries</h2>
    <div id="summaries"></div>
  </div>
</div>
<script>
const DATA = __ATLAS_DATA__;

const COLORS = ["#58a6ff","#3fb950","#d29922","#f85149","#bc8cff","#39c5cf",
                "#ff7b72","#7ee787","#ffa657","#a5d6ff","#d2a8ff","#79c0ff"];
function esc(s){ const d=document.createElement("div"); d.textContent=String(s??""); return d.innerHTML; }

// Header
const m = DATA.self_model.metrics || {};
document.getElementById("hdr-meta").textContent =
  `commit ${DATA.git_commit||"?"} · generated ${DATA.generated_at_utc} · ` +
  `${(DATA.self_model.modules||[]).length} modules · ${(DATA.self_model.edges||[]).length} import edges` +
  (DATA.self_model.source_run_id ? ` · self-model run ${DATA.self_model.source_run_id}` : "");

// --- Capability panel ---
function pillClass(level, readiness){
  if (readiness === "ready" || level === "very_high" || level === "high") return "green";
  if (level === "medium") return "yellow";
  if (level === "low" || level === "very_low" || readiness === "blocked") return "red";
  return "gray";
}
const capsEl = document.getElementById("caps");
if (!DATA.capabilities.length) capsEl.innerHTML = '<div class="kv">No capability intake records yet.</div>';
function trailHtml(t){
  const b=t.before||{}, a=t.after||{};
  const move = `${esc(b.confidence_level||"?")}/${esc(b.readiness||"?")} <span class="arrow">→</span> ${esc(a.confidence_level||"?")}/${esc(a.readiness||"?")}`;
  const clamp = t.promotion && t.promotion.clamped
    ? ` <span class="clamp">clamped (raw ${esc(t.promotion.raw_level)} → effective ${esc(t.promotion.effective_level)})</span>` : "";
  return `
    <div class="trail-item">
      <b>${esc(t.decision||"?")}</b> · ${esc(t.quality_verdict||"?")} · ${move}${clamp}
      <div class="kv">score ${esc(b.score)} → ${esc(a.score)} · intake <code>${esc((t.intake_id||"").slice(0,8))}</code></div>
      <div class="when">${esc(t.created_at||"")}</div>
    </div>`;
}
for (const c of DATA.capabilities){
  const cls = pillClass(c.confidence_level, c.readiness);
  const counts = Object.entries(c.decision_counts||{}).map(([k,v])=>`${k}: ${v}`).join(", ");
  const trail = (c.trail||[]).map(trailHtml).join("");
  const el = document.createElement("div");
  el.className = "cap";
  el.innerHTML = `
      <span class="hint">${(c.trail||[]).length} intake(s) ▾</span>
      <span class="name">${esc(c.capability_id)}</span>
      <span class="pill ${cls}">${esc(c.confidence_level||"?")} / ${esc(c.readiness||"?")}</span>
      <div class="kv">score <b>${esc(c.score)}</b> · last decision <b>${esc(c.last_decision)}</b></div>
      <div class="kv">intakes — ${esc(counts||"none")}</div>
      <div class="trail">${trail || '<div class="kv">no intake records</div>'}</div>`;
  el.addEventListener("click", ()=> el.classList.toggle("open"));
  capsEl.appendChild(el);
}

// --- Evidence summaries panel ---
const sumEl = document.getElementById("summaries");
if (!DATA.evidence_summaries.length) sumEl.innerHTML = '<div class="kv">No tracked summaries yet — run emit_evidence_summary.</div>';
for (const s of DATA.evidence_summaries){
  const cls = s.quality_verdict === "SUBSTANTIVE" ? "green" :
              s.quality_verdict === "EMPTY" ? "red" : "gray";
  sumEl.insertAdjacentHTML("beforeend", `
    <div class="summary">
      <span class="name">${esc(s.capability_id||"?")}</span>
      <span class="pill ${cls}">${esc(s.quality_verdict||"?")}</span>
      <span class="pill ${s.decision==="accepted"?"green":s.decision==="quarantined"?"red":"gray"}">${esc(s.decision||"?")}</span>
      <div class="kv">chain <b>${esc(s.chain_status)}</b> · run <b>${esc((s.run_id||"").slice(0,8))}</b> · commit <b>${esc(s.git_commit)}</b></div>
      <div class="kv">${esc(s.generated_at_utc||"")}</div>
      <div class="kv"><code>${esc(s.path)}</code></div>
    </div>`);
}

// --- Module bubble graph (vanilla force layout, SVG) ---
const svg = document.getElementById("graph");
const tooltip = document.getElementById("tooltip");
const wrap = document.getElementById("graph-wrap");
const NS = "http://www.w3.org/2000/svg";

const modules = DATA.self_model.modules || [];
const edges = DATA.self_model.edges || [];
const idx = new Map(modules.map((m,i)=>[m,i]));
const degree = new Array(modules.length).fill(0);
const links = [];
for (const [a,b] of edges){
  if (idx.has(a) && idx.has(b)) {
    links.push([idx.get(a), idx.get(b)]);
    degree[idx.get(a)]++; degree[idx.get(b)]++;
  }
}
const groupOf = name => name.split(".")[0];
const groups = [...new Set(modules.map(groupOf))].sort();
const groupColor = new Map(groups.map((g,i)=>[g, COLORS[i % COLORS.length]]));

// legend
document.getElementById("legend").innerHTML =
  groups.map(g=>`<div><span class="dot" style="background:${groupColor.get(g)}"></span>${esc(g)}</div>`).join("");

let W = wrap.clientWidth || 800, H = wrap.clientHeight || 600;
svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

const N = modules.length;
const nodes = modules.map((name,i)=>({
  name, i, g: groupOf(name),
  r: 4 + Math.min(14, Math.sqrt(degree[i]) * 2.2),
  x: W/2 + Math.cos(i/N*2*Math.PI)*(Math.min(W,H)/3) + (Math.random()-0.5)*40,
  y: H/2 + Math.sin(i/N*2*Math.PI)*(Math.min(W,H)/3) + (Math.random()-0.5)*40,
  vx: 0, vy: 0,
}));

const edgeGroup = document.createElementNS(NS,"g");
const nodeGroup = document.createElementNS(NS,"g");
svg.appendChild(edgeGroup); svg.appendChild(nodeGroup);
const lineEls = links.map(()=> {
  const l = document.createElementNS(NS,"line");
  l.setAttribute("stroke","#30363d"); l.setAttribute("stroke-opacity","0.45");
  edgeGroup.appendChild(l); return l;
});
const circleEls = nodes.map(n=>{
  const c = document.createElementNS(NS,"circle");
  c.setAttribute("r", n.r);
  c.setAttribute("fill", groupColor.get(n.g));
  c.setAttribute("fill-opacity","0.85");
  c.setAttribute("stroke","#0d1117");
  c.addEventListener("mouseenter", e=>{
    tooltip.style.display="block";
    tooltip.innerHTML = `<b>${esc(n.name)}</b><br>${degree[n.i]} import edge(s) · group ${esc(n.g)}`;
    highlight(n.i);
  });
  c.addEventListener("mousemove", e=>{
    const r = wrap.getBoundingClientRect();
    tooltip.style.left = (e.clientX - r.left + 14) + "px";
    tooltip.style.top = (e.clientY - r.top + 8) + "px";
  });
  c.addEventListener("mouseleave", ()=>{ tooltip.style.display="none"; highlight(-1); });
  nodeGroup.appendChild(c); return c;
});
function highlight(i){
  links.forEach(([a,b],k)=>{
    const on = (i>=0 && (a===i || b===i));
    lineEls[k].setAttribute("stroke", on ? "#58a6ff" : "#30363d");
    lineEls[k].setAttribute("stroke-opacity", on ? "0.9" : "0.45");
  });
}

// simple force simulation
let alpha = 1;
function tick(){
  // link attraction
  for (const [a,b] of links){
    const na=nodes[a], nb=nodes[b];
    const dx=nb.x-na.x, dy=nb.y-na.y;
    const d=Math.max(1, Math.hypot(dx,dy));
    const f=(d-60)*0.004*alpha;
    na.vx+=dx/d*f; na.vy+=dy/d*f; nb.vx-=dx/d*f; nb.vy-=dy/d*f;
  }
  // charge repulsion (grid-bucketed approximation)
  for (let i=0;i<nodes.length;i++){
    for (let j=i+1;j<nodes.length;j++){
      const na=nodes[i], nb=nodes[j];
      const dx=nb.x-na.x, dy=nb.y-na.y;
      const d2=dx*dx+dy*dy;
      if (d2 > 22500) continue;
      const d=Math.max(6, Math.sqrt(d2));
      const f=280/(d*d)*alpha;
      na.vx-=dx/d*f; na.vy-=dy/d*f; nb.vx+=dx/d*f; nb.vy+=dy/d*f;
    }
  }
  for (const n of nodes){
    // centering + integrate
    n.vx += (W/2-n.x)*0.0012*alpha; n.vy += (H/2-n.y)*0.0012*alpha;
    n.x += n.vx; n.y += n.vy; n.vx*=0.85; n.vy*=0.85;
    n.x = Math.max(n.r, Math.min(W-n.r, n.x));
    n.y = Math.max(n.r, Math.min(H-n.r, n.y));
  }
  links.forEach(([a,b],k)=>{
    lineEls[k].setAttribute("x1",nodes[a].x); lineEls[k].setAttribute("y1",nodes[a].y);
    lineEls[k].setAttribute("x2",nodes[b].x); lineEls[k].setAttribute("y2",nodes[b].y);
  });
  nodes.forEach((n,i)=>{
    circleEls[i].setAttribute("cx",n.x); circleEls[i].setAttribute("cy",n.y);
  });
  alpha *= 0.995;
  if (alpha > 0.02) requestAnimationFrame(tick);
}
if (nodes.length) requestAnimationFrame(tick);
else {
  const t = document.createElementNS(NS,"text");
  t.setAttribute("x",W/2); t.setAttribute("y",H/2);
  t.setAttribute("fill","#8b949e"); t.setAttribute("text-anchor","middle");
  t.textContent = "No self-model yet — run: axiom execution-chain-run";
  svg.appendChild(t);
}
</script>
</body>
</html>
"""
