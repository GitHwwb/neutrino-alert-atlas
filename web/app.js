// Frontend logic: load precomputed events, filter/rank them, render the map
// and the in-view list. Heavy astronomy is server-side; here we do vector math
// and DOM updates only.

const DATA_URL = "data/events.json";
const { geodeticToEcef, distancePointToSegment } = window.NeutrinoGeometry;

const els = {
  lat: document.getElementById("lat"),
  lon: document.getElementById("lon"),
  useGps: document.getElementById("useGps"),
  resetView: document.getElementById("resetView"),
  status: document.getElementById("status"),
  results: document.getElementById("results"),
  resultsSection: document.getElementById("results-section"),
  resultsSummary: document.getElementById("results-summary"),
  searchInput: document.getElementById("searchInput"),
  sortBy: document.getElementById("sortBy"),
  filterPills: document.querySelectorAll(".pill[data-filter]"),
  timeline: document.getElementById("timeline"),
  timelineLabel: document.getElementById("timelineLabel"),
  playBtn: document.getElementById("playBtn"),
  details: document.getElementById("details"),
  detailsTitle: document.getElementById("detailsTitle"),
  detailsBody: document.getElementById("detailsBody"),
  detailsLinks: document.getElementById("detailsLinks"),
  closeDetails: document.getElementById("closeDetails"),
  aladinWrap: document.getElementById("aladinWrap"),
  loadAladin: document.getElementById("loadAladin"),
  aladinDiv: document.getElementById("aladin-lite-div"),
  hideAladin: document.getElementById("hideAladin"),
  simbadWrap: document.getElementById("simbadWrap"),
  simbadList: document.getElementById("simbadList"),
  simbadEmpty: document.getElementById("simbadEmpty"),
};

const state = {
  payload: null,
  events: [],
  observer: null,
  observerMarker: null,
  trajectoryLayer: null,
  activeId: null,
  eventMarkers: new Map(),
  // Filters
  filters: {
    gold: true,
    bronze: true,
    km3net: true,
    up: true,
    down: true,
    timelineCursor: null,   // Date or null
    search: "",
  },
  sortBy: "date",
  listExpanded: false,
  timelineMin: null,
  timelineMax: null,
  playTimer: null,
  aladinReady: false,
};

// --- Map ---
const INITIAL_VIEW = { center: [20, 0], zoom: 2 };
// maxBounds + viscosity:1 hard-stops the user from dragging the map outside
// the world view; minZoom keeps the world from shrinking below useful size.
// Longitude bounds are wide so worldCopyJump wraparound still works smoothly.
const map = L.map("map", {
  worldCopyJump: true,
  maxBounds: [[-85, -540], [85, 540]],
  maxBoundsViscosity: 1.0,
  minZoom: 2,
}).setView(INITIAL_VIEW.center, INITIAL_VIEW.zoom);
// CartoDB Voyager (no-labels) — a muted-color cartographic basemap that
// reads as gentle rather than stark dark, while still letting the event
// markers carry the visual weight. Free for personal/non-commercial use
// with attribution to OpenStreetMap + CARTO.
L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
  maxZoom: 10,
  subdomains: "abcd",
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
}).addTo(map);
// Reference markers for operating high-energy neutrino telescopes worldwide.
// IceCube is the only one whose public alert catalog this Atlas currently
// ingests; the others are shown for geographic context. Hover for details.
const DETECTORS = [
  {
    id: "icecube", name: "IceCube",
    lat: -89.99, lon: 0,
    region: "Amundsen-Scott Station, South Pole",
    medium: "Antarctic ice",
    depth: "1450 – 2450 m below surface",
    status: "Operating since 2010 · ~1 km³ instrumented",
    catalog: "180+ Gold/Bronze alerts ingested here",
  },
  {
    id: "km3net-arca", name: "KM3NeT / ARCA",
    lat: 36.2667, lon: 16.1,
    region: "Capo Passero, Sicily (Mediterranean)",
    medium: "Sea water",
    depth: "3500 m subsea",
    status: "Phased deployment · ~28 of 230 detection units installed",
    catalog: "Public alerts via GCN circulars · KM3-230213A (~220 PeV)",
  },
  {
    id: "km3net-orca", name: "KM3NeT / ORCA",
    lat: 42.8, lon: 6.0333,
    region: "Toulon, France (Mediterranean)",
    medium: "Sea water",
    depth: "2450 m subsea",
    status: "Phased deployment · oscillation / atmospheric focus",
    catalog: "No public astrophysical alert feed",
  },
  {
    id: "baikal-gvd", name: "Baikal-GVD",
    lat: 51.7667, lon: 104.4,
    region: "Lake Baikal, Russia",
    medium: "Fresh water",
    depth: "750 – 1300 m underwater",
    status: "Phased deployment · ~13 clusters of 8 strings",
    catalog: "Occasional GCN circulars",
  },
];

const ICECUBE_LATLNG = [DETECTORS[0].lat, DETECTORS[0].lon];

