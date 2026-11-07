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
    "Old Business": "Every business item still open, carried from meeting to meeting until it's marked done. Update the text, give it an owner or a due date, or mark it done; done items show as done in tonight's minutes, then drop off.",
    "New Business": "Each item you add here is tracked: next week it's in Old Business, and it stays there until it's marked done.",
    "Upcoming Events": "Carried forward from last meeting. Delete past events, add new ones.",
    "Winners": "e.g. “50/50 drawing – Jim F $7.50” and “Weekly drawing – Dave G, not registered (up to $62)”.",
    "Upcoming Chow": "This section comes from the chow schedule and is updated when you submit. To change who brings chow, use the Chow page.",
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
  const STEP_LABEL = { "Upcoming Chow": "Chow" };  // the minutes' section keeps its full name
  function go(i) { S.step = Math.max(0, Math.min(STEPS.length - 1, i)); render(); save(); window.scrollTo(0, 0); }
  document.getElementById("prev").onclick = () => go(S.step - 1);
  document.getElementById("next").onclick = () => go(S.step + 1);

  function render() {
    const nav = document.getElementById("steps");
    nav.replaceChildren(...STEPS.map((s, i) => h("button", { class: i === S.step ? "on" : "", onclick: () => go(i) }, `${i + 1}. ${STEP_LABEL[s] || s}`)));
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
  async function noteStatus(n, status) {
    const r = await fetch(`/business/notes/${n.id}/${status}`, { method: "POST", headers: { Accept: "application/json" },
      body: new URLSearchParams({ meeting: M.slug }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { alert(j.error || j.detail || "Couldn't save"); return; }
    D.business = j; render(); save();
  }
  // What to ask a member about: the AI's short prompts when there are any, with what they actually said one click away.
  function followUp(k, past) {
    if (k.startsWith("g:")) return h("p", { class: "hint" }, "Guest: ask what brought them in, and their license and callsign.");
    if (!past.length) return h("p", { class: "hint" }, "No earlier reports on record.");
    const said = past.map(([d, t]) => h("div", { class: "past" }, h("b", {}, d + ": "), t));
    const asks = (D.ask_about || {})[k];
    if (!asks) return h("div", {}, h("div", { class: "hint" }, "Follow up on what they said before:"), said);
    return h("div", { class: "askabout" },
      h("div", { class: "hint" }, asks.length ? "Ask about " : "Nothing from earlier reports needs a follow-up ", h("span", { class: "badge ai" }, "AI")),
      asks.length ? h("ul", {}, asks.map((a) => h("li", {}, a))) : null,
      h("details", {}, h("summary", { class: "hint" }, "What they said before"), said));
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
        (D.business.notes || []).filter((n) => n.by === k).map((n) => h("div", { class: "bizcomment" }, h("b", {}, "They sent a note: "), n.text)),
        followUp(k, past),
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
    // Notes members sent in for tonight (Business page): read them out, then add them to the reports.
    const notes = (D.business.notes || []).length ? h("div", { class: "notesbox" },
      h("h3", {}, `Notes sent in (${D.business.notes.length})`),
      h("p", { class: "hint" }, "Members who sent a note for tonight. Read it out, then add it to the reports."),
      D.business.notes.map((n) => h("div", { class: "bizcomment" }, h("b", {}, `${n.name}: `), n.text, " ",
        h("button", { class: "btn small", onclick: async () => {
          S.others.push(`${n.name} sent a note: ${n.text}`);
          await noteStatus(n, "read"); } }, "Add to reports"),
        h("button", { class: "btn small ghost", onclick: () => noteStatus(n, "dismissed") }, "Skip")))) : null;
    const others = h("div", {}, h("h3", { style: "margin-top:1.2rem" }, "Other reports"),
      h("p", { class: "hint" }, "For news passed along by someone who isn't present, e.g. “Jeremy sent a message recommending…”."),
      itemRows(S.others, (arr) => { S.others = arr; }));
    return h("div", {}, h("h2", {}, "Community Reports"), notes, h("div", { class: "cols2" }, queue, h("div", {}, floor, others)));
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
    if (sec === "Upcoming Chow") return chowSection();
    if (sec === "Old Business" || sec === "New Business") return businessSection(sec);
    const arr = (M.sections[sec] || []).map((i) => i.text);
    const set = (a) => { M.sections[sec] = a.map((t) => ({ text: t, member: null })); };
    const rows = itemRows(arr, set);
    const motion = sec === "New Business" || sec === "Old Business" ? h("button", { class: "btn small ghost", onclick: () => {
      arr.push("Motion: ___ moved to ___, seconded by ___. Passed."); set(arr); render(); save(); } }, "+ Motion") : null;
    const hint = [HINTS[sec], EMPTY_NOTE].filter(Boolean).join(" ");
    return h("div", {}, h("h2", {}, sec), h("p", { class: "hint" }, hint), rows, motion);
  }

  // ---------- business: tracked items (business.py); every change is saved on the server at once ----------
  function businessSection(sec) {
    const isNew = sec === "New Business";
    const box = h("div", {});
    const send = async (url, data) => {
      const r = await fetch(url, { method: "POST", headers: { Accept: "application/json" },
        body: new URLSearchParams({ meeting: M.slug, ...data }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { alert(j.error || j.detail || "Couldn't save"); return; }
      D.business = j; saved.textContent = "Saved ✓"; saved.className = "saved"; draw();
    };
    const fmtDate = (d) => new Date(d + "T12:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
    const row = (x) => {
      const done = x.status === "done";
      const ta = h("textarea", { rows: 1, oninput: (e) => grow(e.target),
        onchange: (e) => send(`/business/${x.id}/edit`, { text: e.target.value }) });
      ta.value = x.text;
      const owner = h("select", { title: "Owner", onchange: (e) => send(`/business/${x.id}/edit`, { owner: e.target.value }) },
        h("option", { value: "" }, "No owner"),
        D.members.map((m) => h("option", { value: m.id, selected: m.id === x.owner }, m.name)));
      const due = h("input", { type: "date", value: x.due || "", title: "Due date",
        onchange: (e) => send(`/business/${x.id}/edit`, { due: e.target.value }) });
      return h("div", { class: "bizitem" + (done ? " done" : "") + (x.overdue ? " overdue" : "") },
        h("div", { class: "row" }, ta,
          h("button", { class: "btn small" + (done ? "" : " ghost"), title: done ? "Not done after all" : "Mark done",
            onclick: () => send(`/business/${x.id}/done`, { done: done ? 0 : 1 }) }, done ? "✓ Done" : "Done"),
          isNew ? h("button", { class: "btn small ghost", title: "Delete (added by mistake)",
            onclick: () => { if (confirm("Delete this item?")) send(`/business/${x.id}/delete`, {}); } }, "✕") : null),
        h("div", { class: "row meta" }, owner, " due ", due,
          x.overdue ? h("span", { class: "badge warn" }, `overdue since ${fmtDate(x.due)}`) : null,
          !isNew ? h("span", { class: "hint" }, ` since ${fmtDate(x.opened)}`) : null),
        (x.new_comments || []).map((c) => h("div", { class: "bizcomment" }, h("b", {}, `${c.name}: `), c.text)));
    };
    const add = () => {
      const ta = h("textarea", { rows: 1, placeholder: isNew ? "New item…" : "", oninput: (e) => grow(e.target) });
      const go = () => { if (ta.value.trim()) send("/business/add", { text: ta.value }); };
      return h("div", {}, h("div", { class: "row" }, ta, h("button", { class: "btn small", onclick: go }, "+ Add item")),
        h("button", { class: "btn small ghost", onclick: () => { ta.value = "Motion: ___ moved to ___, seconded by ___. Passed."; ta.focus(); grow(ta); } }, "+ Motion"));
    };
    const draw = () => {
      const items = isNew ? D.business.new : D.business.old;
      box.replaceChildren(
        ...(items.length ? items.map(row) : [h("p", { class: "muted" }, isNew ? "Nothing new yet." : "No open items.")]),
        isNew ? add() : h("p", { class: "hint" }, "New items go in New Business. ", h("a", { href: "/business", target: "_blank" }, "All business items")));
      setTimeout(() => box.querySelectorAll("textarea").forEach(grow), 0);
    };
    draw();
    return h("div", {}, h("h2", {}, sec), h("p", { class: "hint" }, HINTS[sec]), box);
  }

  // ---------- chow: did tonight's member bring it? The rest is read-only, from the chow schedule. ----------
  function chowSection() {
    const C = D.chow;
    const box = h("div", { class: "chowbox" }), list = h("ul", { class: "chowlist" });
    const showList = () => {
      M.sections["Upcoming Chow"] = C.section.map((t) => ({ text: t, member: null }));
      list.replaceChildren(...(C.section.length ? C.section.map((t) => h("li", {}, t)) : [h("li", { class: "muted" }, "Nothing scheduled.")]));
    };
    const post = async (data) => {
      const r = await fetch("/chow/record", { method: "POST", headers: { Accept: "application/json" },
        body: new URLSearchParams({ date: C.date, note: "", ...data }) });
      const j = await r.json();
      if (!r.ok) { alert(j.error || "Couldn't save"); return; }
      Object.assign(C, { covered_by: null, note: "" }, data, { section: j.section }); draw(); showList(); save();
    };
    const draw = () => {
      if (!C.member) { box.replaceChildren(h("b", {}, "Chow tonight: "), C.status === "none" ? "no chow tonight." : "nobody was scheduled."); return; }
      const what = h("input", { placeholder: "What they brought (optional)", value: C.note || "", size: 26 });
      const cover = h("select", {}, h("option", { value: "" }, "Who brought it?"),
        D.members.filter((m) => m.id !== C.member).map((m) => h("option", { value: m.id, selected: m.id === C.covered_by }, m.name)));
      const done = { provided: "✓ provided", missed: "✗ not provided", covered: "brought by someone else" }[C.status];
      box.replaceChildren(
        h("div", {}, h("b", {}, "Chow tonight: "), C.name, done ? h("span", { class: "badge" }, " " + done) : null,
          C.status === "covered" && C.covered_by ? ` (${people[C.covered_by]?.name || C.covered_by})` : "",
          C.note ? `: ${C.note}` : ""),
        h("div", { class: "row" }, what,
          h("button", { class: "btn small", onclick: () => post({ status: "provided", note: what.value }) }, "Provided"),
          h("button", { class: "btn small ghost", onclick: () => { if (confirm(`Record that ${C.name} did not provide chow? (Bylaws VII.F: $35 added to dues.)`)) post({ status: "missed" }); } }, "Not provided"),
          C.status && C.status !== "scheduled" ? h("button", { class: "btn small ghost", title: "Clear", onclick: () => post({ status: "scheduled" }) }, "Undo") : null),
        h("details", { class: "edit" }, h("summary", {}, "Someone else brought it"),
          h("div", { class: "row" }, cover,
            h("button", { class: "btn small ghost", onclick: () => { if (!cover.value) return alert("Pick who brought it."); post({ status: "covered", covered_by: cover.value, note: what.value }); } }, "Save"))));
    };
    draw(); showList();
    return h("div", {}, h("h2", {}, "Chow"), box,
      h("p", { class: "hint" }, HINTS["Upcoming Chow"], " ", h("a", { href: "/chow", target: "_blank" }, "Open the Chow page")),
      h("h3", {}, "In the minutes (Upcoming Chow)"), list);
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
