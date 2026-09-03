"""HTML documentation landing page and live playground.

Ports the shared Command-Code-style design system used across every Stat APIs
service (see GitHub/routes/docs.py), recolored to the forge accent orange.
Registered before the catch-all ``/{username}`` route so ``/`` and
``/playground`` resolve here.
"""

import json
import re
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from services.registry import parse_instances

router = APIRouter(tags=["Documentation"])

PLATFORM = "GitHost"
PLATFORM_KEY = "githost"
ACCENT = "#fb923c"
_ACCENT_INK = "#050506"
DESCRIPTION = (
    "Profile, repository, commit, and heatmap analytics for Forgejo, Gitea, "
    "and Codeberg, or any Gitea-compatible instance by base URL."
)
PARAM = "username"
SAMPLE = "taf"
TRY_PATH = "/taf/profile?host=git.taf.sh"
REPO = "tashifkhan/GitHost-Stats-API"

CANONICAL_ENDPOINTS = [
    ("GET", "/{username}", "Summary"),
    ("GET", "/{username}/profile", "Profile"),
    ("GET", "/{username}/stats", "Commit totals and language topics"),
    ("GET", "/{username}/stats/svg", "Embeddable stats SVG card (theme, exclude; 24h cache)"),
    ("GET", "/{username}/heatmap", "Contribution heatmap"),
    ("GET", "/{username}/badges", "Derived achievements"),
    ("GET", "/{username}/repos", "Repositories with star/fork totals"),
    ("GET", "/{username}/orgs", "Organization memberships"),
]
LEGACY_ENDPOINTS = []

# ── Shared Command-Code-style design system (identical across every platform) ──

_BASE_CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --bg:#000;--panel:#0a0a0c;--panel-2:#121214;
  --ink:#fafafa;--muted:#9b9ba4;--faint:#6b6b73;
  --line:#1f1f22;--line-2:#2a2a2f;--guide:rgba(255,255,255,.12);
  --accent-ink:#050506;--r:6px;
  --sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,'Liberation Mono','Courier New',monospace;
}
html{scroll-behavior:smooth;overflow-x:clip}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased;overflow-x:clip;max-width:100%}
body.nav-open{overflow:hidden}
a{color:inherit;text-decoration:none}
::selection{background:color-mix(in srgb,var(--accent) 38%,transparent)}
*::-webkit-scrollbar{width:9px;height:9px}
*::-webkit-scrollbar-thumb{background:var(--line-2);border-radius:6px}

.topbar{position:sticky;top:0;z-index:50;height:54px;display:flex;align-items:center;gap:14px;padding:0 20px;overflow:hidden;
  background:color-mix(in srgb,var(--bg) 78%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:9px;flex:1 1 auto;min-width:0;font-family:var(--mono);font-weight:600;letter-spacing:-.01em;font-size:14.5px}
.brand .glyph{flex:none;display:grid;place-items:center;width:24px;height:24px;border-radius:var(--r);background:var(--accent);color:var(--accent-ink);font-size:13px;font-weight:800;text-transform:uppercase}
.brand .glyph svg{width:15px;height:15px}
.brand-text{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.brand .sub{color:var(--faint);font-weight:500}
.topnav{margin-left:auto;display:flex;align-items:center;gap:2px;flex:none}
.topnav a{padding:6px 11px;border-radius:var(--r);color:var(--muted);font-size:13px;font-weight:500;transition:.15s;white-space:nowrap}
.topnav a:hover{color:var(--ink);background:var(--panel-2)}
.topnav a.cta{color:var(--accent-ink);background:var(--accent);font-weight:600}
.topnav a.cta:hover{filter:brightness(1.08)}
.topnav a.icon{display:grid;place-items:center;width:32px;height:32px;padding:0;color:var(--muted);border:1px solid var(--line);border-radius:var(--r)}
.topnav a.icon:hover{color:var(--ink);background:var(--panel-2);border-color:var(--line-2)}
.topnav a.icon svg{width:16px;height:16px}

.wrap{display:grid;grid-template-columns:262px minmax(0,1fr) 224px;max-width:1480px;margin:0 auto;min-width:0}
aside.side{position:sticky;top:54px;align-self:start;height:calc(100vh - 54px);overflow:auto;padding:22px 14px 48px;border-right:1px solid var(--line)}
.search{display:flex;align-items:center;gap:8px;width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:var(--r);background:var(--panel);color:var(--faint);font-size:13px;margin-bottom:20px}
.search svg{flex:none;opacity:.7}
.search input{border:0;background:transparent;color:var(--ink);font-family:var(--sans);font-size:13px;width:100%;outline:none}
.search kbd{font-family:var(--mono);font-size:11px;color:var(--faint);border:1px solid var(--line);border-radius:4px;padding:1px 5px}
.navgroup{margin-bottom:20px}
.navgroup h4{margin:0 0 6px;padding:0 8px;font-size:11px;font-weight:600;letter-spacing:.13em;text-transform:uppercase;color:var(--faint)}
.navgroup a{display:block;padding:6px 10px;border-radius:var(--r);color:var(--muted);font-size:13.5px;transition:.12s;outline:none;-webkit-tap-highlight-color:transparent}
.navgroup a:focus,.navgroup a:focus-visible{outline:none;box-shadow:none}
.navgroup a:hover{color:var(--ink);background:var(--panel-2)}
.navgroup a.active{color:var(--ink);background:color-mix(in srgb,var(--accent) 13%,transparent)}

main.doc{min-width:0;padding:42px 52px 96px;overflow-x:clip}
.eyebrow{color:var(--accent);font-family:var(--mono);font-size:12px;letter-spacing:.15em;text-transform:uppercase;margin-bottom:13px}
h1.title{font-size:clamp(32px,4.4vw,46px);line-height:1.05;letter-spacing:-.025em;margin:0 0 16px;font-weight:700;overflow-wrap:anywhere}
.lede{color:var(--muted);font-size:17px;line-height:1.7;max-width:660px;margin:0 0 4px}
.metarow{display:flex;flex-wrap:wrap;gap:7px;margin:22px 0 6px}
.chip{font-family:var(--mono);font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:var(--r);padding:4px 10px;background:var(--panel)}

.steps{position:relative;margin-top:10px;padding-left:34px;border-left:1px dashed var(--guide)}
.section{padding-top:48px;scroll-margin-top:78px}
.section-head{position:relative;display:flex;align-items:center;gap:13px;margin-bottom:14px}
.step{position:absolute;left:-49px;top:-2px;display:grid;place-items:center;width:30px;height:30px;border-radius:var(--r);
  background:var(--bg);border:1px solid var(--line-2);color:var(--ink);font-family:var(--mono);font-weight:600;font-size:13.5px}
.section-head h2{margin:0;font-size:21px;letter-spacing:-.02em;font-weight:650}
.section p{color:var(--muted);max-width:660px;margin:0 0 4px}
.section a.link{color:var(--accent);border-bottom:1px solid color-mix(in srgb,var(--accent) 45%,transparent)}

.code{position:relative;border:1px solid var(--line);border-radius:var(--r);background:var(--panel);overflow:hidden;margin:16px 0;max-width:min(740px,100%)}
.code::before{content:"";position:absolute;left:0;top:10px;bottom:10px;width:2px;border-radius:2px;background:var(--accent);z-index:1}
.code .cap{display:flex;align-items:center;gap:8px;padding:9px 13px;border-bottom:1px solid var(--line);font-family:var(--mono);font-size:12px;color:var(--muted)}
.code .cap .dot{width:8px;height:8px;border-radius:50%;background:var(--accent);opacity:.85}
.code .copy{margin-left:auto;cursor:pointer;color:var(--faint);font-size:11px;font-family:var(--mono);border:1px solid var(--line);border-radius:5px;padding:3px 8px;background:transparent}
.code .copy:hover{color:var(--ink);border-color:var(--line-2)}
.code pre{margin:0;padding:15px 16px;overflow:auto;font-family:var(--mono);font-size:13px;line-height:1.7;color:#d6d6dc}
.code.small pre{font-size:12.5px;max-height:360px}
.code .cmt{color:var(--faint)}

.callout{position:relative;display:flex;gap:11px;border:1px solid var(--line);border-radius:var(--r);background:color-mix(in srgb,var(--accent) 6%,var(--panel));padding:13px 15px 13px 18px;margin:16px 0;max-width:min(740px,100%)}
.callout::before{content:"";position:absolute;left:0;top:10px;bottom:10px;width:2px;border-radius:2px;background:var(--accent)}
.callout .ic{flex:none;color:var(--accent);font-weight:700;font-family:var(--mono)}
.callout .t{color:var(--accent);font-weight:600;font-size:13px}
.callout p{margin:3px 0 0;color:var(--muted);font-size:14px}
.callout b{color:var(--ink)}

.eps{display:grid;gap:8px;margin:16px 0;max-width:min(760px,100%)}
.ep{position:relative;border:1px solid var(--line);border-radius:var(--r);background:var(--panel);overflow:hidden;transition:border-color .15s;min-width:0;max-width:100%}
.ep.open{border-color:color-mix(in srgb,var(--accent) 28%,var(--line))}
.ep.open::before{content:"";position:absolute;left:0;top:10px;bottom:10px;width:2px;border-radius:2px;background:var(--accent);z-index:3}
.ep-head{display:flex;align-items:center;gap:13px;width:100%;min-width:0;text-align:left;background:transparent;border:0;color:inherit;cursor:pointer;padding:12px 14px;font:inherit}
.ep-head:hover{background:var(--panel-2)}
.ep.open .ep-head{background:var(--panel-2)}
.ep .verb{flex:none;font-family:var(--mono);font-weight:700;font-size:11px;letter-spacing:.04em;color:var(--accent-ink);background:var(--accent);border-radius:4px;padding:3px 8px}
.ep-path{font-family:var(--mono);font-size:13.5px;color:var(--ink);min-width:0;overflow-wrap:anywhere}
.ep-desc{margin-left:auto;color:var(--muted);font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:42%}
.chev{flex:none;color:var(--faint);font-family:var(--mono);transition:.2s;transform:rotate(0)}
.ep.open .chev{transform:rotate(90deg);color:var(--accent)}
.ep-body{display:none;padding:2px 15px 16px;border-top:1px solid var(--line);overflow-x:auto}
.ep.open .ep-body{display:block}
.ep-sub{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--faint);margin:15px 0 8px;font-weight:600}
.ep-note{color:var(--muted);font-size:13px;margin:4px 0}
.ptable{width:100%;border-collapse:collapse;font-size:13px}
.ptable th{text-align:left;color:var(--faint);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.07em;padding:6px 10px;border-bottom:1px solid var(--line)}
.ptable td{padding:8px 10px;border-bottom:1px solid var(--line);color:var(--muted);vertical-align:top;overflow-wrap:anywhere}
.ptable tr:last-child td{border-bottom:0}
.ptable td code{font-family:var(--mono);color:var(--ink)}
.req{font-family:var(--mono);font-size:11px;color:var(--accent)}.opt{font-family:var(--mono);font-size:11px;color:var(--faint)}

code.ic{font-family:var(--mono);font-size:.86em;background:var(--panel-2);border:1px solid var(--line);border-radius:4px;padding:1px 5px;color:var(--ink)}

.foot{margin-top:56px;padding-top:22px;border-top:1px solid var(--line);display:flex;flex-wrap:wrap;gap:14px;justify-content:space-between;color:var(--faint);font-size:13px}
.foot a{color:var(--muted)}.foot a:hover{color:var(--ink)}

aside.toc{position:sticky;top:54px;align-self:start;height:calc(100vh - 54px);overflow:auto;padding:44px 22px}
.toc h5{margin:0 0 13px;font-size:11px;font-weight:600;letter-spacing:.13em;text-transform:uppercase;color:var(--faint)}
.toc a{display:block;padding:6px 0 6px 13px;border-left:1px solid var(--line);color:var(--faint);font-size:13px;transition:.12s}
.toc a:hover{color:var(--ink)}
.toc a.active{color:var(--accent);border-left-color:var(--accent)}

.menu-btn{display:none}
.nav-scrim{display:none}
@media(max-width:1180px){.wrap{grid-template-columns:262px minmax(0,1fr)}aside.toc{display:none}}
@media(max-width:860px){
  .wrap{grid-template-columns:minmax(0,1fr)}
  .topbar{padding:0 14px;gap:10px}
  .topnav a:not(.cta):not(.icon){display:none}
  aside.side{position:fixed;left:0;top:0;bottom:0;width:min(300px,86vw);height:100dvh;min-height:100%;align-self:stretch;padding:62px 14px calc(28px + env(safe-area-inset-bottom,0px));background:var(--bg);z-index:45;transform:translateX(-105%);visibility:hidden;pointer-events:none;transition:transform .2s ease,visibility .2s ease;border-right:1px solid var(--line);-webkit-overflow-scrolling:touch}
  aside.side.open{transform:none;visibility:visible;pointer-events:auto}
  .nav-scrim{display:block;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:44;opacity:0;visibility:hidden;pointer-events:none;transition:opacity .2s ease,visibility .2s ease}
  .nav-scrim.open{opacity:1;visibility:visible;pointer-events:auto}
  main.doc{padding:28px 18px 80px}
  .steps{padding-left:0;border-left:0}
  .step{position:static;left:auto;top:auto}
  .menu-btn{display:inline-grid;place-items:center;width:32px;height:32px;flex:none;border:1px solid var(--line);border-radius:var(--r);background:var(--panel);color:var(--ink);cursor:pointer;font-size:18px;line-height:1}
  h1.title{font-size:clamp(26px,8vw,32px)}
  .lede{font-size:16px}
  .ep-desc{display:none}
  .ep-head{gap:8px;flex-wrap:wrap}
  .ep-path{font-size:12.5px}
  .code pre{white-space:pre-wrap;word-break:break-word}
  .search kbd{display:none}
  .section-head{flex-wrap:wrap}
}
@media(max-width:420px){
  .topnav a.icon{display:none}
  .brand .sub{display:none}
  .topbar{padding:0 12px;gap:8px}
}
"""

_PLAYGROUND_CSS = """
.pg-main{max-width:760px;margin:0 auto;padding:56px 24px 110px}
.pg-eyebrow{text-align:center;color:var(--accent);font-family:var(--mono);font-size:12px;letter-spacing:.15em;text-transform:uppercase;margin-bottom:14px;animation:pg-fade-up .5s ease both}
.pg-h1{text-align:center;font-family:var(--mono);font-size:clamp(26px,4vw,38px);letter-spacing:-.02em;margin:0 0 14px;animation:pg-fade-up .5s .05s ease both}
.pg-sub{text-align:center;color:var(--muted);font-size:15px;line-height:1.65;max-width:600px;margin:0 auto 36px;animation:pg-fade-up .5s .1s ease both}

@keyframes pg-fade-up{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
@keyframes pg-spin{to{transform:rotate(360deg)}}
@keyframes pg-pulse-bar{0%,100%{opacity:1}50%{opacity:.3}}
@keyframes pg-shimmer{0%{background-position:-220px 0}100%{background-position:220px 0}}
@keyframes pg-shake{10%,90%{transform:translateX(-1px)}20%,80%{transform:translateX(2px)}30%,50%,70%{transform:translateX(-4px)}40%,60%{transform:translateX(4px)}}
@keyframes pg-ring{0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--accent) 45%,transparent)}100%{box-shadow:0 0 0 9px transparent}}

