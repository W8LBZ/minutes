// A dropdown you can also type into: click (or ▾) to see every name, type to narrow the list,
// arrow keys + Enter or a click to pick. The input keeps the chosen name; the server matches it to a member.
//   makeCombo(input, [{value: "Amy Able", note: "KD8AMY"}, ...], {empty: "(nobody)"})
// On the Business page, <input data-combo="ID"> takes its names from <datalist id="ID">.
function makeCombo(input, options, { empty = "(nobody)" } = {}) {
  input.removeAttribute("list");
  input.setAttribute("autocomplete", "off");
  input.setAttribute("role", "combobox");
  const wrap = document.createElement("span");
  wrap.className = "combo";
  if (input.parentNode) input.replaceWith(wrap);
  const arrow = document.createElement("button");
  arrow.type = "button"; arrow.className = "combo-arrow"; arrow.tabIndex = -1; arrow.title = "Show all"; arrow.textContent = "▾";
  const menu = document.createElement("ul");
  menu.className = "combo-menu"; menu.hidden = true;
  wrap.append(input, arrow, menu);
  let shown = [], at = -1;

  const pick = (v) => {
    input.value = v; close();
    input.dispatchEvent(new Event("change", { bubbles: true }));
  };
  const close = () => { menu.hidden = true; at = -1; };
  const open = (filter) => {
    const f = (filter || "").toLowerCase().trim();
    shown = [{ value: "", note: empty }, ...options.filter((o) => !f || o.value.toLowerCase().includes(f) || (o.note || "").toLowerCase().includes(f))];
    if (f) shown = shown.slice(1);  // while typing, only matches
    menu.replaceChildren(...shown.map((o, i) => {
      const li = document.createElement("li");
      li.textContent = o.value || o.note;
      if (o.value && o.note) { const s = document.createElement("span"); s.textContent = o.note; li.append(s); }
      if (!o.value) li.className = "none";
      li.addEventListener("mousedown", (e) => { e.preventDefault(); pick(o.value); });
      return li;
    }));
    if (!shown.length) { const li = document.createElement("li"); li.className = "none"; li.textContent = "No member by that name"; menu.append(li); }
    at = f && shown.length ? 0 : -1; mark(); menu.hidden = false;
  };
  const mark = () => [...menu.children].forEach((li, i) => li.classList.toggle("at", i === at));

  input.addEventListener("focus", () => open(""));
  input.addEventListener("click", () => menu.hidden && open(""));
  input.addEventListener("input", () => open(input.value));
  input.addEventListener("blur", () => setTimeout(close, 120));
  arrow.addEventListener("mousedown", (e) => { e.preventDefault(); if (menu.hidden) { input.focus(); open(""); } else close(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (menu.hidden) open("");
      at = Math.max(0, Math.min(shown.length - 1, at + (e.key === "ArrowDown" ? 1 : -1))); mark();
      menu.children[at]?.scrollIntoView({ block: "nearest" }); e.preventDefault();
    } else if (e.key === "Enter" && !menu.hidden && at >= 0 && shown[at]) { pick(shown[at].value); e.preventDefault(); }
    else if (e.key === "Escape") close();
  });
  return wrap;  // put this in the page when the input wasn't in it yet
}

document.querySelectorAll("input[data-combo]").forEach((input) => {
  const list = document.getElementById(input.dataset.combo);
  makeCombo(input, [...list.options].map((o) => ({ value: o.value, note: o.textContent })));
});
