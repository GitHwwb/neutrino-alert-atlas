// Frontend logic: load precomputed events, compute closest-approach distance per
// observer, render the map and ranked list. All the heavy astronomy is already
// done server-side; here we only do basic 3D vector math.

const DATA_URL = "data/events.json";
const EARTH_RADIUS_KM = 6371.0; // mean radius for observer placement; precise enough at the km scale we care about.

const els = {
  lat: document.getElementById("lat"),
  lon: document.getElementById("lon"),
  useGps: document.getElementById("useGps"),
  go: document.getElementById("go"),
  status: document.getElementById("status"),
  results: document.getElementById("results"),
  resultsSection: document.getElementById("results-section"),
  resultsSummary: document.getElementById("results-summary"),
  details: document.getElementById("details"),
  detailsTitle: document.getElementById("detailsTitle"),
  detailsBody: document.getElementById("detailsBody"),
  detailsLinks: document.getElementById("detailsLinks"),
  closeDetails: document.getElementById("closeDetails"),
  aladinWrap: document.getElementById("aladinWrap"),
  loadAladin: document.getElementById("loadAladin"),
  aladinDiv: document.getElementById("aladin-lite-div"),
  hideAladin: document.getElementById("hideAladin"),
};

const state = {
  payload: null,
  events: [],
  observer: null,        // {lat, lon}
  observerMarker: null,
  trajectoryLayer: null,
  activeId: null,
  eventMarkers: new Map(),
};

const INITIAL_VIEW = { center: [20, 0], zoom: 2 };
const map = L.map("map", { worldCopyJump: true }).setView(INITIAL_VIEW.center, INITIAL_VIEW.zoom);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 8,
  attribution: '&copy; OpenStreetMap',
}).addTo(map);

// IceCube marker at South Pole
const ICECUBE_LATLNG = [-89.99, 0];
L.circleMarker(ICECUBE_LATLNG, {
  radius: 6, color: "#4cc3ff", weight: 2, fillColor: "#4cc3ff", fillOpacity: 1,
}).bindTooltip("IceCube (South Pole)", { permanent: false }).addTo(map);

function latLonToECEF(latDeg, lonDeg, radiusKm = EARTH_RADIUS_KM) {
  const lat = (latDeg * Math.PI) / 180;
  const lon = (lonDeg * Math.PI) / 180;
  return [
    radiusKm * Math.cos(lat) * Math.cos(lon),
    radiusKm * Math.cos(lat) * Math.sin(lon),
    radiusKm * Math.sin(lat),
  ];
}

const sub = (a, b) => [a[0]-b[0], a[1]-b[1], a[2]-b[2]];
const cross = (a, b) => [
  a[1]*b[2] - a[2]*b[1],
  a[2]*b[0] - a[0]*b[2],
  a[0]*b[1] - a[1]*b[0],
];
const norm = (a) => Math.hypot(a[0], a[1], a[2]);

function closestApproachKm(observerEcef, icecubeEcef, sourceUnit) {
  const v = sub(observerEcef, icecubeEcef);
  return norm(cross(v, sourceUnit));
}

function formatDate(iso) {
  const d = new Date(iso);
  return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
}

function formatDistance(km) {
  if (km < 1000) return `${km.toFixed(0)} km`;
  return `${(km / 1000).toFixed(2)} × 10³ km`;
}