.pg-bar{position:sticky;top:66px;z-index:10;background:color-mix(in srgb,var(--panel) 92%,transparent);backdrop-filter:blur(10px);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:32px;animation:pg-fade-up .5s .15s ease both;transition:border-color .2s,box-shadow .2s}
.pg-bar:focus-within{border-color:color-mix(in srgb,var(--accent) 50%,var(--line));box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 12%,transparent)}
.pg-bar-row{display:flex;gap:10px;align-items:flex-start}
.pg-input-wrap{position:relative;flex:1;min-width:0}
.pg-input-icon{position:absolute;left:13px;top:50%;transform:translateY(-50%);color:var(--faint);display:flex;pointer-events:none;transition:color .15s}
.pg-input-wrap:focus-within .pg-input-icon{color:var(--accent)}
.pg-input{width:100%;background:var(--bg);border:1px solid var(--line-2);border-radius:var(--r);padding:11px 34px 11px 38px;color:var(--ink);font-family:var(--mono);font-size:14px;outline:none;transition:border-color .15s,box-shadow .15s}
.pg-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 16%,transparent)}
.pg-input.shake{animation:pg-shake .4s ease}
#pg-host.shake{animation:pg-shake .4s ease}
.pg-input-clear{position:absolute;right:6px;top:50%;transform:translateY(-50%);width:22px;height:22px;display:none;align-items:center;justify-content:center;border:0;border-radius:50%;background:transparent;color:var(--faint);font-size:16px;line-height:1;cursor:pointer;transition:.15s}
.pg-input-clear:hover{background:var(--line);color:var(--ink)}
.pg-input-wrap.has-value .pg-input-clear{display:flex}
.pg-target{display:flex;flex-direction:column;gap:5px;min-width:170px}
.pg-target label{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);font-family:var(--mono)}
.pg-target select,.pg-target input{background:var(--bg);border:1px solid var(--line-2);border-radius:var(--r);padding:10px 11px;color:var(--ink);font-family:var(--mono);font-size:13px;outline:none;height:42px}
.pg-target select:focus,.pg-target input:focus{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 16%,transparent)}
.pg-btn{position:relative;display:flex;align-items:center;justify-content:center;gap:7px;background:var(--accent);color:var(--accent-ink);border:0;border-radius:var(--r);padding:0 18px;font-weight:700;font-family:var(--mono);cursor:pointer;font-size:14px;white-space:nowrap;transition:filter .15s,transform .08s}
.pg-btn:hover{filter:brightness(1.08)}
.pg-btn:active{transform:scale(.97)}
.pg-btn:disabled{opacity:.7;cursor:default;transform:none}
.pg-runall{flex:none;min-width:118px;height:42px}
.pg-hint{margin:12px 2px 0;color:var(--faint);font-size:12.5px;line-height:1.6;overflow-wrap:anywhere}