function plotDetectors() {
  for (const d of DETECTORS) {
    const isPrimary = d.id === "icecube";
    const m = L.circleMarker([d.lat, d.lon], {
      radius: isPrimary ? 6 : 5,
      color: "#6ad1ff",
      weight: 2,
      fillColor: isPrimary ? "#6ad1ff" : "#0a0e16",
      fillOpacity: isPrimary ? 0.9 : 0.95,
    });
    m.bindTooltip(
      `<strong>${d.name}</strong><br>` +
        `<span class="t-region">${d.region}</span><br>` +
        `<span class="t-meta">${d.medium} · ${d.depth}</span><br>` +
        `<span class="t-status">${d.status}</span><br>` +
        `<span class="t-catalog">${d.catalog}</span>`,
      { direction: "top", className: "detector-tooltip", offset: [0, -6] },
    );
    m.addTo(map);
  }
}
plotDetectors();

// On-map legend: decodes the marker language (dot vs ring, color = signalness)
// where people first meet it, instead of only in Methods at the page bottom.
// A Leaflet control gets us corner placement + click isolation for free.
const legendControl = L.control({ position: "bottomleft" });
legendControl.onAdd = () => {
  const div = L.DomUtil.create("div", "map-legend");
  // Collapsed by default on small screens where map real estate is scarce.
  const open = window.matchMedia("(min-width: 720px)").matches ? " open" : "";
  div.innerHTML = `
    <details${open}>
      <summary>Legend</summary>
      <div class="lg-body">
        <div class="lg-row"><span class="lg-dot"></span>up-going · Earth entry point</div>
        <div class="lg-row"><span class="lg-ring"></span>down-going · sub-source point</div>
        <div class="lg-row"><span class="lg-pin"></span>neutrino telescope</div>
        <div class="lg-tiers">
          <span class="lg-tier"><i class="lg-strip gold"></i>Gold</span>
          <span class="lg-tier"><i class="lg-strip bronze"></i>Bronze</span>
          <span class="lg-tier"><i class="lg-strip km3"></i>KM3NeT</span>
        </div>
        <div class="lg-hint">Gold/Bronze: muted → vivid = IceCube signalness; KM3NeT = fixed cyan</div>
      </div>
    </details>`;
  L.DomEvent.disableClickPropagation(div);
  L.DomEvent.disableScrollPropagation(div);
  return div;
};
legendControl.addTo(map);

// --- Math ---
function closestApproachKm(observerEcef, detectorEcef, entryEcef) {
  if (!Array.isArray(entryEcef)) return null;
  return distancePointToSegment(observerEcef, detectorEcef, entryEcef);
}

// --- Formatting ---
// Escape strings that originate outside this codebase (GCN comments, SIMBAD
// names/types, event IDs) before they go through innerHTML.
function esc(s) {
  return String(s).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}
function formatDate(iso) {
  return new Date(iso).toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}
function shortDate(iso) { return iso.slice(0, 10); }
function formatDistance(km) {
  if (km < 1000) return `${km.toFixed(0)} km`;
  return `${(km / 1000).toFixed(2)} × 10³ km`;
}
// Energies are TeV throughout (the GCN table's unit; hand-curated events are
// normalized to TeV in the pipeline). Roll over to PeV/EeV for readability.
function formatEnergy(tev) {
  if (!Number.isFinite(tev)) return "—";
  if (tev >= 1e6) return `${(tev / 1e6).toPrecision(3)} EeV`;
  if (tev >= 1e3) return `${(tev / 1e3).toPrecision(3)} PeV`;
  return `${tev.toPrecision(3)} TeV`;
}
function formatSignalness(value) {
  return Number.isFinite(value) ? `${(value * 100).toFixed(0)}%` : "not published";
}
function formatFar(value, digits = 2) {
  return Number.isFinite(value) ? `${value.toFixed(digits)}/yr` : "not published";
}

// --- Marker helpers ---
function markerLatLon(e) {
  return e.is_up_going ? [e.entry_lat, e.entry_lon] : [e.subsource_lat, e.subsource_lon];
}
// Base hue per alert tier. Markers are drawn at a single uniform size; the
// IceCube color is interpolated between muted slate and its tier color by
// signalness. KM3NeT stays fixed cyan because its paper does not publish an
// IceCube-comparable signalness.
const TIER_BASE = { GOLD: "#f5cf4e", BRONZE: "#cf8a44", KM3NET: "#6ad1ff" };
const MUTED_LOW = "#3c4760";

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgbToHex([r, g, b]) {
  const v = (r << 16) | (g << 8) | b;
  return "#" + v.toString(16).padStart(6, "0");
}
function mixHex(a, b, t) {
  const ra = hexToRgb(a), rb = hexToRgb(b);
  return rgbToHex([0, 1, 2].map((i) => Math.round(ra[i] + (rb[i] - ra[i]) * t)));
}

function eventColor(e) {
  if (e.notice_type === "KM3NET") return TIER_BASE.KM3NET;
  const sig = Number.isFinite(e.signalness)
    ? Math.max(0, Math.min(1, e.signalness))
    : 0;
  const base = TIER_BASE[e.notice_type] || TIER_BASE.BRONZE;
  // 15% mix at sig=0 (heavily muted), 100% at sig=1 (full tier color).
  return mixHex(MUTED_LOW, base, 0.15 + 0.85 * sig);
}

