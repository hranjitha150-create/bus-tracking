(() => {
  'use strict';
  const cache = new Map();
  document.querySelectorAll('input[data-place-search]').forEach(input => {
    const wrap = document.createElement('div');
    wrap.className = 'place-search-wrap';
    input.before(wrap);
    wrap.append(input);
    const list = document.createElement('ul');
    list.id = `${input.id}-places`;
    list.className = 'place-suggestions';
    list.setAttribute('role', 'listbox');
    list.setAttribute('aria-label', 'Suggested locations');
    list.hidden = true;
    wrap.append(list);
    const feedback = document.createElement('p');
    feedback.id = `${input.id}-place-status`;
    feedback.className = 'place-search-status';
    feedback.setAttribute('role', 'status');
    wrap.after(feedback);
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-controls', list.id);
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-describedby', [input.getAttribute('aria-describedby'), feedback.id].filter(Boolean).join(' '));
    let timer, controller, sequence = 0, active = -1, labels = [];
    const close = () => {
      list.hidden = true;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      active = -1;
    };
    const cancel = () => { clearTimeout(timer); controller?.abort(); sequence++; };
    const choose = index => {
      if (!labels[index]) return;
      cancel();
      input.value = labels[index];
      close();
      feedback.textContent = 'Location selected.';
      input.dispatchEvent(new Event('change', {bubbles: true}));
    };
    const show = (results, broadened = false) => {
      labels = results;
      list.replaceChildren();
      active = -1;
      input.removeAttribute('aria-activedescendant');
      labels.forEach((label, index) => {
        const option = document.createElement('li');
        option.id = `${list.id}-${index}`;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');
        option.textContent = label;
        option.addEventListener('mousedown', event => event.preventDefault());
        option.addEventListener('click', () => choose(index));
        list.append(option);
      });
      list.hidden = !labels.length;
      input.setAttribute('aria-expanded', String(Boolean(labels.length)));
      feedback.textContent = labels.length ? `${broadened ? 'Broader locality matches, not exact building addresses. ' : ''}${labels.length} suggestions. Use arrow keys and Enter to choose. Places by Photon / OpenStreetMap.` : 'No map match. You can save this address manually, or search using the area and city.';
    };
    input.addEventListener('input', () => {
      cancel();
      close();
      const query = input.value.trim();
      const current = sequence;
      feedback.textContent = '';
      if (query.length < 3) return;
      if (query.length > 200) { feedback.textContent = 'Use 200 characters or fewer for this location.'; return; }
      timer = setTimeout(async () => {
        const key = query.toLocaleLowerCase();
        if (cache.has(key)) { const saved = cache.get(key); show(saved.results, saved.broadened); return; }
        controller = new AbortController();
        feedback.textContent = 'Searching locations…';
        try {
          const url = new URL(input.dataset.placeUrl, window.location.origin);
          url.searchParams.set('q', query);
          const response = await fetch(url, {signal: controller.signal, credentials: 'same-origin', headers: {'Accept': 'application/json'}});
          if (!response.ok) throw new Error('Search unavailable');
          const data = await response.json();
          if (current !== sequence || document.activeElement !== input) return;
          const results = Array.isArray(data.results) ? data.results.filter(value => typeof value === 'string' && value.length <= input.maxLength).slice(0, 6) : [];
          if (cache.size >= 50) cache.delete(cache.keys().next().value);
          cache.set(key, {results, broadened: data.broadened === true});
          show(results, data.broadened === true);
        } catch (error) {
          if (error.name === 'AbortError' || current !== sequence) return;
          close();
          feedback.textContent = 'Place search is unavailable. You can still enter the location manually.';
        }
      }, 800);
    });
    input.addEventListener('keydown', event => {
      if (event.key === 'Escape') { cancel(); close(); feedback.textContent = ''; return; }
      if (list.hidden) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        active = event.key === 'ArrowDown' ? (active + 1) % labels.length : (active <= 0 ? labels.length - 1 : active - 1);
        [...list.children].forEach((option, index) => option.setAttribute('aria-selected', String(index === active)));
        input.setAttribute('aria-activedescendant', list.children[active].id);
        list.children[active].scrollIntoView({block: 'nearest'});
      } else if (event.key === 'Enter' && active >= 0) { event.preventDefault(); choose(active); }
    });
    input.addEventListener('blur', () => { cancel(); close(); });
  });
})();
