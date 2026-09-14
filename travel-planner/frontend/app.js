// Frontend (Vercel) and backend (Render) are separate deployments, so calls
// need an absolute URL - except in local dev, where `uvicorn main:app` serves
// both this file and the API from the same origin, and a relative path works.
// If you rename the Render service, update the URL below and redeploy.
const API_BASE = ["localhost", "127.0.0.1"].includes(window.location.hostname)
  ? ""
  : "https://ai-travel-planner-api.onrender.com";

function qs(id) {
  return document.getElementById(id);
}

function show(el) {
  el.classList.remove("hidden");
}

function hide(el) {
  el.classList.add("hidden");
}

// ---------- tabs: "Plan a Trip" / "Decision Log" ----------

let lastRunId = null;
let loadedTraceRunId = null;

function switchTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabId);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === tabId);
  });
  if (tabId === "log-tab") loadTraceIfNeeded();
}

function initTabs() {
  const tabButtons = document.querySelectorAll(".tab-btn");
  if (!tabButtons.length) return;
  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });
}

// ---------- English-only date picker (native <input type="date"> renders its ----------
// ---------- calendar in the OS/browser locale, which we can't force to English) ----------

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const WEEKDAY_NAMES = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];

function pad2(n) {
  return String(n).padStart(2, "0");
}