function buildMarker(e) {
  const color = eventColor(e);
  const sig = Number.isFinite(e.signalness)
    ? Math.max(0, Math.min(1, e.signalness))
    : null;
  const [lat, lon] = markerLatLon(e);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;

  // All markers are uniformly sized. Up-going = filled 7px dot; down-going =
  // 13px hollow ring with a 2.5px stroke. Signalness is encoded purely by
  // color intensity (computed in eventColor) so the geometry of the map
  // doesn't get noisier with crowded confident events. Hit area is 22px.
  const totalPx = 22;
  const cls = `ev ev-${e.is_up_going ? "up" : "down"}`;
  const html = `<div class="${cls}" style="--c:${color}" data-id="${e.id}"></div>`;
  const icon = L.divIcon({
    html,
    className: "ev-wrap",
    iconSize: [totalPx, totalPx],
    iconAnchor: [totalPx / 2, totalPx / 2],
  });
  const markerLabel =
    `${shortDate(e.datetime_utc)} ${e.notice_type} ` +
    `${e.is_up_going ? "up-going" : "down-going"} candidate alert`;
  const m = L.marker([lat, lon], {
    icon,
    riseOnHover: true,
    bubblingMouseEvents: false,
    keyboard: false,
    title: markerLabel,
    alt: markerLabel,
  });
  m.bindTooltip(
    `${shortDate(e.datetime_utc)} · ${e.notice_type} · ` +
      `${e.is_up_going ? "up-going" : "down-going"} · ` +
      `sig ${formatSignalness(sig)}`,
    { direction: "top", offset: [0, -12] },
  );
  m.on("click", () => focusEvent(e.id));
  // Keep the event on the entry so filter passes don't need an O(n) lookup.
  return { marker: m, halo: null, event: e };
}

