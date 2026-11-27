// Small progressive enhancements. Everything works without JavaScript too.
(function () {
  const csrf = () => document.getElementById("csrf")?.value || "";

  // Print button
  document.querySelectorAll("[data-print]").forEach((b) => b.addEventListener("click", () => window.print()));

  // Show a spinner on slow forms (AI / URL import)
  document.querySelectorAll("form[data-busy]").forEach((f) =>
    f.addEventListener("submit", () => {
      const btn = f.querySelector("button");
      if (btn) btn.classList.add("busy");
      const p = document.createElement("p");
      p.className = "busynote";
      p.textContent = f.dataset.busy;
      f.appendChild(p);
    })
  );

  // Photo previews on the import page
  const photos = document.querySelector('input[name="photos"]');
  const preview = document.getElementById("photoPreview");
  if (photos && preview) {
    photos.addEventListener("change", () => {
      preview.innerHTML = "";
      [...photos.files].forEach((file) => {
        const img = document.createElement("img");
        img.src = URL.createObjectURL(file);
        img.alt = file.name;
        preview.appendChild(img);
      });
    });
  }

  // Filter a checkbox list
  document.querySelectorAll("[data-filter]").forEach((input) => {
    const list = document.querySelector(input.dataset.filter);
    input.addEventListener("input", () => {
      const q = input.value.toLowerCase();
      list.querySelectorAll("label").forEach((l) => {
        l.style.display = l.textContent.toLowerCase().includes(q) ? "" : "none";
      });
    });
  });

  // Auto-growing textarea
  document.querySelectorAll("textarea[data-autogrow]").forEach((t) => {
    const grow = () => { t.style.height = "auto"; t.style.height = t.scrollHeight + 2 + "px"; };
    t.addEventListener("input", grow);
    t.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !t.value.includes("\n")) { e.preventDefault(); t.form.requestSubmit(); }
    });
  });

  // Tick shopping items without a page reload
  document.querySelectorAll(".shoplist form.toggle").forEach((f) =>
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      const li = f.closest("li");
      try {
        const res = await fetch(f.action, {
          method: "POST",
          headers: { "x-csrf-token": csrf(), "x-requested-with": "fetch" },
          body: new FormData(f),
        });
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();
        li.classList.toggle("checked", data.checked);
        f.querySelector(".tick").textContent = data.checked ? "✓" : "";
      } catch (err) {
        f.submit();
      }
    })
  );
})();

// Cook mode: swipe / arrow keys / tap edges to move between steps, and keep the screen on (tablets).
(function () {
  const stage = document.querySelector("[data-cook]");
  if (!stage) return;
  const go = (dir) => { const url = stage.dataset[dir]; if (url) location.href = url; };
  document.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") { e.preventDefault(); go("next"); }
    if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); go("prev"); }
  });
  let x0 = null, y0 = null;
  stage.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
  stage.addEventListener("touchend", (e) => {
    if (x0 === null) return;
    const dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0;
    if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) go(dx < 0 ? "next" : "prev");
    x0 = null;
  });
  // Screen Wake Lock (iPadOS 16.4+, Chrome, Edge). Silently ignored where unsupported.
  let lock = null;
  const keepAwake = async () => {
    try { if ("wakeLock" in navigator && document.visibilityState === "visible") lock = await navigator.wakeLock.request("screen"); } catch (e) { /* not allowed */ }
  };
  keepAwake();
  document.addEventListener("visibilitychange", keepAwake);
})();

// Open the "I cooked this" panel when arriving from cook mode.
(function () {
  if (location.hash) { const d = document.getElementById(location.hash.slice(1)); if (d && d.tagName === "DETAILS") d.open = true; }
})();

