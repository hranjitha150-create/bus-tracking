(() => {
  const form = document.getElementById('bulk-stop-form');
  if (!form) return;
  const rows = document.getElementById('bulk-stop-rows');
  const total = document.getElementById('id_stops-TOTAL_FORMS');
  const add = document.getElementById('add-stop-row');
  const feedback = document.getElementById('bulk-stop-feedback');
  add.addEventListener('click', () => {
    const index = Number(total.value);
    if (index >= 200) { feedback.textContent = 'Save these stops before adding more. A route supports up to 500 stops.'; return; }
    const template = document.getElementById('empty-stop-row');
    const row = template.content.firstElementChild.cloneNode(true);
    row.querySelectorAll('[name], [id], [for]').forEach(element => {
      ['name', 'id', 'for'].forEach(attribute => {
        if (element.hasAttribute(attribute)) element.setAttribute(attribute, element.getAttribute(attribute).replaceAll('__prefix__', String(index)));
      });
    });
    rows.append(row);
    total.value = index + 1;
    row.querySelector('input')?.focus();
  });
  rows.addEventListener('click', event => {
    const button = event.target.closest('[data-remove-stop]');
    if (!button) return;
    const row = button.closest('[data-stop-row]');
    row.querySelector('input[name$="-DELETE"]').checked = true;
    row.querySelectorAll('input,textarea').forEach(input => input.required = false);
    row.hidden = true;
    feedback.textContent = 'Stop removed from this batch. Save all stops to finish.';
  });
})();
