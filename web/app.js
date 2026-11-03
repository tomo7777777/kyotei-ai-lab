/* 競艇AIラボ（GitHub版） */
(() => {
  const REPO = "tomo7777777/kyotei-ai-lab";
  const LOCAL = /^(localhost|127\.0\.0\.1)$/.test(location.hostname) && !new URLSearchParams(location.search).has("remote");
  const DATA = LOCAL ? "../data/" : `https://raw.githubusercontent.com/${REPO}/main/data/`;
  const view = document.getElementById("view");
  const dateSel = document.getElementById("date");
  const state = { tab: "ai", sub: "honmei", date: null, day: null, venue: null, race: null, racer: null, cache: {} };

  // ---------- 便利関数 ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (x, d = 0) => (x == null ? "–" : (x * 100).toFixed(d) + "%");
  const yen = (n) => (n == null ? "–" : n.toLocaleString("ja-JP") + "円");
  const boat = (n) => `<span class="boat l${n}">${n}</span>`;
  const combo = (c) => c.split("-").join("-");
  const fmtDate = (hd) => `${+hd.slice(4, 6)}月${+hd.slice(6, 8)}日`;
  const wd = (hd) => "日月火水木金土"[new Date(+hd.slice(0, 4), +hd.slice(4, 6) - 1, +hd.slice(6, 8)).getDay()];
  const todayJST = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10).replace(/-/g, "");
  const nowHM = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(11, 16);

  async function getJSON(path, ttlMs = 60000) {
    const c = state.cache[path];
    if (c && Date.now() - c.t < ttlMs) return c.v;
    const bust = Math.floor(Date.now() / 60000);
    const res = await fetch(`${DATA}${path}?v=${bust}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    const v = await res.json();
    state.cache[path] = { t: Date.now(), v };
    return v;
  }

  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
  };
  const favs = () => store.get("kyotei.favs", {});
  const setFavs = (f) => store.set("kyotei.favs", f);

  function raceKey(r) { return `${r.jcd}-${r.rno}`; }
  function findRace(key) { return state.day?.races.find((r) => raceKey(r) === key); }
  function resultBadge(r, bets) {
    if (!r.result) {
      return r.deadline <= nowHM() && state.date === todayJST() ? `<span class="pill gray">結果待ち</span>` : `<span class="pill gray">締切 ${esc(r.deadline)}</span>`;
    }
    if (!bets) return `<span class="pill gray">結果 ${esc(r.result.tri)}</span>`;
    return bets.includes(r.result.tri)
      ? `<span class="pill good">的中 ${yen(r.result.pay)}</span>`
      : `<span class="pill bad">不的中 ${esc(r.result.tri)}</span>`;
  }

  // ---------- 画面: AI予想 ----------
  function honmeiCard(r) {
    const ai = r.ai;
    const order = [...r.boats].sort((a, b) => ai.p[b.lane - 1] - ai.p[a.lane - 1]);
    const lines = order.slice(0, 6).map((b) => {
      const p = ai.p[b.lane - 1];
      return `<div class="bline"><span class="mark">${ai.marks[b.lane] || ""}</span>${boat(b.lane)}
        <div class="bname">${esc(b.name)}<span class="muted">${esc(b.cls)}・${esc(b.branch)}</span><div class="bar"><i style="width:${Math.min(100, p * 100 / 0.8)}%"></i></div></div>
        <span class="pct">${pct(p)}</span></div>`;
    }).join("");
    const top = Object.fromEntries(ai.top);
    const bets = ai.bets.map((c) => {
      const pr = top[c];
      const od = r.odds?.[c];
      const ev = od ? pr * od : null;
      const hit = r.result?.tri === c;
      return `<div class="bet ${hit ? "hit" : ""}"><span class="combo">${combo(c)}${pr >= 0.2 ? ' <span class="star" title="確率20%以上">★</span>' : ""}</span>
        <span class="muted mono">${pct(pr, 1)}</span><span class="mono small">${od ? od.toFixed(1) + "倍" : ""}</span><span class="mono small">${ev ? "期待値" + Math.round(ev * 100) + "%" : ""}</span></div>`;
    }).join("");
    return `<div class="card">
      <div class="row between wrap"><div class="race-title">${esc(r.venue)} ${r.rno}R</div>${resultBadge(r, ai.bets)}</div>
      <div class="row wrap muted small"><span>締切 ${esc(r.deadline)}</span><span>自信度 <b class="mono">${ai.conf}</b></span>${r.grade ? `<span>${esc(r.grade)}</span>` : ""}</div>
      <div class="lines">${lines}</div>
      <div class="muted small" style="margin-top:10px">推奨3連単5点（★は確率20%以上）${r.odds_at ? `・オッズ ${esc(r.odds_at)}時点` : ""}</div>
      <div class="bets">${bets}</div>
      <div style="margin-top:8px"><button class="back" data-open="${raceKey(r)}">レースの詳しい情報 ›</button></div>
    </div>`;
  }

  function head2Card(r) {
    const ai = r.ai;
    const [h1, h2] = ai.head2;
    const b = (n) => r.boats[n - 1];
    const win = r.result ? +r.result.tri.split("-")[0] : null;
    const badge = r.result
      ? (ai.head2.includes(win) ? `<span class="pill good">頭的中 ${esc(r.result.tri)}</span>` : `<span class="pill bad">${win}号艇が1着 ${esc(r.result.tri)}</span>`)
      : resultBadge(r);
    let tenji = `<div class="muted small" style="margin-top:8px">展示の情報は、展示の後（締切の約25分前）に出ます。</div>`;
    if (r.tenji) {
      const rows = [1, 2, 3, 4, 5, 6].map((n) => {
        const t = r.tenji[n] || {};
        const head = ai.head2.includes(n);
        return `<tr class="${head ? "hl" : ""}"><td class="l">${boat(n)} ${esc(b(n).name)}${head ? ' <span class="pill">頭</span>' : ""}</td>
          <td class="mono ${t.rank === 1 ? "rank1" : t.rank >= 5 ? "rank5" : ""}">${t.tenji ?? "–"}</td><td class="mono">${t.rank ?? "–"}</td><td class="mono">${t.ex_course ?? "–"}</td><td class="mono">${esc(t.ex_st ?? "–")}</td></tr>`;
      }).join("");
      tenji = `<div class="tablewrap" style="margin-top:10px"><table><thead><tr><th>艇</th><th>展示タイム</th><th>順位</th><th>展示進入</th><th>ST</th></tr></thead><tbody>${rows}</tbody></table></div>
        <div class="muted small">展示の情報は参考です。頭2艇の予想は朝のまま変えていません。</div>`;
    }
    return `<div class="card">
      <div class="row between wrap"><div class="race-title">${esc(r.venue)} ${r.rno}R</div>${badge}</div>
      <div class="muted small">締切 ${esc(r.deadline)}・1号艇 ${esc(b(1).name)} の1着率 <b class="mono">${pct(ai.p[0])}</b></div>
      <div class="lines">
        <div class="bline"><span class="mark">頭1</span>${boat(h1)}<div class="bname">${esc(b(h1).name)}<span class="muted">${esc(b(h1).cls)}</span></div><span class="pct">${pct(ai.p[h1 - 1])}</span></div>
        <div class="bline"><span class="mark">頭2</span>${boat(h2)}<div class="bname">${esc(b(h2).name)}<span class="muted">${esc(b(h2).cls)}</span></div><span class="pct">${pct(ai.p[h2 - 1])}</span></div>
      </div>
      ${tenji}
      <div style="margin-top:8px"><button class="back" data-open="${raceKey(r)}">レースの詳しい情報 ›</button></div>
    </div>`;
  }

  function statBlock(title, s, kind) {
    if (!s) return "";
    const roi = s.points ? Math.round((s.pay / (s.points * 100)) * 100) : null;
    if (kind === "head2") {
      return `<div class="stat"><div class="k">${title}</div><div class="v">${s.races ? Math.round((s.hits / s.races) * 100) + "%" : "–"}</div><div class="muted small">${s.hits}/${s.races}レースで頭的中${s.pending ? `・残り${s.pending}` : ""}</div></div>`;
    }
    return `<div class="stat"><div class="k">${title}</div><div class="v ${roi == null ? "" : roi >= 100 ? "good" : "bad"}">${roi == null ? "–" : roi + "%"}</div>
      <div class="muted small">的中 ${s.hits}/${s.races}・購入 ${yen(s.points * 100)}・払戻 ${yen(s.pay)}${s.pending ? `・残り${s.pending}` : ""}</div></div>`;
  }

  async function recordsSection(kind) {
    let rec;
    try { rec = await getJSON("records.json"); } catch { return ""; }
    const d = rec.days.find((x) => x.date === state.date);
    const since = rec.since ? fmtDate(rec.since) : "";
    let html = `<h2>成績</h2><p class="lead">朝に決めた予想のうち、決めた時点で締切前だったレースだけを数えています（各100円）。記録開始 ${since}。</p>`;
    if (kind === "head2") {
      html += `<div class="stats">${statBlock(`${fmtDate(state.date)}`, d?.head2, "head2")}${statBlock("記録開始から", rec.total.head2, "head2")}</div>`;
    } else {
      html += `<div class="stats">${statBlock(`${fmtDate(state.date)}・推奨5点`, d?.top5)}${statBlock("記録開始から・推奨5点", rec.total.top5)}
        ${statBlock(`${fmtDate(state.date)}・20%以上だけ`, d?.strong)}${statBlock("記録開始から・20%以上だけ", rec.total.strong)}</div>`;
    }
    const rows = rec.days.map((x) => {
      const s = kind === "head2" ? x.head2 : x.top5;
      const s2 = x.strong;
      if (kind === "head2") return `<tr><td>${fmtDate(x.date)}</td><td class="mono">${s.hits}/${s.races}</td><td class="mono">${s.races ? Math.round((s.hits / s.races) * 100) + "%" : "–"}</td></tr>`;
      const roi = s.points ? Math.round((s.pay / (s.points * 100)) * 100) + "%" : "–";
      const roi2 = s2.points ? Math.round((s2.pay / (s2.points * 100)) * 100) + "%" : "–";
      return `<tr><td>${fmtDate(x.date)}</td><td class="mono">${s.hits}/${s.races}</td><td class="mono">${roi}</td><td class="mono">${s2.hits}/${s2.races}</td><td class="mono">${roi2}</td></tr>`;
    }).join("");
    const head = kind === "head2" ? `<tr><th>日付</th><th>頭的中</th><th>的中率</th></tr>` : `<tr><th>日付</th><th>5点 的中</th><th>回収率</th><th>20%以上</th><th>回収率</th></tr>`;
    html += `<details class="card"><summary>日別の成績を見る</summary><div class="tablewrap" style="margin-top:8px"><table><thead>${head}</thead><tbody>${rows}</tbody></table></div></details>`;
    return html;
  }

  async function renderAI() {
    const day = state.day;
    const seg = `<div class="seg"><button data-sub="honmei" class="${state.sub === "honmei" ? "on" : ""}">本命狙い</button><button data-sub="head2" class="${state.sub === "head2" ? "on" : ""}">頭2艇</button></div>`;
    if (!day) { view.innerHTML = seg + `<div class="empty">この日の予想はまだありません。毎朝5時20分ごろに作ります。</div>`; return; }
    let body = "";
    if (state.sub === "honmei") {
      const races = day.picks.map(findRace).filter(Boolean);
      body = `<h2>AIが自信のある${races.length}レース</h2><p class="lead">${esc(day.fixed_at)}に固定した朝の予想です。一日を通して変わりません。自信度はその日の全レースの中での順位（100が一番）です。</p>`
        + (races.length ? races.map(honmeiCard).join("") : `<div class="empty">対象のレースはありません。</div>`)
        + await recordsSection("top5");
    } else {
      const races = day.head2.map(findRace).filter(Boolean);
      body = `<h2>頭2艇（1号艇が負けそうなレース）</h2><p class="lead">朝のAIで1号艇の1着率が21%以下のレースで、1号艇以外の1着候補を2艇出します。3連単の買い目は出しません。</p>`
        + (races.length ? races.map(head2Card).join("") : `<div class="empty">今日は対象のレースがありません。</div>`)
        + await recordsSection("head2");
    }
    view.innerHTML = seg + body + footer();
  }

  // ---------- 画面: レース ----------
  function renderRaces() {
    const day = state.day;
    if (!day) { view.innerHTML = `<div class="empty">この日のレースはまだありません。</div>`; return; }
    if (state.race) return renderRaceDetail(findRace(state.race));
    const venues = [...new Map(day.races.map((r) => [r.jcd, r.venue])).entries()].sort();
    if (!state.venue || !venues.find(([j]) => j === state.venue)) state.venue = venues[0]?.[0];
    const chips = venues.map(([j, v]) => `<button class="chip ${j === state.venue ? "on" : ""}" data-venue="${j}">${esc(v)}</button>`).join("");
    const cells = day.races.filter((r) => r.jcd === state.venue).sort((a, b) => a.rno - b.rno).map((r) => {
      const tags = [];
      if (day.picks.includes(raceKey(r))) tags.push(`<span class="pill">本命</span>`);
      if (day.head2.includes(raceKey(r))) tags.push(`<span class="pill">頭2艇</span>`);
      const res = r.result ? `<div class="mono small">${esc(r.result.tri)} ${yen(r.result.pay)}</div>` : `<div class="muted small">締切 ${esc(r.deadline)}</div>`;
      return `<button class="rcell" data-open="${raceKey(r)}"><div class="row between"><b>${r.rno}R</b><span class="muted small mono">◎${r.ai.honmei}</span></div>${res}<div class="row wrap">${tags.join("")}</div></button>`;
    }).join("");
    view.innerHTML = `<h2>${fmtDate(state.date)}（${wd(state.date)}）のレース</h2><p class="lead">場を選んで、レースをタップすると出走表とAIの確率が見られます。</p><div class="chips">${chips}</div><div class="grid12">${cells}</div>` + footer();
  }

  function renderRaceDetail(r) {
    if (!r) { state.race = null; return renderRaces(); }
    const ai = r.ai;
    const f = favs();
    const rows = r.boats.map((b) => `<tr class="${f[b.toban] ? "hl" : ""}">
      <td class="l">${boat(b.lane)} <button class="back" data-racer="${b.toban}">${esc(b.name)}</button> <span class="muted small">${esc(b.cls)}</span></td>
      <td class="mono"><b>${pct(ai.p[b.lane - 1])}</b></td>
      <td class="mono">${b.nat_win.toFixed(2)}</td><td class="mono">${b.loc_win.toFixed(2)}</td>
      <td class="mono">${b.c_n ? pct(b.c_win) : "–"}<span class="muted small"> (${b.c_n})</span></td>
      <td class="mono">${b.st_avg.toFixed(2)}</td><td class="mono">${b.motor_2.toFixed(0)}%</td></tr>`).join("");
    const top = ai.top.map(([c, p]) => `<div class="bet ${r.result?.tri === c ? "hit" : ""}"><span class="combo">${c}</span><span class="muted mono">${pct(p, 1)}</span><span></span><span></span></div>`).join("");
    const tags = [];
    if (state.day.picks.includes(raceKey(r))) tags.push(`<span class="pill">本命狙いの対象</span>`);
    if (state.day.head2.includes(raceKey(r))) tags.push(`<span class="pill">頭2艇の対象</span>`);
    view.innerHTML = `<button class="back" data-backrace>‹ レース一覧</button>
      <h2>${esc(r.venue)} ${r.rno}R</h2><div class="row wrap muted small"><span>締切 ${esc(r.deadline)}</span>${r.grade ? `<span>${esc(r.grade)}</span>` : ""}<span>自信度 ${ai.conf}</span>${tags.join("")}</div>
      ${r.result ? `<div class="card"><div class="row between"><b>結果</b><span class="mono"><b>${esc(r.result.tri)}</b>　${yen(r.result.pay)}</span></div></div>` : ""}
      <div class="card"><h3>出走表とAIの1着率</h3><div class="tablewrap"><table><thead><tr><th>艇・選手</th><th>AI 1着率</th><th>全国勝率</th><th>当地勝率</th><th>この枠の1着率</th><th>平均ST</th><th>モーター</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="muted small" style="margin-top:6px">「この枠の1着率」は過去1年にこの枠で走ったときの1着率（かっこ内は回数）。選手名をタップすると癖が見られます。</div></div>
      <div class="card"><h3>AIの3連単 上位10点</h3><div class="bets">${top}</div></div>` + footer();
  }

  // ---------- 画面: 選手の癖 ----------
  function habits(p) {
    const out = [];
    const c1 = p.course["1"], c2 = p.course["2"], c4 = p.course["4"];
    if (c1 && c1.n >= 5) {
      if (c1.win >= 0.65) out.push("イン逃げが強い");
      else if (c1.win <= 0.4) out.push("インで取りこぼしが多い");
    }
    const sashi = (p.kimarite["差し"] || 0) + (p.kimarite["まくり差し"] || 0);
    const makuri = p.kimarite["まくり"] || 0;
    if (sashi >= 3 && sashi > makuri * 1.5) out.push("差しが得意");
    if (makuri >= 3 && makuri > sashi) out.push("まくりが得意");
    const sts = Object.values(p.course).filter((c) => c && c.st != null && c.n >= 3);
    if (sts.length) {
      const st = sts.reduce((a, c) => a + c.st * c.n, 0) / sts.reduce((a, c) => a + c.n, 0);
      if (st <= 0.14) out.push("スタートが速い");
      else if (st >= 0.18) out.push("スタートが遅め");
    }
    const ent = Object.entries(p.entry || {}).filter(([l, e]) => +l >= 3 && e.n >= 3);
    if (ent.some(([, e]) => e.inner >= 0.3)) out.push("前付けすることがある");
    const outer = ["4", "5", "6"].map((k) => p.course[k]).filter((c) => c && c.n >= 5);
    if (outer.length && outer.reduce((a, c) => a + c.top3 * c.n, 0) / outer.reduce((a, c) => a + c.n, 0) >= 0.45) out.push("外枠でも舟券に絡む");
    if (c2 && c2.n >= 5 && c2.top2 >= 0.5) out.push("2コースで連に絡みやすい");
    if (c4 && c4.n >= 5 && c4.win >= 0.25) out.push("カドから攻める");
    if (p.F >= 2) out.push(`フライング${p.F}回（期間中）`);
    return out;
  }

  async function renderRacer() {
    if (state.racer) return renderRacerProfile(state.racer);
    let idx = [];
    try { idx = await getJSON("racers_index.json", 3600e3); } catch {}
    const q = store.get("kyotei.q", "");
    view.innerHTML = `<h2>選手の癖</h2><p class="lead">名前か登録番号で探せます。過去1年の公式データから、コース別の成績・スタート・決まり手を出します。</p>
      <input class="input" id="q" placeholder="例：峰竜太、4320" value="${esc(q)}" autocomplete="off" />
      <div id="hits"></div>` + footer();
    const input = document.getElementById("q");
    const hits = document.getElementById("hits");
    const show = () => {
      const v = input.value.trim().replace(/\s/g, "");
      store.set("kyotei.q", v);
      if (!v) {
        const today = state.day ? state.day.races.flatMap((r) => r.boats.filter((b) => b.cls === "A1").map((b) => [b.toban, b.name, b.branch, b.cls])) : [];
        const uniq = [...new Map(today.map((x) => [x[0], x])).values()].slice(0, 30);
        hits.innerHTML = uniq.length ? `<div class="muted small" style="margin:12px 2px 4px">この日に走るA1級の選手</div>` + list(uniq) : "";
        return;
      }
      const m = idx.filter((x) => x[0].startsWith(v) || x[1].includes(v)).slice(0, 40);
      hits.innerHTML = m.length ? list(m) : `<div class="empty">見つかりませんでした。</div>`;
    };
    const list = (arr) => `<div class="card" style="padding:4px 14px">` + arr.map((x) => `<button class="rcell" style="display:block;width:100%;border:0;border-bottom:1px solid var(--line);border-radius:0" data-racer="${x[0]}"><b>${esc(x[1])}</b> <span class="muted small">${x[0]}・${esc(x[2])}・${esc(x[3])}</span></button>`).join("") + `</div>`;
    input.addEventListener("input", show);
    show();
  }

  async function renderRacerProfile(toban) {
    view.innerHTML = `<div class="skel"></div><div class="skel"></div>`;
    let p;
    try { p = await getJSON(`racers/${toban}.json`, 3600e3); } catch { view.innerHTML = `<button class="back" data-backracer>‹ 選手を探す</button><div class="empty">この選手のデータはまだありません。</div>`; return; }
    const f = favs();
    const fav = f[toban];
    const rows = [1, 2, 3, 4, 5, 6].map((c) => {
      const x = p.course[c];
      if (!x) return `<tr><td>${c}コース</td><td class="mono">0</td><td>–</td><td>–</td><td>–</td><td>–</td></tr>`;
      return `<tr><td>${c}コース</td><td class="mono">${x.n}</td><td class="mono">${pct(x.win)}</td><td class="mono">${pct(x.top2)}</td><td class="mono">${pct(x.top3)}</td><td class="mono">${x.st != null ? x.st.toFixed(2) : "–"}</td></tr>`;
    }).join("");
    const kim = Object.entries(p.kimarite).filter(([k]) => k).map(([k, v]) => `<span class="tag">${esc(k)} ${v}</span>`).join("") || `<span class="muted small">1着なし</span>`;
    const lost = Object.entries(p.lost_in1 || {}).filter(([k]) => k).map(([k, v]) => `<span class="tag">${esc(k)} ${v}</span>`).join("") || `<span class="muted small">なし</span>`;
    const ent = Object.entries(p.entry).sort().map(([l, e]) => `<tr><td>${boat(+l)} 枠</td><td class="mono">${e.n}</td><td class="mono">${pct(e.same)}</td><td class="mono">${pct(e.inner)}</td></tr>`).join("");
    const rec = p.recent.map((x) => `<tr><td>${fmtDate(x.date)}</td><td class="l">${esc(x.venue)} ${x.rno}R</td><td class="mono">${x.lane}</td><td class="mono">${x.course}</td><td class="mono ${x.rank === 1 ? "rank1" : ""}">${x.rank > 6 ? "失" : x.rank}</td><td class="mono">${esc(x.st)}</td></tr>`).join("");
    const today = state.day ? state.day.races.filter((r) => r.boats.some((b) => b.toban === toban)) : [];
    const h = habits(p);
    view.innerHTML = `<button class="back" data-backracer>‹ 選手を探す</button>
      <div class="row between wrap" style="margin-top:6px"><h2 style="margin:6px 0">${esc(p.name)}</h2><button class="favbtn ${fav ? "on" : ""}" data-fav="${toban}" data-name="${esc(p.name)}">${fav ? "★ お気に入り" : "☆ お気に入りに追加"}</button></div>
      <div class="muted small">${toban}・${esc(p.branch)}・${esc(p.cls)}・全国勝率 ${esc(p.nat_win)}・集計 ${fmtDate(p.period[0])}〜${fmtDate(p.period[1])}（${p.starts}走）</div>
      ${h.length ? `<div class="card"><h3>癖</h3>${h.map((x) => `<span class="tag">${esc(x)}</span>`).join("")}</div>` : ""}
      ${today.length ? `<div class="card"><h3>${fmtDate(state.date)}の出走</h3>${today.map((r) => `<button class="chip" data-open="${raceKey(r)}">${esc(r.venue)} ${r.rno}R（${r.boats.find((b) => b.toban === toban).lane}号艇）</button>`).join(" ")}</div>` : ""}
      <div class="card"><h3>コース別の成績</h3><div class="tablewrap"><table><thead><tr><th>進入</th><th>回数</th><th>1着率</th><th>2連対率</th><th>3連対率</th><th>平均ST</th></tr></thead><tbody>${rows}</tbody></table></div></div>
      <div class="card"><h3>1着の決まり手</h3>${kim}<h3 style="margin-top:12px">1コースで負けたときの相手の決まり手</h3>${lost}</div>
      <div class="card"><h3>進入の傾向</h3><div class="tablewrap"><table><thead><tr><th>枠</th><th>回数</th><th>枠なり</th><th>内に入った</th></tr></thead><tbody>${ent}</tbody></table></div></div>
      ${fav ? `<div class="card"><h3>メモ</h3><textarea class="input" id="memo" placeholder="気づいたことをメモ">${esc(fav.memo || "")}</textarea><div class="muted small">この端末に保存されます。</div></div>` : ""}
      <div class="card"><h3>最近の20走</h3><div class="tablewrap"><table><thead><tr><th>日付</th><th>レース</th><th>枠</th><th>進入</th><th>着</th><th>ST</th></tr></thead><tbody>${rec}</tbody></table></div></div>` + footer();
    const memo = document.getElementById("memo");
    if (memo) memo.addEventListener("input", () => { const ff = favs(); if (ff[toban]) { ff[toban].memo = memo.value; setFavs(ff); } });
  }

  // ---------- 画面: お気に入り ----------
  function renderFav() {
    const f = favs();
    const ids = Object.keys(f);
    if (!ids.length) {
      view.innerHTML = `<h2>お気に入り</h2><div class="empty">まだ登録がありません。「選手の癖」で選手を開いて、☆を押すと登録できます。</div>` + footer();
      return;
    }
    const races = state.day?.races || [];
    const cards = ids.map((t) => {
      const runs = races.filter((r) => r.boats.some((b) => b.toban === t));
      const runHtml = runs.length ? runs.map((r) => `<button class="chip" data-open="${raceKey(r)}">${esc(r.venue)} ${r.rno}R ${r.boats.find((b) => b.toban === t).lane}号艇・${esc(r.deadline)}</button>`).join(" ") : `<span class="muted small">${fmtDate(state.date || todayJST())}の出走はありません</span>`;
      return `<div class="card"><div class="row between"><button class="back" style="font-size:16px" data-racer="${t}">${esc(f[t].name)}</button><span class="muted small">${t}</span></div>
        <div class="row wrap" style="margin-top:6px">${runHtml}</div>${f[t].memo ? `<div class="muted small" style="margin-top:6px">メモ：${esc(f[t].memo)}</div>` : ""}</div>`;
    }).join("");
    view.innerHTML = `<h2>お気に入り</h2><p class="lead">登録した選手と、${fmtDate(state.date || todayJST())}の出走です。登録とメモはこの端末に保存されます。</p>${cards}` + footer();
  }

  // ---------- 画面: AI検証 ----------
  async function renderLab() {
    let bt, model;
    try { [bt, model] = await Promise.all([getJSON("backtest.json", 3600e3), getJSON("model.json", 3600e3)]); } catch { view.innerHTML = `<div class="empty">検証データを読み込めませんでした。</div>`; return; }
    const m = Object.entries(bt.monthly_top5).map(([k, v]) => `<tr><td>${k.slice(0, 4)}年${+k.slice(4)}月</td><td class="mono">${v.hits}/${v.races}</td><td class="mono">${v.roi}%</td></tr>`).join("");
    view.innerHTML = `<h2>AI検証</h2><p class="lead">学習に使っていない ${fmtDate(bt.test_from)}〜${fmtDate(bt.test_to)}（${bt.days}日・${bt.n_races.toLocaleString()}レース）で、毎朝と同じ選び方を当てはめた結果です。</p>
      <div class="stats">
        <div class="stat"><div class="k">AI本命の1着率</div><div class="v">${bt.honmei_win}%</div><div class="muted small">全レース</div></div>
        <div class="stat"><div class="k">本命狙い 推奨5点</div><div class="v ${bt.top5.roi >= 100 ? "good" : "bad"}">${bt.top5.roi}%</div><div class="muted small">回収率・的中率 ${bt.top5.hit_rate}%</div></div>
        <div class="stat"><div class="k">頭2艇 頭的中</div><div class="v">${bt.head2.hit_rate}%</div><div class="muted small">${bt.head2.hits}/${bt.head2.races}レース</div></div>
        <div class="stat"><div class="k">全レース 推奨5点</div><div class="v bad">${bt.all5.roi}%</div><div class="muted small">回収率</div></div>
      </div>
      <div class="card"><h3>月ごとの本命狙い（推奨5点）</h3><div class="tablewrap"><table><thead><tr><th>月</th><th>的中</th><th>回収率</th></tr></thead><tbody>${m}</tbody></table></div></div>
      <div class="card"><h3>AIの仕組み</h3>
        <p class="small">全国・当地勝率、級別、モーター・ボート2連率、年齢・体重、その枠での過去1年の1着・2連対・3連対率、平均スタート、直近30走の1着率、場ごとのイン1着率など${model.features.length}項目から、各艇の1着率を出しています。3連単の確率は1着率から計算しています。</p>
        <p class="small">学習データ：${fmtDate(model.train_from)}〜${fmtDate(model.train_to)}の${model.n_races.toLocaleString()}レース（${esc(model.trained_at)}に学習）。毎月1日に最新のデータで学び直します。</p>
        <p class="small">予想の精度（小さいほど正確）：AI ${bt.logloss_model}、枠番だけ ${bt.logloss_lane_only}</p></div>
      <div class="note">控除率が約25%あるため、多くの買い目は長い目で見ると回収率100%を下回ります。過去の検証で100%を超えた条件でも、この先も勝てるとは限りません。</div>` + footer();
  }

  function footer() {
    const u = state.day?.updated_at;
    return `<div class="foot">${u ? `最終更新 ${esc(u)}・` : ""}データ：BOAT RACE公式サイト。予想は参考情報で、的中や利益を保証するものではありません。舟券の購入は20歳以上、無理のない範囲で。</div>`;
  }

  // ---------- 全体 ----------
  async function loadDay(hd) {
    state.date = hd;
    try { state.day = await getJSON(`days/${hd}.json`); } catch { state.day = null; }
  }

  async function render() {
    document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === state.tab));
    if (state.tab === "ai") await renderAI();
    else if (state.tab === "races") renderRaces();
    else if (state.tab === "racer") await renderRacer();
    else if (state.tab === "fav") renderFav();
    else if (state.tab === "lab") await renderLab();
  }

  document.getElementById("nav").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (!b) return;
    state.tab = b.dataset.tab;
    if (state.tab === "races") state.race = null;
    if (state.tab === "racer") state.racer = null;
    window.scrollTo(0, 0);
    render();
  });

  view.addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    if (t.dataset.sub) { state.sub = t.dataset.sub; render(); }
    else if (t.dataset.venue) { state.venue = t.dataset.venue; render(); }
    else if (t.dataset.open) { state.tab = "races"; state.race = t.dataset.open; window.scrollTo(0, 0); render(); }
    else if ("backrace" in t.dataset) { state.race = null; render(); }
    else if (t.dataset.racer) { state.tab = "racer"; state.racer = t.dataset.racer; window.scrollTo(0, 0); render(); }
    else if ("backracer" in t.dataset) { state.racer = null; render(); }
    else if (t.dataset.fav) {
      const f = favs();
      if (f[t.dataset.fav]) delete f[t.dataset.fav]; else f[t.dataset.fav] = { name: t.dataset.name, memo: "" };
      setFavs(f);
      render();
    }
  });

  dateSel.addEventListener("change", async () => { await loadDay(dateSel.value); state.race = null; render(); });

  async function init() {
    view.innerHTML = `<div class="skel"></div><div class="skel"></div><div class="skel"></div>`;
    let days = [];
    try { days = await getJSON("days_index.json"); } catch {}
    const today = todayJST();
    if (!days.includes(today)) days = [today, ...days];
    dateSel.innerHTML = days.map((d) => `<option value="${d}">${fmtDate(d)}（${wd(d)}）${d === today ? "今日" : ""}</option>`).join("");
    await loadDay(days[0]);
    if (!state.day && days[1]) { await loadDay(days[1]); dateSel.value = days[1]; }
    render();
    // 開いている間は5分ごとに最新を読み直す
    setInterval(async () => {
      if (state.date !== todayJST()) return;
      delete state.cache[`days/${state.date}.json`];
      delete state.cache["records.json"];
      await loadDay(state.date);
      if (state.tab === "ai" || (state.tab === "races")) render();
    }, 5 * 60 * 1000);
  }
  init();
})();