.pg-progress{height:3px;border-radius:3px;background:var(--line);overflow:hidden;margin:14px 2px 0;max-height:0;opacity:0;transition:max-height .2s ease,opacity .2s ease,margin .2s ease}
.pg-progress.active{max-height:3px;opacity:1}
.pg-progress-bar{height:100%;width:0%;background:var(--accent);border-radius:3px;transition:width .3s ease}

.pg-recent{position:absolute;top:calc(100% + 8px);left:0;right:0;background:var(--panel-2);border:1px solid var(--line-2);border-radius:var(--r);padding:6px;z-index:20;max-height:230px;overflow:auto;box-shadow:0 12px 28px rgba(0,0,0,.45);opacity:0;transform:translateY(-6px) scale(.98);pointer-events:none;transition:opacity .15s ease,transform .15s ease}
.pg-recent.open{opacity:1;transform:translateY(0) scale(1);pointer-events:auto}
.pg-recent-head{display:flex;justify-content:space-between;align-items:center;padding:6px 8px;font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--faint)}
.pg-recent-head button{background:none;border:0;color:var(--faint);cursor:pointer;font-size:12px;font-family:var(--sans)}
.pg-recent-head button:hover{color:var(--ink)}
.pg-recent-item{display:block;width:100%;text-align:left;background:none;border:0;color:var(--muted);font-family:var(--mono);padding:8px;border-radius:6px;cursor:pointer;font-size:13.5px;transition:background .1s}
.pg-recent-item:hover{background:var(--line);color:var(--ink)}

.pg-group-label{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:8px 0 12px;font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--faint)}
.pg-canonical-list{animation:pg-fade-up .4s .2s ease both}

