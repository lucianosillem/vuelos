// Vuelos · frontend
// IMPORTANTE: rutas relativas (/api, /static) — el gateway agrega el prefijo.
const API = '/api';

const $ = (id) => document.getElementById(id);

// ── Tabs ───────────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach((t) => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
    document.querySelectorAll('.panel').forEach((x) => x.classList.remove('active'));
    t.classList.add('active');
    $('tab-' + t.dataset.tab).classList.add('active');
  });
});

// ── Autocomplete (datalists) ───────────────────────────────────────
function setupAutocomplete(inputId, listId, url, field) {
  const input = $(inputId), list = $(listId);
  let t = null;
  input.addEventListener('input', () => {
    clearTimeout(t);
    const q = input.value.trim();
    if (q.length < 2) { list.innerHTML = ''; return; }
    t = setTimeout(async () => {
      try {
        const r = await fetch(`${API}/${url}?q=${encodeURIComponent(q)}&limit=12`);
        const items = await r.json();
        list.innerHTML = items.map((it) => `<option value="${it[field]}">${it.name ?? ''}</option>`).join('');
      } catch (e) { /* silencio */ }
    }, 250);
  });
}
setupAutocomplete('b-origen', 'airport-list', 'airports', 'icao');
setupAutocomplete('p-origen', 'airport-list', 'airports', 'icao');
setupAutocomplete('p-dest', 'airport-list', 'airports', 'icao');
setupAutocomplete('b-aerolinea', 'airline-list', 'airlines', 'icao');
setupAutocomplete('p-aerolinea', 'airline-list', 'airlines', 'icao');

// países
(async () => {
  const r = await fetch(`${API}/countries`);
  const cs = await r.json();
  $('country-list').innerHTML = cs.map((c) => `<option value="${c.country}"></option>`).join('');
})();

// tipos de avión (liveries)
async function refreshAircraft() {
  const r = await fetch(`${API}/aircraft`);
  const types = await r.json();
  $('aircraft-list').innerHTML = types.map((t) => `<option value="${t}"></option>`).join('');
  const sel = $('l-aircraft');
  const cur = sel.value;
  sel.innerHTML = '<option value="">Todos</option>' + types.map((t) => `<option value="${t}">${t}</option>`).join('');
  sel.value = cur;
}

// ── Buscar rutas ───────────────────────────────────────────────────
$('b-btn').addEventListener('click', buscarRutas);
$('b-origen').addEventListener('keydown', (e) => { if (e.key === 'Enter') buscarRutas(); });
$('b-pais').addEventListener('keydown', (e) => { if (e.key === 'Enter') buscarRutas(); });

async function buscarRutas() {
  const origin = $('b-origen').value.trim();
  const country = $('b-pais').value.trim();
  const airline = $('b-aerolinea').value.trim();
  const max_hours = parseFloat($('b-hours').value) || 2;
  const params = new URLSearchParams({ max_hours, limit: 80 });
  if (origin) params.set('origin', origin);
  else if (country) params.set('country', country);
  if (airline) params.set('airline', airline);
  const el = $('b-results');
  el.innerHTML = '<div class="empty">Buscando…</div>';
  try {
    const r = await fetch(`${API}/search?${params}`);
    if (!r.ok) { el.innerHTML = `<div class="empty">${(await r.json()).detail ?? 'Error'}</div>`; return; }
    const items = await r.json();
    if (!items.length) { el.innerHTML = '<div class="empty">Sin rutas con esos filtros (¿probaste otro país u origen?).</div>'; return; }
    el.innerHTML = items.map((it) => `
      <div class="card">
        <div class="head">
          <span class="title">${it.src} → ${it.dst} <span class="tag">${it.airline}</span></span>
          <span class="badge real">real</span>
        </div>
        <div class="meta">${it.src_name} → ${it.dst_name}</div>
        <div class="meta">${it.km ? it.km + ' km' : ''} ${it.hours ? '· ~' + it.hours + ' hs' : ''}${it.equipment ? ' · ' + it.equipment : ''}</div>
      </div>`).join('');
  } catch (e) {
    el.innerHTML = '<div class="empty">Error de conexión.</div>';
  }
}

