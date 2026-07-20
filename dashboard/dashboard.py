"""Dashboard HTML UI — served by :mod:`dashboard.app`."""

from __future__ import annotations

from dashboard.standalone_ui import panel_css, panel_html, panel_script


def render_dashboard(*, mode: str = "manual") -> str:
    mode = "standalone" if mode == "standalone" else "manual"
    title = (
        "DriveAuth Edge — Standalone Pay"
        if mode == "standalone"
        else "DriveAuth Edge — Manual Pipeline"
    )
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__PAGE_TITLE__</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Sora:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg0: #060a10;
      --bg1: #0b1220;
      --panel: rgba(14, 22, 36, 0.82);
      --panel-solid: #0e1624;
      --border: #243247;
      --border-bright: #35506e;
      --text: #e7eef8;
      --muted: #8fa3bc;
      --faint: #5d7290;
      --cyan: #2dd4bf;
      --cyan-dim: rgba(45, 212, 191, 0.14);
      --sky: #38bdf8;
      --violet: #818cf8;
      --manual: #a5b4fc;
      --accept: #34d399;
      --stepup: #fbbf24;
      --reject: #f87171;
      --risk: #fb7185;
      --glow: 0 0 40px rgba(45, 212, 191, 0.12);
      --radius: 14px;
      --font: "Sora", system-ui, sans-serif;
      --mono: "IBM Plex Mono", ui-monospace, monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; }
    body {
      font-family: var(--font);
      color: var(--text);
      min-height: 100vh;
      background:
        radial-gradient(ellipse 900px 420px at 12% -8%, rgba(45, 212, 191, 0.16), transparent 55%),
        radial-gradient(ellipse 700px 380px at 92% 0%, rgba(56, 189, 248, 0.12), transparent 50%),
        radial-gradient(ellipse 600px 400px at 70% 100%, rgba(129, 140, 248, 0.08), transparent 45%),
        linear-gradient(180deg, var(--bg1), var(--bg0));
      line-height: 1.5;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(143, 163, 188, 0.045) 1px, transparent 1px),
        linear-gradient(90deg, rgba(143, 163, 188, 0.045) 1px, transparent 1px);
      background-size: 48px 48px;
      mask-image: radial-gradient(ellipse 80% 70% at 50% 30%, black, transparent);
      z-index: 0;
    }
    .wrap { position: relative; z-index: 1; }

    header {
      padding: 1.1rem 1.5rem;
      border-bottom: 1px solid rgba(36, 50, 71, 0.9);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
      backdrop-filter: blur(14px);
      background: rgba(6, 10, 16, 0.7);
      position: sticky;
      top: 0;
      z-index: 20;
    }
    .brand { display: flex; align-items: center; gap: 0.85rem; }
    .logo {
      width: 42px; height: 42px;
      border-radius: 12px;
      background:
        linear-gradient(145deg, rgba(45,212,191,0.35), rgba(56,189,248,0.15)),
        var(--panel-solid);
      border: 1px solid rgba(45, 212, 191, 0.35);
      display: grid; place-items: center;
      box-shadow: var(--glow);
      font-family: var(--mono);
      font-weight: 600;
      font-size: 0.72rem;
      letter-spacing: 0.04em;
      color: var(--cyan);
    }
    header h1 {
      font-size: 1.2rem;
      font-weight: 700;
      letter-spacing: -0.03em;
      line-height: 1.15;
    }
    header h1 span { color: var(--cyan); }
    header .sub { color: var(--muted); font-size: 0.78rem; margin-top: 0.15rem; }
    .header-right {
      display: flex; align-items: center; gap: 0.65rem; flex-wrap: wrap;
    }
    .nav-link {
      color: var(--sky);
      text-decoration: none;
      font-size: 0.82rem;
      font-weight: 500;
      border: 1px solid var(--border);
      padding: 0.42rem 0.8rem;
      border-radius: 999px;
      background: var(--panel);
      transition: border-color 0.2s, background 0.2s;
    }
    .nav-link:hover { border-color: var(--sky); background: rgba(56,189,248,0.08); }
    #status-bar { font-size: 0.78rem; color: var(--muted); max-width: 420px; }
    #status-bar code {
      font-family: var(--mono);
      font-size: 0.72rem;
      color: #c4d4f0;
      background: rgba(0,0,0,0.3);
      padding: 0.1rem 0.35rem;
      border-radius: 4px;
    }
    .badge {
      display: inline-block;
      padding: 0.15rem 0.5rem;
      border-radius: 999px;
      font-size: 0.68rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      background: var(--panel);
      border: 1px solid var(--border);
      color: var(--muted);
    }
    .badge.ok { color: var(--accept); border-color: rgba(52,211,153,0.4); }
    .badge.warn { color: var(--stepup); border-color: rgba(251,191,36,0.4); }

    .page {
      max-width: 1680px;
      margin: 0 auto;
      padding: 1.1rem 1.35rem 2.5rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }

    /* Shipped strip */
    .shipped {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 1rem;
      align-items: stretch;
    }
    @media (max-width: 900px) {
      .shipped { grid-template-columns: 1fr; }
    }
    .shipped-intro {
      min-width: 180px;
      padding: 1rem 1.1rem;
      border-radius: var(--radius);
      border: 1px solid rgba(45, 212, 191, 0.28);
      background: linear-gradient(160deg, rgba(45,212,191,0.12), rgba(14,22,36,0.9));
      box-shadow: var(--glow);
    }
    .shipped-intro h2 {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--cyan);
      margin-bottom: 0.35rem;
    }
    .shipped-intro strong {
      display: block;
      font-size: 1.35rem;
      letter-spacing: -0.03em;
      margin-bottom: 0.25rem;
    }
    .shipped-intro p { font-size: 0.78rem; color: var(--muted); }
    .phase-strip {
      display: flex;
      gap: 0.45rem;
      overflow-x: auto;
      padding: 0.15rem;
      scrollbar-width: thin;
    }
    .phase {
      flex: 1 0 110px;
      min-width: 110px;
      padding: 0.7rem 0.75rem;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: var(--panel);
      position: relative;
      overflow: hidden;
      transition: transform 0.2s, border-color 0.2s;
    }
    .phase:hover { transform: translateY(-2px); border-color: var(--border-bright); }
    .phase.done {
      border-color: rgba(52, 211, 153, 0.35);
      background: linear-gradient(180deg, rgba(52,211,153,0.1), var(--panel));
    }
    .phase.partial {
      border-color: rgba(251, 191, 36, 0.35);
      background: linear-gradient(180deg, rgba(251,191,36,0.08), var(--panel));
    }
    .phase .ph-id {
      font-family: var(--mono);
      font-size: 0.65rem;
      color: var(--faint);
      margin-bottom: 0.25rem;
    }
    .phase .ph-title {
      font-size: 0.78rem;
      font-weight: 600;
      letter-spacing: -0.02em;
      margin-bottom: 0.35rem;
    }
    .phase .ph-state {
      font-size: 0.65rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .phase.done .ph-state { color: var(--accept); }
    .phase.partial .ph-state { color: var(--stepup); }

    /* Sources box */
    .sources-box {
      border-radius: var(--radius);
      border: 1px solid rgba(56, 189, 248, 0.3);
      background:
        linear-gradient(135deg, rgba(56,189,248,0.08), transparent 40%),
        var(--panel);
      padding: 1.1rem 1.2rem 1.2rem;
      box-shadow: 0 0 50px rgba(56, 189, 248, 0.06);
    }
    .sources-box > header {
      all: unset;
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-bottom: 0.85rem;
    }
    .sources-box > header h2 {
      font-size: 0.95rem;
      font-weight: 650;
      letter-spacing: -0.02em;
    }
    .sources-box > header p {
      font-size: 0.75rem;
      color: var(--muted);
    }
    .source-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 0.55rem;
    }
    @media (max-width: 1200px) { .source-grid { grid-template-columns: repeat(2, 1fr); } }
    @media (max-width: 640px) { .source-grid { grid-template-columns: 1fr; } }
    .source-card {
      border: 1px solid var(--border);
      border-radius: 12px;
      background: rgba(6, 10, 16, 0.55);
      padding: 0.75rem 0.8rem;
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      transition: border-color 0.25s, box-shadow 0.25s;
    }
    .source-card.active-trust {
      border-color: rgba(45, 212, 191, 0.55);
      box-shadow: 0 0 0 1px rgba(45,212,191,0.15), 0 0 24px rgba(45,212,191,0.12);
    }
    .source-card.active-risk {
      border-color: rgba(251, 113, 133, 0.5);
      box-shadow: 0 0 0 1px rgba(251,113,133,0.12), 0 0 24px rgba(251,113,133,0.1);
    }
    .source-card .sc-top {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.4rem;
    }
    .source-card .sc-name {
      font-size: 0.82rem;
      font-weight: 600;
    }
    .source-card .sc-lane {
      font-size: 0.62rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      padding: 0.12rem 0.4rem;
      border-radius: 999px;
      border: 1px solid var(--border);
    }
    .source-card .sc-lane.trust { color: var(--cyan); border-color: rgba(45,212,191,0.4); background: var(--cyan-dim); }
    .source-card .sc-lane.risk { color: var(--risk); border-color: rgba(251,113,133,0.4); background: rgba(251,113,133,0.1); }
    .source-card .sc-lane.both { color: var(--violet); border-color: rgba(129,140,248,0.4); background: rgba(129,140,248,0.1); }
    .source-card .sc-input {
      font-family: var(--mono);
      font-size: 0.68rem;
      color: #c4d4f0;
    }
    .source-card .sc-source {
      font-size: 0.72rem;
      color: var(--muted);
      line-height: 1.35;
    }
    .source-card .sc-source strong { color: var(--sky); font-weight: 600; }
    .source-card .sc-now {
      font-family: var(--mono);
      font-size: 0.68rem;
      color: var(--faint);
      margin-top: 0.15rem;
    }
    .source-card .sc-now em { color: var(--manual); font-style: normal; }

    /* Main grid */
    .main-grid {
      display: grid;
      grid-template-columns: 300px minmax(0, 1.35fr) 300px;
      gap: 1rem;
      align-items: start;
    }
    @media (max-width: 1280px) {
      .main-grid { grid-template-columns: 1fr 1fr; }
      .pipeline-col { grid-column: 1 / -1; order: -1; }
    }
    @media (max-width: 780px) {
      .main-grid { grid-template-columns: 1fr; }
    }
    .col-stack { display: flex; flex-direction: column; gap: 0.85rem; }

    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 1rem 1.05rem;
      backdrop-filter: blur(8px);
    }
    .panel.manual {
      border-color: rgba(165, 180, 252, 0.35);
      box-shadow: inset 0 0 0 1px rgba(165, 180, 252, 0.08);
    }
    .panel h2 {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 0.35rem;
    }
    .panel .hint {
      font-size: 0.72rem;
      color: var(--faint);
      margin-bottom: 0.7rem;
      line-height: 1.4;
    }
    .panel.manual h2 { color: var(--manual); }
    label {
      display: block;
      font-size: 0.76rem;
      color: var(--muted);
      margin: 0.5rem 0 0.22rem;
    }
    input, select {
      width: 100%;
      padding: 0.48rem 0.65rem;
      border-radius: 8px;
      border: 1px solid var(--border);
      background: rgba(6, 10, 16, 0.75);
      color: var(--text);
      font-size: 0.88rem;
      font-family: var(--font);
    }
    input:focus, select:focus, button:focus-visible {
      outline: 2px solid rgba(45, 212, 191, 0.55);
      outline-offset: 1px;
    }
    input[type="range"] { padding: 0; accent-color: var(--cyan); }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
    .checkbox-row {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      margin-top: 0.5rem;
    }
    .checkbox-row input { width: auto; }
    button {
      cursor: pointer;
      border: none;
      border-radius: 9px;
      padding: 0.55rem 0.9rem;
      font-size: 0.82rem;
      font-weight: 600;
      font-family: var(--font);
      margin-top: 0.65rem;
      margin-right: 0.35rem;
      transition: transform 0.15s, filter 0.15s, background 0.15s;
    }
    button:hover { filter: brightness(1.08); }
    button:active { transform: scale(0.98); }
    .btn-primary {
      background: linear-gradient(135deg, #14b8a6, #0ea5e9);
      color: #031018;
      box-shadow: 0 8px 24px rgba(45, 212, 191, 0.22);
    }
    .btn-secondary { background: #1a273a; color: var(--text); border: 1px solid var(--border); }
    .btn-danger { background: #7f1d1d; color: #fecaca; }
    .scenario-btn {
      display: block;
      width: 100%;
      text-align: left;
      background: rgba(6, 10, 16, 0.6);
      color: var(--text);
      border: 1px solid var(--border);
      margin-top: 0.35rem;
      font-weight: 500;
    }
    .scenario-btn:hover { border-color: var(--cyan); }

    /* Live pipeline */
    .pipeline-panel {
      border-color: rgba(45, 212, 191, 0.28);
      background:
        linear-gradient(180deg, rgba(45,212,191,0.07), transparent 28%),
        var(--panel);
      min-height: 520px;
    }
    .pipeline-head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 0.75rem;
      margin-bottom: 1rem;
      flex-wrap: wrap;
    }
    .pipeline-head h2 {
      font-size: 0.95rem;
      text-transform: none;
      letter-spacing: -0.02em;
      color: var(--text);
      font-weight: 650;
    }
    .pipeline-head .live-pill {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.68rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--cyan);
      border: 1px solid rgba(45,212,191,0.35);
      background: var(--cyan-dim);
      padding: 0.28rem 0.65rem;
      border-radius: 999px;
    }
    .pipeline-head .live-pill .dot {
      width: 7px; height: 7px;
      border-radius: 50%;
      background: var(--cyan);
      box-shadow: 0 0 10px var(--cyan);
      animation: pulse-dot 1.2s ease-in-out infinite;
    }
    .pipeline-head .live-pill.idle { color: var(--muted); border-color: var(--border); background: transparent; }
    .pipeline-head .live-pill.idle .dot { background: var(--faint); box-shadow: none; animation: none; }
    .pipeline-head .live-pill.running { color: var(--sky); }
    @keyframes pulse-dot {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.45; transform: scale(0.75); }
    }
    #path-summary {
      font-family: var(--mono);
      font-size: 0.78rem;
      color: var(--muted);
      margin-bottom: 1rem;
      min-height: 1.2em;
    }
    #path-summary strong { color: var(--text); }

    .flow {
      display: flex;
      flex-direction: column;
      gap: 0;
      position: relative;
    }
    .flow-stage {
      display: grid;
      grid-template-columns: 28px 1fr;
      gap: 0.75rem;
      opacity: 0.45;
      transform: translateX(-4px);
      transition: opacity 0.35s, transform 0.35s, filter 0.35s;
      filter: grayscale(0.4);
    }
    .flow-stage.on {
      opacity: 1;
      transform: none;
      filter: none;
    }
    .flow-stage.active {
      opacity: 1;
      filter: none;
    }
    .flow-rail {
      display: flex;
      flex-direction: column;
      align-items: center;
    }
    .flow-node {
      width: 16px; height: 16px;
      border-radius: 50%;
      border: 2px solid var(--border-bright);
      background: var(--bg0);
      margin-top: 0.55rem;
      position: relative;
      z-index: 1;
      transition: border-color 0.3s, background 0.3s, box-shadow 0.3s;
    }
    .flow-stage.on .flow-node,
    .flow-stage.active .flow-node {
      border-color: var(--cyan);
      background: var(--cyan);
      box-shadow: 0 0 16px rgba(45, 212, 191, 0.55);
    }
    .flow-stage.accept .flow-node { border-color: var(--accept); background: var(--accept); box-shadow: 0 0 16px rgba(52,211,153,0.55); }
    .flow-stage.stepup .flow-node { border-color: var(--stepup); background: var(--stepup); box-shadow: 0 0 16px rgba(251,191,36,0.5); }
    .flow-stage.hold .flow-node { border-color: var(--stepup); background: transparent; box-shadow: none; opacity: 0.55; }
    .flow-stage.block .flow-node,
    .flow-stage.reject .flow-node { border-color: var(--reject); background: var(--reject); box-shadow: 0 0 16px rgba(248,113,113,0.5); }
    .flow-line {
      flex: 1;
      width: 2px;
      min-height: 18px;
      background: linear-gradient(180deg, var(--border-bright), transparent);
      margin: 4px 0;
    }
    .flow-stage:last-child .flow-line { display: none; }
    .flow-card {
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 0.7rem 0.85rem;
      background: rgba(6, 10, 16, 0.55);
      margin-bottom: 0.55rem;
      transition: border-color 0.3s, background 0.3s;
    }
    .flow-stage.on .flow-card,
    .flow-stage.active .flow-card {
      border-color: rgba(45, 212, 191, 0.4);
      background: rgba(45, 212, 191, 0.06);
    }
    .flow-stage.accept .flow-card { border-color: rgba(52,211,153,0.45); background: rgba(52,211,153,0.08); }
    .flow-stage.stepup .flow-card { border-color: rgba(251,191,36,0.45); background: rgba(251,191,36,0.08); }
    .flow-stage.hold .flow-card { border-color: rgba(251,191,36,0.25); background: transparent; opacity: 0.55; }
    .flow-stage.block .flow-card,
    .flow-stage.reject .flow-card { border-color: rgba(248,113,113,0.45); background: rgba(248,113,113,0.08); }
    .flow-card .fc-title {
      font-size: 0.82rem;
      font-weight: 650;
      letter-spacing: -0.02em;
      display: flex;
      justify-content: space-between;
      gap: 0.5rem;
    }
    .flow-card .fc-status {
      font-size: 0.65rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--faint);
    }
    .flow-stage.on .fc-status,
    .flow-stage.active .fc-status { color: var(--cyan); }
    .flow-stage.accept .fc-status { color: var(--accept); }
    .flow-stage.stepup .fc-status { color: var(--stepup); }
    .flow-stage.hold .fc-status { color: var(--faint); }
    .flow-stage.block .fc-status,
    .flow-stage.reject .fc-status { color: var(--reject); }
    .flow-card .fc-detail {
      font-family: var(--mono);
      font-size: 0.7rem;
      color: var(--muted);
      margin-top: 0.25rem;
    }

    /* Escalation staircase — Voice (bottom) → Face → Finger (top) */
    .stair {
      margin-top: 0.75rem;
      padding: 0.65rem 0.55rem 0.55rem;
      border-radius: 12px;
      border: 1px solid rgba(45, 212, 191, 0.18);
      background:
        linear-gradient(165deg, rgba(45,212,191,0.05), transparent 55%),
        rgba(0, 0, 0, 0.28);
    }
    .stair-caption {
      font-size: 0.65rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--cyan);
      margin: 0 0.25rem 0.55rem;
    }
    .stair-steps {
      display: flex;
      flex-direction: column-reverse; /* voice sits on the lowest tread */
      gap: 0;
      align-items: stretch;
    }
    .stair-riser {
      display: flex;
      align-items: center;
      gap: 0.35rem;
      height: 18px;
      margin-left: var(--indent, 0);
      opacity: 0.25;
      transition: opacity 0.3s, color 0.3s;
      color: var(--faint);
      font-size: 0.6rem;
      font-family: var(--mono);
      letter-spacing: 0.04em;
    }
    .stair-riser.on {
      opacity: 1;
      color: var(--stepup);
    }
    .stair-riser .arrow {
      color: inherit;
      font-size: 0.85rem;
      line-height: 1;
      transform: translateY(-1px);
    }
    .stair-step {
      --indent: 0%;
      position: relative;
      margin-left: var(--indent);
      width: calc(100% - var(--indent));
      border-radius: 10px 12px 10px 10px;
      border: 1px solid var(--border);
      border-left-width: 3px;
      border-left-color: var(--border-bright);
      padding: 0.55rem 0.65rem 0.5rem;
      background: rgba(6, 10, 16, 0.65);
      opacity: 0.38;
      transform: translateX(-6px);
      transition: opacity 0.35s, border-color 0.35s, background 0.35s, transform 0.35s, box-shadow 0.35s;
      box-shadow: 4px 4px 0 rgba(0,0,0,0.22);
    }
    .stair-step[data-rung="voice"]  { --indent: 0%; }
    .stair-step[data-rung="face"]   { --indent: 14%; }
    .stair-step[data-rung="stage3"] { --indent: 28%; }
    .stair-riser[data-after="voice"] { --indent: 7%; }
    .stair-riser[data-after="face"]  { --indent: 21%; }
    .stage3-lanes {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0.45rem;
      margin-top: 0.45rem;
    }
    .stair-sub {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.45rem 0.5rem;
      background: rgba(0,0,0,0.25);
      opacity: 0.45;
      transition: opacity 0.3s, border-color 0.3s, background 0.3s, box-shadow 0.3s;
    }
    .stair-sub.on { opacity: 1; }
    .stair-sub.probing {
      opacity: 1;
      border-color: rgba(56, 189, 248, 0.55);
      background: rgba(56, 189, 248, 0.1);
      animation: stair-pulse 0.9s ease-in-out infinite;
    }
    .stair-sub.accept {
      border-color: rgba(52,211,153,0.55);
      background: rgba(52,211,153,0.12);
      box-shadow: 0 0 12px rgba(52,211,153,0.2);
    }
    .stair-sub.escalate {
      border-color: rgba(251,191,36,0.5);
      background: rgba(251,191,36,0.1);
    }
    .stair-sub.reject, .stair-sub.unavailable {
      border-color: rgba(248,113,113,0.45);
      background: rgba(248,113,113,0.08);
    }
    .stair-sub.not_attempted, .stair-sub.skipped, .stair-sub.locked {
      opacity: 0.35;
      border-style: dashed;
    }
    .stair-sub .s-top { margin-bottom: 0.15rem; }
    .stair-sub .s-label { font-size: 0.72rem; }
    .stair-sub .s-score { font-size: 0.85rem; }
    .stair-sub .s-detail { font-size: 0.62rem; min-height: 1.4em; }
    .stage3-or {
      grid-column: 1 / -1;
      text-align: center;
      font-family: var(--mono);
      font-size: 0.65rem;
      color: var(--faint);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      opacity: 0.5;
      transition: opacity 0.3s, color 0.3s;
    }
    .stage3-or.on {
      opacity: 1;
      color: var(--stepup);
    }
    .stage3-or.fallback {
      color: var(--stepup);
      animation: stair-pulse 0.8s ease-in-out 2;
    }
    .mod-badge {
      display: inline-block;
      margin-left: 0.35rem;
      padding: 0.08rem 0.4rem;
      border-radius: 999px;
      font-size: 0.58rem;
      font-family: var(--mono);
      font-weight: 500;
      letter-spacing: 0.02em;
      border: 1px solid var(--border);
      color: var(--muted);
      vertical-align: middle;
    }
    .mod-badge.real { color: var(--accept); border-color: rgba(52,211,153,0.4); }
    .mod-badge.daemon { color: var(--sky); border-color: rgba(56,189,248,0.4); }
    .mod-badge.standin { color: var(--stepup); border-color: rgba(251,191,36,0.4); }
    .pitch-banner {
      margin: 0 0 0.85rem;
      padding: 0.55rem 0.85rem;
      border: 1px solid rgba(45, 212, 191, 0.35);
      border-radius: 10px;
      background: rgba(45, 212, 191, 0.07);
      font-size: 0.82rem;
      color: var(--text);
      line-height: 1.35;
    }
    .pitch-banner strong { color: var(--cyan); font-weight: 600; }
    .scenario-row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      margin-bottom: 0.85rem;
    }
    .scenario-row .scenario-btn {
      font-size: 0.72rem;
      padding: 0.4rem 0.65rem;
    }
    .driver-callout {
      margin: 0.55rem 0 0.35rem;
      padding: 0.45rem 0.65rem;
      border-radius: 8px;
      border: 1px solid var(--border);
      font-size: 0.78rem;
      font-weight: 600;
      background: rgba(0,0,0,0.25);
    }
    .driver-callout.trust { border-color: rgba(52,211,153,0.45); color: var(--accept); }
    .driver-callout.risk { border-color: rgba(248,113,113,0.45); color: var(--reject); }
    .driver-callout.fraud { border-color: rgba(248,113,113,0.55); color: var(--reject); }
    .driver-callout.policy { border-color: rgba(251,191,36,0.45); color: var(--stepup); }
    .policy-tags { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.45rem; }
    .policy-tags .tag {
      background: rgba(251,191,36,0.12);
      border-color: rgba(251,191,36,0.35);
      color: var(--stepup);
    }
    .score-card.driver {
      outline: 1px solid rgba(45, 212, 191, 0.45);
      box-shadow: 0 0 14px rgba(45, 212, 191, 0.12);
    }
    .perf-strip {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(88px, 1fr));
      gap: 0.4rem;
      margin-top: 0.65rem;
      padding-top: 0.65rem;
      border-top: 1px solid var(--border);
    }
    .perf-strip .pm {
      background: rgba(0,0,0,0.28);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.4rem 0.45rem;
    }
    .perf-strip .pm .pl {
      font-size: 0.58rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
    }
    .perf-strip .pm .pv {
      font-family: var(--mono);
      font-size: 0.85rem;
      margin-top: 0.15rem;
      font-variant-numeric: tabular-nums;
    }
    .perf-meta {
      font-size: 0.68rem;
      color: var(--faint);
      margin-top: 0.4rem;
      font-family: var(--mono);
    }
    .audit-toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      align-items: center;
      margin-bottom: 0.55rem;
    }
    .chain-badge {
      font-size: 0.68rem;
      font-family: var(--mono);
      padding: 0.2rem 0.5rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      color: var(--muted);
    }
    .chain-badge.ok { color: var(--accept); border-color: rgba(52,211,153,0.45); }
    .chain-badge.bad { color: var(--reject); border-color: rgba(248,113,113,0.45); }
    .flow-stage.reject .flow-card {
      border-color: rgba(248,113,113,0.65);
      background: rgba(248,113,113,0.14);
      box-shadow: 0 0 18px rgba(248,113,113,0.18);
    }
    .flow-stage.reject .fc-title { color: var(--reject); }
    .stair-step.on {
      opacity: 1;
      transform: none;
    }
    .stair-step.probing {
      opacity: 1;
      border-left-color: var(--sky);
      border-color: rgba(56, 189, 248, 0.55);
      background: rgba(56, 189, 248, 0.1);
      box-shadow: 0 0 18px rgba(56, 189, 248, 0.25), 4px 4px 0 rgba(0,0,0,0.22);
      animation: stair-pulse 0.9s ease-in-out infinite;
    }
    .stair-step.accept {
      border-left-color: var(--accept);
      border-color: rgba(52,211,153,0.55);
      background: rgba(52,211,153,0.1);
      box-shadow: 0 0 16px rgba(52,211,153,0.22), 4px 4px 0 rgba(0,0,0,0.22);
    }
    .stair-step.escalate {
      border-left-color: var(--stepup);
      border-color: rgba(251,191,36,0.5);
      background: rgba(251,191,36,0.1);
    }
    .stair-step.reject {
      border-left-color: var(--reject);
      border-color: rgba(248,113,113,0.55);
      background: rgba(248,113,113,0.1);
    }
    .stair-step.skipped {
      opacity: 0.32;
      border-style: dashed;
      box-shadow: none;
    }
    .stair-step.locked {
      opacity: 0.28;
      border-style: dashed;
      box-shadow: none;
      filter: grayscale(0.5);
    }
    @keyframes stair-pulse {
      0%, 100% { filter: brightness(1); }
      50% { filter: brightness(1.18); }
    }
    .stair-step .s-top {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 0.5rem;
    }
    .stair-step .s-label {
      display: flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.78rem;
      font-weight: 650;
    }
    .stair-step .s-n {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 1.2rem;
      height: 1.2rem;
      border-radius: 5px;
      font-size: 0.62rem;
      font-family: var(--mono);
      font-weight: 700;
      color: var(--bg0);
      background: var(--faint);
    }
    .stair-step.on .s-n,
    .stair-step.probing .s-n { background: var(--sky); }
    .stair-step.accept .s-n { background: var(--accept); }
    .stair-step.escalate .s-n { background: var(--stepup); }
    .stair-step.reject .s-n { background: var(--reject); }
    .stair-step .s-badge {
      font-size: 0.6rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--faint);
    }
    .stair-step.probing .s-badge { color: var(--sky); }
    .stair-step.accept .s-badge { color: var(--accept); }
    .stair-step.escalate .s-badge { color: var(--stepup); }
    .stair-step.reject .s-badge { color: var(--reject); }
    .stair-step.skipped .s-badge { color: var(--faint); }
    .stair-step.locked .s-badge { color: var(--faint); }
    .stair-step .s-score {
      font-family: var(--mono);
      font-size: 1.1rem;
      font-weight: 600;
      margin: 0.12rem 0 0.05rem;
      color: var(--text);
    }
    .stair-step .s-detail {
      font-size: 0.65rem;
      color: var(--muted);
      line-height: 1.3;
    }
    .stair-step .s-bar {
      height: 4px;
      border-radius: 999px;
      background: var(--border);
      margin-top: 0.4rem;
      overflow: hidden;
    }
    .stair-step .s-bar > i {
      display: block;
      height: 100%;
      width: 0;
      background: linear-gradient(90deg, var(--sky), var(--cyan));
      transition: width 0.5s ease;
    }
    .stair-step.accept .s-bar > i { background: var(--accept); }
    .stair-step.reject .s-bar > i { background: var(--reject); }
    .stair-step.escalate .s-bar > i { background: var(--stepup); }
    .stair-foot {
      margin: 0.55rem 0.25rem 0;
      font-size: 0.62rem;
      color: var(--faint);
      font-family: var(--mono);
    }

    .decision-banner {
      padding: 1.05rem 1rem;
      border-radius: 12px;
      text-align: center;
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      margin-bottom: 0.9rem;
      border: 1px solid var(--border);
      background: rgba(6,10,16,0.5);
      transition: background 0.35s, color 0.35s, border-color 0.35s, box-shadow 0.35s;
    }
    .decision-ACCEPT {
      background: rgba(52,211,153,0.12);
      color: var(--accept);
      border-color: rgba(52,211,153,0.5);
      box-shadow: 0 0 30px rgba(52,211,153,0.12);
    }
    .decision-STEP_UP_REQUIRED {
      background: rgba(251,191,36,0.12);
      color: var(--stepup);
      border-color: rgba(251,191,36,0.5);
      box-shadow: 0 0 30px rgba(251,191,36,0.12);
    }
    .decision-REJECT {
      background: rgba(248,113,113,0.12);
      color: var(--reject);
      border-color: rgba(248,113,113,0.5);
      box-shadow: 0 0 30px rgba(248,113,113,0.12);
    }

    .scores {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 0.55rem;
      margin-bottom: 0.9rem;
    }
    .score-card {
      background: rgba(6,10,16,0.55);
      border: 1px solid var(--border);
      border-radius: 11px;
      padding: 0.7rem 0.55rem;
      text-align: center;
    }
    .score-card .label {
      font-size: 0.65rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }
    .score-card .value {
      font-family: var(--mono);
      font-size: 1.35rem;
      font-weight: 650;
      margin-top: 0.15rem;
    }
    .bar-wrap {
      height: 6px;
      background: var(--border);
      border-radius: 999px;
      margin-top: 0.45rem;
      overflow: hidden;
    }
    .bar { height: 100%; border-radius: 999px; transition: width 0.45s ease; width: 0; }

    .meta { font-size: 0.82rem; color: var(--muted); }
    .meta dt { font-weight: 600; color: var(--text); margin-top: 0.45rem; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; }
    .meta dd { margin-left: 0; font-family: var(--mono); font-size: 0.75rem; color: #c4d4f0; }
    .tags { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.3rem; }
    .tag {
      font-size: 0.68rem;
      padding: 0.15rem 0.42rem;
      border-radius: 6px;
      background: rgba(6,10,16,0.6);
      border: 1px solid var(--border);
      color: var(--muted);
      font-family: var(--mono);
    }
    .audit-list { max-height: 240px; overflow-y: auto; font-size: 0.76rem; }
    .audit-item {
      padding: 0.5rem 0;
      border-bottom: 1px solid var(--border);
    }
    .audit-item:last-child { border-bottom: none; }

    .sep {
      border: none;
      border-top: 1px solid var(--border);
      margin: 0.75rem 0;
    }
    .manual-block-title {
      margin-top: 0.85rem;
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--manual);
    }
    /* STANDALONE_PAY_CSS */
    .nav-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      align-items: center;
    }
    .nav-link.active {
      border-color: rgba(45, 212, 191, 0.55);
      color: var(--cyan);
      background: rgba(45, 212, 191, 0.1);
    }
    body.mode-standalone .manual-only { display: none !important; }
    body.mode-manual .standalone-only { display: none !important; }
    body.mode-standalone .main-grid {
      grid-template-columns: 240px minmax(320px, 1.2fr) minmax(280px, 1fr);
    }
    @media (max-width: 1100px) {
      body.mode-standalone .main-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body class="__BODY_MODE__">
  <div class="wrap">
  <header>
    <div class="brand">
      <div class="logo">DA</div>
      <div>
        <h1>DriveAuth <span>Edge</span></h1>
        <div class="sub">__PAGE_SUB__</div>
      </div>
    </div>
    <div class="header-right">
      <nav class="nav-tabs" aria-label="Pipeline pages">
        <a class="nav-link __NAV_MANUAL__" href="/manual">Manual pipeline</a>
        <a class="nav-link __NAV_STANDALONE__" href="/standalone">Standalone pay</a>
        <a class="nav-link" href="/register">Register driver</a>
        <a class="nav-link" href="/fleet">Fleet health</a>
      </nav>
      <div id="status-bar">Loading…</div>
    </div>
  </header>

  <div class="page">
    <!-- STANDALONE_PAY -->
    <section class="shipped manual-only">
      <div class="shipped-intro">
        <h2>July 2026</h2>
        <strong>Shipped stack</strong>
        <p>Code-side MVP through stage 11 (UART finger adapter · Docker · install · perf/fleet). Real Pi / sensor soak still HW-gated.</p>
      </div>
      <div class="phase-strip" id="phase-strip" aria-label="Delivery status"></div>
    </section>

    <section class="sources-box manual-only" id="sources-box">
      <header>
        <h2>Inputs &amp; expected sources</h2>
        <p>What the pipeline consumes · where Nova / vehicle sensors should supply it · dashboard stand-in today</p>
      </header>
      <div class="source-grid" id="source-grid"></div>
    </section>

    <div class="main-grid">
      <!-- Col 1 -->
      <div class="col-stack">
        <section class="panel manual-only">
          <h2>Transaction (Nova → DriveAuth)</h2>
          <p class="hint">Payment fields Nova parses from the utterance / tool call.</p>
          <label>Amount (INR)</label>
          <input id="amount" type="number" value="150" min="0" step="1" />
          <label>Beneficiary</label>
          <input id="beneficiary" type="text" value="Starbucks" />
          <label>Action</label>
          <input id="action" type="text" value="pay" />
          <label>Currency</label>
          <input id="currency" type="text" value="INR" />
          <label>Channel</label>
          <input id="channel" type="text" value="dashboard" />
          <div class="checkbox-row">
            <input id="beneficiary_known" type="checkbox" checked />
            <label for="beneficiary_known" style="margin:0">Known beneficiary</label>
          </div>
          <div class="checkbox-row">
            <input id="is_guest" type="checkbox" />
            <label for="is_guest" style="margin:0">Guest mode</label>
          </div>
        </section>

        <section class="panel">
          <h2>Actions</h2>
          <button class="btn-primary manual-only" onclick="runAuth()">Run authenticate()</button>
          <p class="hint standalone-only" style="margin-top:0">
            Use <strong>Authorize payment</strong> above for live voice/face.
            Session controls below still apply.
          </p>
          <button class="btn-secondary" onclick="loadStatus()">Refresh status</button>
          <button class="btn-secondary" onclick="resetSession()">Reset session</button>
          <hr class="sep" />
          <button class="btn-secondary" onclick="fraudFlag()">+ Soft fraud flag</button>
          <button class="btn-secondary" onclick="fraudClean()">Record clean</button>
          <button class="btn-danger" onclick="fraudReset()">Reset fraud ladder</button>
        </section>

        <section class="panel manual-only">
          <h2>Presets</h2>
          <div id="scenarios"></div>
        </section>
      </div>

      <!-- Col 2: live pipeline -->
      <div class="col-stack pipeline-col">
        <section class="panel pipeline-panel">
          <div class="pitch-banner" role="note">
            <strong>DriveAuth Edge</strong> — cabin biometric auth + payment step-up · offline · auditable · fail-closed
          </div>
          <div id="stage2-banner" class="pitch-banner" role="status" style="margin-top:0.5rem;font-size:0.85rem">
            Stage-2: loading…
          </div>
          <div id="threshold-banner" class="pitch-banner" role="alert" style="display:none;margin-top:0.5rem;border-color:var(--warn,#e6a23c);color:var(--warn,#e6a23c)">
          </div>
          <div class="pipeline-head">
            <div>
              <h2>Live security pipeline</h2>
              <p class="hint" style="margin:0.25rem 0 0">Stages light up from your inputs. Trust ladder ≠ risk signals.</p>
            </div>
            <div id="live-pill" class="live-pill idle"><span class="dot"></span> Idle</div>
          </div>
          <div id="path-summary">Set inputs or pick a preset, then run authenticate.</div>
          <div class="perf-strip" id="perf-strip" aria-label="Inference latency">
            <div class="pm"><div class="pl">Voice ms</div><div class="pv" id="perf-voice">—</div></div>
            <div class="pm"><div class="pl">Face ms</div><div class="pv" id="perf-face">—</div></div>
            <div class="pm"><div class="pl">Finger ms</div><div class="pv" id="perf-finger">—</div></div>
            <div class="pm"><div class="pl">Total ms</div><div class="pv" id="perf-total">—</div></div>
            <div class="pm"><div class="pl">CPU %</div><div class="pv" id="perf-cpu">—</div></div>
            <div class="pm"><div class="pl">RAM %</div><div class="pv" id="perf-ram">—</div></div>
          </div>
          <div class="perf-meta" id="perf-meta">Backend: — · Hailo: —</div>
          <div class="flow" id="pipeline-flow">
            <div class="flow-stage" data-stage="intent">
              <div class="flow-rail"><div class="flow-node"></div><div class="flow-line"></div></div>
              <div class="flow-card">
                <div class="fc-title">1 · Intent / payment<div class="fc-status">—</div></div>
                <div class="fc-detail">amount · beneficiary · action</div>
              </div>
            </div>
            <div class="flow-stage" data-stage="risk">
              <div class="flow-rail"><div class="flow-node"></div><div class="flow-line"></div></div>
              <div class="flow-card">
                <div class="fc-title">2 · Risk model<div class="fc-status">—</div></div>
                <div class="fc-detail">GPS · speed · amount · CAN · beneficiary novelty</div>
              </div>
            </div>
            <div class="flow-stage" data-stage="fraud">
              <div class="flow-rail"><div class="flow-node"></div><div class="flow-line"></div></div>
              <div class="flow-card">
                <div class="fc-title">3 · Fraud ladder<div class="fc-status">—</div></div>
                <div class="fc-detail">bootstrap · normal · elevated · locked</div>
              </div>
            </div>
            <div class="flow-stage" data-stage="ladder">
              <div class="flow-rail"><div class="flow-node"></div><div class="flow-line"></div></div>
              <div class="flow-card">
                <div class="fc-title">4 · Biometric ladder<div class="fc-status">—</div></div>
                <div class="fc-detail">Voice → Face → Stage-3 OR (Finger | Bluetooth OTP)</div>
                <div class="stair" id="escalation-stair" aria-label="Escalation staircase">
                  <div class="stair-caption">Escalation staircase</div>
                  <div class="stair-steps">
                    <div class="stair-step" data-rung="voice" data-step="1">
                      <div class="s-top">
                        <div class="s-label"><span class="s-n">1</span> Voice <span class="mod-badge" id="badge-voice">…</span></div>
                        <div class="s-badge" id="stair-voice-badge">idle</div>
                      </div>
                      <div class="s-score" id="rung-voice-score">—</div>
                      <div class="s-detail" id="rung-voice-detail">ECAPA · QualityGate · lowest friction</div>
                      <div class="s-bar"><i id="rung-voice-bar"></i></div>
                    </div>
                    <div class="stair-riser" data-after="voice"><span class="arrow">↑</span> escalate</div>
                    <div class="stair-step" data-rung="face" data-step="2">
                      <div class="s-top">
                        <div class="s-label"><span class="s-n">2</span> Face <span class="mod-badge" id="badge-face">…</span></div>
                        <div class="s-badge" id="stair-face-badge">idle</div>
                      </div>
                      <div class="s-score" id="rung-face-score">—</div>
                      <div class="s-detail" id="rung-face-detail">MobileFaceNet · PAD <span class="mod-badge" id="badge-liveness">liveness…</span></div>
                      <div class="s-bar"><i id="rung-face-bar"></i></div>
                    </div>
                    <div class="stair-riser" data-after="face"><span class="arrow">↑</span> escalate</div>
                    <div class="stair-step" data-rung="stage3" data-step="3">
                      <div class="s-top">
                        <div class="s-label"><span class="s-n">3</span> Stage-3 OR</div>
                        <div class="s-badge" id="stair-stage3-badge">idle</div>
                      </div>
                      <div class="stage3-lanes">
                        <div class="stage3-or" id="stage3-or">finger OR bluetooth OTP</div>
                        <div class="stair-sub" data-rung="finger" id="sub-finger">
                          <div class="s-top">
                            <div class="s-label">Fingerprint <span class="mod-badge" id="badge-finger">…</span></div>
                            <div class="s-badge" id="stair-finger-badge">idle</div>
                          </div>
                          <div class="s-score" id="rung-finger-score">—</div>
                          <div class="s-detail" id="rung-finger-detail">UART / ManualScores</div>
                          <div class="s-bar"><i id="rung-finger-bar"></i></div>
                        </div>
                        <div class="stair-sub" data-rung="otp" id="sub-otp">
                          <div class="s-top">
                            <div class="s-label">Bluetooth OTP</div>
                            <div class="s-badge" id="stair-otp-badge">idle</div>
                          </div>
                          <div class="s-score" id="rung-otp-score">—</div>
                          <div class="s-detail" id="rung-otp-detail">Paired-phone ladder lane</div>
                          <div class="s-bar"><i id="rung-otp-bar"></i></div>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div class="stair-foot" id="stair-foot">Idle — run authenticate to climb</div>
                </div>
              </div>
            </div>
            <div class="flow-stage" data-stage="policy">
              <div class="flow-rail"><div class="flow-node"></div><div class="flow-line"></div></div>
              <div class="flow-card">
                <div class="fc-title">5 · Policy engine<div class="fc-status">—</div></div>
                <div class="fc-detail">deterministic gates · no ML inventing accept</div>
              </div>
            </div>
            <div class="flow-stage" data-stage="decision">
              <div class="flow-rail"><div class="flow-node"></div><div class="flow-line"></div></div>
              <div class="flow-card">
                <div class="fc-title">6 · Decision<div class="fc-status">—</div></div>
                <div class="fc-detail">ACCEPT · STEP_UP_REQUIRED · REJECT → audit</div>
              </div>
            </div>
          </div>
        </section>

        <section class="panel manual manual-only">
          <h2>Manual stand-ins → auto later</h2>
          <p class="hint">
            Mimic sensors Nova will feed automatically (mic, camera, fingerprint, CAN, GPS).
            Same schema — different source in production.
          </p>
          <div class="manual-block-title">Demo scenarios</div>
          <div class="scenario-row" id="scenario-row"></div>
          <div class="manual-block-title">Biometric match scores</div>
          <label>Voice <span id="voice-val">0.92</span></label>
          <input id="voice" type="range" min="0" max="1" step="0.01" value="0.92" />
          <label>Face <span id="face-val">0.88</span></label>
          <input id="face" type="range" min="0" max="1" step="0.01" value="0.88" />
          <label>Finger <span id="finger-val">0.85</span></label>
          <input id="finger" type="range" min="0" max="1" step="0.01" value="0.85" />
          <label>Behavioral <span id="behavioral-val">0.95</span> <span class="mod-badge" id="badge-can">…</span></label>
          <input id="behavioral" type="range" min="0" max="1" step="0.01" value="0.95" />

          <div class="manual-block-title">GPS (vehicle / telematics)</div>
          <p class="hint">Risk uses trusted-zone only (Phase 0). Distance is telemetry / override.</p>
          <div class="row">
            <div>
              <label>gps_lat</label>
              <input id="gps_lat" type="number" step="0.0001" placeholder="optional" />
            </div>
            <div>
              <label>gps_lon</label>
              <input id="gps_lon" type="number" step="0.0001" placeholder="optional" />
            </div>
          </div>
          <label>gps_accuracy_m</label>
          <input id="gps_accuracy_m" type="number" value="50" min="0" step="1" />
          <div class="checkbox-row">
            <input id="trusted_zone" type="checkbox" checked />
            <label for="trusted_zone" style="margin:0">in_trusted_zone</label>
          </div>
          <label>dist_from_home_km <span style="color:var(--faint);font-weight:400">(telemetry / override · not a risk feature)</span></label>
          <input id="dist_home" type="number" value="0" min="0" step="0.1" />

          <div class="manual-block-title">Vehicle / CAN</div>
          <label>speed_kmh</label>
          <input id="speed" type="number" value="0" min="0" />
          <div class="checkbox-row">
            <input id="ignition_on" type="checkbox" checked />
            <label for="ignition_on" style="margin:0">ignition_on</label>
          </div>
          <div class="checkbox-row">
            <input id="tunnel" type="checkbox" />
            <label for="tunnel" style="margin:0">is_tunnel</label>
          </div>
        </section>
      </div>

      <!-- Col 3 -->
      <div class="col-stack">
        <section class="panel">
          <h2>Result</h2>
          <div id="decision-banner" class="decision-banner">—</div>
          <div id="driver-callout" class="driver-callout" style="display:none"></div>
          <div class="scores">
            <div class="score-card" id="trust-card">
              <div class="label">Trust</div>
              <div class="value" id="trust-val">—</div>
              <div class="bar-wrap"><div class="bar" id="trust-bar" style="background:var(--accept)"></div></div>
            </div>
            <div class="score-card" id="risk-card">
              <div class="label">Risk</div>
              <div class="value" id="risk-val">—</div>
              <div class="bar-wrap"><div class="bar" id="risk-bar" style="background:var(--risk)"></div></div>
            </div>
            <div class="score-card" id="conf-card">
              <div class="label">Confidence</div>
              <div class="value" id="conf-val">—</div>
              <div class="bar-wrap"><div class="bar" id="conf-bar" style="background:var(--sky)"></div></div>
            </div>
          </div>
          <div class="policy-tags" id="policy-tags"></div>
          <dl class="meta">
            <dt>Tier</dt><dd id="tier">—</dd>
            <dt>Policy rule</dt><dd id="policy">—</dd>
            <dt>Stage-3</dt><dd id="stage3-method">—</dd>
            <dt>Step-up</dt><dd id="stepup">—</dd>
            <dt>Legacy (Nova)</dt><dd id="legacy">—</dd>
            <dt>Explanations</dt>
            <dd><div class="tags" id="explanations"></div></dd>
            <dt>Modality scores</dt>
            <dd><pre id="modalities" style="font-size:0.72rem;overflow:auto;margin-top:0.25rem;font-family:var(--mono);color:#c4d4f0"></pre></dd>
          </dl>
        </section>

        <section class="panel">
          <h2>Audit log</h2>
          <div class="audit-toolbar">
            <button class="btn-secondary" type="button" onclick="verifyAuditChain()">Verify chain</button>
            <span class="chain-badge" id="chain-badge">chain · unchecked</span>
            <button class="btn-danger" type="button" id="btn-demo-tamper" style="display:none"
              onclick="demoTamperAudit()">Demo only · tamper last entry</button>
          </div>
          <div class="audit-list" id="audit-list">No events yet.</div>
        </section>
      </div>
    </div>
  </div>
  </div>

  <script>
    function adminHeaders(extra = {}) {
      const headers = Object.assign({}, extra || {});
      if (window.__DRIVEAUTH_ADMIN_KEY__) {
        headers["X-API-Key"] = window.__DRIVEAUTH_ADMIN_KEY__;
      }
      return headers;
    }
    async function adminFetch(path, opts = {}) {
      const opts2 = Object.assign({}, opts);
      opts2.headers = adminHeaders(opts2.headers || {});
      return fetch(path, opts2);
    }

    const PHASES = [
      { id: "P0", title: "Zone-only geo risk", state: "done", label: "Done" },
      { id: "P1–6", title: "Ladder · models · eval", state: "done", label: "Done" },
      { id: "P5", title: "160+ tests", state: "done", label: "Done" },
      { id: "P7–10", title: "Liveness · BLE · keys · CAN", state: "done", label: "Done" },
      { id: "P11", title: "UART · Docker · perf", state: "done", label: "Done" },
      { id: "HW", title: "Pi · Hailo · live bus", state: "partial", label: "HW" },
    ];

    const SOURCES = [
      {
        id: "voice",
        name: "Voice",
        lane: "trust",
        input: "audio_np · ModalityResult.score",
        source: "<strong>Mic / STT buffer</strong> → ECAPA-TDNN + QualityGate",
        nowKey: "voice",
        format: (p) => `slider ${Number(p.mock_scores.voice).toFixed(2)} (dashboard stand-in)`,
      },
      {
        id: "face",
        name: "Face",
        lane: "trust",
        input: "BGR frame · ModalityResult.score",
        source: "<strong>IR / DMS camera</strong> → MobileFaceNet + PAD",
        nowKey: "face",
        format: (p) => `slider ${Number(p.mock_scores.face).toFixed(2)} (dashboard stand-in)`,
      },
      {
        id: "finger",
        name: "Fingerprint",
        lane: "trust",
        input: "ModalityResult.score ∈ [0,1]",
        source: "<strong>UART adapter + daemon</strong> shipped · ManualScores stand-in here · real sensor still HW",
        nowKey: "finger",
        format: (p) => `slider ${Number(p.mock_scores.finger).toFixed(2)} (ManualScores)`,
      },
      {
        id: "behavioral",
        name: "Behavioral / CAN",
        lane: "risk",
        input: "update_behavioral({8 CAN features})",
        source: "<strong>CAN logger harness</strong> · synth bake-off ONNX today · live bus still HW",
        nowKey: "behavioral",
        format: (p) => `slider ${Number(p.mock_scores.behavioral).toFixed(2)} · speed ${p.context.speed_kmh}`,
      },
      {
        id: "payment",
        name: "Payment intent",
        lane: "risk",
        input: "amount · beneficiary · action · currency",
        source: "<strong>Nova utterance / tool call</strong>",
        nowKey: "payment",
        format: (p) => `${p.currency} ${p.amount} → ${p.beneficiary}`,
      },
      {
        id: "gps",
        name: "GPS / zone",
        lane: "risk",
        input: "update_vehicle_context(gps_*) · in_trusted_zone",
        source: "<strong>Vehicle telematics</strong> · risk = zone only (Phase 0) · dist is telemetry",
        nowKey: "gps",
        format: (p) => {
          const c = p.context;
          const g = (c.gps_lat != null && c.gps_lon != null)
            ? `${c.gps_lat}, ${c.gps_lon}`
            : "no GPS fix";
          const zone = c.in_trusted_zone ? "trusted" : "outside";
          const dist = c.dist_from_home_km != null
            ? ` · dist ${c.dist_from_home_km} km (telemetry)`
            : "";
          return `${g} · zone ${zone}${dist}`;
        },
      },
      {
        id: "vehicle",
        name: "Speed / ignition",
        lane: "risk",
        input: "speed_kmh · ignition_on · inbound",
        source: "<strong>OBD / CAN + GPS fusion</strong>",
        nowKey: "vehicle",
        format: (p) => `${p.context.speed_kmh} km/h · ign ${p.context.ignition_on ? "on" : "off"}`,
      },
      {
        id: "guest",
        name: "Guest / channel",
        lane: "both",
        input: "is_guest · channel · beneficiary_known",
        source: "<strong>Nova session context</strong>",
        nowKey: "guest",
        format: (p) => `${p.is_guest ? "guest" : "enrolled"} · ${p.channel} · known ${p.beneficiary_known}`,
      },
    ];

    function bindRange(id, labelId) {
      const el = document.getElementById(id);
      const lbl = document.getElementById(labelId);
      el.addEventListener("input", () => {
        lbl.textContent = el.value;
        refreshSources();
      });
    }
    ["voice","face","finger","behavioral"].forEach(k => bindRange(k, k + "-val"));

    function numOrNull(id) {
      const raw = document.getElementById(id).value;
      if (raw === "" || raw == null) return null;
      const v = parseFloat(raw);
      return Number.isFinite(v) ? v : null;
    }

    function payloadFromForm() {
      return {
        amount: parseFloat(document.getElementById("amount").value) || 0,
        beneficiary: document.getElementById("beneficiary").value,
        beneficiary_known: document.getElementById("beneficiary_known").checked,
        is_guest: document.getElementById("is_guest").checked,
        action: document.getElementById("action").value || "pay",
        currency: document.getElementById("currency").value || "INR",
        channel: document.getElementById("channel").value || "dashboard",
        mock_scores: {
          voice: parseFloat(document.getElementById("voice").value),
          face: parseFloat(document.getElementById("face").value),
          finger: parseFloat(document.getElementById("finger").value),
          behavioral: parseFloat(document.getElementById("behavioral").value),
        },
        context: {
          speed_kmh: parseFloat(document.getElementById("speed").value) || 0,
          in_trusted_zone: document.getElementById("trusted_zone").checked,
          dist_from_home_km: parseFloat(document.getElementById("dist_home").value) || 0,
          is_tunnel: document.getElementById("tunnel").checked,
          ignition_on: document.getElementById("ignition_on").checked,
          gps_lat: numOrNull("gps_lat"),
          gps_lon: numOrNull("gps_lon"),
          gps_accuracy_m: parseFloat(document.getElementById("gps_accuracy_m").value) || 50,
        },
        fingerprint_available: window.__demoFingerAvail,
        stage3_mode: window.__demoStage3Mode || null,
        otp_demo: !!window.__demoOtp,
      };
    }

    function applyPayload(p) {
      document.getElementById("amount").value = p.amount;
      document.getElementById("beneficiary").value = p.beneficiary || "";
      document.getElementById("beneficiary_known").checked = !!p.beneficiary_known;
      document.getElementById("is_guest").checked = !!p.is_guest;
      if (p.action) document.getElementById("action").value = p.action;
      if (p.currency) document.getElementById("currency").value = p.currency;
      if (p.channel) document.getElementById("channel").value = p.channel;
      const m = p.mock_scores || {};
      ["voice","face","finger","behavioral"].forEach(k => {
        if (m[k] != null) {
          document.getElementById(k).value = m[k];
          document.getElementById(k + "-val").textContent = m[k];
        } else if (k === "finger" && m[k] === null) {
          document.getElementById("finger").value = 0;
          document.getElementById("finger-val").textContent = "0";
        }
      });
      const c = p.context || {};
      document.getElementById("speed").value = c.speed_kmh ?? 0;
      document.getElementById("dist_home").value = c.dist_from_home_km ?? 0;
      document.getElementById("trusted_zone").checked = c.in_trusted_zone !== false;
      document.getElementById("tunnel").checked = !!c.is_tunnel;
      document.getElementById("ignition_on").checked = c.ignition_on !== false;
      document.getElementById("gps_lat").value = c.gps_lat ?? "";
      document.getElementById("gps_lon").value = c.gps_lon ?? "";
      document.getElementById("gps_accuracy_m").value = c.gps_accuracy_m ?? 50;
      window.__demoFingerAvail = (p.fingerprint_available === undefined) ? null : p.fingerprint_available;
      window.__demoStage3Mode = p.stage3_mode || null;
      window.__demoOtp = !!p.otp_demo;
      refreshSources();
    }

    function renderPhases() {
      document.getElementById("phase-strip").innerHTML = PHASES.map(p => `
        <div class="phase ${p.state}">
          <div class="ph-id">${p.id}</div>
          <div class="ph-title">${p.title}</div>
          <div class="ph-state">${p.label}</div>
        </div>`).join("");
    }

    function refreshSources(highlight) {
      const p = payloadFromForm();
      const hl = highlight || {};
      document.getElementById("source-grid").innerHTML = SOURCES.map(s => {
        const active = hl[s.id] ? ` active-${hl[s.id]}` : "";
        return `
          <div class="source-card${active}" data-source="${s.id}">
            <div class="sc-top">
              <span class="sc-name">${s.name}</span>
              <span class="sc-lane ${s.lane}">${s.lane}</span>
            </div>
            <div class="sc-input">${s.input}</div>
            <div class="sc-source">${s.source}</div>
            <div class="sc-now">now: <em>${s.format(p)}</em></div>
          </div>`;
      }).join("");
    }

    function setLivePill(mode, text) {
      const el = document.getElementById("live-pill");
      el.className = "live-pill " + mode;
      el.innerHTML = `<span class="dot"></span> ${text}`;
    }

    function resetPipelineVisual() {
      document.querySelectorAll(".flow-stage").forEach(el => {
        el.className = "flow-stage";
        el.querySelector(".fc-status").textContent = "—";
        const detail = el.querySelector(".fc-detail");
        if (detail && detail.dataset.base) detail.textContent = detail.dataset.base;
      });
      document.querySelectorAll(".stair-step").forEach(el => {
        el.className = "stair-step";
      });
      document.querySelectorAll(".stair-sub").forEach(el => {
        el.className = "stair-sub";
      });
      document.querySelectorAll(".stair-riser").forEach(el => {
        el.classList.remove("on");
      });
      const orEl = document.getElementById("stage3-or");
      if (orEl) { orEl.className = "stage3-or"; orEl.textContent = "finger OR bluetooth OTP"; }
      ["voice","face","finger","otp"].forEach(m => {
        const score = document.getElementById("rung-" + m + "-score");
        const bar = document.getElementById("rung-" + m + "-bar");
        const badge = document.getElementById("stair-" + m + "-badge");
        if (score) score.textContent = "—";
        if (bar) bar.style.width = "0%";
        if (badge) badge.textContent = "idle";
      });
      const s3b = document.getElementById("stair-stage3-badge");
      if (s3b) s3b.textContent = "idle";
      document.getElementById("rung-voice-detail").textContent = "ECAPA · QualityGate · lowest friction";
      document.getElementById("rung-face-detail").textContent = "MobileFaceNet · PAD";
      document.getElementById("rung-finger-detail").textContent = "UART / ManualScores";
      const otpDetail = document.getElementById("rung-otp-detail");
      if (otpDetail) otpDetail.textContent = "Paired-phone ladder lane";
      const foot = document.getElementById("stair-foot");
      if (foot) foot.textContent = "Idle — run authenticate to climb";
    }

    // stash base detail text once
    document.querySelectorAll(".flow-stage .fc-detail").forEach(el => {
      el.dataset.base = el.textContent;
    });

    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    async function animatePipeline(pipeline) {
      if (!pipeline || !pipeline.stages) return;
      resetPipelineVisual();
      setLivePill("running", "Streaming");
      document.getElementById("path-summary").innerHTML =
        `Path: <strong>${pipeline.path_summary || "—"}</strong>`;

      const stageEls = {};
      document.querySelectorAll(".flow-stage").forEach(el => {
        stageEls[el.dataset.stage] = el;
      });

      // Progressive unlock: stop after Bio ladder — don't light Policy/Decision yet.
      const pauseAfter = pipeline.pause_after || (pipeline.next_unlock ? "ladder" : null);

      for (const stage of pipeline.stages) {
        const el = stageEls[stage.id];
        if (!el) continue;
        el.classList.add("active", "on");
        if (stage.status && stage.status !== "done") el.classList.add(stage.status);
        el.querySelector(".fc-status").textContent = (stage.status || "done").toUpperCase();
        if (stage.detail) el.querySelector(".fc-detail").textContent = stage.detail;

        if (stage.id === "ladder" && stage.rungs) {
          await animateStaircase(stage.rungs, pipeline);
        }
        await sleep(140);
        if (pauseAfter && stage.id === pauseAfter) break;
      }
      setLivePill("on", pipeline.next_unlock ? "Escalate" : "Live");
    }

    async function animateStaircase(rungs, pipeline) {
      const probed = (pipeline && pipeline.probed) || [];
      const foot = document.getElementById("stair-foot");
      const labelMod = (m) => {
        if (m === "finger") return "Fingerprint";
        if (m === "otp") return "Bluetooth OTP";
        return m.charAt(0).toUpperCase() + m.slice(1);
      };
      const climb = probed.length ? probed.map(labelMod).join(" → ") : "—";
      if (foot) {
        foot.textContent = `Climbing: ${climb}` +
          (pipeline.accept_modality
            ? ` · early-stop @ ${pipeline.accept_modality}`
            : pipeline.next_unlock
              ? ` · escalate · unlock ${pipeline.next_unlock}`
              : "");
      }

      const byId = {};
      rungs.forEach(r => { byId[r.id] = r; });
      const order = probed.length ? probed : [];
      const ladderOrder = ["voice", "face", "finger", "otp"];
      const stage3El = document.querySelector('.stair-step[data-rung="stage3"]');

      for (let i = 0; i < order.length; i++) {
        const id = order[i];
        const rung = byId[id];
        if (!rung) continue;

        if (id === "finger" || id === "otp") {
          if (stage3El) stage3El.className = "stair-step on probing";
          const s3badge = document.getElementById("stair-stage3-badge");
          if (s3badge) s3badge.textContent = "stage-3";
        }

        // Animate finger→OTP OR fallback mid-flow.
        if (id === "otp") {
          const fingerRung = byId["finger"];
          const orEl = document.getElementById("stage3-or");
          if (fingerRung && (fingerRung.status === "unavailable" || fingerRung.status === "escalate")) {
            const subF = document.getElementById("sub-finger");
            if (subF) {
              subF.className = "stair-sub on " + (fingerRung.status || "unavailable");
              document.getElementById("stair-finger-badge").textContent = fingerRung.status || "unavailable";
              document.getElementById("rung-finger-detail").textContent = fingerRung.detail || "unavailable";
            }
            if (orEl) {
              orEl.className = "stage3-or on fallback";
              orEl.textContent = "OR fallback → Bluetooth OTP";
            }
            await sleep(320);
          } else if (orEl) {
            orEl.className = "stage3-or on";
          }
        }

        const isStage3 = (id === "finger" || id === "otp");
        const rEl = isStage3
          ? document.getElementById("sub-" + id)
          : document.querySelector(`.stair-step[data-rung="${id}"]`);
        if (!rEl) continue;

        rEl.className = (isStage3 ? "stair-sub" : "stair-step") + " probing";
        const badge = document.getElementById("stair-" + id + "-badge");
        if (badge) badge.textContent = "probing";
        await sleep(220);

        const score = rung.score;
        const scoreEl = document.getElementById("rung-" + id + "-score");
        const detailEl = document.getElementById("rung-" + id + "-detail");
        const barEl = document.getElementById("rung-" + id + "-bar");
        if (scoreEl) scoreEl.textContent = score == null ? "—" : Number(score).toFixed(3);
        if (detailEl) detailEl.textContent = rung.detail || "";
        if (barEl) barEl.style.width = score == null ? "0%" : Math.round(Number(score) * 100) + "%";
        rEl.className = (isStage3 ? "stair-sub" : "stair-step") + " on " + (rung.status || "");
        if (badge) badge.textContent = rung.status || "done";

        if (rung.status === "escalate") {
          const nextMod = ladderOrder[ladderOrder.indexOf(id) + 1];
          if (nextMod && probed.includes(nextMod) && (id === "voice" || id === "face")) {
            const riser = document.querySelector(`.stair-riser[data-after="${id}"]`);
            if (riser) riser.classList.add("on");
          }
        }
        await sleep(180);
      }

      // Paint non-probed stage-3 lanes (unavailable / not attempted / skipped).
      const stage3 = (pipeline.stages || []).find(s => s.id === "ladder");
      const lanes = (stage3 && stage3.stage3_lanes) || [];
      for (const lane of lanes) {
        if (probed.includes(lane.id)) continue;
        const sub = document.getElementById("sub-" + lane.id);
        if (!sub) continue;
        sub.className = "stair-sub on " + (lane.status || "locked");
        const badge = document.getElementById("stair-" + lane.id + "-badge");
        if (badge) badge.textContent = lane.status || "locked";
        const detail = document.getElementById("rung-" + lane.id + "-detail");
        if (detail) detail.textContent = lane.detail || "";
        const scoreEl = document.getElementById("rung-" + lane.id + "-score");
        if (scoreEl) scoreEl.textContent = lane.score == null ? "—" : Number(lane.score).toFixed(3);
      }
      if (stage3El && (probed.includes("finger") || probed.includes("otp") || lanes.length)) {
        const anyAccept = lanes.some(l => l.status === "accept");
        const anyReject = lanes.every(l => l.status === "reject" || l.status === "unavailable" || l.status === "not_attempted" || l.status === "skipped" || l.status === "locked") && probed.some(p => p === "finger" || p === "otp");
        stage3El.className = "stair-step on " + (anyAccept ? "accept" : (pipeline.accept_modality ? "skipped" : "on"));
        const s3badge = document.getElementById("stair-stage3-badge");
        if (s3badge) {
          s3badge.textContent = pipeline.stage3_method || (anyAccept ? "accept" : "done");
        }
      }

      // Leave non-probed early rungs dark.
      for (const rung of rungs) {
        if (order.includes(rung.id) || rung.stage3) continue;
        if (rung.id === "finger" || rung.id === "otp") continue;
        const rEl = document.querySelector(`.stair-step[data-rung="${rung.id}"]`);
        if (!rEl) continue;
        const status = rung.status === "skipped" ? "skipped" : "locked";
        rEl.className = "stair-step " + status;
        const badge = document.getElementById("stair-" + rung.id + "-badge");
        if (badge) badge.textContent = status;
        const detail = document.getElementById("rung-" + rung.id + "-detail");
        if (detail) detail.textContent = rung.detail || (status === "locked" ? "locked · not in this call" : "");
        const score = document.getElementById("rung-" + rung.id + "-score");
        if (score) score.textContent = "—";
        const bar = document.getElementById("rung-" + rung.id + "-bar");
        if (bar) bar.style.width = "0%";
      }

      if (foot) {
        let msg = `Path: ${climb}`;
        if (pipeline && pipeline.stage3_method) {
          msg += ` · stage3=${pipeline.stage3_method}`;
        }
        if (pipeline && pipeline.next_unlock) {
          msg += ` · escalate · capture ${pipeline.next_unlock}`;
        } else if (pipeline && pipeline.path_summary) {
          msg += ` · ${pipeline.path_summary}`;
        }
        foot.textContent = msg;
      }
    }

    function highlightSourcesFromResult(r, payload) {
      const hl = {
        payment: "risk",
        gps: "risk",
        vehicle: "risk",
        behavioral: "risk",
        guest: "risk",
      };
      const probed = (r.pipeline && r.pipeline.probed) || [];
      probed.forEach(m => { hl[m === "otp" ? "finger" : m] = "trust"; });
      if (!probed.length) {
        hl.voice = "trust";
        hl.face = "trust";
        hl.finger = "trust";
      }
      refreshSources(hl);
    }

    function showResult(r) {
      const banner = document.getElementById("decision-banner");
      const next = r.pipeline && r.pipeline.next_unlock;
      if (next) {
        banner.textContent = "ESCALATE · " + String(next).toUpperCase();
        banner.className = "decision-banner decision-STEP_UP_REQUIRED";
      } else {
        banner.textContent = r.decision;
        banner.className = "decision-banner decision-" + r.decision;
      }

      const driver = r.decision_driver || (r.pipeline && r.pipeline.decision_driver) || {};
      const callout = document.getElementById("driver-callout");
      if (driver.summary) {
        callout.style.display = "block";
        callout.textContent = driver.summary;
        callout.className = "driver-callout " + (driver.lane || "policy");
      } else {
        callout.style.display = "none";
      }

      function setScore(id, barId, val) {
        const pct = Math.round((val || 0) * 100);
        document.getElementById(id).textContent = (val ?? 0).toFixed(3);
        document.getElementById(barId).style.width = pct + "%";
      }
      setScore("trust-val", "trust-bar", r.trust_score);
      setScore("risk-val", "risk-bar", r.risk_score);
      setScore("conf-val", "conf-bar", r.confidence_score);

      ["trust-card","risk-card","conf-card"].forEach(id => {
        document.getElementById(id).classList.remove("driver");
      });
      if (driver.lane === "trust") document.getElementById("trust-card").classList.add("driver");
      if (driver.lane === "risk" || driver.lane === "fraud") document.getElementById("risk-card").classList.add("driver");
      if (driver.lane === "policy" && r.decision !== "ACCEPT") {
        /* policy-driven step-up — leave scores unoutlined */
      }

      const tags = document.getElementById("policy-tags");
      tags.innerHTML = (r.policy_tags || []).map(e => `<span class="tag">${e}</span>`).join("");

      document.getElementById("tier").textContent = r.tier;
      document.getElementById("policy").textContent =
        next ? (`paused · unlock ${next}`) : r.policy_rule;
      document.getElementById("stage3-method").textContent = r.stage3_method || "—";
      document.getElementById("stepup").textContent =
        next ? next : (r.step_up_method || "—");
      document.getElementById("legacy").textContent = r.legacy_decision || "—";

      const expl = document.getElementById("explanations");
      expl.innerHTML = (r.explanations || []).map(e => `<span class="tag">${e}</span>`).join("");
      document.getElementById("modalities").textContent = JSON.stringify(r.modality_scores, null, 2);
      loadPerfStrip();
    }

    async function runAuth() {
      const payload = payloadFromForm();
      if (payload.fingerprint_available == null) delete payload.fingerprint_available;
      if (!payload.stage3_mode) delete payload.stage3_mode;
      if (!payload.otp_demo) delete payload.otp_demo;
      refreshSources();
      resetPipelineVisual();
      setLivePill("running", "Authenticating");
      document.getElementById("path-summary").textContent = "Running authenticate()…";
      document.getElementById("decision-banner").textContent = "…";
      document.getElementById("decision-banner").className = "decision-banner";

      const res = await adminFetch("/api/authenticate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      showResult(data);
      await animatePipeline(data.pipeline);
      highlightSourcesFromResult(data, payload);
      loadAudit();
      loadStatus();
      verifyAuditChain();
    }

    async function loadStatus() {
      const s = await (await fetch("/api/status")).json();
      const maturity = s.profile_mature ? "mature" : (s.profile_maturity || "bootstrap");
      document.getElementById("status-bar").innerHTML =
        `Store: <code>${s.store_dir}</code> · Fraud: <span class="badge">${s.fraud_state}</span> · Profile: <span class="badge ${s.profile_mature ? "ok" : "warn"}">${maturity}</span>` +
        (s.demo_mode ? ` · <span class="badge warn">DEMO</span>` : "");
      const tamperBtn = document.getElementById("btn-demo-tamper");
      if (tamperBtn) tamperBtn.style.display = s.demo_mode ? "" : "none";
    }

    async function loadAudit() {
      const entries = await (await fetch("/api/audit")).json();
      const el = document.getElementById("audit-list");
      if (!entries.length) { el.textContent = "No events yet."; return; }
      el.innerHTML = entries.map(e => `
        <div class="audit-item">
          <strong style="color:${
            e.decision === "ACCEPT" ? "var(--accept)" :
            e.decision === "REJECT" ? "var(--reject)" : "var(--stepup)"
          }">${e.decision}</strong> · ${e.tier} · trust ${e.trust_score} · risk ${e.risk_score}
          <br><span style="color:var(--muted)">${e.ts} · ${e.policy_rule}</span>
        </div>`).join("");
    }

    async function verifyAuditChain() {
      const res = await (await fetch("/api/audit/verify")).json();
      const badge = document.getElementById("chain-badge");
      badge.textContent = res.ok ? "chain · intact" : ("chain · BROKEN · " + (res.reason || ""));
      badge.className = "chain-badge " + (res.ok ? "ok" : "bad");
      const tamperBtn = document.getElementById("btn-demo-tamper");
      if (tamperBtn) tamperBtn.style.display = res.demo_mode ? "" : "none";
    }

    async function demoTamperAudit() {
      const res = await adminFetch("/api/audit/demo_tamper", { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        alert(data.detail || res.statusText);
        return;
      }
      const badge = document.getElementById("chain-badge");
      const v = data.verify || {};
      badge.textContent = v.ok ? "chain · intact (unexpected)" : ("chain · BROKEN · " + (v.reason || "tampered"));
      badge.className = "chain-badge " + (v.ok ? "ok" : "bad");
      loadAudit();
    }

    function fmtMs(v) {
      if (v == null || v === "") return "—";
      const n = Number(v);
      return Number.isFinite(n) ? n.toFixed(1) : "—";
    }

    async function loadPerfStrip() {
      try {
        const perf = await (await fetch("/api/fleet/perf")).json();
        const lat = perf.latency_ms_avg || {};
        document.getElementById("perf-voice").textContent = fmtMs(lat.voice);
        document.getElementById("perf-face").textContent = fmtMs(lat.face);
        document.getElementById("perf-finger").textContent = fmtMs(lat.finger);
        document.getElementById("perf-total").textContent = fmtMs(lat.total);
        const util = perf.utilization || {};
        document.getElementById("perf-cpu").textContent = fmtMs(util.cpu_pct);
        document.getElementById("perf-ram").textContent = fmtMs(util.ram_pct);
        const backend = perf.face_backend || "cpu";
        const hailo = window.__hailoStatus || "Hailo bench pending hardware";
        document.getElementById("perf-meta").textContent =
          `Backend: ${backend === "hailo" ? "Hailo" : "CPU/ONNX"} · ${hailo}` +
          (perf.enabled === false ? " · perf off" : "");
      } catch (e) { /* ignore */ }
    }

    function badgeClass(label) {
      if (!label) return "standin";
      if (label.indexOf("daemon") >= 0) return "daemon";
      if (label.indexOf("real") >= 0) return "real";
      return "standin";
    }

    async function loadModalityBadges() {
      try {
        const data = await (await fetch("/api/modality_sources")).json();
        const mods = data.modalities || {};
        ["voice","face","finger"].forEach(k => {
          const el = document.getElementById("badge-" + k);
          if (!el || !mods[k]) return;
          el.textContent = mods[k].label;
          el.className = "mod-badge " + badgeClass(mods[k].label);
        });
        const can = document.getElementById("badge-can");
        if (can && mods.can) {
          can.textContent = mods.can.label;
          can.className = "mod-badge " + badgeClass(mods.can.label);
        }
        const live = document.getElementById("badge-liveness");
        if (live && mods.liveness) {
          live.textContent = "liveness · " + mods.liveness.label;
          live.className = "mod-badge " + badgeClass(mods.liveness.label);
        }
        if (data.hailo_status) {
          window.__hailoStatus = data.hailo_status;
        }
        // Stage-2 / threshold banners
        const s2 = data.stage2 || {};
        const thr = data.thresholds || {};
        const faceDetail = document.getElementById("rung-face-detail");
        const padOn = !!(mods.face && mods.face.pad_enabled);
        if (faceDetail) {
          faceDetail.innerHTML =
            "MobileFaceNet · PAD " +
            (padOn ? "<span class='mod-badge real'>PAD on</span>" : "<span class='mod-badge standin'>PAD off</span>") +
            " <span class='mod-badge' id='badge-liveness'>liveness…</span>";
          const live2 = document.getElementById("badge-liveness");
          if (live2 && mods.liveness) {
            live2.textContent = "liveness · " + mods.liveness.label;
            live2.className = "mod-badge " + badgeClass(mods.liveness.label);
          }
        }
        const s2el = document.getElementById("stage2-banner");
        if (s2el) {
          const mode = s2.mode || "unknown";
          const cal = s2.calibration_timestamps || {};
          const calTs = cal.face_calibrator || cal.voice_calibrator || cal.face_pad || "—";
          const retrain = s2.needs_retrain
            ? ` · <span class="badge warn">needs retrain</span>`
            : "";
          s2el.innerHTML =
            `<strong>Driver ${data.driver_id || s2.driver_id || "?"}</strong>` +
            ` · Stage-2 <code>${mode}</code>` +
            ` · PAD ${padOn ? "enabled" : "disabled"}` +
            (s2.pad_loo_auc != null ? ` (LOO ${Number(s2.pad_loo_auc).toFixed(3)})` : "") +
            ` · cal ${calTs}` +
            retrain;
        }
        const thrEl = document.getElementById("threshold-banner");
        if (thrEl) {
          if (thr.mode === "demo_override" || thr.demo_banner) {
            const cur = thr.current || {};
            const stock = thr.stock || {};
            thrEl.style.display = "";
            thrEl.innerHTML =
              "<strong>DEMO / OVERRIDE THRESHOLDS</strong> — not stock policy.yaml. " +
              `voice ${stock.ladder_voice}→${cur.ladder_voice} · ` +
              `face ${stock.ladder_face}→${cur.ladder_face}. ` +
              "Lower bars do not improve match quality.";
          } else {
            thrEl.style.display = "none";
            thrEl.textContent = "";
          }
        }
      } catch (e) { /* ignore */ }
    }

    const FEATURED_SCENARIOS = [
      "genuine_driver",
      "finger_otp_fallback",
      "face_replay",
      "zone_novel_stepup",
    ];

    async function loadScenarios() {
      const list = await (await fetch("/api/scenarios")).json();
      const mkBtn = (s) =>
        `<button class="scenario-btn" onclick='applyScenario(${JSON.stringify({request: s.request, profile: s.profile || "mature"})})'>${s.label}</button>`;
      const featured = list.filter(s => FEATURED_SCENARIOS.includes(s.id));
      const rest = list.filter(s => !FEATURED_SCENARIOS.includes(s.id));
      const row = document.getElementById("scenario-row");
      if (row) row.innerHTML = featured.map(mkBtn).join("");
      document.getElementById("scenarios").innerHTML = rest.map(mkBtn).join("") +
        (featured.length ? featured.map(mkBtn).join("") : "");
    }

    async function ensureProfile(mode) {
      const path = mode === "bootstrap" ? "/api/profile/bootstrap" : "/api/profile/mature";
      await adminFetch(path, { method: "POST" });
    }

    async function applyScenario(s) {
      await ensureProfile(s.profile || "mature");
      applyPayload(s.request);
      await runAuth();
      // Clear one-shot demo knobs after run so manual sliders don't stick in OTP mode.
      window.__demoFingerAvail = null;
      window.__demoStage3Mode = null;
      window.__demoOtp = false;
    }

    async function fraudFlag() {
      await adminFetch("/api/fraud/soft-flag", { method: "POST" });
      loadStatus();
    }
    async function fraudClean() {
      await adminFetch("/api/fraud/clean", { method: "POST" });
      loadStatus();
    }
    async function fraudReset() {
      await adminFetch("/api/fraud/reset", { method: "POST" });
      loadStatus();
    }
    async function resetSession() {
      await adminFetch("/api/reset?mature=true", { method: "POST" });
      loadStatus();
      loadAudit();
      resetPipelineVisual();
      setLivePill("idle", "Idle");
      document.getElementById("path-summary").textContent = "Session reset. Run authenticate to stream the pipeline.";
    }

    ["amount","beneficiary","action","currency","channel","speed","dist_home","gps_lat","gps_lon","gps_accuracy_m"]
      .forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("input", () => refreshSources());
      });
    ["beneficiary_known","is_guest","trusted_zone","ignition_on","tunnel"]
      .forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener("change", () => refreshSources());
      });

    renderPhases();
    if (!document.body.classList.contains("mode-standalone")) {
      refreshSources();
      loadScenarios();
    }
    loadStatus();
    loadAudit();
    loadPerfStrip();
    loadModalityBadges();
    // STANDALONE_PAY_JS
    if (document.body.classList.contains("mode-standalone")
        && typeof initStandalonePay === "function") {
      initStandalonePay().catch((e) => console.warn("standalone pay", e));
    }
  </script>
</body>
</html>"""
    pay_html = panel_html() if mode == "standalone" else ""
    pay_js = panel_script() if mode == "standalone" else ""
    pay_css = panel_css() if mode == "standalone" else ""
    sub = (
        "Standalone · OpenRouter STT/TTS · live ECAPA/face · Maps GPS"
        if mode == "standalone"
        else "Manual · slider stand-ins · Trust / Risk / Confidence pipeline"
    )
    return (
        html.replace("__PAGE_TITLE__", title)
        .replace("__BODY_MODE__", f"mode-{mode}")
        .replace("__PAGE_SUB__", sub)
        .replace("__NAV_MANUAL__", "active" if mode == "manual" else "")
        .replace("__NAV_STANDALONE__", "active" if mode == "standalone" else "")
        .replace("/* STANDALONE_PAY_CSS */", pay_css)
        .replace("<!-- STANDALONE_PAY -->", pay_html)
        .replace("// STANDALONE_PAY_JS", (pay_js + "\n    ") if pay_js else "")
    )