// ---------------------------------------------------------------- bread: baker's percentages
// Mirrors app/bread.py so the editor can show weights while typing. The server recalculates on save.
const Bread = (() => {
  const num = (v, d = 0) => { const n = parseFloat(String(v ?? "").replace(",", ".")); return isNaN(n) ? d : n; };
  const LIQ = ["water", "wasser", "milk", "milch", "beer", "bier", "juice", "saft"];
  const isLiquid = (o) => o.liquid ?? LIQ.some((w) => (o.name || "").toLowerCase().includes(w));
  function build(target, s, w, f, h) {
    s = Math.max(0, num(s)); w = Math.max(0, num(w)); f = Math.max(0, num(f)); h = Math.max(0, num(h, 100));
    const parts = s + w + f, unit = parts ? (target || 0) / parts : 0, st = s * unit, stFlour = st * 100 / (100 + h);
    const flour = f * unit + stFlour, water = w * unit + (st - stFlour);
    return { target, ratio: [s, w, f], h, starter: st, water: w * unit, flour: f * unit, totalFlour: flour, totalWater: water, hydration: flour ? water / flour * 100 : 0 };
  }
  function compute(spec) {
    let others = spec.others.map((o) => ({ ...o }));
    const total = spec.total_weight > 0 ? spec.total_weight : spec.pieces * (spec.piece_weight || 0);
    const totalPct = 100 + others.reduce((a, o) => a + o.pct, 0);
    const flourW = totalPct ? total * 100 / totalPct : 0;
    const warnings = [];
    const fsum = spec.flours.reduce((a, f) => a + f.pct, 0);
    if (spec.flours.length && Math.abs(fsum - 100) > 0.05) warnings.push(`The flours add up to ${+fsum.toFixed(2)} %, not 100 %.`);
    const b = spec.levain_build;
    if (b.enabled && spec.levain_pct) {
      const h = build(100, b.starter, b.water, b.flour, b.starter_hydration).hydration;
      const first = others.find(isLiquid);
      others.forEach((o) => { if (o === first) o.levain_pct = +h.toFixed(2); else if (isLiquid(o)) o.levain_pct = 0; });
    }
    const levW = flourW * spec.levain_pct / 100;
    const levOther = others.reduce((a, o) => a + o.levain_pct, 0);
    const levFlour = levW ? levW * 100 / (100 + levOther) : 0;
    const lfsum = spec.flours.reduce((a, f) => a + f.levain_pct, 0);
    if (spec.levain_pct && spec.flours.length && Math.abs(lfsum - 100) > 0.05) warnings.push(`The levain flours add up to ${+lfsum.toFixed(2)} %, not 100 %.`);
    const row = (x, isFlour) => { const w = flourW * x.pct / 100, lw = levFlour * x.levain_pct / 100; return { name: x.name, pct: x.pct, w, lpct: x.levain_pct, lw, fw: w - lw, isFlour }; };
    const flours = spec.flours.map((f) => row(f, true)), rest = others.map((o) => row(o, false));
    [...flours, ...rest].forEach((r) => { if (r.fw < -0.05) warnings.push(`The levain needs more ${r.name} than the whole recipe has.`); });
    const hyd = others.filter(isLiquid).reduce((a, o) => a + o.pct, 0);
    let bld = null;
    if (b.enabled && levW) bld = build(levW * (1 + num(b.extra_pct) / 100), b.starter, b.water, b.flour, b.starter_hydration);
    return { total, totalPct, flourW, levW, levFlour, flours, rest, hyd, warnings, build: bld, pieces: spec.pieces, pieceW: spec.pieces ? total / spec.pieces : total, pieceName: spec.piece_name };
  }
  return { compute, build, num };
})();