function formatIsoDate(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

function attachDatePicker(input) {
  let viewYear, viewMonth; // month is 0-11
  let popup = null;

  function closePopup() {
    if (popup) {
      popup.remove();
      popup = null;
      document.removeEventListener("mousedown", onOutsideClick);
    }
  }

  function onOutsideClick(event) {
    if (popup && !popup.contains(event.target) && event.target !== input) {
      closePopup();
    }
  }

  function renderPopup() {
    popup.innerHTML = "";

    const header = document.createElement("div");
    header.className = "datepicker-header";

    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.className = "datepicker-nav";
    prevBtn.textContent = "‹";
    prevBtn.addEventListener("click", () => {
      viewMonth -= 1;
      if (viewMonth < 0) {
        viewMonth = 11;
        viewYear -= 1;
      }
      renderPopup();
    });

    const label = document.createElement("span");
    label.className = "datepicker-label";
    label.textContent = `${MONTH_NAMES[viewMonth]} ${viewYear}`;

    const nextBtn = document.createElement("button");
    nextBtn.type = "button";
    nextBtn.className = "datepicker-nav";
    nextBtn.textContent = "›";
    nextBtn.addEventListener("click", () => {
      viewMonth += 1;
      if (viewMonth > 11) {
        viewMonth = 0;
        viewYear += 1;
      }
      renderPopup();
    });

    header.appendChild(prevBtn);
    header.appendChild(label);
    header.appendChild(nextBtn);
    popup.appendChild(header);

    const weekdayRow = document.createElement("div");
    weekdayRow.className = "datepicker-grid datepicker-weekdays";
    WEEKDAY_NAMES.forEach((day) => {
      const cell = document.createElement("span");
      cell.textContent = day;
      weekdayRow.appendChild(cell);
    });
    popup.appendChild(weekdayRow);

    const grid = document.createElement("div");
    grid.className = "datepicker-grid";

    const firstOfMonth = new Date(viewYear, viewMonth, 1);
    const startOffset = firstOfMonth.getDay();
    const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

    for (let i = 0; i < startOffset; i++) {
      grid.appendChild(document.createElement("span"));
    }

    for (let day = 1; day <= daysInMonth; day++) {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "datepicker-day";
      cell.textContent = String(day);

      const cellDate = formatIsoDate(new Date(viewYear, viewMonth, day));
      if (cellDate === input.value) cell.classList.add("selected");

      cell.addEventListener("click", () => {
        input.value = cellDate;
        input.dispatchEvent(new Event("change"));
        closePopup();
      });
      grid.appendChild(cell);
    }

    popup.appendChild(grid);
  }

  input.addEventListener("click", () => {
    if (popup) {
      closePopup();
      return;
    }

    const base = input.value ? new Date(`${input.value}T00:00:00`) : new Date();
    viewYear = base.getFullYear();
    viewMonth = base.getMonth();

    popup = document.createElement("div");
    popup.className = "datepicker-popup";
    input.parentElement.appendChild(popup);
    renderPopup();

    setTimeout(() => document.addEventListener("mousedown", onOutsideClick), 0);
  });
}

function initDatePickers() {
  document.querySelectorAll('input[type="text"][id$="_date"]').forEach(attachDatePicker);
}

// ---------- region picker: 1-4 dropdowns, "+" adds another, no duplicates ----------

const REGIONS = ["North America", "Europe", "Asia", "Oceania"];

function initRegionPicker() {
  const rowsContainer = qs("region-rows");
  const addBtn = qs("add-region-btn");
  if (!rowsContainer || !addBtn) return;

  function otherSelectedValues(excludeSelect) {
    return Array.from(rowsContainer.querySelectorAll("select"))
      .filter((select) => select !== excludeSelect)
      .map((select) => select.value);
  }

  function refresh() {
    rowsContainer.querySelectorAll("select").forEach((select) => {
      const used = otherSelectedValues(select);
      const current = select.value;
      select.innerHTML = "";
      REGIONS.filter((region) => !used.includes(region) || region === current).forEach((region) => {
        const option = document.createElement("option");
        option.value = region;
        option.textContent = region;
        select.appendChild(option);
      });
      select.value = current;
    });
    addBtn.disabled = rowsContainer.children.length >= REGIONS.length;
  }

  function addRow(preselectRegion) {
    if (rowsContainer.children.length >= REGIONS.length) return;

    const row = document.createElement("div");
    row.className = "region-row";

    const select = document.createElement("select");
    select.className = "region-select";
    select.addEventListener("change", refresh);
    row.appendChild(select);

    if (rowsContainer.children.length > 0) {
      const removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "region-remove";
      removeBtn.textContent = "×";
      removeBtn.setAttribute("aria-label", "Remove region");
      removeBtn.addEventListener("click", () => {
        row.remove();
        refresh();
      });
      row.appendChild(removeBtn);
    }

    rowsContainer.appendChild(row);
    refresh();
    if (preselectRegion) select.value = preselectRegion;
  }

  addBtn.addEventListener("click", () => addRow());

  addRow(REGIONS[0]);
}

function getSelectedRegions() {
  return Array.from(document.querySelectorAll("#region-rows select"))
    .map((select) => select.value)
    .filter(Boolean);
}

// ---------- Plan a Trip tab: trip form + result ----------

function initTripForm() {
  const form = qs("trip-form");
  if (!form) return;

  const formSection = qs("form-section");
  const loadingSection = qs("loading-section");
  const errorSection = qs("error-section");
  const resultSection = qs("result-section");

  let lastPayload = null;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    lastPayload = {
      start_date: qs("start_date").value,
      end_date: qs("end_date").value,
      travelers: Number(qs("travelers").value),
      budget_per_person: Number(qs("budget_per_person").value),
      currency: qs("currency").value,
      regions: getSelectedRegions(),
    };
    await submitTrip(lastPayload);
  });

  qs("retry-btn").addEventListener("click", async () => {
    if (lastPayload) await submitTrip(lastPayload);
  });

  qs("new-plan-btn").addEventListener("click", () => {
    hide(resultSection);
    show(formSection);
  });

  qs("view-log-btn").addEventListener("click", () => {
    switchTab("log-tab");
  });

  async function submitTrip(payload) {
    hide(formSection);
    hide(errorSection);
    hide(resultSection);
    show(loadingSection);

    try {
      const response = await fetch(`${API_BASE}/api/plan-trip`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${response.status})`);
      }

      const data = await response.json();
      lastRunId = data.run_id;
      renderResult(data);
      hide(loadingSection);
      show(resultSection);
    } catch (err) {
      hide(loadingSection);
      qs("error-message").textContent = err.message || "Something went wrong.";
      show(errorSection);
    }
  }

  function renderResult(data) {
    const rec = data.recommendation;
    qs("result-region").textContent = rec.recommended_region || "";
    qs("result-destination").textContent = rec.destination || "";
    qs("result-reasoning").textContent = rec.reasoning || "";
    qs("result-cost").textContent =
      rec.estimated_total_cost_per_person != null
        ? `${rec.estimated_total_cost_per_person} ${lastPayload.currency}`
        : "n/a";

    const itineraryEl = qs("result-itinerary");
    itineraryEl.innerHTML = "";
    const itinerary = rec.itinerary;
    if (Array.isArray(itinerary)) {
      const list = document.createElement("ol");
      itinerary.forEach((day) => {
        const li = document.createElement("li");
        const label = day.day != null ? `Day ${day.day}: ` : "";
        const activities = Array.isArray(day.activities)
          ? day.activities.join(", ")
          : day.activities || "";
        li.textContent = `${label}${activities}`;
        list.appendChild(li);
      });
      itineraryEl.appendChild(list);
    } else if (itinerary) {
      const pre = document.createElement("pre");
      pre.textContent =
        typeof itinerary === "string" ? itinerary : JSON.stringify(itinerary, null, 2);
      itineraryEl.appendChild(pre);
    }

    const summariesEl = qs("result-summaries");
    summariesEl.innerHTML = "";
    (rec.region_summaries || []).forEach((s) => {
      const li = document.createElement("li");
      li.innerHTML = `<strong>${s.region}:</strong> ${s.verdict}`;
      summariesEl.appendChild(li);
    });
  }
}

// ---------- Decision Log tab: agent trace, grouped by agent ----------

async function loadTraceIfNeeded() {
  const emptyEl = qs("log-empty");
  const loadingEl = qs("log-loading");
  const errorEl = qs("log-error");
  const groupsEl = qs("trace-groups");
  if (!groupsEl) return;

  if (!lastRunId) {
    show(emptyEl);
    hide(loadingEl);
    hide(errorEl);
    groupsEl.innerHTML = "";
    return;
  }

  if (loadedTraceRunId === lastRunId) return;

  hide(emptyEl);
  hide(errorEl);
  groupsEl.innerHTML = "";
  show(loadingEl);

  try {
    const response = await fetch(`${API_BASE}/api/trace/${encodeURIComponent(lastRunId)}`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${response.status})`);
    }
    const data = await response.json();
    renderTrace(data.trace, groupsEl);
    loadedTraceRunId = lastRunId;
    hide(loadingEl);
  } catch (err) {
    hide(loadingEl);
    qs("log-error-message").textContent = err.message || "Could not load the decision log.";
    show(errorEl);
  }
}