// ── Liveries ───────────────────────────────────────────────────────
async function renderLiveries() {
  const f = $('l-aircraft').value;
  const r = await fetch(`${API}/liveries` + (f ? `?aircraft=${encodeURIComponent(f)}` : ''));
  const items = await r.json();
  const el = $('l-results');
  if (!items.length) { el.innerHTML = '<div class="empty">Todavía no hay liveries cargadas. Agregalas arriba (ej: avión B738, aerolínea ARG, livery "70 años").</div>'; return; }
  el.innerHTML = items.map((l) => `
    <div class="card">
      <div class="head">
        <span class="title"><span class="tag">${l.aircraft}</span> · ${l.airline}${l.airline_name ? ' · ' + l.airline_name : ''}</span>
        <button class="btn danger" onclick="delLivery(${l.id})">quitar</button>
      </div>
      <div class="meta">Livery: ${l.livery}${l.notes ? ' — ' + l.notes : ''}</div>
    </div>`).join('');
}

async function delLivery(id) {
  await fetch(`${API}/liveries/${id}`, { method: 'DELETE' });
  renderLiveries();
}

$('l-add').addEventListener('click', async () => {
  const aircraft = $('l-aircraft-add').value.trim().toUpperCase();
  const airline = $('l-airline-add').value.trim().toUpperCase();
  const livery = $('l-livery-add').value.trim();
  if (!aircraft || !airline) return;
  await fetch(`${API}/liveries`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ aircraft, airline, livery }),
  });
  $('l-aircraft-add').value = ''; $('l-airline-add').value = ''; $('l-livery-add').value = '';
  await refreshAircraft();
  renderLiveries();
});

$('l-aircraft').addEventListener('change', renderLiveries);

// ── Planear vuelo ──────────────────────────────────────────────────
$('p-btn').addEventListener('click', planear);
$('p-origen').addEventListener('keydown', (e) => { if (e.key === 'Enter') planear(); });

async function planear() {
  const origin = $('p-origen').value.trim();
  if (!origin) { $('p-results').innerHTML = '<div class="empty">Poné un aeropuerto de origen.</div>'; return; }
  const params = new URLSearchParams({
    origin,
    max_hours: parseFloat($('p-hours').value) || 2,
    invent: $('p-invent').checked ? 'true' : 'false',
  });
  if ($('p-dest').value.trim()) params.set('dest', $('p-dest').value.trim());
  if ($('p-aerolinea').value.trim()) params.set('airline', $('p-aerolinea').value.trim());
  if ($('p-avion').value.trim()) params.set('aircraft', $('p-avion').value.trim());
  const el = $('p-results');
  el.innerHTML = '<div class="empty">Generando plan (chequeo VATSIM en vivo)…</div>';
  try {
    const r = await fetch(`${API}/plan?${params}`);
    if (!r.ok) { el.innerHTML = `<div class="empty">${(await r.json()).detail ?? 'Error'}</div>`; return; }
    const p = await r.json();
    const routeBadge = p.route_real ? '<span class="badge real">ruta real</span>' : '<span class="badge inv">ruta inventada</span>';
    const vatsimBadge = p.vatsim.in_use
      ? '<span class="badge used">callsign OCUPADO en VATSIM</span>'
      : '<span class="badge ok">callsign libre en VATSIM</span>';
    el.innerHTML = `
      <div class="card">
        <div class="head">
          <span class="title">${p.origin.icao} → ${p.dest.icao} ${routeBadge}</span>
          <span>${vatsimBadge}</span>
        </div>
        <div class="meta">${p.origin.name} → ${p.dest.name}${p.dest.city ? ' (' + p.dest.city + ')' : ''}</div>
        <div class="meta">Aerolínea: <span class="tag">${p.airline.icao}</span>${p.airline.name ? ' — ' + p.airline.name : ''}</div>
        <div class="meta">Avión: ${p.aircraft ?? 'sin especificar'} · ${p.km ? p.km + ' km' : ''} ${p.hours ? '· ~' + p.hours + ' hs' : ''}</div>
        <div class="meta">Vuelo: <span class="tag">${p.callsign ?? p.airline.icao + p.flight_number}</span> (número ${p.flight_number})</div>
        <a class="simbrief" href="${p.simbrief_url}" target="_blank" rel="noopener">Abrir en SimBrief ↗</a>
      </div>`;
  } catch (e) {
    el.innerHTML = '<div class="empty">Error de conexión.</div>';
  }
}

// ── init ───────────────────────────────────────────────────────────
refreshAircraft().then(renderLiveries);