.pg-status{flex:none;display:inline-flex;align-items:center;gap:5px;font-family:var(--mono);font-size:11px;color:var(--faint);border:1px solid var(--line);border-radius:5px;padding:3px 8px;white-space:nowrap;transition:color .15s,border-color .15s}
.pg-status.ok{color:#3fb950;border-color:color-mix(in srgb,#3fb950 45%,var(--line))}
.pg-status.err{color:#f85149;border-color:color-mix(in srgb,#f85149 45%,var(--line))}
.pg-status.busy{color:var(--accent);border-color:color-mix(in srgb,var(--accent) 35%,var(--line))}
.pg-run-btn{position:relative;flex:none;display:inline-flex;align-items:center;justify-content:center;gap:6px;min-width:46px;background:var(--accent);color:var(--accent-ink);border:0;border-radius:5px;padding:5px 12px;font-weight:700;font-family:var(--mono);font-size:12px;cursor:pointer;transition:filter .15s,transform .08s}
.pg-run-btn:hover{filter:brightness(1.08)}
.pg-run-btn:active{transform:scale(.95)}
.pg-run-btn:disabled{opacity:.7;cursor:default;transform:none}
.ep[data-path]{transition:border-color .15s,transform .15s,box-shadow .15s}
.ep[data-path]:hover{transform:translateY(-1px);box-shadow:0 6px 18px rgba(0,0,0,.28)}
.ep.ok::before{background:#3fb950}
.ep.err::before{background:#f85149}
.ep.busy::before{background:var(--accent);animation:pg-pulse-bar 1s ease-in-out infinite}
.ep.ok{animation:pg-ring .5s ease}

.pg-spinner{width:13px;height:13px;flex:none;border-radius:50%;border:2px solid color-mix(in srgb,currentColor 25%,transparent);border-top-color:currentColor;animation:pg-spin .7s linear infinite}
.pg-run-btn .pg-spinner{width:11px;height:11px}

.pg-placeholder{color:var(--faint)}
.pg-ep-loading{padding:4px 0 12px}
.pg-ep-loading .req{color:var(--faint);font-family:var(--mono);font-size:12px;margin:0 0 10px;display:flex;align-items:center;gap:7px}
.pg-skel{height:11px;border-radius:4px;margin:8px 0;background:linear-gradient(90deg,var(--line) 25%,var(--line-2) 50%,var(--line) 75%);background-size:440px 100%;animation:pg-shimmer 1.3s linear infinite}
.pg-skel.w90{width:90%}.pg-skel.w70{width:70%}.pg-skel.w50{width:50%}.pg-skel.w35{width:35%}
.pg-ep-meta{display:flex;align-items:center;gap:8px;margin:10px 0 8px;animation:pg-fade-up .3s ease both}
.pg-ep-meta .url{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;font-family:var(--mono);font-size:11.5px;color:var(--muted)}
.pg-copy{flex:none;cursor:pointer;color:var(--faint);font-size:11px;font-family:var(--mono);border:1px solid var(--line);border-radius:5px;padding:3px 8px;background:transparent;transition:.15s}
.pg-copy:hover{color:var(--ink);border-color:var(--line-2)}
.pg-ep-resp{margin:0;padding:12px 14px;overflow:auto;max-height:420px;font-family:var(--mono);font-size:12.5px;line-height:1.7;color:#d6d6dc;background:var(--bg);border:1px solid var(--line);border-radius:var(--r)}

.pg-tabs{display:flex;gap:6px;margin:2px 0 14px;animation:pg-fade-up .3s ease both}
.pg-tab-btn{background:none;border:1px solid var(--line);color:var(--muted);font-family:var(--mono);font-size:11.5px;padding:5px 12px;border-radius:5px;cursor:pointer;transition:.15s}
.pg-tab-btn:hover{color:var(--ink)}
.pg-tab-btn.active{background:var(--panel-2);color:var(--ink);border-color:var(--line-2)}
.pg-view[hidden]{display:none}
.pg-view{animation:pg-fade-up .25s ease both}

.pg-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px;margin:2px 0}
.pg-card{background:var(--bg);border:1px solid var(--line);border-radius:var(--r);padding:11px 13px}
.pg-card-lbl{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);margin-bottom:6px;font-family:var(--mono)}
.pg-card-val{font-size:14px;font-weight:600;color:var(--ink);font-family:var(--mono);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

.pg-section{margin:18px 0 4px}
.pg-section-lbl{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--faint);font-family:var(--mono);margin:0 0 8px}

.pg-table-wrap{overflow:auto;border:1px solid var(--line);border-radius:var(--r);max-height:360px}
.pg-table{width:100%;border-collapse:collapse;font-size:12.5px}
.pg-table th{position:sticky;top:0;text-align:left;color:var(--faint);font-weight:500;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;padding:8px 10px;border-bottom:1px solid var(--line);background:var(--panel-2);white-space:nowrap}
.pg-table td{padding:7px 10px;border-bottom:1px solid var(--line);color:var(--muted);font-family:var(--mono);white-space:nowrap;max-width:240px;overflow:hidden;text-overflow:ellipsis}
.pg-table tr:last-child td{border-bottom:0}
.pg-table-note{color:var(--faint);font-size:11.5px;margin:6px 2px 0}

.pg-chips{display:flex;flex-wrap:wrap;gap:6px}
.pg-chip{font-family:var(--mono);font-size:12px;color:var(--muted);border:1px solid var(--line);border-radius:5px;padding:3px 9px;background:var(--bg)}
.pg-empty{color:var(--faint);font-size:12.5px;margin:4px 0}

.pg-foot-note{text-align:center;color:var(--faint);font-size:13px;margin-top:40px}

@media(max-width:640px){
  .pg-bar-row{flex-direction:column}
  .pg-runall{width:100%;justify-content:center}
  .pg-svg-controls{flex-direction:column;align-items:stretch}
  .pg-svg-controls .pg-btn{width:100%;justify-content:center}
  .pg-main{padding:36px 16px 90px;overflow-x:clip}
  .pg-h1{font-size:clamp(22px,8vw,32px)}
}

.pg-svg-controls{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin-bottom:14px}
.pg-svg-field{display:flex;flex-direction:column;gap:5px;min-width:120px;flex:1}
.pg-svg-field label{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);font-family:var(--mono)}
.pg-svg-field input,.pg-svg-field select{background:var(--bg);border:1px solid var(--line-2);border-radius:var(--r);padding:9px 11px;color:var(--ink);font-family:var(--mono);font-size:13px;outline:none}
.pg-svg-field input:focus,.pg-svg-field select:focus{border-color:var(--accent);box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 16%,transparent)}
.pg-svg-check{display:flex;align-items:center;gap:7px}
.pg-svg-check input{width:auto}
.pg-svg-check span{font-size:12px;color:var(--muted)}
.pg-ep-svg{display:flex;justify-content:center;padding:12px;background:var(--bg);border:1px solid var(--line);border-radius:var(--r)}
.pg-ep-svg img{max-width:100%;height:auto}
.pg-ep-qparams{margin:0 0 12px;padding:12px;border:1px solid var(--line);border-radius:var(--r);background:var(--panel-2)}
.pg-ep-qparams-lbl{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);font-family:var(--mono);margin:0 0 10px}
.pg-ep-qhint{margin:10px 0 0;color:var(--faint);font-size:12px;line-height:1.55}
.pg-ep-qhint .ic{font-size:11px}
"""

_JS = """
document.querySelectorAll('[data-origin]').forEach(function(el){var o=location.origin;el.textContent=(o&&o!=='null')?o:'https://your-host'});
document.querySelectorAll('.copy').forEach(function(b){b.addEventListener('click',function(e){
  e.stopPropagation();
  var pre=b.closest('.code').querySelector('pre');
  navigator.clipboard.writeText(pre.innerText).then(function(){var t=b.textContent;b.textContent='Copied';setTimeout(function(){b.textContent=t},1200)});
})});
document.querySelectorAll('.ep-head').forEach(function(h){h.addEventListener('click',function(){
  var ep=h.parentElement,open=ep.classList.toggle('open');
  h.setAttribute('aria-expanded',open?'true':'false');
})});
var mb=document.querySelector('.menu-btn'),sb=document.querySelector('.side'),scrim=document.querySelector('.nav-scrim');
function isMobileNav(){ return window.matchMedia('(max-width:860px)').matches; }
function setNav(open){
  if(!sb) return;
  var mobile = isMobileNav();
  sb.classList.toggle('open', open);
  if(scrim) scrim.classList.toggle('open', open);
  document.body.classList.toggle('nav-open', mobile && open);
  if(mb){
    mb.setAttribute('aria-expanded', open ? 'true' : 'false');
    mb.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
    mb.innerHTML = open ? '&times;' : '&#9776;';
  }
  if('inert' in sb) sb.inert = mobile && !open;
}
if(mb) mb.addEventListener('click', function(){ setNav(!sb.classList.contains('open')); });
if(scrim) scrim.addEventListener('click', function(){ setNav(false); });
if(sb) sb.querySelectorAll('a').forEach(function(a){ a.addEventListener('click', function(){ if(isMobileNav()) setNav(false); }); });
document.addEventListener('keydown', function(e){ if(e.key === 'Escape') setNav(false); });
window.addEventListener('resize', function(){ if(!isMobileNav()) setNav(false); });
if(isMobileNav()) setNav(false);
var toc={},nav={};
document.querySelectorAll('[data-toc]').forEach(function(a){toc[a.getAttribute('href').slice(1)]=a});
document.querySelectorAll('[data-nav]').forEach(function(a){nav[a.getAttribute('href').slice(1)]=a});
var io=new IntersectionObserver(function(es){es.forEach(function(e){if(e.isIntersecting){
  var id=e.target.id;
  Object.keys(toc).forEach(function(k){toc[k].classList.remove('active')});
  Object.keys(nav).forEach(function(k){nav[k].classList.remove('active')});
  if(toc[id])toc[id].classList.add('active');
  if(nav[id])nav[id].classList.add('active');
}})},{rootMargin:'-12% 0px -75% 0px'});
document.querySelectorAll('.section').forEach(function(s){io.observe(s)});
var si=document.querySelector('.search input');
if(si)si.addEventListener('input',function(){var q=si.value.toLowerCase();
  document.querySelectorAll('.navgroup a').forEach(function(a){a.style.display=a.textContent.toLowerCase().indexOf(q)>-1?'':'none'});
});
function playgroundPath(){
  var base = window.location.pathname.replace(new RegExp('/(docs|redoc)/?$'), '').replace(new RegExp('/$'), '');
  return (base || '') + '/playground';
}
document.querySelectorAll('a[href="/playground"]').forEach(function(a){
  var href = playgroundPath();
  a.setAttribute('href', href);
  a.addEventListener('click', function(e){ e.preventDefault(); window.location.assign(href); });
});
"""

_PLAYGROUND_JS = """
(function(){
  var STORE_KEY = 'pg_recent_' + PLATFORM_KEY;
  var form = document.querySelector('.pg-form');
  var input = document.querySelector('.pg-input');
  var inputWrap = document.querySelector('.pg-input-wrap');
  var clearBtn = document.querySelector('.pg-input-clear');
  var runAllBtn = document.querySelector('.pg-runall');
  var runAllDefaultHTML = runAllBtn.innerHTML;
  var progressEl = document.querySelector('.pg-progress');
  var progressBarEl = document.querySelector('.pg-progress-bar');
  var recentBox = document.querySelector('.pg-recent');
  var canonicalEps = Array.prototype.slice.call(document.querySelectorAll('.pg-canonical-list .ep'));
  var allEps = Array.prototype.slice.call(document.querySelectorAll('.ep[data-path]'));
  var hostSel = document.getElementById('pg-host');
  var buWrap = document.getElementById('pg-bu-wrap');
  var buInput = document.getElementById('pg-baseurl');
  var emInput = document.getElementById('pg-emails');

  if(hostSel){
    hostSel.addEventListener('change', function(){
      if(buWrap) buWrap.style.display = hostSel.value === 'custom' ? '' : 'none';
    });
  }

  function syncHasValue(){ inputWrap.classList.toggle('has-value', input.value.length > 0); }
  syncHasValue();
  input.addEventListener('input', syncHasValue);
  input.addEventListener('animationend', function(){ input.classList.remove('shake'); });
  if(clearBtn){
    clearBtn.addEventListener('click', function(){
      input.value = ''; syncHasValue(); input.focus(); recentBox.classList.remove('open');
    });
  }

  function getRecent(){ try{ return JSON.parse(localStorage.getItem(STORE_KEY)) || []; }catch(e){ return []; } }
  function saveRecent(list){ localStorage.setItem(STORE_KEY, JSON.stringify(list.slice(0, 6))); }
  function pushRecent(h){
    var list = getRecent().filter(function(x){ return x.toLowerCase() !== h.toLowerCase(); });
    list.unshift(h);
    saveRecent(list);
    renderRecent();
  }
  function renderRecent(){
    var list = getRecent();
    if(!list.length){ recentBox.classList.remove('open'); recentBox.innerHTML=''; return; }
    recentBox.innerHTML = '<div class="pg-recent-head">Recent Searches<button type="button" class="pg-clear">Clear</button></div>' +
      list.map(function(h){ return '<button type="button" class="pg-recent-item">' + h.replace(/</g,'&lt;') + '</button>'; }).join('');
    recentBox.querySelector('.pg-clear').addEventListener('click', function(e){ e.stopPropagation(); saveRecent([]); renderRecent(); });
    Array.prototype.forEach.call(recentBox.querySelectorAll('.pg-recent-item'), function(b){
      b.addEventListener('click', function(){ input.value = b.textContent; syncHasValue(); recentBox.classList.remove('open'); });
    });
  }
  renderRecent();
  input.addEventListener('focus', function(){ if(getRecent().length) recentBox.classList.add('open'); });
  document.addEventListener('click', function(e){ if(!recentBox.contains(e.target) && e.target !== input) recentBox.classList.remove('open'); });

  function escHtml(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  function collectTargetParams(q){
    if(hostSel){
      if(!hostSel.value){ return false; }
      if(hostSel.value === 'custom'){
        var b = (buInput && buInput.value || '').trim();
        if(!b){ return false; }
        q.push('base_url=' + encodeURIComponent(b));
      } else {
        q.push('host=' + encodeURIComponent(hostSel.value));
      }
    }
    if(emInput && emInput.value.trim()){
      q.push('emails=' + encodeURIComponent(emInput.value.trim()));
    }
    return true;
  }
  function collectEpParams(ep, q){
    Array.prototype.forEach.call(ep.querySelectorAll('.pg-ep-qparams .pg-q'), function(el){
      var k = el.getAttribute('data-q');
      if(el.type === 'checkbox'){
        if(el.checked) q.push(k + '=true');
      } else if(el.value && String(el.value).trim()){
        q.push(k + '=' + encodeURIComponent(String(el.value).trim()));
      }
    });
  }
  function buildUrl(tmpl, value, ep){
    var url = tmpl.replace(/\\{[^}]+\\}/g, function(){ return encodeURIComponent(value); });
    var q = [];
    if(!collectTargetParams(q)){ return null; }
    collectEpParams(ep, q);
    if(q.length) url += (url.indexOf('?') === -1 ? '?' : '&') + q.join('&');
    return url;
  }

  function nudgeHost(){
    if(!hostSel){ return; }
    hostSel.classList.remove('shake');
    void hostSel.offsetWidth;
    hostSel.classList.add('shake');
    hostSel.focus();
  }

  function isPlainObject(v){ return v !== null && typeof v === 'object' && !Array.isArray(v); }
  function isScalar(v){ return v === null || typeof v !== 'object'; }
  function fmtScalar(v){
    if(v === null || v === undefined || v === '') return '\\u2014';
    if(typeof v === 'boolean') return v ? 'Yes' : 'No';
    return String(v);
  }
  function humanize(key){
    return String(key).replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/_/g, ' ')
      .replace(/^./, function(c){ return c.toUpperCase(); });
  }

  function renderScalarGrid(obj, keys){
    return '<div class="pg-cards">' + keys.map(function(k){
      var v = fmtScalar(obj[k]);
      return '<div class="pg-card"><div class="pg-card-lbl">' + escHtml(humanize(k)) + '</div>' +
        '<div class="pg-card-val" title="' + escHtml(v) + '">' + escHtml(v) + '</div></div>';
    }).join('') + '</div>';
  }

  function renderTable(rows){
    var cap = 25;
    var cols = [];
    rows.slice(0, cap).forEach(function(r){
      if(isPlainObject(r)){
        Object.keys(r).forEach(function(k){ if(cols.indexOf(k) === -1) cols.push(k); });
      }
    });
    if(!cols.length){
      return '<div class="pg-chips">' + rows.slice(0, cap).map(function(v){
        return '<span class="pg-chip">' + escHtml(fmtScalar(v)) + '</span>';
      }).join('') + '</div>';
    }
    cols = cols.slice(0, 8);
    var thead = '<tr>' + cols.map(function(c){ return '<th>' + escHtml(humanize(c)) + '</th>'; }).join('') + '</tr>';
    var tbody = rows.slice(0, cap).map(function(r){
      return '<tr>' + cols.map(function(c){
        var v = isPlainObject(r) ? r[c] : undefined;
        var text = v === undefined ? '\\u2014' : (isScalar(v) ? fmtScalar(v) : JSON.stringify(v));
        return '<td title="' + escHtml(text) + '">' + escHtml(text) + '</td>';
      }).join('') + '</tr>';
    }).join('');
    var note = rows.length > cap ? '<p class="pg-table-note">Showing ' + cap + ' of ' + rows.length + ' rows.</p>' : '';
    return '<div class="pg-table-wrap"><table class="pg-table"><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table></div>' + note;
  }

  function renderSection(label, html){
    return '<div class="pg-section"><div class="pg-section-lbl">' + escHtml(label) + '</div>' + html + '</div>';
  }

  function renderNode(value){
    if(Array.isArray(value)) return value.length ? renderTable(value) : '<p class="pg-empty">Empty list.</p>';
    if(!isPlainObject(value)) return '<p class="pg-empty">' + escHtml(fmtScalar(value)) + '</p>';
    var keys = Object.keys(value);
    if(!keys.length) return '<p class="pg-empty">Empty response.</p>';
    var scalarKeys = keys.filter(function(k){ return isScalar(value[k]); });
    var complexKeys = keys.filter(function(k){ return !isScalar(value[k]); });
    var out = scalarKeys.length ? renderScalarGrid(value, scalarKeys) : '';
    complexKeys.forEach(function(k){
      var v = value[k];
      var inner;
      if(Array.isArray(v)){
        inner = v.length ? renderTable(v) : '<p class="pg-empty">Empty list.</p>';
      } else {
        var subKeys = Object.keys(v);
        inner = (subKeys.length && subKeys.every(function(sk){ return isScalar(v[sk]); }))
          ? renderScalarGrid(v, subKeys)
          : '<pre class="pg-ep-resp">' + escHtml(JSON.stringify(v, null, 2)) + '</pre>';
      }
      out += renderSection(humanize(k), inner);
    });
    return out;
  }

  function setBusy(ep, busy){
    var status = ep.querySelector('.pg-status');
    var runBtn = ep.querySelector('.pg-run-btn');
    var runBtnHTML = runBtn.innerHTML;
    if(busy){
      ep.classList.add('open', 'busy');
      ep.classList.remove('ok', 'err');
      runBtn.disabled = true;
      runBtn.innerHTML = '<span class="pg-spinner"></span>';
      status.innerHTML = '<span class="pg-spinner"></span>';
      status.className = 'pg-status busy';
    } else {
      runBtn.disabled = false;
      runBtn.innerHTML = runBtnHTML;
    }
  }

  function runOne(ep){
    var tmpl = ep.getAttribute('data-path');
    var hasParam = /\\{[^}]+\\}/.test(tmpl);
    var value = input.value.trim();
    if(hasParam && !value){ input.focus(); return Promise.resolve(); }
    var url = buildUrl(tmpl, value, ep);
    if(url === null){
      if(hostSel && !hostSel.value){ nudgeHost(); }
      else if(buInput && hostSel && hostSel.value === 'custom'){ buWrap.style.display = ''; buInput.focus(); }
      return Promise.resolve();
    }
    var status = ep.querySelector('.pg-status');
    var body = ep.querySelector('.ep-body');
    setBusy(ep, true);
    var keepParams = ep.querySelector('.pg-ep-qparams');
    var keepParamsHtml = keepParams ? keepParams.outerHTML : '';
    body.innerHTML = keepParamsHtml + '<div class="pg-ep-loading"><div class="req"><span class="pg-spinner"></span>Requesting ' + escHtml(url) + '\\u2026</div>' +
      '<div class="pg-skel w90"></div><div class="pg-skel w70"></div><div class="pg-skel w50"></div><div class="pg-skel w35"></div></div>';
    var start = performance.now();
    var isSvg = (tmpl && tmpl.indexOf('/stats/svg') !== -1) || (url && url.indexOf('/stats/svg') !== -1);
    return fetch(url).then(function(r){
      var ms = Math.round(performance.now() - start);
      var ctype = (r.headers.get('content-type') || '').toLowerCase();
      if(isSvg || ctype.indexOf('image/svg') !== -1){
        return r.text().then(function(text){
          ep.classList.remove('busy');
          ep.classList.add(r.ok ? 'ok' : 'err');
          status.textContent = r.status + ' \\u00b7 ' + ms + 'ms';
          status.className = 'pg-status ' + (r.ok ? 'ok' : 'err');
          var meta = '<div class=\\"pg-ep-meta\\"><span class=\\"url\\">GET ' + escHtml(url) + '</span><button type=\\"button\\" class=\\"pg-copy\\">Copy URL</button></div>';
          var blob = new Blob([text], {type: 'image/svg+xml'});
          var objUrl = URL.createObjectURL(blob);
          body.innerHTML = keepParamsHtml + meta + '<div class="pg-ep-svg"><img alt="stats svg" src="' + objUrl + '"/></div>' +
            '<pre class="pg-ep-resp" style="margin-top:10px;max-height:180px">' + escHtml(text.slice(0, 1200)) + (text.length > 1200 ? '\\n\\u2026' : '') + '</pre>';
          body.querySelector('.pg-copy').addEventListener('click', function(e){
            e.stopPropagation();
            navigator.clipboard.writeText(url).then(function(){
              var b = e.currentTarget, t = b.textContent;
              b.textContent = 'Copied'; setTimeout(function(){ b.textContent = t; }, 1200);
            });
          });
        });
      }
      return r.text().then(function(text){
        var parsed = null;
        try{ parsed = JSON.parse(text); }catch(e){}
        var pretty = parsed !== null ? JSON.stringify(parsed, null, 2) : text;
        var formatted = '';
        if(parsed !== null){
          var target = (isPlainObject(parsed) && Object.prototype.hasOwnProperty.call(parsed, 'data'))
            ? parsed.data : parsed;
          formatted = renderNode(target);
        }
        ep.classList.remove('busy');
        ep.classList.add(r.ok ? 'ok' : 'err');
        status.textContent = r.status + ' \\u00b7 ' + ms + 'ms';
        status.className = 'pg-status ' + (r.ok ? 'ok' : 'err');
        var meta = '<div class=\\"pg-ep-meta\\"><span class=\\"url\\">GET ' + escHtml(url) + '</span><button type=\\"button\\" class=\\"pg-copy\\">Copy</button></div>';
        var tabs = formatted
          ? '<div class="pg-tabs"><button type="button" class="pg-tab-btn active" data-view="pretty">Formatted</button>' +
            '<button type="button" class="pg-tab-btn" data-view="raw">Raw JSON</button></div>'
          : '';
        var prettyView = '<div class="pg-view" data-view="pretty"' + (formatted ? '' : ' hidden') + '>' + formatted + '</div>';
        var rawView = '<div class="pg-view" data-view="raw"' + (formatted ? ' hidden' : '') + '><pre class="pg-ep-resp">' + escHtml(pretty) + '</pre></div>';
        body.innerHTML = keepParamsHtml + meta + tabs + prettyView + rawView;
        body.querySelector('.pg-copy').addEventListener('click', function(e){
          e.stopPropagation();
          navigator.clipboard.writeText(pretty).then(function(){
            var b = e.currentTarget, t = b.textContent;
            b.textContent = 'Copied'; setTimeout(function(){ b.textContent = t; }, 1200);
          });
        });
        Array.prototype.forEach.call(body.querySelectorAll('.pg-tab-btn'), function(btn){
          btn.addEventListener('click', function(e){
            e.stopPropagation();
            var view = btn.getAttribute('data-view');
            Array.prototype.forEach.call(body.querySelectorAll('.pg-tab-btn'), function(b){ b.classList.toggle('active', b === btn); });
            Array.prototype.forEach.call(body.querySelectorAll('.pg-view'), function(v){ v.hidden = v.getAttribute('data-view') !== view; });
          });
        });
      });
    }).catch(function(err){
      ep.classList.remove('busy'); ep.classList.add('err');
      status.textContent = 'error'; status.className = 'pg-status err';
      body.innerHTML = '<div class="pg-ep-loading">' + escHtml(err.message || 'Request failed.') + '</div>';
    }).finally(function(){ setBusy(ep, false); });
  }

  allEps.forEach(function(ep){
    var head = ep.querySelector('.ep-head');
    var runBtn = ep.querySelector('.pg-run-btn');
    head.addEventListener('click', function(){ ep.classList.toggle('open'); });
    head.addEventListener('keydown', function(e){ if(e.key === 'Enter' || e.key === ' '){ e.preventDefault(); ep.classList.toggle('open'); } });
    runBtn.addEventListener('click', function(e){ e.stopPropagation(); runOne(ep); });
  });

  form.addEventListener('submit', function(e){
    e.preventDefault();
    var value = input.value.trim();
    if(!value){
      input.classList.remove('shake');
      void input.offsetWidth;
      input.classList.add('shake');
      input.focus();
      return;
    }
    if(hostSel && !hostSel.value){
      nudgeHost();
      return;
    }
    if(hostSel && hostSel.value === 'custom' && !(buInput && buInput.value.trim())){
      if(buInput){ buWrap.style.display = ''; buInput.focus(); }
      return;
    }
    recentBox.classList.remove('open');
    pushRecent(value);
    runAllBtn.disabled = true;
    var total = canonicalEps.length, done = 0;
    if(progressEl) progressEl.classList.add('active');
    if(progressBarEl) progressBarEl.style.width = '0%';
    runAllBtn.innerHTML = '<span class="pg-spinner"></span>Running 0/' + total;
    function tick(){
      done++;
      runAllBtn.innerHTML = '<span class="pg-spinner"></span>Running ' + done + '/' + total;
      if(progressBarEl) progressBarEl.style.width = Math.round((done / total) * 100) + '%';
    }
    Promise.all(canonicalEps.map(function(ep){ return runOne(ep).then(tick); })).finally(function(){
      runAllBtn.disabled = false;
      runAllBtn.innerHTML = runAllDefaultHTML;
      if(progressEl) setTimeout(function(){ progressEl.classList.remove('active'); }, 400);
    });
  });
})();
"""

_SEARCH_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-3.5-3.5"/></svg>'
_GITHUB_ICON = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>'
_BRANCH_GLYPH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><circle cx="6" cy="6" r="2.6"/><circle cx="6" cy="18" r="2.6"/><circle cx="18" cy="7" r="2.6"/><path d="M6 8.6v6.8"/><path d="M17.9 9.6C17.4 13.5 13 14.6 8.6 15"/></svg>'


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _favicon_link() -> str:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<rect width="24" height="24" rx="5" fill="{ACCENT}"/>'
        f'<g fill="none" stroke="{_ACCENT_INK}" stroke-width="2.2" stroke-linecap="round">'
        f'<circle cx="7.2" cy="7.2" r="2.1"/><circle cx="7.2" cy="17" r="2.1"/>'
        f'<circle cx="17" cy="8.2" r="2.1"/><path d="M7.2 9.3v5.6"/>'
        f'<path d="M16.9 10.3c-.5 3.3-4.2 4.3-7.9 4.7"/></g></svg>'
    )
    return '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,' + quote(svg) + '"/>'


def _head(title: str, styles: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"/>'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>'
        + _favicon_link()
        + f"<title>{title}</title>"
        '<link rel="preconnect" href="https://fonts.googleapis.com"/>'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>'
        '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>'
        f"<style>:root{{--accent:{ACCENT};}}</style>"
        f"<style>{styles}</style>"
    )


def _topbar(show_menu_btn: bool = True) -> str:
    menu_btn = '<button class="menu-btn" type="button" aria-label="Open navigation" aria-expanded="false" aria-controls="docs-nav">&#9776;</button>' if show_menu_btn else ""
    return f"""
