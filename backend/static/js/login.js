(() => {
  'use strict';
  const toggle = document.querySelector('.password-toggle');
  if (!toggle) return;
  const input = document.getElementById(toggle.getAttribute('aria-controls'));
  if (!input) return;
  toggle.hidden = false;
  toggle.addEventListener('click', () => {
    const visible = input.type === 'password';
    input.type = visible ? 'text' : 'password';
    input.toggleAttribute('data-password-visible', visible);
    toggle.textContent = visible ? 'Hide' : 'Show';
    toggle.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
    toggle.setAttribute('aria-pressed', String(visible));
  });
})();
