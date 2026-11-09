(() => {
  const container = document.getElementById('fleet-map');
  if (!container) return;
  const feedback = document.getElementById('map-feedback');
  if (typeof L === 'undefined') { feedback.textContent = 'The map library could not load. Check your internet connection. Bus and stop records remain available in the table.'; return; }
  const parse = id => { const el = document.getElementById(id); return el ? JSON.parse(el.textContent) : null; };
  const route = parse('route-data');
  const map = L.map(container).setView([20, 0], 2);
  const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
  tiles.on('tileerror', () => { feedback.textContent = 'Map tiles are unavailable. Actual GPS records are still shown in the table.'; });
  const markers = L.layerGroup().addTo(map);
  const busMarkers = new Map();
  let lastFleet = [];
  let updatesAvailable = true;
  let tileError = false;
  const inspect = document.getElementById('inspect-bus');
  function inspectBus(focus = true) {
    const bus = lastFleet.find(bus => String(bus.id) === inspect?.value);
    const description = document.getElementById('bus-inspection');
    if (!bus || !description) return;
    description.textContent = `${bus.bus_number} · Driver: ${bus.driver_name || 'Unassigned'} · Route: ${bus.route_code || 'Unassigned'} · ${bus.is_simulated ? 'SIMULATED DEVELOPMENT GPS · ' : ''}${updatesAvailable ? labels[bus.gps_status] : 'Refresh failed — last known data'} · Trip: ${bus.trip_status} · Next: ${updatesAvailable ? bus.next_stop?.name || 'Unavailable' : 'Unavailable'} · Recorded: ${when(bus.recorded_at)}`;
    const marker = busMarkers.get(bus.id);
    if (marker && focus) { map.setView(marker.getLatLng(), Math.max(map.getZoom(), 15)); marker.openPopup(); }
  }
  inspect?.addEventListener('change', inspectBus);
  const bounds = [];
  const when = value => value ? new Date(value).toLocaleString() : 'Unavailable';
  const labels = {live: 'Live', stale: 'Stale GPS', unavailable: 'GPS unavailable', not_started: 'Not started / last known', completed: 'Trip completed / last known', inactive: 'Inactive vehicle'};
  function popup(title, lines) {
    const root = document.createElement('div'); root.className = 'map-popup';
    const heading = document.createElement('strong'); heading.textContent = title; root.append(heading);
    lines.forEach(line => { const p = document.createElement('p'); p.textContent = line; root.append(p); });
    return root;
  }
  if (route) {
    const stops = route.stops.map(stop => [stop.latitude, stop.longitude]);
    route.stops.forEach(stop => {
      L.circleMarker([stop.latitude, stop.longitude], {radius: 6, color: '#315ce8', fillColor: '#fff', fillOpacity: 1, weight: 2}).addTo(map).bindPopup(popup(`${stop.order}. ${stop.name}`, [`${stop.latitude}, ${stop.longitude}`, route.route_code]));
    });
    if (route.geometry?.type === 'LineString') {
      L.geoJSON(route.geometry, {style: {color: '#315ce8', weight: 4}}).addTo(map);
      route.geometry.coordinates.forEach(point => bounds.push([point[1], point[0]]));
    } else if (stops.length > 1) {
      L.polyline(stops, {color: '#6383d6', weight: 3, dashArray: '6 8'}).addTo(map);
    }
    bounds.push(...stops);
  }
  function renderFleet(fleet, fit = false) {
    updatesAvailable = true;
    lastFleet = fleet;
    const ids = new Set(fleet.filter(bus => Number.isFinite(bus.latitude) && Number.isFinite(bus.longitude)).map(bus => bus.id));
    for (const [id, marker] of busMarkers) { if (!ids.has(id)) { markers.removeLayer(marker); busMarkers.delete(id); } }
    if (inspect) {
      const value = inspect.value;
      inspect.replaceChildren(new Option('Select a registered bus', ''));
      fleet.forEach(bus => inspect.add(new Option(`${bus.bus_number}${bus.is_simulated ? ' (SIMULATED)' : ''}`, bus.id)));
      inspect.value = value;
    }
    const positions = [];
    fleet.forEach(bus => {
      if (!Number.isFinite(bus.latitude) || !Number.isFinite(bus.longitude)) return;
      const point = [bus.latitude, bus.longitude]; positions.push(point);
      const style = `bus-marker ${bus.gps_status} ${bus.is_simulated ? 'simulated' : ''}`;
      let marker = busMarkers.get(bus.id);
      if (!marker) { marker = L.marker(point, {icon: L.divIcon({className: style, html: '▣', iconSize: [30, 30]})}).addTo(markers); marker.bindPopup(''); busMarkers.set(bus.id, marker); }
      else { marker.setLatLng(point); if (marker.options.icon.options.className !== style) marker.setIcon(L.divIcon({className: style, html: '▣', iconSize: [30, 30]})); }
      marker.setPopupContent(popup(bus.bus_number, [bus.is_simulated ? 'SIMULATED DEVELOPMENT GPS' : labels[bus.gps_status], `Driver: ${bus.driver_name || 'Unassigned'}`, `Route: ${bus.route_code || 'Unassigned'}`, `Trip: ${bus.trip_status}`, `Next stop: ${bus.next_stop?.name || 'Unavailable'}`, `Recorded: ${when(bus.recorded_at)}`, `Received: ${when(bus.received_at)}`]));
    });
    if (fit && (bounds.length || positions.length)) map.fitBounds([...bounds, ...positions], {padding: [35, 35], maxZoom: 15});
    feedback.textContent = `${positions.length} bus position${positions.length === 1 ? '' : 's'} available. ${positions.length || bounds.length ? 'Historical positions are labeled; purple markers are SIMULATED.' : 'No GPS positions or route coordinates available yet.'}`;
    inspectBus(false);
    const tbody = document.getElementById('fleet-rows');
    if (!tbody) return;
    tbody.replaceChildren();
    if (!fleet.length) {
      const td = document.createElement('td'); td.colSpan = 8; td.className = 'table-empty'; td.textContent = 'No buses registered.';
      const tr = document.createElement('tr'); tr.append(td); tbody.append(tr);
    }
    fleet.forEach(bus => {
      const tr = document.createElement('tr');
      [bus.bus_number, bus.registration_number, bus.route_code || 'Unassigned', bus.driver_name || 'Unassigned', (bus.is_simulated ? 'SIMULATED · ' : '') + labels[bus.gps_status], bus.trip_status, when(bus.recorded_at), when(bus.received_at)].forEach((value, index) => {
        const td = document.createElement('td');
        if (index === 0) {
          const a = document.createElement('a'); a.href = `/portal/buses/${bus.id}/`; a.textContent = value; td.append(a);
          const note = document.createElement('small'); note.className = 'cell-note'; note.textContent = bus.is_active ? 'Active vehicle' : 'Inactive vehicle'; td.append(note);
        } else if (index === 4) {
          const badge = document.createElement('span'); badge.className = `status-badge ${bus.gps_status}`; badge.textContent = value; td.append(badge);
        } else td.textContent = value;
        tr.append(td);
      });
      tbody.append(tr);
    });
    const count = document.getElementById('fleet-count'); if (count) count.textContent = fleet.length;
    const activeCount = document.getElementById('active-bus-count'); if (activeCount) activeCount.textContent = fleet.filter(bus => bus.is_active).length;
  }
  renderFleet(parse('fleet-data') || [], true);
  if (!container.dataset.liveUrl) return;
  const button = document.getElementById('refresh-fleet');
  let pending = false;
  async function refresh() {
    if (pending || document.hidden) return;
    pending = true; button.disabled = true; button.textContent = 'Refreshing…';
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(container.dataset.liveUrl, {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}, signal: controller.signal});
      if (!response.ok) throw new Error('Could not refresh positions. Check your connection and sign-in. Displayed records may be outdated.');
      const data = await response.json(); renderFleet(data.results);
      feedback.textContent += ` Refreshed ${new Date().toLocaleTimeString()}.`;
    } catch (error) {
      updatesAvailable = false;
      feedback.textContent = error.name === 'AbortError' ? 'Refresh timed out. Displayed records may be outdated. Try again.' : error.message;
      for (const [id, marker] of busMarkers) {
        marker.setIcon(L.divIcon({className: 'bus-marker inactive', html: '▣', iconSize: [30, 30]}));
        marker.setPopupContent(popup(lastFleet.find(bus => bus.id === id)?.bus_number || 'Bus', ['Refresh failed — last known position. Current trip, GPS and next stop could not be verified.']));
      }
      document.querySelectorAll('#fleet-rows .status-badge').forEach(badge => { badge.className = 'status-badge inactive'; badge.textContent = 'Refresh failed / last known'; });
      inspectBus(false);
    }
    finally { clearTimeout(timeout); pending = false; button.disabled = false; button.textContent = '↻ Refresh positions'; }
  }
  button.addEventListener('click', refresh);
  const seconds = Math.max(5, Math.min(300, Number(container.dataset.pollSeconds) || 10));
  const timer = setInterval(refresh, seconds * 1000);
  window.addEventListener('pagehide', () => clearInterval(timer), {once: true});
})();