(function () {
  const g = (w) => (Math.round(w * 10) / 10).toFixed(1).replace(/\.0$/, "");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  // Recipe type switch: show the bread editor or the plain ingredients box.
  const radios = document.querySelectorAll("input[data-kind]");
  const applyKind = () => {
    const k = document.querySelector("input[data-kind]:checked")?.value;
    document.querySelectorAll(".kind-bread").forEach((el) => (el.hidden = k !== "bread"));
    document.querySelectorAll(".kind-standard").forEach((el) => (el.hidden = k === "bread"));
  };
  radios.forEach((r) => r.addEventListener("change", applyKind));

  const ed = document.querySelector("[data-bread-editor]");
  if (!ed) return;
  const preview = ed.querySelector("[data-bread-preview]");

  ed.querySelectorAll("[data-add-row]").forEach((btn) => btn.addEventListener("click", () => {
    const list = ed.querySelector(`[data-rows="${btn.dataset.addRow}"]`);
    const row = list.lastElementChild.cloneNode(true);
    row.querySelectorAll("input").forEach((i) => { if (i.type === "checkbox") i.checked = false; else i.value = ""; });
    list.appendChild(row); renumber(); row.querySelector("input").focus();
  }));
  function renumber() {
    ed.querySelectorAll('[data-rows="other"] input[name="other_liquid"]').forEach((c, i) => (c.value = i));
  }

  function read() {
    const val = (n) => ed.querySelector(`[name="${n}"]`)?.value;
    const flours = [...ed.querySelectorAll('[data-rows="flour"] .brow')].map((r) => ({
      name: r.querySelector('[name="flour_name"]').value.trim(), pct: Bread.num(r.querySelector('[name="flour_pct"]').value),
      levain_pct: Bread.num(r.querySelector('[name="flour_lpct"]').value) })).filter((x) => x.name);
    const others = [...ed.querySelectorAll('[data-rows="other"] .brow')].map((r) => ({
      name: r.querySelector('[name="other_name"]').value.trim(), pct: Bread.num(r.querySelector('[name="other_pct"]').value),
      levain_pct: Bread.num(r.querySelector('[name="other_lpct"]').value), liquid: r.querySelector('[name="other_liquid"]').checked })).filter((x) => x.name);
    return {
      flours, others, levain_pct: Bread.num(val("levain_pct")), pieces: Math.max(1, Bread.num(val("pieces"), 1)),
      piece_weight: Bread.num(val("piece_weight")), total_weight: Bread.num(val("total_weight")), piece_name: val("piece_name") || "pieces",
      levain_build: { enabled: ed.querySelector('[name="build_enabled"]').checked, starter: val("build_starter"), water: val("build_water"),
        flour: val("build_flour"), starter_hydration: val("build_starter_hydration"), extra_pct: val("build_extra_pct") },
    };
  }

  function render() {
    const r = Bread.compute(read());
    const lev = r.levW > 0.05;
    const tr = (x, cls = "") => `<tr class="${cls}"><th>${x.isFlour ? "– " : ""}${esc(x.name)}</th><td>${+x.pct.toFixed(2)}%</td><td>${g(x.w)} g</td>` +
      (lev ? `<td>${+x.lpct.toFixed(2)}%</td><td>${x.lw > 0.05 ? g(x.lw) + " g" : ""}</td><td>${g(x.fw)} g</td>` : "") + "</tr>";
    let h = `<div class="tablewrap"><table class="bread"><thead><tr class="grouphead"><th></th><th colspan="2">Recipe</th>${lev ? '<th colspan="2">Levain</th><th>Final dough</th>' : ""}</tr></thead><tbody>`;
    h += `<tr class="flourtotal"><th>Flour</th><td>100%</td><td>${g(r.flourW)} g</td>${lev ? `<td>100%</td><td>${g(r.levFlour)} g</td><td>${g(r.flourW - r.levFlour)} g</td>` : ""}</tr>`;
    h += r.flours.map((x) => tr(x, "sub")).join("") + r.rest.map((x) => tr(x)).join("");
    if (lev) h += `<tr class="levrow"><th>Levain</th><td></td><td></td><td></td><td></td><td>${g(r.levW)} g</td></tr>`;
    h += `</tbody><tfoot><tr><th></th><td>${+r.totalPct.toFixed(2)}%</td><td>${g(r.total)} g</td>${lev ? `<td></td><td>${g(r.levW)} g</td><td>${g(r.total)} g</td>` : ""}</tr></tfoot></table></div>`;
    h += `<p class="breadsum">${r.pieces} ${esc(r.pieceName)} × ${g(r.pieceW)} g = <b>${g(r.total)} g</b> dough · hydration <b>${+r.hyd.toFixed(1)}%</b></p>`;
    if (r.build) { const b = r.build; h += `<p class="breadsum">Levain build: <b>${g(b.starter)} g</b> starter + <b>${g(b.water)} g</b> water + <b>${g(b.flour)} g</b> flour = ${g(b.target)} g at ${+b.hydration.toFixed(1)}% hydration.</p>`; }
    h += r.warnings.map((w) => `<p class="flash error">${esc(w)}</p>`).join("");
    preview.innerHTML = h;
  }
  ed.addEventListener("input", render);
  ed.addEventListener("change", render);
  renumber(); render();
})();