// --- Filtering ---
function passesFilters(e) {
  if (e.notice_type === "GOLD" && !state.filters.gold) return false;
  if (e.notice_type === "BRONZE" && !state.filters.bronze) return false;
  if (e.notice_type === "KM3NET" && !state.filters.km3net) return false;
  if (e.is_up_going && !state.filters.up) return false;
  if (!e.is_up_going && !state.filters.down) return false;
  if (state.filters.timelineCursor) {
    if (new Date(e.datetime_utc) > state.filters.timelineCursor) return false;
  }
  if (state.filters.search) {
    const q = state.filters.search.toLowerCase();
    const hay = `${e.id} ${e.ra_deg} ${e.dec_deg} ${e.comments || ""}`.toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

// updateListAfter=false lets timeline playback refresh markers every tick
// while deferring the (DOM-heavy) list rebuild to a slower cadence.
function applyFilters(updateListAfter = true) {
  for (const entry of state.eventMarkers.values()) {
    const show = passesFilters(entry.event);
    if (show) {
      if (entry.halo && !map.hasLayer(entry.halo)) entry.halo.addTo(map);
      if (!map.hasLayer(entry.marker)) entry.marker.addTo(map);
    } else {
      if (entry.halo && map.hasLayer(entry.halo)) map.removeLayer(entry.halo);
      if (map.hasLayer(entry.marker)) map.removeLayer(entry.marker);
    }
  }
  // If the active event was filtered out, clear it.
  if (state.activeId) {
    const active = state.eventMarkers.get(state.activeId)?.event;
    if (active && !passesFilters(active)) clearSelection();
  }
  if (updateListAfter) updateList();
}

// --- List rendering (events in current map bounds) ---

// Whether to count an event as "in view." Has to handle two awkward cases:
//   1. Mercator projection can't display lat beyond ±85.05°, so events at the
//      south pole (where neutrinos with dec ≈ 0° enter Earth) fall outside any
//      strict bounds rectangle even when the user is zoomed all the way out.
//   2. With worldCopyJump the map renders multiple world copies — an event at
//      lon -170 should count as in-view even if the visible bounds are
//      -150 to +210, because lon -170 + 360 = 190 is inside.
// When the visible longitude span is ≥ 320° we treat it as a world view and
// include everything; otherwise we do a wraparound-aware bounds check.
function isWorldView(bounds) {
  return bounds.getEast() - bounds.getWest() >= 320 || map.getZoom() <= 2;
}
function eventInView(e, bounds) {
  const [lat, lon] = markerLatLon(e);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
  if (isWorldView(bounds)) return true;
  if (lat < bounds.getSouth() || lat > bounds.getNorth()) return false;
  const west = bounds.getWest(), east = bounds.getEast();
  return (lon >= west && lon <= east)
      || (lon - 360 >= west && lon - 360 <= east)
      || (lon + 360 >= west && lon + 360 <= east);
}

function detectorAnchor(e) {
  // Per-event detector ECEF (set by the Python pipeline). Fall back to
  // IceCube for older events that pre-date the multi-detector field.
  return e.detector_ecef_km || state.payload.icecube_ecef_km;
}
function detectorLatLon(e) {
  if (Number.isFinite(e.detector_lat) && Number.isFinite(e.detector_lon)) {
    return [e.detector_lat, e.detector_lon];
  }
  return ICECUBE_LATLNG;
}

function annotateWithDistance(events) {
  if (!state.observer) return events.map((e) => ({ event: e, distanceKm: null }));
  const obs = geodeticToEcef(state.observer.lat, state.observer.lon);
  return events.map((e) => ({
    event: e,
    distanceKm: closestApproachKm(obs, detectorAnchor(e), e.entry_ecef_km),
  }));
}

function sortRanked(ranked) {
  const by = state.sortBy;
  const nullableDescending = (field) => (a, b) => {
    const left = a.event[field];
    const right = b.event[field];
    if (!Number.isFinite(left) && !Number.isFinite(right)) return 0;
    if (!Number.isFinite(left)) return 1;
    if (!Number.isFinite(right)) return -1;
    return right - left;
  };
  const nullableAscending = (field) => (a, b) => {
    const left = a.event[field];
    const right = b.event[field];
    if (!Number.isFinite(left) && !Number.isFinite(right)) return 0;
    if (!Number.isFinite(left)) return 1;
    if (!Number.isFinite(right)) return -1;
    return left - right;
  };
  const cmp = {
    date: (a, b) => b.event.datetime_utc.localeCompare(a.event.datetime_utc),
    distance: (a, b) => {
      if (a.distanceKm == null && b.distanceKm == null) return 0;
      if (a.distanceKm == null) return 1;
      if (b.distanceKm == null) return -1;
      return a.distanceKm - b.distanceKm;
    },
    signalness: nullableDescending("signalness"),
    energy: nullableDescending("energy"),
    far: nullableAscending("far_per_yr"),
  }[by] || ((a, b) => 0);
  return ranked.slice().sort(cmp);
}

function updateList() {
  if (!state.payload) return;
  const bounds = map.getBounds();
  const visible = state.events.filter((e) => passesFilters(e) && eventInView(e, bounds));
  const ranked = sortRanked(annotateWithDistance(visible));
  renderResults(ranked);
}

const PAGE_SIZE = 25;

function renderResults(ranked) {
  els.resultsSection.hidden = false;
  const totalFiltered = state.events.filter(passesFilters).length;
  const inView = ranked.length;
  const shown = state.listExpanded ? inView : Math.min(PAGE_SIZE, inView);

  const sortDesc = {
    date: "most recent",
    distance: "closest approach to observer",
    signalness: "highest signalness",
    energy: "highest reported energy estimate",
    far: "lowest false-alarm rate",
  }[state.sortBy] || state.sortBy;
  const distHint =
    state.sortBy === "distance" && !state.observer
      ? " — set an observer location to enable distance ranking"
      : "";

  els.resultsSummary.textContent =
    `Showing ${shown} of ${inView} events in view ` +
    `(${totalFiltered} after filters, ${state.payload.event_count} catalog total) ` +
    `· sorted by ${sortDesc}${distHint}`;

  els.results.innerHTML = "";
  for (const { event: e, distanceKm } of ranked.slice(0, shown)) {
    const li = document.createElement("li");
    li.className = "event";
    li.dataset.id = e.id;
    if (e.id === state.activeId) li.classList.add("active");
    li.innerHTML = `
      <span class="badge ${e.notice_type}">${e.notice_type}</span>
      <div>
        <div class="primary">
          ${formatDate(e.datetime_utc)} · ${esc(e.id)}
        </div>
        <div class="meta">
          RA ${e.ra_deg.toFixed(2)}° · Dec ${e.dec_deg.toFixed(2)}° ·
          σ<sub>90</sub> ${e.err90_arcmin.toFixed(0)}′ ·
          sig ${formatSignalness(e.signalness)} ·
          E ${formatEnergy(e.energy)} ·
          FAR ${formatFar(e.far_per_yr)} ·
          ${e.is_up_going ? "up-going" : "down-going"}
        </div>
      </div>
      <div class="dist">${
        distanceKm == null
          ? '<span class="label">click to inspect</span>'
          : `<span class="label">Closest approach</span>${formatDistance(distanceKm)}`
      }</div>
    `;
    // Rows act as buttons: reachable by Tab, activated by Enter/Space.
    li.tabIndex = 0;
    li.setAttribute("role", "button");
    li.addEventListener("click", () => focusEvent(e.id));
    li.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); focusEvent(e.id); }
    });
    els.results.appendChild(li);
  }

  // Pagination footer: only render when there's more to show than the page size.
  if (inView > PAGE_SIZE) {
    const li = document.createElement("li");
    li.className = "show-more";
    if (state.listExpanded) {
      li.textContent = `Showing all ${inView} · collapse to ${PAGE_SIZE}`;
    } else {
      li.textContent = `Show all ${inView} events (${inView - PAGE_SIZE} more)`;
    }
    li.tabIndex = 0;
    li.setAttribute("role", "button");
    const toggleExpand = () => {
      state.listExpanded = !state.listExpanded;
      renderResults(ranked);
    };
    li.addEventListener("click", toggleExpand);
    li.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); toggleExpand(); }
    });
    els.results.appendChild(li);
  }
}

// --- Selection & details ---
function setMarkerSelectedClass(id, on) {
  // Find the divIcon's inner element and toggle the .selected class on its wrap.
  // We tagged each .ev with data-id so we can find it without an iconElement reference.
  const el = document.querySelector(`.ev[data-id="${CSS.escape(id)}"]`);
  if (!el) return;
  el.closest(".ev-wrap")?.classList.toggle("selected", on);
}

function focusEvent(id) {
  if (state.activeId === id) { clearSelection(); return; }
  if (state.activeId) setMarkerSelectedClass(state.activeId, false);
  const e = state.events.find((x) => x.id === id);
  if (!e) return;
  state.activeId = id;
  setMarkerSelectedClass(id, true);
  document.querySelectorAll(".event").forEach((node) => {
    node.classList.toggle("active", node.dataset.id === id);
  });
  drawTrajectory(e);
  showDetails(e);
}

