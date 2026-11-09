/* One map and one bus marker, updated in place as authorized snapshots arrive. */
(() => {
  const container = document.getElementById('student-map');
  if (!container || !window.StudentTransit) return;
  const feedback = document.getElementById('map-feedback');
  if (typeof L === 'undefined') { container.classList.add('map-load-failed'); container.textContent = 'Map unavailable. Check your connection; trip details and recorded coordinates are shown below.'; feedback.textContent = 'The map library could not load.'; return; }
  const map = L.map(container).setView([20, 0], 2);
  const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'}).addTo(map);
  let tileError = false;
  tiles.on('tileerror', () => { tileError = true; feedback.textContent = 'Map tiles could not load. Route stops and GPS records remain available.'; });
  const routeLayers = L.layerGroup().addTo(map);
  let busMarker = null;
  let previousSignature = '';
  let previousBus = null;
  let lastGPSStatus = '';
  let routeBounds = [];
  let lastSnapshot = window.StudentTransit.getSnapshot();
  const empty = document.getElementById('map-empty');
  const fitButton = document.getElementById('fit-student-map');
  const coordinateOK = point => point && Number.isFinite(point.latitude) && Number.isFinite(point.longitude) && Math.abs(point.latitude) <= 90 && Math.abs(point.longitude) <= 180;
  const point = stop => [stop.latitude, stop.longitude];
  function popup(title, lines) {
    const div = document.createElement('div'); div.className = 'student-popup';
    const strong = document.createElement('strong'); strong.textContent = title; div.append(strong);
    lines.forEach(text => { const p = document.createElement('p'); p.textContent = text; div.append(p); });
    return div;
  }
  function validGeometry(geometry) {
    return geometry?.type === 'LineString' && Array.isArray(geometry.coordinates) && geometry.coordinates.length >= 2 && geometry.coordinates.every(pair => Array.isArray(pair) && pair.length === 2 && pair.every(Number.isFinite) && Math.abs(pair[0]) <= 180 && Math.abs(pair[1]) <= 90);
  }
  function icon(gps) { return L.divIcon({className: `student-bus-icon ${gps.status} ${lastSnapshot.trip?.is_simulated ? 'simulated' : ''}`, html: '▣', iconSize: [36, 36], iconAnchor: [18, 18]}); }
  function fit() {
    if (container.offsetParent === null) return;
    map.invalidateSize();
    const coordinates = [...routeBounds];
    if (busMarker) coordinates.push([busMarker.getLatLng().lat, busMarker.getLatLng().lng]);
    if (coordinates.length) map.fitBounds(coordinates, {padding: [35, 35], maxZoom: 16});
  }
  function freshness(gps) {
    if (busMarker) {
      if (gps.status !== lastGPSStatus) { busMarker.setIcon(icon(gps)); lastGPSStatus = gps.status; }
      const data = lastSnapshot;
      busMarker.setPopupContent(popup(data.bus?.bus_number || 'Assigned bus', [gps.label, `Trip: ${data.trip_label}`, `Next stop: ${gps.is_fresh && data.progress?.status === 'available' ? data.progress.next_stop?.name || 'Route finished' : 'Unavailable'}`, `Recorded: ${data.location?.recorded_at ? new Date(data.location.recorded_at).toLocaleString() : 'Not available'}`, data.trip?.is_simulated ? 'SIMULATED DEVELOPMENT GPS — not a real bus position.' : gps.is_fresh ? 'Current GPS sample' : 'Last known position; this is not live GPS.']));
    }
    if (!tileError) feedback.textContent = `${gps.label}. ${lastSnapshot.route?.geometry_label || 'Route details are not available.'}`;
  }
  function update(data, gps) {
    lastSnapshot = data;
    const newBus = data.bus?.id || null;
    const changedBus = previousBus !== newBus;
    if (changedBus && busMarker) { map.removeLayer(busMarker); busMarker = null; }
    const signature = JSON.stringify([newBus, data.route, data.pickup_stop?.id]);
    const changedRoute = signature !== previousSignature;
    if (changedRoute) {
      routeLayers.clearLayers(); routeBounds = [];
      const route = data.route;
      const stops = (route?.stops || []).filter(coordinateOK);
      stops.forEach((stop, index) => {
        const pickup = stop.id === data.pickup_stop?.id;
        const start = index === 0, destination = index === stops.length - 1;
        const type = [start ? 'start' : '', destination ? 'destination' : '', pickup ? 'pickup' : ''].filter(Boolean).join(' ');
        const wrapper = document.createElement('span'); wrapper.className = `student-stop-icon ${type}`; wrapper.textContent = stop.order;
        const label = [start ? 'Start' : '', destination ? 'Destination' : '', pickup ? 'Your assigned pickup stop' : ''].filter(Boolean).join(' · ');
        L.marker(point(stop), {icon: L.divIcon({className: '', html: wrapper, iconSize: [28, 28], iconAnchor: [14, 14]})}).addTo(routeLayers).bindPopup(popup(`${stop.order}. ${stop.name}`, [label, stop.address || 'Address not provided', `${stop.latitude}, ${stop.longitude}`]));
        routeBounds.push(point(stop));
      });
      if (validGeometry(route?.geometry)) {
        L.geoJSON(route.geometry, {style: {color: '#3c8b77', weight: 4, opacity: .7, dashArray: route.is_approximate ? '7 9' : null}}).addTo(routeLayers);
        route.geometry.coordinates.forEach(pair => routeBounds.push([pair[1], pair[0]]));
      } else if (stops.length > 1) {
        L.polyline(stops.map(point), {color: '#96ac98', weight: 3, dashArray: '7 9'}).addTo(routeLayers);
      }
      previousSignature = signature;
    }
    if (data.status === 'assigned' && coordinateOK(data.location)) {
      if (!busMarker) { busMarker = L.marker(point(data.location), {icon: icon(gps), zIndexOffset: 500}).addTo(map).bindPopup(''); lastGPSStatus = gps.status; }
      else busMarker.setLatLng(point(data.location));
    } else if (busMarker) { map.removeLayer(busMarker); busMarker = null; }
    previousBus = newBus;
    empty.hidden = Boolean(routeBounds.length || busMarker);
    freshness(gps);
    if (changedRoute || changedBus) {
      requestAnimationFrame(() => {
        fit();
        if (container.dataset.initialFocus === 'pickup' && coordinateOK(data.pickup_stop) && data.status === 'assigned') map.setView(point(data.pickup_stop), 16);
      });
    }
  }
  document.addEventListener('student:snapshot', event => update(event.detail.snapshot, event.detail.gps));
  document.addEventListener('student:freshness', event => freshness(event.detail.gps));
  fitButton?.addEventListener('click', fit);
  window.addEventListener('resize', () => map.invalidateSize());
  window.addEventListener('pagehide', () => { if (busMarker) busMarker.closePopup(); });
  update(lastSnapshot, window.StudentTransit.getGPS());
})();