function renderTrace(events, container) {
  container.innerHTML = "";
  const groups = new Map();
  events.forEach((event) => {
    const agent = event.agent || "Unknown agent";
    if (!groups.has(agent)) groups.set(agent, []);
    groups.get(agent).push(event);
  });

  groups.forEach((agentEvents, agentName) => {
    const section = document.createElement("section");
    section.className = "card trace-agent";

    const heading = document.createElement("h2");
    heading.textContent = agentName;
    section.appendChild(heading);

    agentEvents.forEach((event) => {
      if (event.type === "step") {
        const stepEl = document.createElement("div");
        stepEl.className = "trace-step";
        let html = "";
        if (event.thought) html += `<p class="thought"><strong>Thought:</strong> ${escapeHtml(event.thought)}</p>`;
        if (event.tool) html += `<p class="action"><strong>Action:</strong> ${escapeHtml(event.tool)}(${escapeHtml(event.tool_input || "")})</p>`;
        stepEl.innerHTML = html;
        stepEl.dataset.timestamp = event.timestamp;
        section.appendChild(stepEl);
      } else if (event.type === "task_complete") {
        const finalEl = document.createElement("details");
        finalEl.className = "trace-final";
        const summary = document.createElement("summary");
        summary.textContent = "Final output";
        finalEl.appendChild(summary);
        const pre = document.createElement("pre");
        pre.textContent = formatMaybeJson(event.output);
        finalEl.appendChild(pre);
        section.appendChild(finalEl);
      }
    });

    container.appendChild(section);
  });
}

function formatMaybeJson(text) {
  if (!text) return "";
  try {
    return JSON.stringify(JSON.parse(text), null, 2);
  } catch (e) {
    return text;
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

initTabs();
initTripForm();
initDatePickers();
initRegionPicker();