<header class="topbar">
  {menu_btn}
  <a class="brand" href="/"><span class="glyph">{_BRANCH_GLYPH}</span><span class="brand-text">{PLATFORM}<span class="sub">/ API</span></span></a>
  <nav class="topnav">
    <a href="/">Home</a>
    <a href="/docs">OpenAPI</a>
    <a href="/redoc">ReDoc</a>
    <a class="icon" href="https://github.com/{REPO}" target="_blank" rel="noreferrer" title="View source on GitHub">{_GITHUB_ICON}</a>
    <a class="cta" href="/playground">Try it</a>
  </nav>
</header>"""


def _section_of(path: str) -> str | None:
    p = path.strip("/")
    known = ("profile", "stats", "heatmap", "badges", "repos", "orgs")
    for s in known:
        if p == s or p.endswith("/" + s):
            return s
    segs = [x for x in p.split("/") if x]
    if len(segs) == 1 and segs[0].startswith("{"):
        return "summary"
    return None


def _params_of(path: str) -> list[tuple[str, str]]:
    rows = []
    for t in re.findall(r"{([^}]+)}", path):
        rows.append((t, f"The {PLATFORM} {PARAM} to look up."))
    return rows


_QUERY_BLOCKS = {
    "stats": None,
    "heatmap": (
        '<div class="ep-sub">Query parameters</div>'
        '<table class="ptable"><thead><tr><th>Name</th><th>Type</th><th></th>'
        "<th>Description</th></tr></thead><tbody>"
        '<tr><td><code>view</code></td><td>string</td><td><span class="opt">optional</span></td>'
        "<td><code>all</code> (default), <code>last_365</code>, or <code>year</code>.</td></tr>"
        '<tr><td><code>year</code></td><td>int</td><td><span class="opt">optional</span></td>'
        "<td>Calendar year, required when <code>view=year</code>.</td></tr>"
        '<tr><td><code>deep</code></td><td>bool</td><td><span class="opt">optional</span></td>'
        "<td>Rebuild full history from commit walks; resumable and cached.</td></tr>"
        "</tbody></table>"
    ),
}


def _qparams_html(section: str | None) -> str:
    if section == "heatmap":
        block = _QUERY_BLOCKS["heatmap"]
    elif section == "stats":
        block = ""
    else:
        return ""

    extras = (
        '<div class="ep-sub">Target selection</div>'
        '<table class="ptable"><thead><tr><th>Name</th><th>Type</th><th></th>'
        "<th>Description</th></tr></thead><tbody>"
        '<tr><td><code>host</code></td><td>string</td><td><span class="opt">optional</span></td>'
        "<td>Registered instance key (<code>taf</code>, <code>codeberg</code>, <code>gitea</code>).</td></tr>"
        '<tr><td><code>base_url</code></td><td>string</td><td><span class="opt">optional</span></td>'
        "<td>Any Gitea-compatible instance URL; SSRF-guarded.</td></tr>"
        "</tbody></table>"
    )
    return block + extras


_TARGET_HTML = ""


def _example_block(section: str) -> str | None:
    platform = "forgejo"
    username = SAMPLE
    data: dict
    if section == "summary":
        data = {
            "totalSolved": 294, "totalActiveDays": 12,
            "totalRepos": 3, "totalStars": 18, "totalForks": 2, "followers": 7,
        }
    elif section == "profile":
        data = {
            "displayName": "Tashif Ahmad Khan", "username": username,
            "avatar": "https://git.taf.sh/avatars/...", "country": None,
            "bio": None, "websites": [], "social": {"github": None},
            "verified": False,
        }
    elif section == "stats":
        data = {
            "totalSolved": 294, "totalQuestions": None, "acceptanceRate": None,
            "byDifficulty": {"easy": 0, "medium": 0, "hard": 0},
            "topicAnalysis": [
                {"topic": "Go", "count": 1146971},
                {"topic": "Makefile", "count": 8383},
            ],
        }
    elif section == "heatmap":
        data = {
            "totalSubmissions": 294, "totalActiveDays": 12,
            "currentStreak": 2, "longestStreak": 6, "maxDailySubmissions": 51,
            "firstActiveDate": "2026-08-11", "lastActiveDate": "2026-08-22",
            "dailyContributions": [{"date": "2026-08-21", "count": 3, "level": 2}],
            "availableYears": [2026], "view": "all",
            "source": "synthesized", "complete": True,
        }
    elif section == "badges":
        data = {
            "count": 3,
            "active": {"id": "week-streak", "name": "Week Streak", "icon": None, "level": "6 day best streak"},
            "list": [
                {"id": "week-streak", "name": "Week Streak", "icon": None, "level": "6 day best streak"},
                {"id": "first-star", "name": "First Star", "icon": None, "level": "18 stars earned"},
                {"id": "hello-world", "name": "Hello World", "icon": None, "level": "3 repositories"},
            ],
        }
    elif section == "repos":
        data = {
            "count": 3, "totalStars": 18, "totalForks": 2,
            "repos": [{
                "id": 7, "name": "relayroom", "fullName": "taf/relayroom",
                "language": "Go", "stars": 18, "forks": 2, "isFork": False,
            }],
        }
    elif section == "orgs":
        data = {"count": 1, "orgs": [{"username": "relayroom-labs"}], "restricted": False}
    else:
        return None
    envelope = {
        "status": "success",
        "platform": platform,
        "instance": "taf",
        "software": {"name": "Forgejo", "version": "16.0.3+gitea-1.22.0"},
        "username": username,
        "cached": False,
        "data": data,
    }
    return json.dumps(envelope, indent=2)


def _endpoint_rows(endpoints: list[tuple[str, str, str]]) -> str:
    out = []
    for method, path, summary in endpoints:
        section = _section_of(path)
        params = _params_of(path)

        prows = "".join(
            f'<tr><td><code>{n}</code></td><td>string</td><td><span class="req">required</span></td>'
            f"<td>{d}</td></tr>"
            for n, d in params
        )
        if params:
            ptable = (
                '<div class="ep-sub">Path parameters</div>'
                '<table class="ptable"><thead><tr><th>Name</th><th>Type</th><th></th>'
                f"<th>Description</th></tr></thead><tbody>{prows}</tbody></table>"
            )
        else:
            ptable = '<div class="ep-sub">Path parameters</div><p class="ep-note">None.</p>'

        if path.rstrip("/").endswith("/heatmap"):
            ptable += _qparams_html("heatmap")
        elif path.rstrip("/").endswith("/stats") or path.rstrip("/").endswith("/stats/svg"):
            ptable += _qparams_html("stats")
        elif section in ("repos", "badges", ""):
            ptable += _qparams_html("stats")

        example = _example_block(section)
        if example:
            block = (
                '<div class="ep-sub">Response &middot; 200 OK</div>'
                '<div class="code small"><div class="cap"><span class="dot"></span>application/json'
                f'<button class="copy">Copy</button></div><pre>{_esc(example)}</pre></div>'
            )
        elif path.rstrip("/").endswith("/stats/svg"):
            block = (
                '<div class="ep-sub">Response &middot; 200 OK</div>'
                '<p class="ep-note">Returns <code class="ic">image/svg+xml</code> (not JSON). '
                'Use the <a class="link" href="/playground">playground</a> to preview the card live.</p>'
            )
        else:
            block = (
                '<div class="ep-sub">Response &middot; 200 OK</div>'
                '<p class="ep-note">No inline example for this shape. See the '
                '<a class="link" href="/docs">OpenAPI schema</a> for the exact response.</p>'
            )
        out.append(
            '<div class="ep"><button class="ep-head" aria-expanded="false">'
            f'<span class="verb">{method}</span><code class="ep-path">{path}</code>'
            f'<span class="ep-desc">{summary}</span><span class="chev">&rsaquo;</span></button>'
            f'<div class="ep-body">{ptable}{block}</div></div>'
        )
    return "".join(out)


def _playground_rows(endpoints: list[tuple[str, str, str]]) -> str:
    out = []
    for method, path, summary in endpoints:
        section = _section_of(path)
        is_svg = path.rstrip("/").endswith("/stats/svg")
        if is_svg:
            params_html = (
                '<div class="pg-ep-qparams">'
                '<div class="pg-ep-qparams-lbl">Query parameters</div>'
                '<div class="pg-svg-controls" style="margin:0">'
                '<div class="pg-svg-field" style="flex:1">'
                "<label>theme</label>"
                '<select class="pg-q" data-q="theme">'
                '<option value="dark" selected>dark</option>'
                '<option value="light">light</option>'
                "</select></div>"
                '<div class="pg-svg-field" style="flex:2">'
                "<label>exclude</label>"
                '<input class="pg-q" data-q="exclude" type="text" placeholder="e.g. Markdown,SVG"/>'
                "</div></div>"
                '<p class="pg-ep-qhint">Optional. <code class="ic">theme</code> picks light/dark; '
                "<code class=\"ic\">exclude</code> omits languages (comma-separated). "
                'Response is <code class="ic">image/svg+xml</code>, cached 24h.</p>'
                "</div>"
            )
        elif section == "heatmap":
            params_html = (
                '<div class="pg-ep-qparams">'
                '<div class="pg-ep-qparams-lbl">Query parameters</div>'
                '<div class="pg-svg-controls" style="margin:0">'
                '<div class="pg-svg-field" style="flex:1">'
                "<label>view</label>"
                '<select class="pg-q" data-q="view">'
                '<option value="all" selected>all</option>'
                '<option value="last_365">last_365</option>'
                '<option value="year">year</option>'
                "</select></div>"
                '<div class="pg-svg-field" style="flex:1">'
                "<label>year</label>"
                '<input class="pg-q" data-q="year" type="number" placeholder="2026"/>'
                "</div>"
                '<div class="pg-svg-field" style="flex:0 0 auto">'
                '<label>&nbsp;</label>'
                '<div class="pg-svg-check"><input class="pg-q" data-q="deep" type="checkbox"/><span>deep history</span></div>'
                "</div></div>"
                "<p class=\"pg-ep-qhint\">Every Gitea-family heatmap caps at ~371 days server-side. "
                "<code class=\"ic\">deep=true</code> rebuilds full history from commit walks "
                "(delta-refreshed, resumable); the payload reports "
                "<code class=\"ic\">source</code> and <code class=\"ic\">complete</code>.</p>"
                "</div>"
            )
        else:
            params_html = ""
        body_seed = (
            params_html
            + '<pre class="pg-ep-resp"><span class="pg-placeholder">'
            + (
                "Run this endpoint to preview the live SVG card here."
                if is_svg
                else "Run this endpoint to see the live response here."
            )
            + "</span></pre>"
        )
        svg_attr = ' data-svg="1"' if is_svg else ""
        out.append(
            f'<div class="ep" data-path="{_esc(path)}"{svg_attr}>'
            '<div class="ep-head pg-row" role="button" tabindex="0">'
            f'<span class="verb">{method}</span>'
            f'<code class="ep-path">{path}</code>'
            f'<span class="ep-desc">{summary}</span>'
            '<span class="pg-status"></span>'
            '<button type="button" class="pg-run-btn">Run</button>'
            '<span class="chev">&rsaquo;</span>'
            "</div>"
            f'<div class="ep-body">{body_seed}</div>'
            "</div>"
        )
    return "".join(out)


def _host_options() -> tuple[str, int]:
    targets = parse_instances()
    options = ['<option value="" disabled selected>select a forge&hellip;</option>']
    for t in targets.values():
        label = f'{t.key}: {t.base_url.replace("https://", "")}'
        options.append(f'<option value="{t.key}">{label}</option>')
    options.append('<option value="custom">custom base URL&hellip;</option>')
    return "".join(options), len(targets)


def _instance_table_rows() -> str:
    targets = parse_instances()
    return "".join(
        f"<tr><td><code>{t.key}</code></td>"
        f"<td><code>{t.base_url}</code></td>"
        f"<td>{'token configured' if t.token else 'anonymous'}</td></tr>"
        for t in targets.values()
    )


def _docs_html() -> str:
    param = "{" + PARAM + "}"
    logo_svg = _BRANCH_GLYPH
    canonical = _endpoint_rows(CANONICAL_ENDPOINTS)
    legacy = (
        f'<div class="eps">{_endpoint_rows(LEGACY_ENDPOINTS)}</div>'
        if LEGACY_ENDPOINTS
        else "<p>No legacy aliases. Every path already uses the canonical route files.</p>"
    )

    curl_sample = (
        f'<span class="cmt"># Fetch a profile from git.taf.sh</span>\n'
        f"curl <span data-origin></span>/{SAMPLE}/profile?host=git.taf.sh\n"
        f'<span class="cmt"># Same user on Codeberg</span>\n'
        f"curl <span data-origin></span>/{SAMPLE}/profile?host=codeberg"
    )
    envelope_sample = _esc(
        "{\n"
        '  "status": "success",\n'
        '  "message": "retrieved",\n'
        '  "platform": "forgejo",\n'
        '  "instance": "taf",\n'
        '  "software": { "name": "Forgejo", "version": "16.0.3+gitea-1.22.0" },\n'
        f'  "username": "{SAMPLE}",\n'
        '  "cached": false,\n'
        '  "data": { ... }\n'
        "}"
    )

    body = f"""
{_topbar()}
<div class="nav-scrim" id="nav-scrim"></div>
<div class="wrap">
  <aside class="side" id="docs-nav">
    <div class="search">{_SEARCH_SVG}<input placeholder="Search the docs..." aria-label="Search"/><kbd>/</kbd></div>
    <div class="navgroup"><h4>Get Started</h4>
      <a href="#introduction" data-nav>Introduction</a>
      <a href="#quickstart" data-nav>Quickstart</a>
      <a href="#hosts" data-nav>Pick a Host</a>
      <a href="#envelope" data-nav>Response Envelope</a>
    </div>
    <div class="navgroup"><h4>Endpoints</h4>
      <a href="#canonical" data-nav>Canonical</a>
      <a href="#deep-history" data-nav>Deep History</a>
      <a href="#legacy" data-nav>Legacy</a>
    </div>
    <div class="navgroup"><h4>Reference</h4>
      <a href="/playground">Live Playground</a>
      <a href="/docs">OpenAPI Explorer</a>
      <a href="/redoc">ReDoc</a>
      <a href="https://github.com/{REPO}" target="_blank" rel="noreferrer">Source &#8599;</a>
    </div>
  </aside>

  <main class="doc">
    <section id="introduction">
      <div class="eyebrow">Stat API &middot; {PLATFORM}</div>
      <h1 class="title">GitHost Stats API</h1>
      <p class="lede">{DESCRIPTION}</p>
      <p class="lede">One client speaks to git.taf.sh, Codeberg, gitea.com, or any instance you paste in. Every canonical endpoint shares the same envelope as all other Stat APIs services.</p>
      <div class="metarow">
        <span class="chip">REST</span>
        <span class="chip">JSON</span>
        <span class="chip">No auth for public data</span>
        <span class="chip">{param}</span>
        <span class="chip">?base_url=anywhere</span>
      </div>
    </section>

    <div class="steps">
      <section class="section" id="quickstart">
        <div class="section-head"><span class="step">1</span><h2>Make your first request</h2></div>
        <p>Send a <code class="ic">GET</code> request to any handle. Replace <code class="ic">{SAMPLE}</code> with the {PARAM} you want to inspect. No key needed for public data.</p>
        <div class="code">
          <div class="cap"><span class="dot"></span>Terminal<button class="copy">Copy</button></div>
          <pre>{curl_sample}</pre>
        </div>
        <div class="callout">
          <span class="ic">i</span>
          <div><span class="t">Tip</span>
            <p>Prefer a browser? Try the <a class="link" href="/playground">live playground</a>, open <a class="link" href="{TRY_PATH}">{TRY_PATH}</a> for raw JSON, or explore every route interactively in the <a class="link" href="/docs">OpenAPI explorer</a>.</p>
          </div>
        </div>
      </section>

      <section class="section" id="hosts">
        <div class="section-head"><span class="step">2</span><h2>Pick a host</h2></div>
        <p>Every request names its forge: any registered key via <code class="ic">?host=</code>, or your own instance via <code class="ic">?base_url=</code>. Requests without one are rejected. The embed-safe prefix <code class="ic">/f/{{key}}/{{username}}/...</code> puts the host in the path and keeps badges clean inside READMEs.</p>
        <table class="ptable" style="max-width:740px">
          <thead><tr><th>Key</th><th>Base URL</th><th>Auth</th></tr></thead>
          <tbody>{_instance_table_rows()}</tbody>
        </table>
        <div class="callout">
          <span class="ic">i</span>
          <div><span class="t">SSRF guard</span>
            <p>Caller-supplied base URLs are validated before anything is fetched: HTTPS only, no credentials in the URL, every resolved address checked against reserved ranges, redirects re-validated per hop. Disable custom URLs entirely with <code class="ic">GITHOST_ALLOW_CUSTOM_BASE=false</code>.</p>
          </div>
        </div>
      </section>

      <section class="section" id="envelope">
        <div class="section-head"><span class="step">3</span><h2>Response envelope</h2></div>
        <p>Successful responses follow one consistent shape. The <code class="ic">data</code> object carries the endpoint-specific payload while the outer fields stay identical everywhere. GitHost adds <code class="ic">instance</code> and <code class="ic">software</code> so you always know which forge answered.</p>
        <div class="code">
          <div class="cap"><span class="dot"></span>200 OK &middot; application/json<button class="copy">Copy</button></div>
          <pre>{envelope_sample}</pre>
        </div>
      </section>

      <section class="section" id="canonical">
        <div class="section-head"><span class="step">4</span><h2>Canonical endpoints</h2></div>
        <p>The canonical surface. Build against these. Click any endpoint to see its parameters and an example response.</p>
        <div class="eps">{canonical}</div>
      </section>

      <section class="section" id="deep-history">
        <div class="section-head"><span class="step">5</span><h2>Deep history</h2></div>
        <p>The native heatmap endpoint caps at roughly 371 days on every Gitea-family instance. Pass <code class="ic">deep=true</code> to rebuild the full calendar from commit walks instead.</p>
        <div class="code">
          <div class="cap"><span class="dot"></span>Terminal<button class="copy">Copy</button></div>
          <pre><span class="cmt"># Full history, rebuilt from git itself</span>