// Stand-alone levain calculator: update while typing.
(function () {
  const f = document.querySelector("[data-levain-form]");
  if (!f) return;
  const out = document.querySelector(".levainresult");
  const g = (w) => (Math.round(w * 10) / 10).toFixed(1).replace(/\.0$/, "");
  const update = () => {
    const v = (n) => f.querySelector(`[name="${n}"]`).value;
    const b = Bread.build(Bread.num(v("target")), v("s"), v("w"), v("f"), v("h"));
    const cells = out.querySelectorAll("tbody td.strong");
    if (cells.length === 3) { cells[0].textContent = g(b.starter) + " g"; cells[1].textContent = g(b.water) + " g"; cells[2].textContent = g(b.flour) + " g"; }
    const sum = out.querySelector(".breadsum");
    if (sum) sum.innerHTML = `Levain contains <b>${g(b.totalFlour)} g flour</b> and <b>${g(b.totalWater)} g water</b> (starter included) = <b>${+b.hydration.toFixed(1)}% hydration</b>.`;
    const sh = out.querySelector("[data-sh]"); if (sh) sh.textContent = `(${Bread.num(v("h"), 100)}% hydration)`;
    try { history.replaceState(null, "", "/levain?" + new URLSearchParams(new FormData(f))); } catch (e) {}
    const head = out.querySelector("thead th"); if (head) head.textContent = `Feed ${+b.ratio[0]} : ${+b.ratio[1]} : ${+b.ratio[2]}`;
    const tds = out.querySelectorAll("tbody tr td:first-of-type"); b.ratio.forEach((x, i) => tds[i] && (tds[i].textContent = +x));
    const foot = out.querySelectorAll("tfoot td"); if (foot.length === 2) { foot[0].textContent = +(b.ratio[0] + b.ratio[1] + b.ratio[2]); foot[1].textContent = g(b.target) + " g"; }
  };
  f.addEventListener("input", update);
  f.addEventListener("change", update);
  f.addEventListener("submit", (e) => { e.preventDefault(); update(); });
})();

// Buttons that are only needed without JavaScript (the page recalculates live instead).
document.querySelectorAll("[data-js-hide]").forEach((b) => (b.hidden = true));

// Live scaling on the recipe page: re-fetch the page with the new numbers and swap the parts that change.
(function () {
  document.querySelectorAll("form[data-live-form]").forEach((f) => {
    let timer = null, seq = 0;
    const run = async () => {
      const qs = new URLSearchParams(new FormData(f));
      for (const [k, v] of [...qs]) if (!String(v).trim()) qs.delete(k);
      const url = f.getAttribute("action") + (qs.toString() ? "?" + qs : "");
      const my = ++seq;
      try {
        const r = await fetch(url, { headers: { "x-requested-with": "fetch" } });
        if (!r.ok || my !== seq) return;
        const doc = new DOMParser().parseFromString(await r.text(), "text/html");
        document.querySelectorAll("[data-live-swap]").forEach((el) => {
          const n = doc.querySelector(`[data-live-swap="${el.dataset.liveSwap}"]`);
          if (n) el.replaceWith(n);
        });
        history.replaceState(null, "", url);
      } catch (e) { /* keep the old numbers; the button-less form still submits on Enter */ }
    };
    const later = () => { clearTimeout(timer); timer = setTimeout(run, 250); };
    f.addEventListener("input", later);
    f.addEventListener("change", later);
    f.addEventListener("submit", (e) => { e.preventDefault(); clearTimeout(timer); run(); });
  });
})();