function clearSelection() {
  if (state.activeId) setMarkerSelectedClass(state.activeId, false);
  state.activeId = null;
  if (state.trajectoryLayer) {
    state.trajectoryLayer.remove();
    state.trajectoryLayer = null;
  }
  if (state.subsourceMarker) {
    state.subsourceMarker.remove();
    state.subsourceMarker = null;
  }
  document.querySelectorAll(".event.active").forEach((n) => n.classList.remove("active"));
  hideDetails();
}

function drawTrajectory(event) {
  if (state.trajectoryLayer) { state.trajectoryLayer.remove(); state.trajectoryLayer = null; }
  if (state.subsourceMarker) { state.subsourceMarker.remove(); state.subsourceMarker = null; }
  const color = eventColor(event);
  if (event.is_up_going) {
    state.trajectoryLayer = L.polyline(
      [[event.entry_lat, event.entry_lon], detectorLatLon(event)],
      { color, weight: 2.5, opacity: .9, dashArray: "5 5" },
    ).addTo(map);
  } else {
    // Down-going: the selected event marker already pinpoints the sub-source
    // point, so we just add a ~600 km highlight ring around it for emphasis.
    // (No separate center pin — that used to sit exactly on top of the marker.)
    // L.circle uses a geographic radius so it reads clearly at any zoom.
    state.subsourceMarker = L.circle(
      [event.subsource_lat, event.subsource_lon],
      { radius: 600000, color, weight: 3, opacity: 0.9, fillColor: color, fillOpacity: 0.15 },
    ).addTo(map);
  }
}

function showDetails(event) {
  const obs = state.observer;
  const distStr = obs
    ? formatDistance(closestApproachKm(
        geodeticToEcef(obs.lat, obs.lon),
        detectorAnchor(event),
        event.entry_ecef_km,
      ))
    : null;
  const fov = Math.max(2, (event.err90_arcmin / 60) * 6).toFixed(2);
  const aladinAppUrl = `https://aladin.cds.unistra.fr/AladinLite/?target=${event.ra_deg}+${event.dec_deg}&fov=${fov}&survey=P%2FDSS2%2Fcolor`;
  const gcnNoticeUrl = `https://gcn.gsfc.nasa.gov/notices_amon_g_b/${event.id}.amon`;
  const circularsUrl = `https://gcn.nasa.gov/circulars?query=${encodeURIComponent(event.id)}`;

  const detectorName = event.detector || "IceCube";
  els.detailsTitle.innerHTML =
    `<span class="badge ${event.notice_type}">${event.notice_type}</span> ` +
    `${detectorName} candidate alert ${esc(event.id)}`;

  els.detailsBody.innerHTML = `
    <dt>Detector</dt>
    <dd>${detectorName}</dd>
    <dt>Arrival at detector</dt>
    <dd>${formatDate(event.datetime_utc)}</dd>
    ${obs ? `<dt>Closest approach to you</dt><dd>${distStr}</dd>` : ""}
    <dt>Sky position (J2000)</dt>
    <dd>RA ${event.ra_deg.toFixed(4)}°, Dec ${event.dec_deg.toFixed(4)}°</dd>
    <dt>Localization</dt>
    <dd>
      90% radius ${event.err90_arcmin.toFixed(1)}′ (${(event.err90_arcmin / 60).toFixed(2)}°),
      50% radius ${event.err50_arcmin.toFixed(1)}′
    </dd>
    <dt>Reported energy estimate</dt>
    <dd>${formatEnergy(event.energy)}</dd>
    <dt>Energy basis</dt>
    <dd>${esc(event.energy_basis || "See source notice")}</dd>
    <dt>Signalness</dt>
    <dd>${
      Number.isFinite(event.signalness)
        ? `${(event.signalness * 100).toFixed(1)}% under the IceCube alert model`
        : "Not published in IceCube-alert terms"
    }</dd>
    <dt>False-alarm rate</dt>
    <dd>${
      Number.isFinite(event.far_per_yr)
        ? `${event.far_per_yr.toFixed(3)} per year`
        : "Not published in IceCube-alert terms"
    }</dd>
    <dt>Earth traversal</dt>
    <dd>${
      event.is_up_going
        ? `Up-going: entered atmosphere near ${event.entry_lat.toFixed(2)}°, ${event.entry_lon.toFixed(2)}° and traveled through Earth's interior to ${esc(detectorName)}`
        : `Down-going: arrived from above ${esc(detectorName)}'s horizon, no significant Earth traversal`
    }</dd>
    <dt>Comments</dt>
    <dd class="wrap">${esc(event.comments || "—")}</dd>
  `;

  // Nearby SIMBAD objects are populated server-side. Gracefully hide this
  // section for payloads that predate the lookup field.
  renderSimbad(event);

  // IceCube GCN notice URL only exists for IceCube events with run/event IDs;
  // hand-curated entries from other detectors get a reference link instead.
  const linkParts = [];
  if (event.detector === "IceCube" || !event.detector) {
    linkParts.push(`<a href="${gcnNoticeUrl}" target="_blank" rel="noopener">GCN notice ↗</a>`);
    linkParts.push(`<a href="${circularsUrl}" target="_blank" rel="noopener">Follow-up circulars ↗</a>`);
  } else if (event.reference_url) {
    linkParts.push(`<a href="${event.reference_url}" target="_blank" rel="noopener">Reference paper ↗</a>`);
  }
  linkParts.push(`<a href="${aladinAppUrl}" target="_blank" rel="noopener">Sky view in new tab ↗</a>`);
  els.detailsLinks.innerHTML = linkParts.join("\n");

  els.aladinWrap.hidden = false;
  els.loadAladin.hidden = false;
  els.hideAladin.hidden = true;
  els.aladinDiv.innerHTML = "";
  els.aladinDiv.style.display = "none";

  // Reveal the details panel but keep the viewport on the map — don't yank the
  // page down. The user can scroll to the details when they want them.
  els.details.hidden = false;

  if (state.aladinReady) {
    embedAladin(event);
  } else {
    els.loadAladin.onclick = () => loadAladinScript().then(() => embedAladin(event));
  }
}

function renderSimbad(event) {
  const lookup = event.simbad_lookup;
  if (!lookup || !Array.isArray(lookup.candidates)) {
    els.simbadWrap.hidden = true;
    return;
  }
  els.simbadWrap.hidden = false;
  els.simbadList.innerHTML = "";
  if (lookup.status === "error") {
    els.simbadEmpty.textContent = "SIMBAD lookup was unavailable when this catalog was generated.";
    els.simbadEmpty.hidden = false;
    return;
  }
  const cands = lookup.candidates;
  if (cands.length === 0) {
    els.simbadEmpty.textContent = "No cataloged SIMBAD objects fall within the 90% localization region.";
    els.simbadEmpty.hidden = false;
    return;
  }
  els.simbadEmpty.hidden = true;
  for (const c of cands) {
    const li = document.createElement("li");
    const simbadUrl = `https://simbad.cds.unistra.fr/simbad/sim-id?Ident=${encodeURIComponent(c.name)}`;
    li.innerHTML = `
      <span class="name"><a href="${simbadUrl}" target="_blank" rel="noopener">${esc(c.name)}</a></span>
      <span class="otype">${esc(c.otype || "—")}</span>
      <span class="sep">${c.sep_arcmin == null ? "" : c.sep_arcmin.toFixed(2) + "′"}</span>
    `;
    els.simbadList.appendChild(li);
  }
}

