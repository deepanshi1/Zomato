"use strict";

// All server text (names, cuisines, explanations) is inserted with textContent,
// never innerHTML: it comes from scraped listings and a language model.

// Empty means same origin; config.js sets it when the page is hosted apart from the API.
const API_BASE = String(window.API_BASE || "").replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 60000;
const BUDGET_LABELS = { low: "low (up to ₹400)", medium: "medium (₹401–800)", high: "high (above ₹800)" };
const FIELDS = ["locality", "cuisine", "budget", "min_rating", "preferences"];
const ALL_CUISINES = "All cuisines";
const ALL_CUISINE_WORDS = new Set(["", "all", "all cuisines", "any"]);

const $ = (id) => document.getElementById(id);
const els = {
  form: $("search"),
  locality: $("locality"),
  cuisine: $("cuisine"),
  rating: $("min_rating"),
  ratingValue: $("rating-value"),
  preferences: $("preferences"),
  prefCount: $("pref-count"),
  submit: $("submit"),
  submitLabel: $("submit-label"),
  cuisineCount: $("cuisine-count"),
  formMessage: $("form-message"),
  results: $("results"),
  intro: $("intro"),
  loading: $("loading"),
  error: $("error"),
  errorMessage: $("error-message"),
  retry: $("retry"),
  empty: $("empty"),
  emptyReason: $("empty-reason"),
  shortlist: $("shortlist"),
  summary: $("summary"),
  summaryText: $("summary-text"),
  digestTitle: $("digest-title"),
  digestBudget: $("digest-budget"),
  cards: $("cards"),
  poolNote: $("pool-note"),
  template: $("card-template"),
};

// Facet values keyed by lowercase, so typed input maps back to the catalog's spelling.
const facets = { locality: new Map(), cuisine: new Map() };
let latestRequest = 0;
let inFlight = null;

const inr = new Intl.NumberFormat("en-IN");

function titleCase(text) {
  return text.replace(/\b\p{L}/gu, (c) => c.toUpperCase());
}

function fold(text) {
  return text.trim().replace(/\s+/g, " ").toLowerCase();
}

// ---------------------------------------------------------------------------
// Facets
// ---------------------------------------------------------------------------

function fillOptions(datalist, map, values, label) {
  datalist.replaceChildren();
  for (const value of values) {
    const display = label(value);
    map.set(fold(value), display);
    const option = document.createElement("option");
    option.value = display;
    datalist.append(option);
  }
}

async function loadFacets() {
  try {
    const response = await fetch(`${API_BASE}/facets`);
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "The restaurant list is not available right now.");
    fillOptions($("locality-options"), facets.locality, body.localities || [], (v) => v);
    fillOptions($("cuisine-options"), facets.cuisine, [ALL_CUISINES, ...(body.cuisines || [])], titleCase);
    els.locality.placeholder = "Start typing, e.g. Banashankari";
    els.cuisine.placeholder = "All cuisines, or type e.g. Italian";
    const cuisineTotal = (body.cuisines || []).length;
    els.cuisineCount.textContent = cuisineTotal ? `${cuisineTotal} styles` : "";
    els.locality.disabled = els.cuisine.disabled = els.submit.disabled = false;
  } catch (err) {
    els.locality.placeholder = els.cuisine.placeholder = "Unavailable";
    showFormMessage(
      err instanceof TypeError
        ? "Could not reach the server. Check that it is running, then reload the page."
        : `${err.message} Reload the page to try again.`
    );
  }
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

function setFieldError(field, message) {
  const errorEl = $(`${field}-error`);
  const input = field === "budget" ? null : $(field);
  if (errorEl) {
    errorEl.textContent = message || "";
    errorEl.hidden = !message;
  }
  if (input) input.setAttribute("aria-invalid", message ? "true" : "false");
}

function clearErrors() {
  FIELDS.forEach((field) => setFieldError(field, ""));
  showFormMessage("");
}

function showFormMessage(message) {
  els.formMessage.textContent = message;
  els.formMessage.hidden = !message;
}

function checkFacet(field, label) {
  const input = els[field];
  const match = facets[field].get(fold(input.value));
  if (!input.value.trim()) {
    setFieldError(field, `Choose a ${label} from the list.`);
    return null;
  }
  if (!match) {
    setFieldError(field, `"${input.value.trim()}" is not in our ${label} list. Pick one of the suggestions.`);
    return null;
  }
  input.value = match;
  return match;
}

// Cuisine is optional: blank or "All cuisines" means no cuisine filter (returns ALL_CUISINES).
function checkCuisine() {
  if (ALL_CUISINE_WORDS.has(fold(els.cuisine.value))) {
    els.cuisine.value = "";
    return ALL_CUISINES;
  }
  return checkFacet("cuisine", "cuisine");
}

function readForm() {
  clearErrors();
  const locality = checkFacet("locality", "locality");
  const cuisine = checkCuisine();
  if (!locality || !cuisine) {
    showFormMessage("Please fix the highlighted fields.");
    (locality ? els.cuisine : els.locality).focus();
    return null;
  }
  const preferences = els.preferences.value.trim();
  return {
    locality,
    ...(cuisine !== ALL_CUISINES ? { cuisine } : {}),
    budget: els.form.elements.budget.value,
    min_rating: Number(els.rating.value),
    ...(preferences ? { preferences } : {}),
  };
}

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

