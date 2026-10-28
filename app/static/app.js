/* Trial Feasibility Copilot: the sliders (risk maths mirrored from app/risk.py, no model call)
   and the server-sent events that fill each audit section as it is ready. */
"use strict";

function pace(n, sites, months) {
  n = Number(n); sites = Number(sites); months = Number(months);
  if (!(n > 0 && sites > 0 && months > 0)) return null;
  return n / (sites * months);
}

// Same sum as risk.share_at_least: share of completed comparables whose pace was >= value.
function shareAtLeast(q, value) {
  if (value === null || value === undefined || !q || !q.length) return null;
  if (value <= q[0]) return 1.0;
  if (value > q[q.length - 1]) return 0.0;
  const k = q.length;
  for (let i = 1; i < k; i++) {
    if (value <= q[i]) {
      const span = q[i] - q[i - 1];
      const frac = span > 0 ? (value - q[i - 1]) / span : 1.0;
      const below = (i - 1 + frac) / (k - 1);
      return Math.round((1.0 - below) * 10000) / 10000;
    }
  }
  return 0.0;
}

function whatIf(n, sites, months, q, offset) {
  const p = pace(n, sites, months);
  const pCmp = months ? pace(n, sites, Number(months) + Number(offset || 0)) : null;
  return { pace: p, share: shareAtLeast(q, pCmp) };
}

if (typeof module !== "undefined") module.exports = { pace, shareAtLeast, whatIf };

if (typeof document !== "undefined") {
  function bindSliders(root) {
    const box = (root || document).querySelector("#pace-box");
    if (!box || box.dataset.bound) return;
    box.dataset.bound = "1";
    const q = JSON.parse(box.dataset.q || "[]");
    const s = box.querySelector("#sl-sites"), m = box.querySelector("#sl-months");
    const upd = () => {
      const r = whatIf(box.dataset.planned, s.value, m.value, q, box.dataset.offset);
      box.querySelector("#sites-val").textContent = s.value;
      box.querySelector("#months-val").textContent = m.value;
      box.querySelector("#pace-out").textContent = r.pace === null ? "–" : r.pace.toFixed(2);
      box.querySelector("#share-out").textContent = r.share === null ? "–" : (100 * r.share).toFixed(1) + "%";
      box.querySelector("#pace-formula").textContent =
        Number(box.dataset.planned).toLocaleString() + " planned patients ÷ (" + s.value + " sites × " + m.value + " months)";
    };
    s.addEventListener("input", upd);
    m.addEventListener("input", upd);
    const reg = box.querySelector("#use-registry-sites");
    if (reg) reg.addEventListener("click", () => { s.value = reg.dataset.v; upd(); });
  }

  function stream(el) {
    const job = el.dataset.job;
    if (!job || el.dataset.streaming) return;
    el.dataset.streaming = "1";
    const es = new EventSource("/events/" + job);
    es.onmessage = (e) => {
      const ev = JSON.parse(e.data);
      const target = document.getElementById(ev.target);
      if (target) {
        if (ev.mode === "append") target.insertAdjacentHTML("beforeend", ev.html);
        else target.innerHTML = ev.html;
        if (window.htmx) htmx.process(target);
        bindSliders(target.closest(".audit") || document);
      }
      if (ev.done) { es.close(); el.dataset.done = "1"; }
    };
    es.onerror = () => { es.close(); };
  }

  document.addEventListener("DOMContentLoaded", () => bindSliders(document));
  document.addEventListener("htmx:afterSwap", (e) => {
    const a = e.target.querySelector && e.target.querySelector(".audit[data-job]");
    if (a) stream(a);
    bindSliders(e.target);
  });
}
