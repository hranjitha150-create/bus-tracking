/* Student requests have fixed URLs. Bus IDs are never selected by this client. */
(() => {
  const source = document.getElementById('student-snapshot');
  if (!source) return;
  let snapshot = JSON.parse(source.textContent);
  let connection = navigator.onLine ? 'online' : 'offline';
  let clockOffset = Date.parse(snapshot.generated_at) - Date.now();
  let stopped = false;
  let pending = false;
  let controller;
  let pollTimer;
  let ageTimer;
  let routeSignature = '';
  const refreshButton = document.getElementById('refresh-student');
  const notice = document.getElementById('connection-status');
  const menu = document.getElementById('student-menu');
  const sidebar = document.getElementById('student-sidebar');
  const formatTime = value => value ? new Date(value).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'}) : 'Not available';
  const coordinates = value => value && Number.isFinite(value.latitude) && Number.isFinite(value.longitude) ? `${value.latitude.toFixed(7)}, ${value.longitude.toFixed(7)}` : 'Not available';
  function bind(key, value) {
    document.querySelectorAll(`[data-bind="${key}"]`).forEach(el => { el.textContent = value ?? 'Not available'; });
  }
  function effectiveGPS() {
    if (connection !== 'online') return {status: connection === 'offline' ? 'offline' : 'error', label: snapshot.location ? 'Connection lost — last known position' : 'Tracking connection unavailable', is_fresh: false};
    const gps = {...snapshot.gps};
    if (gps.status === 'fresh') {
      const now = Date.now() + clockOffset;
      const times = [Date.parse(gps.recorded_at), Date.parse(gps.received_at)];
      if (times.some(time => !Number.isFinite(time) || now - time > gps.freshness_seconds * 1000)) {
        gps.status = 'stale'; gps.label = 'GPS update is stale'; gps.is_fresh = false;
      }
    }
    return gps;
  }
  function renderETA(gps) {
    const eta = snapshot.eta || {};
    const available = eta.status === 'available' && gps.is_fresh && Number.isFinite(eta.seconds) && eta.seconds >= 0;
    bind('eta-value', available ? eta.seconds < 60 ? 'Less than 1 min' : `${Math.ceil(eta.seconds / 60)} min` : 'Unavailable');
    bind('eta-message', available ? `${eta.arrival_at ? `Expected ${formatTime(eta.arrival_at)}. ` : ''}${eta.message || 'Estimated arrival at your pickup stop.'}` : connection !== 'online' ? 'Reconnect to check arrival estimates.' : eta.status === 'available' && !gps.is_fresh ? 'A fresh GPS update is required for an arrival estimate.' : eta.message || 'A reliable arrival estimate is not available.');
  }
  function renderGPS() {
    const gps = effectiveGPS();
    bind('journey-description', `${gps.label}. Positions are shown only when GPS records are available.`);
    document.querySelectorAll('[data-gps-badge]').forEach(el => { el.className = `gps-pill ${gps.status}`; el.textContent = gps.label; });
    renderETA(gps);
    const progress = snapshot.progress || {};
    const reliable = gps.is_fresh && progress.status === 'available';
    const distanceLabel = value => Number.isFinite(value) ? value >= 1000 ? `${(value/1000).toFixed(1)} km` : `${Math.round(value)} m` : 'Unavailable';
    bind('next-stop', reliable ? progress.next_stop?.name || 'Route destination reached' : 'Unavailable');
    bind('next-distance', reliable ? distanceLabel(progress.distance_to_next_stop_m) : 'Unavailable');
    bind('pickup-distance', reliable ? progress.pickup_passed ? 'Your stop has been passed' : distanceLabel(progress.distance_to_pickup_m) : 'Unavailable');
    bind('route-progress', reliable ? `${progress.percent}% of route` : (connection !== 'online' ? 'Connection unavailable' : gps.status !== 'fresh' ? gps.label : (progress.reason || 'Awaiting route match').replaceAll('_', ' ')));
    document.dispatchEvent(new CustomEvent('student:freshness', {detail: {gps, connection}}));
  }
  function renderStops() {
    const list = document.getElementById('student-stop-list');
    if (!list) return;
    const signature = JSON.stringify([snapshot.route, snapshot.pickup_stop?.id]);
    if (signature === routeSignature) return;
    routeSignature = signature;
    list.replaceChildren();
    const stops = snapshot.route?.stops || [];
    if (!stops.length) {
      const li = document.createElement('li'); li.className = 'empty-stops'; li.textContent = 'No stops have been added to your assigned route.'; list.append(li);
    }
    stops.forEach((stop, index) => {
      const li = document.createElement('li'); const pickup = stop.id === snapshot.pickup_stop?.id;
      li.className = `route-stop${pickup ? ' is-pickup' : ''}`;
      const number = document.createElement('span'); number.className = 'stop-number'; number.textContent = stop.order;
      const content = document.createElement('div'); const h3 = document.createElement('h3'); h3.textContent = stop.name;
      if (pickup) { const label = document.createElement('span'); label.className = 'pickup-label'; label.textContent = 'YOUR PICKUP'; h3.append(label); }
      const address = document.createElement('p'); address.textContent = stop.address || 'Address not provided';
      const position = document.createElement('small'); position.textContent = coordinates(stop);
      content.append(h3, address, position);
      const endpoint = document.createElement('span'); endpoint.className = 'stop-endpoint'; endpoint.textContent = index === 0 ? 'START' : index === stops.length - 1 ? 'DESTINATION' : '';
      li.append(number, content, endpoint); list.append(li);
    });
  }
  function render() {
    const assigned = snapshot.status === 'assigned';
    document.querySelectorAll('[data-simulation-warning]').forEach(el => { el.hidden = !snapshot.trip?.is_simulated; });
    document.querySelectorAll('[data-assigned]').forEach(el => { el.hidden = !assigned; });
    document.querySelectorAll('[data-unassigned]').forEach(el => { el.hidden = assigned; });
    bind('assignment-message', snapshot.message);
    document.querySelectorAll('[data-config-notice]').forEach(el => { el.hidden = !snapshot.message; el.textContent = snapshot.message; });
    const bus = snapshot.bus, route = snapshot.route, pickup = snapshot.pickup_stop;
    bind('bus-number', bus?.bus_number || 'Not assigned');
    bind('bus-registration', bus?.registration_number || 'Not available');
    bind('bus-capacity', bus?.capacity);
    bind('bus-description', bus?.description || 'No additional information.');
    bind('route-code', route?.route_code || 'Route pending');
    bind('route-name', route?.route_name || 'Route pending');
    bind('route-start', route?.start_location || 'Not available');
    bind('route-end', route?.destination || 'Not available');
    bind('pickup-name', pickup?.name || 'Pending confirmation');
    bind('pickup-address', pickup?.address || 'Address not provided.');
    bind('pickup-order', pickup?.order || '—');
    bind('pickup-coordinates', coordinates(pickup));
    bind('stop-count', route?.stop_count || 0);
    bind('geometry-label', route?.geometry_label || 'Route geometry is unavailable.');
    bind('trip-label', snapshot.trip_label);
    bind('trip-note', snapshot.active_trip ? 'Your bus is on a trip' : snapshot.trip_status === 'COMPLETED' ? 'This journey has ended' : 'Check back for the next journey');
    bind('last-gps', formatTime(snapshot.gps.recorded_at));
    bind('last-received', formatTime(snapshot.gps.received_at));
    bind('bus-coordinates', coordinates(snapshot.location));
    bind('poll-interval', snapshot.poll_interval_seconds);
    bind('journey-heading', snapshot.active_trip ? 'Your bus journey is in progress' : snapshot.trip_status === 'COMPLETED' ? 'Your bus journey is complete' : 'Your route is ready when your bus is');
    bind('journey-description', `${snapshot.gps.label}. Positions are shown only when GPS records are available.`);
    renderStops();
    renderGPS();
    document.dispatchEvent(new CustomEvent('student:snapshot', {detail: {snapshot, gps: effectiveGPS(), connection}}));
  }
  function setConnection(state, message = '') {
    connection = state;
    notice.hidden = !message; notice.textContent = message;
    document.getElementById('session-login').hidden = state !== 'unauthorized';
    renderGPS();
  }
  async function refresh() {
    if (stopped || pending || document.hidden || connection === 'unauthorized') return;
    if (!navigator.onLine) { setConnection('offline', 'You’re offline. Tracking is paused; displayed positions are last known records.'); return; }
    pending = true;
    controller = new AbortController();
    if (refreshButton) { refreshButton.disabled = true; refreshButton.textContent = 'Refreshing…'; }
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch('/api/student/my-bus/location/', {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}, signal: controller.signal});
      if (stopped) return;
      if (response.status === 401 || response.status === 403) {
        clearInterval(pollTimer);
        snapshot = {...snapshot, status: 'session_expired', message: 'Your session has expired or this account can no longer access the student portal. Sign in again.', bus: null, route: null, pickup_stop: null, assignment: null, active_trip: null, trip: null, location: null, gps: {status: 'unavailable', label: 'Sign in to track your bus', is_fresh: false}, eta: {status: 'unavailable'}};
        setConnection('unauthorized', 'Sign in again to continue tracking.'); render(); return;
      }
      if (!response.ok) throw new Error('The tracking service could not refresh. Your last known position is retained; try again.');
      const data = await response.json();
      if (stopped) return;
      if (!data || !['assigned', 'unassigned', 'profile_unavailable'].includes(data.status) || !data.gps || !Number.isFinite(Date.parse(data.generated_at)) || (data.status === 'assigned' && !data.bus)) throw new Error('The tracking response was incomplete. Please try again.');
      snapshot = data; clockOffset = Date.parse(data.generated_at) - Date.now();
      setConnection('online'); render(); schedulePolling();
    } catch (error) {
      if (!stopped && connection !== 'offline') setConnection('error', error.name === 'AbortError' ? 'The tracking request timed out. Displayed records may be outdated; try refreshing.' : error.message);
    } finally {
      clearTimeout(timeout); pending = false;
      if (refreshButton) { refreshButton.disabled = false; refreshButton.textContent = '↻ Refresh'; }
    }
  }
  function schedulePolling() {
    clearInterval(pollTimer);
    if (!refreshButton || stopped || connection === 'unauthorized') return;
    const seconds = Number.isFinite(snapshot.poll_interval_seconds) ? Math.max(2, Math.min(300, snapshot.poll_interval_seconds)) : 10;
    pollTimer = setInterval(refresh, seconds * 1000);
  }
  menu?.addEventListener('click', () => { const open = sidebar.classList.toggle('open'); menu.setAttribute('aria-expanded', String(open)); });
  document.addEventListener('click', event => { if (!sidebar.contains(event.target) && !menu.contains(event.target)) { sidebar.classList.remove('open'); menu.setAttribute('aria-expanded', 'false'); } });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { sidebar.classList.remove('open'); menu.setAttribute('aria-expanded', 'false'); document.querySelectorAll('.student-account[open]').forEach(el => { el.open = false; }); } });
  refreshButton?.addEventListener('click', refresh);
  window.addEventListener('offline', () => { controller?.abort(); setConnection('offline', 'You’re offline. Tracking is paused; displayed positions are last known records.'); });
  window.addEventListener('online', () => { if (connection !== 'unauthorized') { setConnection('error', 'Connection restored. Checking your assigned bus…'); refresh(); } });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { renderGPS(); refresh(); } });
  window.addEventListener('pagehide', () => { stopped = true; clearInterval(pollTimer); clearInterval(ageTimer); controller?.abort(); });
  window.addEventListener('pageshow', event => { if (event.persisted) { stopped = false; schedulePolling(); ageTimer = setInterval(() => { if (!document.hidden) renderGPS(); }, 1000); refresh(); } });
  window.StudentTransit = Object.freeze({getSnapshot: () => snapshot, getGPS: effectiveGPS});
  render(); schedulePolling();
  ageTimer = setInterval(() => { if (!document.hidden) renderGPS(); }, 1000);
  if (!navigator.onLine) setConnection('offline', 'You’re offline. Reconnect to check your assigned bus.');
})();