function hideDetails() { els.details.hidden = true; }

// --- Stat strip (header) ---
// One editorial line of scale + recency, computed from the live payload so it
// never drifts from the data. Relies on initTimeline() having run first.
function renderStatStrip() {
  const strip = document.getElementById("statStrip");
  const detectors = [...new Set(state.events.map((e) => e.detector || "IceCube"))];
  const items = [
    `<strong>${state.payload.event_count}</strong> events`,
    `${state.timelineMin.toISOString().slice(0, 4)}–${state.timelineMax.toISOString().slice(0, 4)}`,
    detectors.join(" + "),
    `latest alert ${state.timelineMax.toISOString().slice(0, 10)}`,
    "source checked every 3 h",
  ];
  strip.innerHTML = items
    .map((s) => `<span class="stat">${s}</span>`)
    .join('<span class="stat-sep" aria-hidden="true">·</span>');
  strip.hidden = false;
}

// --- Aladin Lite (lazy) ---
let aladinScriptPromise = null;
function loadAladinScript() {
  if (aladinScriptPromise) return aladinScriptPromise;
  aladinScriptPromise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js";
    s.charset = "utf-8";
    s.onload = () => {
      if (window.A && window.A.init) {
        window.A.init.then(() => { state.aladinReady = true; resolve(); }).catch(reject);
      } else {
        reject(new Error("Aladin global not found after load"));
      }
    };
    s.onerror = () => reject(new Error("Failed to load Aladin Lite"));
    document.head.appendChild(s);
  });
  return aladinScriptPromise;
}
function embedAladin(event) {
  els.loadAladin.hidden = true;
  els.hideAladin.hidden = false;
  els.aladinDiv.style.display = "block";
  els.aladinDiv.innerHTML = "";
  const fov = Math.max(2, (event.err90_arcmin / 60) * 6);
  const aladin = window.A.aladin(els.aladinDiv, {
    target: `${event.ra_deg} ${event.dec_deg}`,
    fov, survey: "P/DSS2/color", cooFrame: "ICRS",
    showReticle: true, showCooGrid: true,
  });
  // 90% error circle around the reconstructed neutrino direction.
  const errorOverlay = window.A.graphicOverlay({ color: "#6ad1ff", lineWidth: 2 });
  aladin.addOverlay(errorOverlay);
  errorOverlay.add(window.A.circle(event.ra_deg, event.dec_deg, event.err90_arcmin / 60));

  // Nearby SIMBAD catalog objects within the localization region.
  const candidates = (event.simbad_lookup?.candidates || []).filter(
    (c) => Number.isFinite(c.ra_deg) && Number.isFinite(c.dec_deg),
  );
  if (candidates.length > 0) {
    const cat = window.A.catalog({
      name: "Nearby SIMBAD objects",
      sourceSize: 14,
      shape: "circle",
      color: "#f472b6",
      onClick: "showPopup",
    });
    aladin.addCatalog(cat);
    cat.addSources(
      candidates.map((c) =>
        window.A.source(c.ra_deg, c.dec_deg, {
          name: c.name,
          type: c.otype || "—",
          separation: c.sep_arcmin != null ? `${c.sep_arcmin.toFixed(2)}'` : "—",
        }),
      ),
    );
  }
}