function showOnly(panel) {
  for (const el of [els.intro, els.loading, els.error, els.empty, els.shortlist]) {
    el.hidden = el !== panel;
  }
  els.results.setAttribute("aria-busy", panel === els.loading ? "true" : "false");
}

function showError(message) {
  els.errorMessage.textContent = message;
  els.cards.replaceChildren();
  showOnly(els.error);
}

function formatRating(rating) {
  return rating == null ? "Not rated" : `★ ${rating.toFixed(1)}`;
}

function formatCost(cost) {
  return cost == null ? "Not listed" : `₹${inr.format(cost)}`;
}

function safeUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

function renderCard(rec) {
  const card = els.template.content.firstElementChild.cloneNode(true);
  card.querySelector(".rank").textContent = rec.rank;
  card.querySelector(".name").textContent = rec.name;
  card.querySelector(".cuisines").textContent = rec.cuisines.map(titleCase).join(" · ");
  card.querySelector(".rating").textContent = formatRating(rec.rating);
  card.querySelector(".cost").textContent = formatCost(rec.cost_for_two);
  card.querySelector(".explanation").textContent = rec.explanation;
  const href = rec.url && safeUrl(rec.url);
  if (href) {
    const link = card.querySelector(".link");
    link.href = href;
    link.hidden = false;
    link.setAttribute("aria-label", `View ${rec.name} on Zomato`);
  }
  return card;
}

function emptyReason(stats, query) {
  const out = Object.fromEntries(stats.rules.map((r) => [r.rule, r.out]));
  const cuisine = query.cuisine ? titleCase(query.cuisine) : null;
  const kind = cuisine ? `${cuisine} restaurant` : "restaurant";
  const where = `in ${query.locality}`;
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  if (!out.locality) return `We have no restaurants listed ${where}.`;
  if (!out.cuisine) {
    return `We found ${plural(out.locality, "restaurant")} ${where}, but none serve ${cuisine}.`;
  }
  if (!out.budget) {
    return `We found ${plural(out.cuisine, kind)} ${where}, ` +
      `but none in the ${BUDGET_LABELS[query.budget]} budget.`;
  }
  return `We found ${plural(out.budget, kind)} ${where} in your budget, ` +
    `but none rated ${query.min_rating.toFixed(1)} or higher.`;
}

function renderResults(body, query) {
  const recs = body.recommendations || [];
  if (recs.length === 0) {
    els.emptyReason.textContent = emptyReason(body.filter_stats, query);
    showOnly(els.empty);
    return;
  }
  els.summaryText.textContent = body.summary || "";
  els.digestTitle.textContent = `Foodie digest for ${query.locality}`;
  els.digestBudget.textContent = `Budget: ${BUDGET_LABELS[query.budget]}`;
  els.summary.hidden = !body.summary;
  els.cards.replaceChildren(...recs.map(renderCard));
  const { matched, pool } = body.filter_stats;
  els.poolNote.textContent = matched > pool
    ? `Ranked from the top ${pool} of ${matched} matching restaurants.`
    : `Ranked from ${matched} matching restaurant${matched === 1 ? "" : "s"}.`;
  showOnly(els.shortlist);
}

function applyFieldErrors(errors) {
  let shown = false;
  for (const { field, message } of errors || []) {
    if (FIELDS.includes(field)) {
      setFieldError(field, message);
      shown = true;
    }
  }
  return shown;
}

// ---------------------------------------------------------------------------
// Submit
// ---------------------------------------------------------------------------

async function submit(event) {
  event.preventDefault();
  const query = readForm();
  if (!query) return;

  if (inFlight) inFlight.abort();
  const controller = new AbortController();
  inFlight = controller;
  const requestId = ++latestRequest;
  const timer = setTimeout(() => controller.abort("timeout"), REQUEST_TIMEOUT_MS);

  els.submit.disabled = true;
  els.submitLabel.textContent = "Searching…";
  showOnly(els.loading);

  try {
    const response = await fetch(`${API_BASE}/recommendations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(query),
      signal: controller.signal,
    });
    const body = await response.json().catch(() => ({}));
    if (requestId !== latestRequest) return; // a newer search replaced this one

    if (response.ok) {
      renderResults(body, query);
    } else if (response.status === 400) {
      applyFieldErrors(body.errors);
      showFormMessage("Please fix the highlighted fields.");
      showOnly(els.intro);
    } else {
      showError(body.detail || `Something went wrong (HTTP ${response.status}). Please try again.`);
    }
  } catch (err) {
    if (requestId !== latestRequest) return;
    if (controller.signal.reason === "timeout") {
      showError("This is taking too long. Please try again in a moment.");
    } else {
      showError("Could not reach the server. Check your connection and try again.");
    }
  } finally {
    clearTimeout(timer);
    if (requestId === latestRequest) {
      inFlight = null;
      els.submit.disabled = false;
      els.submitLabel.textContent = "Find my food";
    }
  }
}

// ---------------------------------------------------------------------------
// Wire up
// ---------------------------------------------------------------------------

els.form.addEventListener("submit", submit);
els.rating.addEventListener("input", () => {
  els.ratingValue.textContent = `${Number(els.rating.value).toFixed(1)} ★`;
});
els.retry.addEventListener("click", () => els.form.requestSubmit());
els.preferences.addEventListener("input", () => {
  els.prefCount.textContent = els.preferences.value.length;
});
for (const field of ["locality", "cuisine"]) {
  els[field].addEventListener("input", () => setFieldError(field, ""));
}

loadFacets();