curl <span data-origin></span>/{SAMPLE}/heatmap?deep=true&amp;view=all</pre>
        </div>
        <div class="callout">
          <span class="ic">i</span>
          <div><span class="t">How it stays cheap</span>
            <p>A Redis manifest keyed by repo id stores each walk's position. Unchanged repos cost zero upstream calls, changed repos fetch only newer pages, and unfinished walks resume from their bookmark on the next request. Heatmap blocks report <code class="ic">source: native | synthesized</code> and <code class="ic">complete: true | false</code>.</p>
          </div>
        </div>
      </section>

      <section class="section" id="legacy">
        <div class="section-head"><span class="step">6</span><h2>Legacy compatibility</h2></div>
        <p>Kept working for existing integrations. Prefer the canonical routes above for anything new.</p>
        {legacy}
      </section>
    </div>

    <div class="foot">
      <span>{PLATFORM} Stats API &middot; part of the Stat APIs family</span>
      <span><a href="/docs">OpenAPI</a> &middot; <a href="/redoc">ReDoc</a> &middot; <a href="https://github.com/{REPO}" target="_blank" rel="noreferrer">Source</a></span>
    </div>
  </main>

  <aside class="toc">
    <h5>On this page</h5>
    <a href="#introduction" data-toc>Introduction</a>
    <a href="#quickstart" data-toc>Quickstart</a>
    <a href="#hosts" data-toc>Pick a Host</a>
    <a href="#envelope" data-toc>Response Envelope</a>
    <a href="#canonical" data-toc>Canonical Endpoints</a>
    <a href="#deep-history" data-toc>Deep History</a>
    <a href="#legacy" data-toc>Legacy Compatibility</a>
  </aside>