// --- Observer location ---
function readObserverInputs() {
  const lat = parseFloat(els.lat.value);
  const lon = parseFloat(els.lon.value);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { lat, lon };
}
function setObserver(lat, lon) {
  state.observer = { lat, lon };
  if (state.observerMarker) state.observerMarker.remove();
  state.observerMarker = L.marker([lat, lon])
    .addTo(map)
    .bindTooltip(`You: ${lat.toFixed(3)}, ${lon.toFixed(3)}`);
  map.setView([lat, lon], 3);
}

// --- Timeline ---
function initTimeline() {
  const dates = state.events.map((e) => new Date(e.datetime_utc));
  state.timelineMin = new Date(Math.min(...dates));
  state.timelineMax = new Date(Math.max(...dates));
  els.timeline.value = 1000; // start showing all events
  setTimelineCursorFromSlider();
}
function setTimelineCursorFromSlider() {
  const v = parseInt(els.timeline.value, 10);
  if (v >= 1000) {
    state.filters.timelineCursor = null;
    els.timelineLabel.textContent = "all events";
  } else {
    const spanMs = state.timelineMax - state.timelineMin;
    const cursor = new Date(state.timelineMin.getTime() + (v / 1000) * spanMs);
    state.filters.timelineCursor = cursor;
    els.timelineLabel.textContent = `up to ${cursor.toISOString().slice(0, 10)}`;
  }
}
// Inline SVG so the glyphs render identically everywhere — the ▶/❚❚ text
// characters fall back to emoji or mismatched metrics on some platforms.
const ICON_PLAY = '<svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true"><path d="M3 1.6 10.2 6 3 10.4Z" fill="currentColor"/></svg>';
const ICON_PAUSE = '<svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true"><rect x="2.4" y="1.8" width="2.6" height="8.4" rx=".8" fill="currentColor"/><rect x="7" y="1.8" width="2.6" height="8.4" rx=".8" fill="currentColor"/></svg>';
function setPlayButtonState(playing) {
  els.playBtn.classList.toggle("playing", playing);
  els.playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
  els.playBtn.innerHTML = `<span class="icon">${playing ? ICON_PAUSE : ICON_PLAY}</span>`;
}
function togglePlay() {
  if (state.playTimer) {
    clearInterval(state.playTimer);
    state.playTimer = null;
    setPlayButtonState(false);
    updateList(); // sync the list with wherever playback was paused
    return;
  }
  // If at end (or anywhere ≥ 1000), restart from the beginning.
  if (parseInt(els.timeline.value, 10) >= 1000) {
    els.timeline.value = 0;
    setTimelineCursorFromSlider();
    applyFilters();
  }
  setPlayButtonState(true);
  // ~8 seconds for a full sweep at 40ms tick (1000 / 5 = 200 ticks).
  // Markers update every tick; the list rebuild is DOM-heavy, so it runs at
  // ~5 Hz and once more on the final frame.
  let tick = 0;
  state.playTimer = setInterval(() => {
    let v = parseInt(els.timeline.value, 10) + 5;
    const done = v >= 1000;
    if (done) {
      v = 1000;
      clearInterval(state.playTimer);
      state.playTimer = null;
      setPlayButtonState(false);
    }
    els.timeline.value = v;
    setTimelineCursorFromSlider();
    applyFilters(false);
    tick++;
    if (done || tick % 5 === 0) updateList();
  }, 40);
}

// --- Load + wire up ---
async function loadEvents() {
  els.status.textContent = "Loading events…";
  try {
    // "no-cache" (not no-store) = always revalidate against the server's ETag.
    // Fresh data after each cron regen, but unchanged data is a ~free 304
    // instead of a full re-download.
    const res = await fetch(DATA_URL, { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.payload = await res.json();
    state.events = state.payload.events;
    initTimeline();
    renderStatStrip();
    plotAllEvents();
    els.status.textContent =
      `${state.payload.event_count} events loaded ` +
      `(updated ${formatDate(state.payload.generated_at_utc)}). ` +
      `Pan and zoom the map — the list below updates to events in view.`;
    updateList();
  } catch (err) {
    console.error(err);
    els.status.textContent = `Failed to load events.json: ${err.message}`;
  }
}

function plotAllEvents() {
  state.eventMarkers.forEach((entry) => {
    entry.marker.remove();
    if (entry.halo) entry.halo.remove();
  });
  state.eventMarkers.clear();
  let skipped = 0;
  for (const e of state.events) {
    const built = buildMarker(e);
    if (!built) { skipped++; continue; }
    state.eventMarkers.set(e.id, built);
    if (passesFilters(e)) {
      // Halo first so it renders behind the marker.
      if (built.halo) built.halo.addTo(map);
      built.marker.addTo(map);
    }
  }
  if (skipped) console.warn(`Skipped ${skipped} events with invalid coordinates`);
}

// --- Event listeners ---

// Setting observer from manual lat/lon — fires on Enter or blur.
function commitObserverInputs() {
  const obs = readObserverInputs();
  if (!obs) {
    els.status.textContent = "Enter a valid latitude (-90 to 90) and longitude (-180 to 180).";
    return;
  }
  setObserver(obs.lat, obs.lon);
  reportClosest(obs);
}
function reportClosest(obs) {
  const ranked = state.events
    .filter(passesFilters)
    .map((e) => closestApproachKm(
      geodeticToEcef(obs.lat, obs.lon), detectorAnchor(e), e.entry_ecef_km,
    ))
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  if (ranked.length) {
    els.status.textContent = `Closest event (under current filters) passed ${formatDistance(ranked[0])} from you.`;
  }
}
for (const inp of [els.lat, els.lon]) {
  inp.addEventListener("change", commitObserverInputs);
  inp.addEventListener("keydown", (ev) => { if (ev.key === "Enter") commitObserverInputs(); });
}

els.useGps.addEventListener("click", () => {
  if (!navigator.geolocation) {
    els.status.textContent = "Geolocation not supported in this browser.";
    return;
  }
  els.status.textContent = "Asking browser for location…";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      els.lat.value = pos.coords.latitude.toFixed(4);
      els.lon.value = pos.coords.longitude.toFixed(4);
      commitObserverInputs();
    },
    (err) => { els.status.textContent = `Couldn't get location: ${err.message}. Type lat/lon manually.`; },
    { enableHighAccuracy: false, timeout: 10000 },
  );
});

