/* Tablekeeper browser client.
 *
 * One page shell serves "/", "/signup", "/login" and "/lookup"; this script renders the
 * screen for the current path and keeps navigation in the page (no reloads), so a pending
 * booking and its retry identity survive anything that happens on the server in between.
 *
 * The server is authoritative. A confirmation is only ever shown from a server response;
 * a lost response leaves the booking "uncertain" until an identical retry (same body, same
 * Idempotency-Key) returns the original result.
 */
"use strict";

(() => {
  // ------------------------------------------------------------------ DOM helpers

  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(props || {})) {
      if (value === undefined || value === null || value === false) continue;
      if (name === "class") node.className = value;
      else if (name === "testid") node.setAttribute("data-testid", value);
      else if (name === "text") node.textContent = value;
      else if (name.startsWith("on") && typeof value === "function") node.addEventListener(name.slice(2), value);
      else if (value === true) node.setAttribute(name, "");
      else node.setAttribute(name, String(value));
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : String(child));
    }
    return node;
  }

  function field(label, control, extraClass) {
    return el("div", { class: `field ${extraClass || ""}`.trim() },
      el("label", { for: control.id }, label), control);
  }

  function notice(kind, testid, ...content) {
    const role = kind === "error" ? "alert" : "status";
    return el("div", { class: `notice notice--${kind}`, testid, role }, el("div", {}, ...content));
  }

  /** Replace a region's content, keeping keyboard focus on the "same" control if it had it. */
  function refill(region, content) {
    const active = document.activeElement;
    let selector = null;
    if (active && active !== document.body && region.contains(active)) {
      if (active.dataset.testid) selector = `[data-testid="${CSS.escape(active.dataset.testid)}"]`;
      else if (active.id) selector = `#${CSS.escape(active.id)}`;
    }
    region.replaceChildren(...[].concat(content).filter(Boolean));
    if (selector) {
      const again = region.querySelector(selector);
      if (again) again.focus({ preventScroll: true });
    }
  }

  const pad = (n) => String(n).padStart(2, "0");

  function todayIso() {
    const d = new Date();
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }

  const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
    weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  });

  /** "2026-09-24" -> "Thu 24 Sep 2026" (a calendar date at the restaurant, no zone shift). */
  function formatDate(iso) {
    const [y, m, d] = String(iso).split("-").map(Number);
    if (!y || !m || !d) return String(iso);
    return DATE_FORMAT.format(new Date(Date.UTC(y, m - 1, d)));
  }

  const localDate = (startsAtLocal) => startsAtLocal.slice(0, 10);
  const localTime = (startsAtLocal) => startsAtLocal.slice(11, 16);

  const SHORT_LABEL = /^[A-Za-z]?\d+[A-Za-z]?$/;

  /** Human seating names: "Table 4", "Tables 1 + 2", "Window" or "Window + Bar". */
  function seatingName(tableIds, labels) {
    const names = tableIds.map((id) => labels.get(id) ?? id);
    const numbered = names.every((n) => SHORT_LABEL.test(n));
    if (names.length === 1) return numbered ? `Table ${names[0]}` : names[0];
    return numbered ? `Tables ${names.join(" + ")}` : names.join(" + ");
  }

  /** A version-4 UUID; crypto.getRandomValues also works outside secure contexts. */
  function newIdempotencyKey() {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  // ------------------------------------------------------------------ session

  const SESSION_KEY = "tablekeeper.session";

  function readSession() {
    try {
      const saved = JSON.parse(localStorage.getItem(SESSION_KEY));
      return saved && typeof saved.token === "string" ? saved : null;
    } catch {
      return null;
    }
  }

  let session = readSession();

  function setSession(next) {
    session = next;
    if (next) search.authPrompt = false;
    try {
      if (next) localStorage.setItem(SESSION_KEY, JSON.stringify(next));
      else localStorage.removeItem(SESSION_KEY);
    } catch {
      /* storage unavailable: the session lives for this page only */
    }
    renderAccount();
  }

  // ------------------------------------------------------------------ API

  /** The request reached no definite outcome: network failure, timeout or a 5xx. */
  class Uncertain extends Error {}

  async function api(method, path, { body, key, auth = false, timeoutMs = 15000 } = {}) {
    const headers = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (auth && session) headers.Authorization = `Bearer ${session.token}`;
    if (key) headers["Idempotency-Key"] = key;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(path, {
        method, headers, cache: "no-store", credentials: "same-origin", signal: controller.signal,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      const text = await response.text();
      let data = null;
      if (text) {
        try { data = JSON.parse(text); } catch { data = null; }
      }
      if (response.status >= 500 || (response.ok && text && data === null)) {
        throw new Uncertain(`HTTP ${response.status}`);
      }
      return { status: response.status, data };
    } catch (err) {
      throw err instanceof Uncertain ? err : new Uncertain(err && err.message ? err.message : "network error");
    } finally {
      clearTimeout(timer);
    }
  }

  const errorCode = (result) => result && result.data && result.data.error ? result.data.error.code : null;

  const MESSAGES = {
    table_unavailable: "Sorry — that seating was just taken for this time. Availability has been refreshed: choose another table or time.",
    outside_opening_hours: "The restaurant isn't open for the whole booking at that time.",
    not_on_slot_grid: "Bookings start on the restaurant's time slots. Please pick a time from the list.",
    party_exceeds_capacity: "That seating is too small for your party. Choose a larger table or a combined option.",
    invalid_local_time: "That time doesn't exist on this date because the clocks change. Please pick another time.",
    combination_not_allowed: "Those tables can't be joined together. Please choose another option.",
    cutoff_passed: "This booking starts too soon to be changed or cancelled online. Please contact the restaurant.",
    reservation_cancelled: "This booking has already been cancelled.",
    unauthenticated: "Your session has ended. Please log in again.",
    email_taken: "An account with that email already exists. Try logging in instead.",
    not_found: "We couldn't find that.",
  };

  function messageFor(result) {
    const code = errorCode(result);
    if (code && MESSAGES[code]) return MESSAGES[code];
    const detail = result && result.data && result.data.error ? result.data.error.message : "";
    if (detail) return `Please check the details and try again: ${detail}.`;
    return `Something went wrong (HTTP ${result ? result.status : "?"}). Please try again.`;
  }

  const OFFLINE = "We couldn't reach Tablekeeper. Check your connection and try again.";

  // ------------------------------------------------------------------ navigation

  const main = document.getElementById("main");
  const SCREENS = {
    "/": { title: "Find a table", render: renderSearch },
    "/signup": { title: "Create an account", render: renderSignup },
    "/login": { title: "Log in", render: renderLogin },
    "/lookup": { title: "My booking", render: renderLookup },
  };

  function navigate(href, { replace = false } = {}) {
    history[replace ? "replaceState" : "pushState"](null, "", href);
    render({ moveFocus: true });
  }

  function safeNext(value, fallback = "/") {
    return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") ? value : fallback;
  }

  function render({ moveFocus = false } = {}) {
    const screen = SCREENS[location.pathname] || SCREENS["/"];
    document.title = `${screen.title} · Tablekeeper`;
    for (const link of document.querySelectorAll("[data-nav]")) {
      if (link.getAttribute("data-nav") === location.pathname) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    main.replaceChildren();
    screen.render(main);
    if (moveFocus) main.focus({ preventScroll: false });
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-link]");
    if (!link || event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const url = new URL(link.href, location.href);
    if (url.origin !== location.origin) return;
    event.preventDefault();
    navigate(url.pathname + url.search);
  });
  window.addEventListener("popstate", () => render());

  function renderAccount() {
    const box = document.getElementById("account");
    if (!box) return;
    if (session) {
      const initial = (session.display_name || "?").trim().charAt(0).toUpperCase() || "?";
      box.replaceChildren(
        el("span", { class: "account__user" },
          el("span", { class: "account__avatar", "aria-hidden": "true" }, initial),
          el("span", { class: "visually-hidden" }, "Signed in as "),
          el("span", { class: "account__name", testid: "current-user" }, session.display_name)),
        el("button", { type: "button", class: "btn btn--quiet", testid: "logout-button", onclick: logout }, "Log out"),
      );
    } else {
      box.replaceChildren(
        el("a", { href: "/login", "data-link": true, class: "btn btn--quiet" }, "Log in"),
        el("a", { href: "/signup", "data-link": true, class: "btn btn--primary" }, "Sign up"),
      );
    }
  }

  function logout() {
    setSession(null);
    search.selection = null;
    search.booking = null;
    search.authPrompt = false;
    lookup.reservation = null;
    lookup.error = null;
    lookup.mine = null;
    render();
  }

  /** A 401 on an authenticated call means the stored session is no longer valid. */
  function sessionEnded() {
    setSession(null);
  }

  // ------------------------------------------------------------------ search and booking

  /** The restaurant list the server embedded in the page, or null. */
  function embeddedRestaurants() {
    try {
      const data = JSON.parse(document.getElementById("restaurants-data").textContent);
      return Array.isArray(data) ? data : null;
    } catch {
      return null;
    }
  }

  const search = {
    restaurants: embeddedRestaurants(),   // [{id, name, timezone}]; refreshed on each visit
    restaurantsFailed: false,
    form: { restaurantId: "", date: todayIso(), party: "2" },
    seq: 0,                   // the newest search owns the screen; older responses are dropped
    result: null,             // {status: "loading"|"ready"|"error"|"invalid", params, ...}
    selection: null,          // the seating and slot the booking form describes
    booking: null,            // {partySize, attempt, pending, error, uncertain, confirmation}
    authPrompt: false,
  };

  function renderSearch(root) {
    root.append(
      el("section", { class: "hero" },
        el("h1", {}, "Find a table"),
        el("p", {}, "Choose a restaurant, a date and how many of you are coming. We'll show every open time — including tables that can be joined for bigger groups.")),
      searchCard(),
      el("section", { class: "results", id: "results", "aria-live": "polite", "aria-label": "Availability" }),
      el("div", { id: "booking-region" }),
    );
    loadRestaurants();   // fresh on every visit: the list may have changed since the last one
    renderResults();
    renderBooking();
  }

  function searchCard() {
    const select = el("select", { id: "search-restaurant", testid: "restaurant-select", name: "restaurant" });
    fillRestaurantOptions(select);
    select.addEventListener("change", () => { search.form.restaurantId = select.value; });
    const date = el("input", { id: "search-date", type: "date", testid: "date-input", name: "date", value: search.form.date });
    date.addEventListener("input", () => { search.form.date = date.value; });
    const party = el("input", {
      id: "search-party", type: "number", testid: "party-size-input", name: "party",
      min: 1, step: 1, inputmode: "numeric", value: search.form.party,
    });
    party.addEventListener("input", () => { search.form.party = party.value; });
    const form = el("form", { class: "search-form", novalidate: true, "aria-label": "Search availability" },
      field("Restaurant", select, "field--restaurant"),
      field("Date", date),
      field("Party size", party),
      el("button", { type: "submit", class: "btn btn--primary", testid: "search-button" }, "Show tables"));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      runSearch({ restaurantId: select.value, date: date.value, party: party.value.trim() });
    });
    return el("section", { class: "card" }, form);
  }

  function fillRestaurantOptions(select) {
    if (!search.restaurants) {
      select.replaceChildren(el("option", { value: "" }, search.restaurantsFailed ? "Restaurants unavailable" : "Loading restaurants…"));
      return;
    }
    if (!search.restaurants.length) {
      select.replaceChildren(el("option", { value: "" }, "No restaurants yet"));
      return;
    }
    select.replaceChildren(...search.restaurants.map((r) => el("option", { value: r.id }, r.name)));
    if (!search.restaurants.some((r) => r.id === search.form.restaurantId)) {
      search.form.restaurantId = search.restaurants[0].id;
    }
    select.value = search.form.restaurantId;
  }

  async function loadRestaurants() {
    let loaded = null;
    try {
      const result = await api("GET", "/restaurants");
      if (result.status === 200) loaded = result.data.restaurants;
    } catch {
      /* keep whatever list is already shown */
    }
    if (loaded) search.restaurants = loaded;
    search.restaurantsFailed = !search.restaurants;
    const select = document.querySelector("[data-testid='restaurant-select']");
    if (select) fillRestaurantOptions(select);
    if (search.restaurantsFailed) renderResults();
  }

  function validSearch(params) {
    if (!params.restaurantId) return "Choose a restaurant.";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(params.date)) return "Choose a date.";
    if (!/^\d+$/.test(params.party) || Number(params.party) < 1) return "Party size must be a whole number of at least 1.";
    return null;
  }

  /** Run a search. `refresh` re-reads the current results without closing the booking form. */
  async function runSearch(params, { refresh = false } = {}) {
    const seq = ++search.seq;
    const previous = search.result && search.result.status === "ready" ? search.result : null;
    if (!refresh) {
      search.selection = null;
      search.booking = null;
      search.authPrompt = false;
      const problem = validSearch(params);
      if (problem) {
        search.result = { status: "invalid", params, message: problem };
        renderResults();
        renderBooking();
        return;
      }
    }
    search.result = { status: "loading", params, previous: refresh ? previous : null };
    renderResults();
    renderBooking();
    let next;
    try {
      const query = new URLSearchParams({ restaurant_id: params.restaurantId, date: params.date, party_size: params.party });
      const [detail, availability] = await Promise.all([
        api("GET", `/restaurants/${encodeURIComponent(params.restaurantId)}`),
        api("GET", `/availability?${query}`),
      ]);
      if (detail.status === 200 && availability.status === 200) {
        next = { status: "ready", params, detail: detail.data, availability: availability.data };
      } else {
        next = { status: "error", params, message: messageFor(availability.status !== 200 ? availability : detail) };
      }
    } catch {
      next = { status: "error", params, message: OFFLINE };
    }
    if (seq !== search.seq) return;   // a newer search started: this response is stale
    search.result = next;
    renderResults();
    renderBooking();
  }

  function refreshAvailability() {
    const current = search.result;
    if (current && current.params) runSearch(current.params, { refresh: true });
  }

  function renderResults() {
    const region = document.getElementById("results");
    if (!region) return;
    refill(region, resultsContent());
  }

  function resultsContent() {
    const out = [];
    if (search.authPrompt) {
      out.push(notice("error", "auth-error",
        el("p", {}, el("strong", {}, "Log in to book this table. "), "Your search stays right here."),
        el("p", {},
          el("a", { href: "/login?next=/", "data-link": true }, "Log in"), " or ",
          el("a", { href: "/signup?next=/", "data-link": true }, "create an account"), ".")));
    }
    const result = search.result;
    if (search.restaurantsFailed && !search.restaurants) {
      out.push(notice("error", null, el("p", {}, "We couldn't load the list of restaurants. "),
        el("button", { type: "button", class: "btn btn--secondary", onclick: () => loadRestaurants() }, "Try again")));
      return out;
    }
    if (!result) {
      out.push(el("div", { class: "empty" },
        el("h3", {}, "Your table is a search away"),
        el("p", {}, "Pick a restaurant, date and party size above, then choose a time and table.")));
      return out;
    }
    if (result.status === "invalid") {
      out.push(notice("error", null, el("p", {}, result.message)));
      return out;
    }
    if (result.status === "error") {
      out.push(notice("error", null, el("p", {}, result.message),
        el("p", {}, el("button", { type: "button", class: "btn btn--secondary", onclick: () => runSearch(result.params) }, "Try again"))));
      return out;
    }
    if (result.status === "loading" && !result.previous) {
      out.push(el("div", { class: "results__head" },
        el("h2", { class: "results__title" }, "Checking availability…")));
      out.push(el("div", { class: "skeleton", "aria-busy": "true", "aria-label": "Loading availability" },
        el("div", { class: "skeleton__row" }), el("div", { class: "skeleton__row" }), el("div", { class: "skeleton__row" })));
      return out;
    }
    const view = result.status === "loading" ? result.previous : result;
    out.push(...gridView(view, result.status === "loading"));
    return out;
  }

  function gridView(view, refreshing) {
    const { detail, availability, params } = view;
    const labels = new Map(detail.tables.map((t) => [t.id, t.label]));
    const capacity = new Map(detail.tables.map((t) => [t.id, t.capacity]));
    const pairs = Array.isArray(detail.combinable) ? detail.combinable : [];
    const slots = availability.slots;
    const open = slots.filter((s) => (s.available_options || s.available_table_ids).length).length;
    const party = Number(params.party);
    const head = el("div", { class: "results__head" },
      el("h2", { class: "results__title" }, `${detail.name} · ${formatDate(params.date)}`),
      el("p", { class: "results__meta" },
        refreshing ? "Updating availability…"
          : slots.length ? `Party of ${party} · ${open} of ${slots.length} times with a free table · times are local to the restaurant`
            : `Party of ${party} · no bookable times on this day`));
    if (!slots.length) {
      return [head, el("div", { class: "empty", testid: "no-slots" },
        el("h3", {}, "No tables on this day"),
        el("p", {}, `${detail.name} isn't taking bookings on ${formatDate(params.date)}. Please try another date.`))];
    }
    const legend = el("ul", { class: "legend", "aria-label": "Legend" },
      el("li", {}, el("span", { class: "swatch swatch--open" }), "Available — select to book"),
      el("li", {}, el("span", { class: "swatch swatch--off" }), "Unavailable"),
      el("li", {}, el("span", { class: "swatch swatch--picked" }), "Your selection"));
    const grid = el("div", { class: "grid", testid: "availability-grid", role: "list", "aria-busy": refreshing ? "true" : "false" });
    for (const slot of slots) {
      const time = localTime(slot.starts_at_local);
      const singles = new Set(slot.available_table_ids);
      // Seats come from the options when offered: they follow the policy for this date.
      const offered = new Map((slot.available_options || []).map((o) => [o.table_ids.join("+"), o.capacity]));
      const options = el("div", { class: "slot-options" });
      for (const table of detail.tables) {
        options.append(cell(view, slot, [table.id], singles.has(table.id), labels, capacity, offered));
      }
      for (const pair of pairs) {
        options.append(cell(view, slot, pair, offered.has(pair.join("+")), labels, capacity, offered));
      }
      grid.append(el("div", { class: "slot-row", role: "listitem" },
        el("div", { class: "slot-time" }, el("time", { datetime: slot.starts_at }, time)),
        options));
    }
    return [head, legend, grid];
  }

  function cell(view, slot, tableIds, available, labels, capacity, offered) {
    const key = tableIds.join("+");
    const time = localTime(slot.starts_at_local);
    const name = seatingName(tableIds, labels);
    const seats = offered.get(key) ?? tableIds.reduce((sum, id) => sum + (capacity.get(id) || 0), 0);
    const picked = Boolean(search.selection && search.selection.key === key
      && search.selection.startsAtLocal === slot.starts_at_local);
    const classes = ["cell", tableIds.length > 1 && "cell--pair", available ? "cell--open" : "cell--off", picked && "cell--picked"]
      .filter(Boolean).join(" ");
    const testid = `slot-${key}-${time}`;
    const content = [
      el("span", { class: "cell__name" }, name),
      el("span", { class: "cell__meta" }, available ? `Seats ${seats}${tableIds.length > 1 ? " · joined" : ""}` : "Unavailable"),
    ];
    if (!available) {
      // Not a control: clicking it does nothing, and it is not a tab stop.
      return el("span", { class: classes, testid, "data-available": "false" }, ...content,
        el("span", { class: "visually-hidden" }, ` at ${time}`));
    }
    return el("button", {
      type: "button", class: classes, testid, "data-available": "true",
      "aria-pressed": picked ? "true" : "false",
      "aria-label": `${name}, seats ${seats}, ${time}`,
      onclick: () => choose(view, slot, tableIds, labels, seats),
    }, ...content);
  }

  function choose(view, slot, tableIds, labels, seats) {
    if (!session) {
      search.authPrompt = true;
      renderResults();
      const prompt = document.querySelector("[data-testid='auth-error'] a");
      if (prompt) prompt.focus();
      return;
    }
    search.authPrompt = false;
    search.selection = {
      key: tableIds.join("+"),
      tableIds: tableIds.slice(),
      startsAtLocal: slot.starts_at_local,
      restaurantId: view.detail.id,
      restaurantName: view.detail.name,
      labels,
      seats,
    };
    if (!search.booking) {
      search.booking = { partySize: String(view.params.party), attempt: null, pending: false, error: null, uncertain: null, confirmation: null };
    } else {
      // A different seating is a different request; earlier outcomes no longer describe it.
      Object.assign(search.booking, { error: null, uncertain: null, confirmation: null });
    }
    renderResults();
    renderBooking();
    const form = document.querySelector("[data-testid='booking-form']");
    if (form) {
      form.scrollIntoView({ block: "nearest", behavior: "smooth" });
      const party = form.querySelector("[data-testid='booking-party-size']");
      if (party) party.focus({ preventScroll: true });
    }
  }

  function renderBooking() {
    const region = document.getElementById("booking-region");
    if (!region) return;
    const selection = search.selection;
    const booking = search.booking;
    if (!selection || !booking) {
      region.replaceChildren();
      return;
    }
    refill(region, bookingCard(selection, booking));
  }

  function bookingCard(selection, booking) {
    const name = seatingName(selection.tableIds, selection.labels);
    const date = localDate(selection.startsAtLocal);
    const time = localTime(selection.startsAtLocal);
    const party = el("input", {
      id: "booking-party", type: "number", testid: "booking-party-size", name: "party_size",
      min: 1, step: 1, inputmode: "numeric", value: booking.partySize,
    });
    party.addEventListener("input", () => { booking.partySize = party.value; });
    const submitLabel = booking.pending ? "Booking…" : booking.uncertain ? "Try again" : "Confirm booking";
    const form = el("form", { testid: "booking-form", novalidate: true, "aria-labelledby": "booking-title" },
      el("div", { class: "booking__summary", testid: "booking-summary" },
        el("strong", {}, name),
        el("span", {}, selection.restaurantName),
        el("span", {}, `${formatDate(date)} at ${time}`),
        el("span", {}, `seats ${selection.seats}`)),
      el("div", { class: "booking__row" },
        field("Party size", party),
        el("button", {
          type: "submit", class: "btn btn--primary", testid: "booking-submit",
          "aria-busy": booking.pending ? "true" : "false",
        }, submitLabel)),
      booking.error ? notice("error", "booking-error", el("p", {}, booking.error.message),
        booking.error.login ? el("p", {}, el("a", { href: "/login?next=/", "data-link": true }, "Log in"), " to continue.") : null) : null,
      booking.uncertain ? notice("warn", "booking-uncertain",
        el("p", {}, el("strong", {}, "We couldn't confirm your booking. ")),
        el("p", {}, booking.uncertain)) : null);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitBooking();
    });
    return el("section", { class: "card booking panel", "aria-labelledby": "booking-title" },
      el("h2", { id: "booking-title" }, booking.confirmation ? "Your booking" : "Complete your booking"),
      el("p", { class: "muted" }, "Check the details, set your party size and confirm."),
      form,
      booking.confirmation ? confirmationView(booking.confirmation) : null);
  }

  /** Bring a new confirmation into view; on a phone it sits below a long grid. */
  function showConfirmation() {
    const box = document.querySelector("[data-testid='confirmation']");
    if (box) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function confirmationView({ reservation, restaurantName, labels }) {
    const tableIds = reservation.table_ids || [reservation.table_id];
    const seating = seatingName(tableIds, labels);
    const when = `${formatDate(localDate(reservation.starts_at_local))} at ${localTime(reservation.starts_at_local)}`;
    const guests = `${reservation.party_size} ${reservation.party_size === 1 ? "guest" : "guests"}`;
    return el("section", { class: "confirmation", testid: "confirmation", role: "status", "aria-labelledby": "confirmation-title" },
      el("h3", { id: "confirmation-title" }, "You're booked — see you soon!"),
      el("p", {}, "Your booking reference is ", el("span", { class: "reference", testid: "confirmation-reference" }, reservation.reference)),
      el("p", { testid: "confirmation-details" }, `${restaurantName} · ${seating} · ${when} · ${guests}`),
      el("dl", { class: "facts" },
        el("dt", {}, "Seating"), el("dd", { testid: "confirmation-tables" }, seating),
        el("dt", {}, "Status"), el("dd", {}, reservation.status)),
      el("p", {}, el("a", { href: `/lookup?reference=${encodeURIComponent(reservation.reference)}`, "data-link": true }, "View or cancel this booking")));
  }

  async function submitBooking() {
    const selection = search.selection;
    const booking = search.booking;
    if (!selection || !booking || booking.pending) return;
    if (!session) {
      booking.error = { message: "Please log in to book this table.", login: true };
      booking.uncertain = null;
      renderBooking();
      return;
    }
    const party = String(booking.partySize).trim();
    if (!/^\d+$/.test(party) || Number(party) < 1) {
      booking.error = { message: "Enter a party size of at least 1." };
      renderBooking();
      return;
    }
    const body = { restaurant_id: selection.restaurantId, starts_at_local: selection.startsAtLocal, party_size: Number(party) };
    if (selection.tableIds.length === 1) body.table_id = selection.tableIds[0];
    else body.table_ids = selection.tableIds.slice();
    const fingerprint = JSON.stringify(body);
    // Same form, same body: the same request, retried under the same key (§7). Anything
    // changed: a new request with a new key, whose result is not the old confirmation.
    if (!booking.attempt || booking.attempt.fingerprint !== fingerprint || booking.attempt.userId !== session.user_id) {
      booking.attempt = { key: newIdempotencyKey(), fingerprint, userId: session.user_id };
      booking.confirmation = null;
    }
    const attempt = booking.attempt;
    booking.pending = true;
    booking.error = null;
    renderBooking();
    let result = null;
    try {
      result = await api("POST", "/reservations", { body, key: attempt.key, auth: true });
    } catch {
      result = null;
    }
    booking.pending = false;
    if (search.booking !== booking) return;   // the form was closed meanwhile
    if (!result) {
      booking.uncertain = "The connection dropped before the restaurant answered, so your table may or may not be reserved. Press “Try again” to check — retrying the same booking never books twice.";
      booking.error = null;
      renderBooking();
      return;
    }
    booking.uncertain = null;
    if (result.status === 200 || result.status === 201) {
      booking.error = null;
      booking.confirmation = { reservation: result.data, restaurantName: selection.restaurantName, labels: selection.labels };
      renderBooking();
      showConfirmation();
      refreshAvailability();
      return;
    }
    if (result.status === 401) {
      sessionEnded();
      booking.error = { message: MESSAGES.unauthenticated, login: true };
    } else {
      booking.error = { message: messageFor(result) };
    }
    renderBooking();
    if (errorCode(result) === "table_unavailable") refreshAvailability();
  }

  // ------------------------------------------------------------------ lookup

  const lookup = {
    reference: "",
    seq: 0,
    status: "idle",           // idle | loading | found | missing
    reservation: null,
    restaurantName: null,
    labels: new Map(),
    error: null,              // {message, login}
    cancelling: false,
    mine: null,               // the caller's bookings, for quick access
  };

  function renderLookup(root) {
    const input = el("input", {
      id: "lookup-reference", type: "text", testid: "lookup-reference-input", name: "reference",
      autocomplete: "off", autocapitalize: "characters", spellcheck: "false", value: lookup.reference,
      placeholder: "e.g. K3P7QW",
    });
    input.addEventListener("input", () => { lookup.reference = input.value; });
    const form = el("form", { class: "lookup-form", novalidate: true, "aria-label": "Find a booking" },
      field("Booking reference", input),
      el("button", { type: "submit", class: "btn btn--primary", testid: "lookup-submit" }, "Find booking"));
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      runLookup(input.value);
    });
    root.append(
      el("section", { class: "hero" },
        el("h1", {}, "Your booking"),
        el("p", {}, "Enter the reference from your confirmation to see the details or cancel.")),
      el("section", { class: "card" }, form),
      el("div", { id: "lookup-result", class: "panel", "aria-live": "polite" }),
      el("div", { id: "my-bookings" }),
    );
    const fromUrl = new URLSearchParams(location.search).get("reference");
    if (fromUrl && fromUrl.trim().toUpperCase() !== (lookup.reservation && lookup.reservation.reference)) {
      input.value = fromUrl;
      lookup.reference = fromUrl;
      runLookup(fromUrl);
    } else {
      renderLookupResult();
    }
    renderMyBookings();
  }

  async function runLookup(raw) {
    const reference = String(raw || "").trim().toUpperCase();
    const seq = ++lookup.seq;
    lookup.reservation = null;
    lookup.cancelling = false;
    if (!reference) {
      lookup.status = "missing";
      lookup.error = { message: "Enter the booking reference from your confirmation." };
      renderLookupResult();
      return;
    }
    if (!session) {
      lookup.status = "missing";
      lookup.error = { message: "Log in to look up your bookings.", login: true };
      renderLookupResult();
      return;
    }
    lookup.status = "loading";
    lookup.error = null;
    renderLookupResult();
    let next = { status: "missing", error: { message: OFFLINE } };
    try {
      const result = await api("GET", `/reservations/${encodeURIComponent(reference)}`, { auth: true });
      if (result.status === 200) {
        const names = await restaurantNames(result.data.restaurant_id);
        next = { status: "found", reservation: result.data, error: null, ...names };
      } else if (result.status === 401) {
        sessionEnded();
        next = { status: "missing", error: { message: "Your session has ended. Log in to look up your bookings.", login: true } };
      } else if (result.status === 404) {
        next = { status: "missing", error: { message: `We couldn't find a booking with reference ${reference} on your account. Check the reference and try again.` } };
      } else {
        next = { status: "missing", error: { message: messageFor(result) } };
      }
    } catch {
      /* keep the offline message */
    }
    if (seq !== lookup.seq) return;
    Object.assign(lookup, next);
    renderLookupResult();
  }

  /** Restaurant name and table labels for display; falls back to ids if unavailable. */
  async function restaurantNames(restaurantId) {
    try {
      const result = await api("GET", `/restaurants/${encodeURIComponent(restaurantId)}`);
      if (result.status === 200) {
        return { restaurantName: result.data.name, labels: new Map(result.data.tables.map((t) => [t.id, t.label])) };
      }
    } catch {
      /* fall through */
    }
    return { restaurantName: restaurantId, labels: new Map() };
  }

  function renderLookupResult() {
    const region = document.getElementById("lookup-result");
    if (!region) return;
    refill(region, lookupContent());
  }

  function lookupError() {
    if (!lookup.error) return null;
    return notice("error", "reservation-error", el("p", {}, lookup.error.message),
      lookup.error.login ? el("p", {}, el("a", { href: "/login?next=/lookup", "data-link": true }, "Log in"), " or ",
        el("a", { href: "/signup?next=/lookup", "data-link": true }, "create an account"), ".") : null);
  }

  function lookupContent() {
    if (lookup.status === "loading") {
      return el("div", { class: "skeleton", "aria-busy": "true", "aria-label": "Looking up your booking" }, el("div", { class: "skeleton__row" }));
    }
    if (lookup.status !== "found" || !lookup.reservation) return lookupError();
    const r = lookup.reservation;
    const tableIds = r.table_ids || [r.table_id];
    const status = r.status;
    return el("article", { class: "card", testid: "reservation-detail", "aria-labelledby": "detail-title" },
      el("div", { class: "detail__head" },
        el("h2", { id: "detail-title" }, lookup.restaurantName),
        el("span", { class: `badge badge--${status}`, testid: "reservation-status" }, status)),
      el("dl", { class: "facts" },
        el("dt", {}, "Reference"), el("dd", {}, r.reference),
        el("dt", {}, "When"), el("dd", {}, `${formatDate(localDate(r.starts_at_local))} at ${localTime(r.starts_at_local)}`),
        el("dt", {}, "Seating"), el("dd", { testid: "reservation-tables" }, seatingName(tableIds, lookup.labels)),
        el("dt", {}, "Party"), el("dd", {}, `${r.party_size} ${r.party_size === 1 ? "guest" : "guests"}`)),
      status === "confirmed"
        ? el("div", { class: "btn-row" },
          el("button", {
            type: "button", class: "btn btn--danger", testid: "reservation-cancel-button",
            "aria-busy": lookup.cancelling ? "true" : "false", onclick: cancelReservation,
          }, lookup.cancelling ? "Cancelling…" : "Cancel booking"),
          el("span", { class: "muted" }, "Cancelling releases your table straight away."))
        : el("p", { class: "muted" }, "This booking is cancelled and its table has been released."),
      lookupError());
  }

  async function cancelReservation() {
    const reservation = lookup.reservation;
    if (!reservation || lookup.cancelling) return;
    const seq = lookup.seq;
    lookup.cancelling = true;
    lookup.error = null;
    renderLookupResult();
    let error = null;
    let updated = null;
    try {
      const result = await api("POST", `/reservations/${encodeURIComponent(reservation.reference)}/cancel`, { auth: true });
      if (result.status === 200) updated = result.data;
      else if (result.status === 401) {
        sessionEnded();
        error = { message: "Your session has ended. Log in to cancel this booking.", login: true };
      } else error = { message: messageFor(result) };
    } catch {
      error = { message: "We couldn't confirm the cancellation because the connection dropped. Look the booking up again to see its current status." };
    }
    if (seq !== lookup.seq) return;
    lookup.cancelling = false;
    if (updated) lookup.reservation = updated;
    lookup.error = error;
    renderLookupResult();
    lookup.mine = null;
    renderMyBookings();
  }

  async function renderMyBookings() {
    const region = document.getElementById("my-bookings");
    if (!region) return;
    if (!session) {
      region.replaceChildren();
      return;
    }
    if (!lookup.mine) {
      try {
        const [mine, restaurants] = await Promise.all([
          api("GET", "/reservations", { auth: true }), api("GET", "/restaurants")]);
        if (mine.status !== 200 || restaurants.status !== 200) return;
        lookup.mine = {
          reservations: mine.data.reservations,
          names: new Map(restaurants.data.restaurants.map((r) => [r.id, r.name])),
        };
      } catch {
        return;
      }
    }
    const target = document.getElementById("my-bookings");
    if (!target || !session) return;
    const { reservations, names } = lookup.mine;
    if (!reservations.length) {
      target.replaceChildren();
      return;
    }
    target.replaceChildren(el("section", { class: "card panel", "aria-labelledby": "mine-title" },
      el("h2", { id: "mine-title" }, "Your bookings"),
      el("ul", { class: "my-bookings" }, reservations.slice(0, 12).map((r) => el("li", {},
        el("button", {
          type: "button",
          onclick: () => {
            const input = document.querySelector("[data-testid='lookup-reference-input']");
            if (input) input.value = r.reference;
            lookup.reference = r.reference;
            runLookup(r.reference);
          },
        },
        el("span", {}, el("strong", {}, names.get(r.restaurant_id) || r.restaurant_id), ` · ${formatDate(localDate(r.starts_at_local))} at ${localTime(r.starts_at_local)}`),
        el("span", { class: "muted" }, `${r.reference} · ${r.status}`)))))));
  }

  // ------------------------------------------------------------------ signup and login

  function authScreen(root, { title, intro, fields, submitLabel, testid, onSubmit, switchTo }) {
    const errorBox = el("div", { class: "auth-error-slot" });
    const button = el("button", { type: "submit", class: "btn btn--primary", testid }, submitLabel);
    const form = el("form", { class: "auth-form", novalidate: true }, ...fields.map((f) => field(f.label, f.input)), errorBox, button);
    let busy = false;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (busy) return;
      busy = true;
      button.setAttribute("aria-busy", "true");
      errorBox.replaceChildren();
      const message = await onSubmit();
      busy = false;
      button.setAttribute("aria-busy", "false");
      if (message && errorBox.isConnected) {
        errorBox.replaceChildren(notice("error", "auth-error", el("p", {}, message)));
      }
    });
    root.append(el("section", { class: "card narrow" },
      el("h1", {}, title),
      el("p", { class: "muted" }, intro),
      session ? notice("info", null, el("p", {}, `You're signed in as ${session.display_name}. Continuing will switch accounts.`)) : null,
      form,
      el("p", { class: "auth-switch" }, switchTo)));
  }

  function textInput(id, testid, type, autocomplete) {
    return el("input", { id, type, testid, autocomplete, required: true });
  }

  function renderSignup(root) {
    const email = textInput("signup-email", "signup-email", "email", "email");
    const password = textInput("signup-password", "signup-password", "password", "new-password");
    const name = textInput("signup-name", "signup-display-name", "text", "nickname");
    const next = safeNext(new URLSearchParams(location.search).get("next"));
    authScreen(root, {
      title: "Create your account",
      intro: "Save your details once and book a table in a couple of taps.",
      fields: [
        { label: "Your name", input: name },
        { label: "Email", input: email },
        { label: "Password (at least 8 characters)", input: password },
      ],
      submitLabel: "Create account",
      testid: "signup-submit",
      switchTo: [ "Already have an account? ", el("a", { href: `/login?next=${encodeURIComponent(next)}`, "data-link": true }, "Log in") ],
      onSubmit: async () => {
        try {
          const result = await api("POST", "/auth/signup", {
            body: { email: email.value.trim(), password: password.value, display_name: name.value.trim() },
          });
          if (result.status === 201) {
            setSession({ token: result.data.token, user_id: result.data.user_id, display_name: result.data.display_name });
            navigate(next);
            return null;
          }
          if (errorCode(result) === "validation_failed") {
            return "Please check your details: enter your name, a valid email address and a password of at least 8 characters.";
          }
          return messageFor(result);
        } catch {
          return OFFLINE;
        }
      },
    });
  }

  function renderLogin(root) {
    const email = textInput("login-email", "login-email", "email", "email");
    const password = textInput("login-password", "login-password", "password", "current-password");
    const next = safeNext(new URLSearchParams(location.search).get("next"));
    authScreen(root, {
      title: "Welcome back",
      intro: "Log in to book a table and manage your reservations.",
      fields: [
        { label: "Email", input: email },
        { label: "Password", input: password },
      ],
      submitLabel: "Log in",
      testid: "login-submit",
      switchTo: [ "New here? ", el("a", { href: `/signup?next=${encodeURIComponent(next)}`, "data-link": true }, "Create an account") ],
      onSubmit: async () => {
        try {
          const result = await api("POST", "/auth/login", { body: { email: email.value.trim(), password: password.value } });
          if (result.status === 200) {
            setSession({ token: result.data.token, user_id: result.data.user_id, display_name: result.data.display_name });
            navigate(next);
            return null;
          }
          if (result.status === 401) return "That email and password don't match an account. Please try again.";
          if (errorCode(result) === "validation_failed") return "Enter your email address and password.";
          return messageFor(result);
        } catch {
          return OFFLINE;
        }
      },
    });
  }

  // ------------------------------------------------------------------ start

  renderAccount();
  render();
})();