</div>
"""
    return body


def _playground_html() -> str:
    host_options, _count = _host_options()
    canonical_rows = _playground_rows(CANONICAL_ENDPOINTS)
    body = f"""
{_topbar(show_menu_btn=False)}
<main class="pg-main">
  <div class="pg-eyebrow">Live Playground &middot; {PLATFORM}</div>
  <h1 class="pg-h1">Run every endpoint against any forge</h1>
  <p class="pg-sub">Enter a {PARAM}, pick a registered host or paste your own instance URL, then run any endpoint below against the live API. Requests go straight from your browser to the forge and nowhere else.</p>

  <div class="pg-bar">
    <form class="pg-form" autocomplete="off">
      <div class="pg-bar-row">
        <div class="pg-input-wrap">
          <span class="pg-input-icon">{_SEARCH_SVG}</span>
          <input class="pg-input" type="text" placeholder="Enter username (e.g. {SAMPLE})" aria-label="{PLATFORM} {PARAM}"/>
          <button type="button" class="pg-input-clear" aria-label="Clear {PARAM}" tabindex="-1">&times;</button>
          <div class="pg-recent"></div>
        </div>
        <div class="pg-target">
          <label>HOST</label>
          <select id="pg-host">{host_options}</select>
        </div>
        <div class="pg-target" id="pg-bu-wrap" style="display:none">
          <label>BASE URL</label>
          <input id="pg-baseurl" type="text" placeholder="https://git.example.com"/>
        </div>
        <div class="pg-target">
          <label>EXTRA EMAILS</label>
          <input id="pg-emails" type="text" placeholder="you@private.dev"/>
        </div>
        <button class="pg-btn pg-runall" type="submit">{_SEARCH_SVG}Run all</button>
      </div>
      <div class="pg-progress"><div class="pg-progress-bar"></div></div>
    </form>
    <p class="pg-hint">The host selector applies to every endpoint below. <code class="ic">deep</code> on the heatmap rebuilds full history from commit walks. Prefer raw JSON in a new tab? Open <a class="link" href="{TRY_PATH}">{TRY_PATH}</a>.</p>
  </div>

  <div class="pg-group-label"><span>Canonical endpoints &middot; {len(CANONICAL_ENDPOINTS)}</span></div>
  <div class="eps pg-canonical-list">{canonical_rows}</div>

  <p class="pg-foot-note">Part of the <a class="link" href="https://github.com/{REPO}" target="_blank" rel="noreferrer">Stat APIs</a> family.</p>
</main>
"""
    script = f"var PLATFORM_KEY={json.dumps(PLATFORM_KEY)};\n{_PLAYGROUND_JS}"
    return (
        _head(f"{PLATFORM} Playground", _BASE_CSS + _PLAYGROUND_CSS)
        + "</head><body>"
        + f"{body}<script>{script}</script></body></html>"
    )


def _docs_page() -> HTMLResponse:
    page = (
        _head("GitHost Stats API", _BASE_CSS)
        + "</head><body>"
        + _docs_html()
        + f"<script>{_JS}</script></body></html>"
    )
    return HTMLResponse(page)


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def docs_landing() -> HTMLResponse:
    return _docs_page()


@router.get("/playground", response_class=HTMLResponse, include_in_schema=False)
async def playground() -> HTMLResponse:
    return HTMLResponse(_playground_html())