els.resetView.addEventListener("click", () => {
  clearSelection();
  // Also clear the observer pin and the lat/lon inputs so reset is a clean slate.
  if (state.observerMarker) {
    state.observerMarker.remove();
    state.observerMarker = null;
  }
  state.observer = null;
  els.lat.value = "";
  els.lon.value = "";
  els.status.textContent = "";
  map.setView(INITIAL_VIEW.center, INITIAL_VIEW.zoom);
  updateList();
});

els.closeDetails.addEventListener("click", clearSelection);
els.hideAladin.addEventListener("click", () => {
  els.aladinDiv.innerHTML = "";
  els.aladinDiv.style.display = "none";
  els.hideAladin.hidden = true;
  els.loadAladin.hidden = false;
});

// Filter pills — click toggles on/off.
for (const pill of els.filterPills) {
  pill.addEventListener("click", () => {
    const key = pill.dataset.filter;
    state.filters[key] = !state.filters[key];
    pill.classList.toggle("on", state.filters[key]);
    pill.setAttribute("aria-pressed", state.filters[key]);
    applyFilters();
  });
}

// Results-bar controls.
let searchDebounce;
els.searchInput.addEventListener("input", () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => {
    state.filters.search = els.searchInput.value.trim();
    applyFilters();
  }, 100);
});
els.sortBy.addEventListener("change", () => {
  state.sortBy = els.sortBy.value;
  updateList();
});

// Timeline
els.timeline.addEventListener("input", () => {
  setTimelineCursorFromSlider();
  applyFilters();
});
els.playBtn.addEventListener("click", togglePlay);

// Map
map.on("moveend", updateList);
map.on("click", clearSelection);
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") clearSelection(); });

// --- AGM2015 image overlay (real data from Usman et al. 2015, github.com/ultralytics/agm2015, AGPL-3.0)
// No cache-busting: the overlays change ~never, and Pages' max-age=600 + ETag
// keeps them fresh enough while letting repeat visits skip the download.
const AGM_CHANNELS = {
  all:        "data/agm2015_all.webp",
  reactor:    "data/agm2015_reactor.webp",
  geological: "data/agm2015_geological.webp",
};
let agmLayer = null;
let agmOn = false;
let agmChannel = "all";
const agmPill = document.querySelector('.pill[data-layer="agm"]');
const agmSel  = document.getElementById("agmChannel");

function ensureAgmLayer() {
  if (agmLayer) {
    agmLayer.setUrl(AGM_CHANNELS[agmChannel]);
    return;
  }
  // scripts/build_agm_layers.py crops each source figure to its exact map
  // rectangle (a clean -180..+180 / +90..-90 equirectangular globe) and
  // reprojects it to a square Web Mercator PNG covering the full Mercator
  // world. So the overlay registers 1:1 with the basemap at the standard
  // Web Mercator bounds — no fudge factor. The colorbar + 10^x labels sit
  // over the eastern Pacific (~+173°), composited within the map by design.
  agmLayer = L.imageOverlay(AGM_CHANNELS[agmChannel],
    [[-85.05112877980659, -180], [85.05112877980659, 180]],
    { className: "agm-overlay", interactive: false },
  );
}
function applyAgm() {
  if (agmOn) {
    ensureAgmLayer();
    if (!map.hasLayer(agmLayer)) agmLayer.addTo(map);
    else agmLayer.setUrl(AGM_CHANNELS[agmChannel]);
    agmSel.hidden = false;
  } else {
    if (agmLayer && map.hasLayer(agmLayer)) agmLayer.remove();
    agmSel.hidden = true;
  }
}
agmPill.addEventListener("click", () => {
  agmOn = !agmOn;
  agmPill.classList.toggle("on", agmOn);
  agmPill.setAttribute("aria-pressed", agmOn);
  applyAgm();
});
agmSel.addEventListener("change", () => {
  agmChannel = agmSel.value;
  applyAgm();
});

loadEvents();
