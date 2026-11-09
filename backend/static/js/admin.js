(() => {
  const toggle = document.getElementById('menu-toggle');
  const sidebar = document.getElementById('sidebar');
  toggle?.addEventListener('click', () => {
    const open = sidebar.classList.toggle('open');
    toggle.setAttribute('aria-expanded', String(open));
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      sidebar?.classList.remove('open');
      toggle?.setAttribute('aria-expanded', 'false');
      document.querySelectorAll('details.account-menu[open]').forEach(menu => menu.open = false);
    }
  });
  document.addEventListener('click', event => {
    if (!sidebar?.contains(event.target) && !toggle?.contains(event.target)) {
      sidebar?.classList.remove('open');
      toggle?.setAttribute('aria-expanded', 'false');
    }
  });
  document.querySelectorAll('form[data-record-form]').forEach(form => {
    form.addEventListener('submit', () => {
      form.setAttribute('aria-busy', 'true');
      form.querySelectorAll('button[type="submit"],button:not([type])').forEach(button => {
        button.disabled = true;
        button.textContent = button.dataset.loadingText || 'Saving…';
      });
    });
  });
  const form = document.querySelector('[data-pickup-url]');
  if (!form) return;
  const bus = form.querySelector('[name="bus"]');
  const pickup = form.querySelector('[name="pickup_stop"]');
  const feedback = document.getElementById('pickup-feedback');
  let controller;
  bus.addEventListener('change', async () => {
    controller?.abort();
    controller = new AbortController();
    pickup.replaceChildren(new Option('Select a pickup stop', ''));
    if (!bus.value) { feedback.textContent = 'Select a bus first.'; return; }
    pickup.disabled = true;
    feedback.textContent = 'Loading stops for this bus’s active route…';
    try {
      const response = await fetch(`${form.dataset.pickupUrl}?bus=${encodeURIComponent(bus.value)}`, {signal: controller.signal, credentials: 'same-origin', headers: {'Accept': 'application/json'}});
      if (!response.ok) throw new Error('Could not load stops. Check your connection and sign-in, then select the bus again.');
      const data = await response.json();
      data.results.forEach(stop => pickup.add(new Option(`${stop.order}. ${stop.name}`, stop.id)));
      pickup.disabled = false;
      feedback.textContent = data.results.length ? 'Only stops on this bus’s active route are available.' : 'No route stops are available. Assign an active driver and route with stops first.';
    } catch (error) {
      if (error.name === 'AbortError') return;
      pickup.disabled = false;
      feedback.textContent = error.message;
    }
  });
})();