async function loadEvents() {
  els.status.textContent = "Loading events…";
  try {
    const res = await fetch(DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.payload = await res.json();
    state.events = state.payload.events;
    els.status.textContent =
      `${state.payload.event_count} events loaded ` +
      `(updated ${formatDate(state.payload.generated_at_utc)}). ` +
      `Enter a location to rank them.`;
    plotAllEvents();
  } catch (err) {
    els.status.textContent = `Failed to load events.json: ${err.message}`;
  }
}

function shortDate(iso) {
  return iso.slice(0, 10); // YYYY-MM-DD
}

function plotAllEvents() {
  // Two kinds of markers:
  //  - Filled circles at atmospheric entry points for up-going events
  //    (the neutrino actually pierced Earth's surface here).
  //  - Hollow ring markers at the sub-source point for down-going events
  //    (the source was overhead at this location at event time; the neutrino
  //    did not traverse Earth's interior).
  for (const e of state.events) {
    const color = e.notice_type === "GOLD" ? "#e6c14a" : "#b87333";
    const lat = e.is_up_going ? e.entry_lat : e.subsource_lat;
    const lon = e.is_up_going ? e.entry_lon : e.subsource_lon;
    const m = L.circleMarker([lat, lon], {
      radius: e.is_up_going ? 3 : 4,
      color,
      weight: e.is_up_going ? 1 : 2,
      fillColor: e.is_up_going ? color : "transparent",
      fillOpacity: e.is_up_going ? 0.6 : 0,
      bubblingMouseEvents: false,
    }).bindTooltip(
      `${shortDate(e.datetime_utc)} · ${e.notice_type}` +
        ` · ${e.is_up_going ? "up-going" : "down-going"}`,
    );
    m.on("click", () => focusEvent(e.id));
    m.addTo(map);
    state.eventMarkers.set(e.id, m);
  }
}

function rankEvents(observerLat, observerLon) {
  const obs = latLonToECEF(observerLat, observerLon);
  const ic = state.payload.icecube_ecef_km;
  const ranked = state.events.map((e) => ({
    event: e,
    distanceKm: closestApproachKm(obs, ic, e.source_ecef_unit),
  }));
  ranked.sort((a, b) => a.distanceKm - b.distanceKm);
  return ranked;
}

function renderResults(ranked) {
  els.resultsSection.hidden = false;
  els.resultsSummary.textContent =
    `Closest ${Math.min(20, ranked.length)} of ${ranked.length} events`;
  els.results.innerHTML = "";
  for (const { event: e, distanceKm } of ranked.slice(0, 20)) {
    const li = document.createElement("li");
    li.className = "event";
    li.dataset.id = e.id;
    li.innerHTML = `
      <span class="badge ${e.notice_type}">${e.notice_type}</span>
      <div>
        <div>${formatDate(e.datetime_utc)}</div>
        <div class="meta">
          RA ${e.ra_deg.toFixed(2)}° · Dec ${e.dec_deg.toFixed(2)}° ·
          90% err ${e.err90_arcmin.toFixed(0)}′ ·
          signalness ${(e.signalness * 100).toFixed(0)}%
          ${e.is_up_going ? "· up-going" : "· down-going"}
        </div>
      </div>
      <div class="dist">${formatDistance(distanceKm)}</div>
    `;
    li.addEventListener("click", () => focusEvent(e.id));
    els.results.appendChild(li);
  }
}

function focusEvent(id) {
  // Toggle: clicking the active event again clears it.
  if (state.activeId === id) {
    clearSelection();
    return;
  }
  const e = state.events.find((x) => x.id === id);
  if (!e) return;
  state.activeId = id;
  document.querySelectorAll(".event").forEach((node) => {
    node.classList.toggle("active", node.dataset.id === id);
  });
  drawTrajectory(e);
  showDetails(e);
}

function clearSelection() {
  state.activeId = null;
  if (state.trajectoryLayer) {
    state.trajectoryLayer.remove();
    state.trajectoryLayer = null;
  }
  document.querySelectorAll(".event.active").forEach((n) => n.classList.remove("active"));
  hideDetails();
}

function showDetails(event) {
  const obs = state.observer;
  const ic = state.payload.icecube_ecef_km;
  const distStr = obs
    ? formatDistance(closestApproachKm(latLonToECEF(obs.lat, obs.lon), ic, event.source_ecef_unit))
    : null;

  const fov = Math.max(2, (event.err90_arcmin / 60) * 6).toFixed(2);
  // GCN circulars search uses the IceCube event identifier. The "IceCube-YYMMDDA"
  // convention isn't directly derivable here, so we search by run/event ID which
  // usually appears in the body of the circulars.
  const circularsQuery = encodeURIComponent(event.id);
  // Aladin Lite app URL — opens in a new tab as a fallback if user doesn't want the embed.
  const aladinAppUrl = `https://aladin.cds.unistra.fr/AladinLite/?target=${event.ra_deg}+${event.dec_deg}&fov=${fov}&survey=P%2FDSS2%2Fcolor`;
  const gcnNoticeUrl = `https://gcn.gsfc.nasa.gov/notices_amon_g_b/${event.id}.amon`;
  const circularsUrl = `https://gcn.nasa.gov/circulars?query=${circularsQuery}`;

  els.detailsTitle.innerHTML =
    `<span class="badge ${event.notice_type}">${event.notice_type}</span> ` +
    `IceCube alert ${event.id}`;

  els.detailsBody.innerHTML = `
    <dt>Arrival at IceCube</dt>
    <dd>${formatDate(event.datetime_utc)}</dd>
    ${obs ? `<dt>Closest approach to you</dt><dd>${distStr}</dd>` : ""}
    <dt>Sky position (J2000)</dt>
    <dd>RA ${event.ra_deg.toFixed(4)}°, Dec ${event.dec_deg.toFixed(4)}°</dd>
    <dt>Localization</dt>
    <dd>
      90% radius ${event.err90_arcmin.toFixed(1)}′ (${(event.err90_arcmin / 60).toFixed(2)}°),
      50% radius ${event.err50_arcmin.toFixed(1)}′
    </dd>
    <dt>Reconstructed energy</dt>
    <dd>${event.energy.toExponential(3)} (GCN units; typically TeV for IceCube alerts)</dd>
    <dt>Signalness</dt>
    <dd>${(event.signalness * 100).toFixed(1)}% probability of astrophysical origin</dd>
    <dt>False-alarm rate</dt>
    <dd>${event.far_per_yr.toFixed(3)} per year</dd>
    <dt>Earth traversal</dt>
    <dd>${
      event.is_up_going
        ? `Up-going: entered atmosphere near ${event.entry_lat.toFixed(2)}°, ${event.entry_lon.toFixed(2)}° and traveled through Earth's interior to IceCube`
        : "Down-going: arrived from above IceCube's horizon, no significant Earth traversal"
    }</dd>
    <dt>Comments</dt>
    <dd class="wrap">${event.comments || "—"}</dd>
  `;

  els.detailsLinks.innerHTML = `
    <a href="${gcnNoticeUrl}" target="_blank" rel="noopener">GCN notice ↗</a>
    <a href="${circularsUrl}" target="_blank" rel="noopener">Follow-up circulars ↗</a>
    <a href="${aladinAppUrl}" target="_blank" rel="noopener">Sky view in new tab ↗</a>
  `;

  els.aladinWrap.hidden = false;
  els.loadAladin.hidden = false;
  els.aladinDiv.innerHTML = "";
  els.aladinDiv.style.display = "none";

  els.details.hidden = false;
  els.details.scrollIntoView({ behavior: "smooth", block: "nearest" });

  // If Aladin is already loaded from a previous click, just reuse it.
  if (state.aladinReady) {
    embedAladin(event);
  } else {
    els.loadAladin.onclick = () => loadAladinScript().then(() => embedAladin(event));
  }
}

function hideDetails() {
  els.details.hidden = true;
}

let aladinScriptPromise = null;
function loadAladinScript() {
  if (aladinScriptPromise) return aladinScriptPromise;
  aladinScriptPromise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js";
    s.charset = "utf-8";
    s.onload = () => {
      // Aladin exposes a global `A` and `A.init` (a Promise) per their docs.
      if (window.A && window.A.init) {
        window.A.init.then(() => {
          state.aladinReady = true;
          resolve();
        }).catch(reject);
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
  // Recreate the viewer each time so target/fov refresh cleanly.
  const aladin = window.A.aladin(els.aladinDiv, {
    target: `${event.ra_deg} ${event.dec_deg}`,
    fov,
    survey: "P/DSS2/color",
    cooFrame: "ICRS",
    showReticle: true,
    showCooGrid: true,
  });
  // Draw the 90% error circle around the reconstructed position.
  const overlay = window.A.graphicOverlay({ color: "#4cc3ff", lineWidth: 2 });
  aladin.addOverlay(overlay);
  overlay.add(window.A.circle(event.ra_deg, event.dec_deg, event.err90_arcmin / 60));
  state.aladinViewer = aladin;
}

els.closeDetails.addEventListener("click", clearSelection);

els.hideAladin.addEventListener("click", () => {
  els.aladinDiv.innerHTML = "";
  els.aladinDiv.style.display = "none";
  els.hideAladin.hidden = true;
  els.loadAladin.hidden = false;
});

document.getElementById("resetView").addEventListener("click", () => {
  map.setView(INITIAL_VIEW.center, INITIAL_VIEW.zoom);
});

map.on("click", clearSelection);
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") clearSelection();
});

function drawTrajectory(event) {
  if (state.trajectoryLayer) state.trajectoryLayer.remove();
  const color = event.notice_type === "GOLD" ? "#e6c14a" : "#b87333";
  if (event.is_up_going) {
    // Through-Earth chord: line from atmospheric entry point to IceCube.
    state.trajectoryLayer = L.polyline(
      [[event.entry_lat, event.entry_lon], ICECUBE_LATLNG],
      { color, weight: 2, opacity: .9, dashArray: "4 4" },
    ).addTo(map);
  } else {
    // Down-going: the neutrino came from above IceCube and didn't traverse Earth.
    // Mark the sub-source point (source overhead here at event time) with a small
    // ring; no Earth-traversal line to draw.
    state.trajectoryLayer = L.circleMarker(
      [event.subsource_lat, event.subsource_lon],
      { radius: 10, color, weight: 2, fillOpacity: 0, dashArray: "3 3" },
    ).addTo(map);
  }
}

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
    .bindTooltip(`You: ${lat.toFixed(3)}, ${lon.toFixed(3)}`, { permanent: false });
  map.setView([lat, lon], 3);
}

els.go.addEventListener("click", () => {
  const obs = readObserverInputs();
  if (!obs) {
    els.status.textContent = "Enter a valid latitude (-90 to 90) and longitude (-180 to 180).";
    return;
  }
  setObserver(obs.lat, obs.lon);
  const ranked = rankEvents(obs.lat, obs.lon);
  renderResults(ranked);
  els.status.textContent =
    `Closest event passed ${formatDistance(ranked[0].distanceKm)} from you.`;
});

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
      els.go.click();
    },
    (err) => {
      els.status.textContent = `Couldn't get location: ${err.message}. Type lat/lon manually.`;
    },
    { enableHighAccuracy: false, timeout: 10000 },
  );
});

loadEvents();
