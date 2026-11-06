// Leader console: one agenda step at a time; every change autosaves the draft minutes.
(() => {
  const D = window.CONSOLE;
  const M = D.meeting;
  const S = Object.assign({ done: [], skipped: [], current: null, reports: null, others: [], step: 0 }, D.state);
  const people = Object.fromEntries(D.members.map((m) => [m.id, m]));
  const STEPS = ["Attendance", "Bills and Communications", "Financial Report", "Community Reports",
    "Old Business", "New Business", "Winners", "Upcoming Chow", "Upcoming Events", "Review"];
  const EMPTY_NOTE = "Leave it empty if there's nothing this week; empty sections are left out of the minutes.";
  const HINTS = {
    "Old Business": "Carried forward from last meeting (its Old and New Business). Delete what's finished, update the rest.",
    "Upcoming Events": "Carried forward from last meeting. Delete past events, add new ones.",
    "Winners": "e.g. “50/50 drawing – Jim F $7.50” and “Weekly drawing – Dave G, not registered (up to $62)”.",
    "Upcoming Chow": "Leave it empty to show “See the attached chow list”.",
  };
  const RECENT_GUESTS = 8; // quick-pick buttons; older guests are in the name field's autocomplete
  // A guest on their Nth visit or later gets a reminder to invite them to apply for membership.
  const visitNo = (g) => { const p = D.guest_history[key(g.callsign)] || D.guest_history[key(g.name)]; return p && !p.member ? p.visits + 1 : 1; };
  const inviteDue = (g) => visitNo(g) >= D.invite_after;
  const INVITE = "Invite them to apply for membership";
  const ordinal = (n) => n + (["th", "st", "nd", "rd"][(n % 100 - 20) % 10] || ["th", "st", "nd", "rd"][n % 100] || "th");
  const panel = document.getElementById("panel");
  const saved = document.getElementById("saved");

  // ---------- helpers ----------
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "class") el.className = v;
      else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid);
    return el;
  };
  const key = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const label = (k) => k.startsWith("g:") ? k.slice(2) : (people[k]?.short || k);
  const fullName = (k) => k.startsWith("g:") ? k.slice(2) + " (guest)" : (people[k]?.name || k);
  const grow = (ta) => { ta.style.height = "auto"; ta.style.height = ta.scrollHeight + 2 + "px"; };

  // ---------- reports model ----------
  if (!S.reports) { // first load of this draft (or reopened): rebuild from saved minutes
    S.reports = {};
    for (const it of M.sections["Community Reports"] || []) {
      if (it.member) { S.reports[it.member] = it.text; if (!S.done.includes(it.member)) S.done.push(it.member); }
      else S.others.push(it.text);
    }
  }
  const present = () => [...M.remote, ...M.in_person, ...M.guests.map((g) => "g:" + g.name)];
  const remaining = () => present().filter((k) => !S.done.includes(k) && !S.skipped.includes(k) && k !== S.current);

  function reportText(k) {
    let t = (S.reports[k] || "").trim();
    if (!t) return "";
    const first = k.startsWith("g:") ? k.slice(2).split(" ")[0] : people[k]?.name.split(" ")[0];
    const lead = t.toLowerCase();
    if (first && !lead.startsWith(first.toLowerCase()) && !lead.startsWith(label(k).toLowerCase())) t = `${label(k)} ${t}`;
    return t;
  }
  function syncReports() {
    M.sections["Community Reports"] = [
      ...S.done.map((k) => ({ text: reportText(k), member: k.startsWith("g:") ? null : k })).filter((i) => i.text),
      ...S.others.filter((t) => t.trim()).map((t) => ({ text: t, member: null })),
    ];
  }

  // ---------- saving ----------
  let timer = null;
  const waiters = []; // every caller of save() is resolved when the next actual save finishes
  function save(now = false) {
    saved.textContent = "Saving…"; saved.className = "saved dirty";
    clearTimeout(timer);
    const done = new Promise((resolve) => waiters.push(resolve));
    timer = setTimeout(async () => {
      syncReports();
      try {
        const r = await fetch(`/api/meetings/${M.slug}`, {
          method: "PUT", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ meeting: M, state: S }),
        });
        if (!r.ok) throw new Error(await r.text());
        saved.textContent = "Saved ✓"; saved.className = "saved";
      } catch (e) { saved.textContent = "Not saved: " + e.message; saved.className = "saved err"; }
      waiters.splice(0).forEach((r) => r());
    }, now ? 0 : 700);
    return done;
  }
  document.getElementById("leader").addEventListener("change", (e) => { M.leader = e.target.value; save(); });
  window.addEventListener("beforeunload", (e) => { if (saved.classList.contains("dirty")) e.preventDefault(); });

  // ---------- steps ----------
  function go(i) { S.step = Math.max(0, Math.min(STEPS.length - 1, i)); render(); save(); window.scrollTo(0, 0); }
  document.getElementById("prev").onclick = () => go(S.step - 1);
  document.getElementById("next").onclick = () => go(S.step + 1);

  function render() {
    const nav = document.getElementById("steps");
    nav.replaceChildren(...STEPS.map((s, i) => h("button", { class: i === S.step ? "on" : "", onclick: () => go(i) }, `${i + 1}. ${s}`)));
    const step = STEPS[S.step];
    panel.replaceChildren(
      step === "Attendance" ? attendance() :
      step === "Community Reports" ? reports() :
      step === "Review" ? review() : listSection(step));
    panel.querySelectorAll("textarea").forEach(grow);
  }

  // ---------- attendance ----------
  function attendance() {
    const where = (id) => M.in_person.includes(id) ? "inperson" : M.remote.includes(id) ? "online" : "";
    const cycle = (id) => {
      const w = where(id);
      M.in_person = M.in_person.filter((x) => x !== id); M.remote = M.remote.filter((x) => x !== id);
      if (w === "") M.in_person.push(id); else if (w === "inperson") M.remote.push(id);
      render(); save();
    };
    // Guests: tap a recent guest, or type a name (autocomplete covers everyone who has visited).
    const same = (a, b) => (a.callsign && b.callsign && key(a.callsign) === key(b.callsign)) || key(a.name) === key(b.name);
    const here = (g) => M.guests.some((x) => same(x, g));
    const visitNote = (g) => `${ordinal(g.visits + 1)} visit`;
    const toggleGuest = (g) => {
      if (here(g)) M.guests = M.guests.filter((x) => !same(x, g));
      else M.guests.push({ name: g.name, callsign: g.callsign || "", notes: visitNote(g) });
      render(); save();
    };
    const recent = D.past_guests.slice(0, RECENT_GUESTS);
    const datalist = h("datalist", { id: "pastguests" },
      D.past_guests.map((g) => h("option", { value: g.name }, [g.callsign, `${g.visits} visit${g.visits > 1 ? "s" : ""}`].filter(Boolean).join(" · "))));
    const guestInfo = h("div", { class: "ghint" });
    const gname = h("input", { type: "text", placeholder: "Guest name", list: "pastguests", autocomplete: "off", oninput: () => {
      const g = D.guest_history[key(gname.value)];
      guestInfo.textContent = !g ? "" : g.member ? `${g.name} is a member now. Mark them above instead.`
        : `${g.name}${g.callsign ? " " + g.callsign : ""}: ${ordinal(g.visits + 1)} visit (last ${g.last})` + (g.visits + 1 >= D.invite_after ? `. ${INVITE}.` : "");
      if (g && g.callsign && !gcall.value) gcall.value = g.callsign;
    } });
    const gcall = h("input", { type: "text", placeholder: "Callsign", size: 9 });
    const gnote = h("input", { type: "text", placeholder: "Note (optional)" });
    const add = () => {
      if (!gname.value.trim()) return;
      const prev = D.guest_history[key(gname.value)];
      const g = { name: gname.value.trim(), callsign: gcall.value.trim().toUpperCase(), notes: gnote.value.trim() };
      if (prev && !prev.member && !g.notes) g.notes = visitNote(prev);
      if (!here(g)) M.guests.push(g);
      render(); save();
    };
    const n = (w) => w === "inperson" ? M.in_person.length : M.remote.length;
    return h("div", {},
      h("h2", {}, `Attendance: ${M.in_person.length} in person, ${M.remote.length} online, ${M.guests.length + M.visitors} guest${M.guests.length + M.visitors === 1 ? "" : "s"}`),
      h("p", { class: "legend" }, "Tap a name to cycle: ", h("span", { class: "mbtn" }, "absent"), "→",
        h("span", { class: "mbtn inperson" }, `in person (${n("inperson")})`), "→", h("span", { class: "mbtn online" }, `online (${n("online")})`)),
      h("div", { class: "grid" }, D.members.map((m) => h("button", { class: "mbtn " + where(m.id), onclick: () => cycle(m.id) },
        m.name, h("small", {}, [m.callsign, where(m.id) === "inperson" ? "in person" : where(m.id) === "online" ? "online" : ""].filter(Boolean).join(" · "))))),
      h("h2", { style: "margin-top:1.4rem" }, "Guests"),
      recent.length ? [h("p", { class: "hint" }, "Recent guests: tap to add or remove. Type below for anyone else."),
        h("div", { class: "grid" }, recent.map((g) => h("button", { class: "mbtn " + (here(g) ? "inperson" : ""), onclick: () => toggleGuest(g) },
          g.name, h("small", {}, [g.callsign, `${g.visits} visit${g.visits > 1 ? "s" : ""}`, here(g) ? "here" : ""].filter(Boolean).join(" · ")),
          g.visits + 1 >= D.invite_after ? h("span", { class: "invite" }, "invite to join") : null)))] : null,
      datalist,
      M.guests.map((g, i) => h("div", { class: "row" }, h("span", { style: "flex:1" }, `${g.name} ${g.callsign || ""} ${g.notes ? "(" + g.notes + ")" : ""}`,
          inviteDue(g) ? h("span", { class: "invite" }, "invite to join") : null),
        h("button", { class: "btn small ghost", onclick: () => { M.guests.splice(i, 1); render(); save(); } }, "Remove"))),
      h("div", { class: "row" }, gname, gcall, gnote, h("button", { class: "btn small", onclick: add }, "Add guest")),
      guestInfo,
      h("p", { class: "counter" }, "Visitors whose names aren't recorded (e.g. family): ",
        h("button", { class: "btn small ghost", onclick: () => { M.visitors = Math.max(0, M.visitors - 1); render(); save(); } }, "−"),
        h("b", {}, String(M.visitors)),
        h("button", { class: "btn small ghost", onclick: () => { M.visitors++; render(); save(); } }, "+")));
  }

  // ---------- community reports ----------
  function call(k) { if (S.current && !S.done.includes(S.current)) S.skipped.push(S.current); S.skipped = S.skipped.filter((x) => x !== k); S.current = k; render(); save(); }
  function finish(nothing) {
    const k = S.current; if (!k) return;
    if (nothing && !(S.reports[k] || "").trim()) S.reports[k] = "nothing new";
    if (!S.done.includes(k)) S.done.push(k);
    S.current = null; render(); save();
  }
  function reports() {
    const rem = remaining();
    const groups = [["Online", rem.filter((k) => M.remote.includes(k))], ["In person", rem.filter((k) => M.in_person.includes(k))],
      ["Guests", rem.filter((k) => k.startsWith("g:"))]];
    const suggest = () => { const g = groups.find(([, ks]) => ks.length); if (g) call(g[1][Math.floor(Math.random() * g[1].length)]); };
    const li = (k, btn) => h("li", { class: k === S.current ? "cur" : "" }, h("span", {}, fullName(k)), btn);
    const queue = h("div", { class: "queue" },
      h("button", { class: "btn", onclick: suggest, disabled: !rem.length }, "Suggest next"),
      h("p", { class: "hint" }, "Online members first, then in person. Or click any name."),
      groups.map(([title, ks]) => ks.length ? [h("h3", {}, `${title} (${ks.length})`),
        h("ul", {}, ks.map((k) => li(k, h("button", { class: "btn small ghost", onclick: () => call(k) }, "Call on"))))] : null),
      S.skipped.length ? [h("h3", {}, "Come back to"), h("ul", {}, S.skipped.map((k) => li(k, h("button", { class: "btn small ghost", onclick: () => call(k) }, "Call on"))))] : null,
      S.done.length ? [h("h3", {}, `Done (${S.done.length})`), h("ul", {}, S.done.map((k) => li(k, h("button", { class: "btn small ghost", onclick: () => { S.done = S.done.filter((x) => x !== k); S.current = k; render(); save(); } }, "Edit"))))] : null,
      present().length ? null : h("p", { class: "hint" }, "Mark attendance first."));
    let floor;
    if (S.current) {
      const k = S.current;
      const past = k.startsWith("g:") ? [] : (D.history[k] || []);
      const ta = h("textarea", { rows: 4, placeholder: "What are they working on? (their name is added automatically)", oninput: (e) => { S.reports[k] = e.target.value; grow(e.target); save(); } });
      ta.value = S.reports[k] || "";
      floor = h("div", { class: "floor" },
        h("h3", {}, `${fullName(k)} has the floor`),
        k.startsWith("g:") && inviteDue(M.guests.find((g) => "g:" + g.name === k) || { name: k.slice(2) })
          ? h("div", { class: "invitebox" }, `This is ${k.slice(2).split(" ")[0]}'s ${ordinal(visitNo(M.guests.find((g) => "g:" + g.name === k)))} visit. ${INVITE}.`) : null,
        past.length ? h("div", {}, h("div", { class: "hint" }, "Follow up on what they said before:"),
          past.map(([d, t]) => h("div", { class: "past" }, h("b", {}, d + ": "), t))) : h("p", { class: "hint" }, k.startsWith("g:") ? "Guest: ask what brought them in, and their license and callsign." : "No earlier reports on record."),
        ta,
        h("div", { class: "row" },
          h("button", { class: "btn", onclick: () => finish(false) }, "Done"),
          h("button", { class: "btn ghost", onclick: () => finish(true) }, "Nothing new"),
          h("button", { class: "btn ghost", onclick: () => { S.skipped.push(k); S.current = null; render(); save(); } }, "Come back later")));
      setTimeout(() => ta.focus(), 0);
    } else {
      floor = h("div", { class: "floor" }, h("h3", {}, rem.length ? "Who's next?" : "Everyone has reported"),
        h("p", { class: "hint" }, rem.length ? "Press “Suggest next” or call on someone." : "Use “Edit” to change a report, or move on to Old Business."));
    }
    const others = h("div", {}, h("h3", { style: "margin-top:1.2rem" }, "Other reports"),
      h("p", { class: "hint" }, "For news passed along by someone who isn't present, e.g. “Jeremy sent a message recommending…”."),
      itemRows(S.others, (arr) => { S.others = arr; }));
    return h("div", {}, h("h2", {}, "Community Reports"), h("div", { class: "cols2" }, queue, h("div", {}, floor, others)));
  }

  // ---------- plain list sections ----------
  function itemRows(arr, setArr) {
    const wrap = h("div", {});
    const draw = () => wrap.replaceChildren(
      ...arr.map((t, i) => {
        const ta = h("textarea", { rows: 1, oninput: (e) => { arr[i] = e.target.value; setArr(arr); grow(e.target); save(); } });
        ta.value = t;
        return h("div", { class: "row" }, ta, h("button", { class: "btn small ghost", title: "Remove", onclick: () => { arr.splice(i, 1); setArr(arr); draw(); save(); } }, "✕"));
      }),
      h("button", { class: "btn small ghost", onclick: () => { arr.push(""); setArr(arr); draw(); wrap.querySelectorAll("textarea")[arr.length - 1].focus(); } }, "+ Add item"));
    draw();
    setTimeout(() => wrap.querySelectorAll("textarea").forEach(grow), 0);
    return wrap;
  }
  function listSection(sec) {
    const arr = (M.sections[sec] || []).map((i) => i.text);
    const set = (a) => { M.sections[sec] = a.map((t) => ({ text: t, member: null })); };
    const rows = itemRows(arr, set);
    const motion = sec === "New Business" || sec === "Old Business" ? h("button", { class: "btn small ghost", onclick: () => {
      arr.push("Motion: ___ moved to ___, seconded by ___. Passed."); set(arr); render(); save(); } }, "+ Motion") : null;
    const hint = [HINTS[sec], sec === "Upcoming Chow" ? null : EMPTY_NOTE].filter(Boolean).join(" ");
    return h("div", {}, h("h2", {}, sec), h("p", { class: "hint" }, hint), rows, motion);
  }

  // ---------- review & submit ----------
  function review() {
    const box = h("div", { class: "hint" }, "Loading preview…");
    save(true).then(async () => {
      const r = await fetch(`/api/meetings/${M.slug}/live`); box.className = ""; box.innerHTML = await r.text();
    });
    const missing = present().filter((k) => !S.done.includes(k));
    const invites = M.guests.filter(inviteDue);
    return h("div", {},
      h("h2", {}, "Review"),
      invites.length ? h("div", { class: "invitebox" }, `Before closing: invite ${invites.map((g) => `${g.name} (${ordinal(visitNo(g))} visit)`).join(", ")} to apply for membership.`) : null,
      missing.length ? h("p", { class: "hint" }, `No report recorded for: ${missing.map(label).join(", ")}.`) : null,
      h("p", {}, h("button", { class: "btn warn", onclick: async () => {
        const E = D.email, who = E.only_to ? `TEST MODE: only to ${E.only_to.join(", ")}` : `all ${E.roster} members on the roster`;
        if (!confirm(`Submit these minutes? They will be published to the archive and emailed (${who}).`)) return;
        await save(true); document.getElementById("submitform").submit();
      } }, "Submit minutes")),
      box);
  }

  render();
})();
