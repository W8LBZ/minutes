// Click a column header in any table.list to sort by it (numbers numerically, text/dates alphabetically).
document.querySelectorAll("table.list").forEach((table) => {
  table.querySelectorAll("th").forEach((th, col) => {
    th.style.cursor = "pointer";
    th.title = "Sort";
    th.addEventListener("click", () => {
      const body = table.tBodies[0];
      const dir = th.dataset.dir === "asc" ? "desc" : "asc";
      table.querySelectorAll("th").forEach((h) => { delete h.dataset.dir; h.classList.remove("asc", "desc"); });
      th.dataset.dir = dir; th.classList.add(dir);
      const key = (row) => {
        const t = row.cells[col]?.innerText.trim() ?? "";
        const n = parseFloat(t.replace(/[%,]/g, ""));
        return /^-?[\d.]+%?$/.test(t) ? n : t.toLowerCase();
      };
      const rows = [...body.rows].sort((a, b) => {
        const x = key(a), y = key(b);
        return (x < y ? -1 : x > y ? 1 : 0) * (dir === "asc" ? 1 : -1);
      });
      rows.forEach((r) => body.appendChild(r));
    });
  });
});
