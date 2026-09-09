/* Inline ROB editing — shared by the Stores list and the dashboard low-ROB panel.
   Click ✎ in a .rob-cell, type the new quantity, Enter/✓ saves, Esc/✕ confirms/cancels.
   Every save POSTs to /stores/adjust/<id> which logs a stock_corrections audit row. */
(function () {
  'use strict';

  function robFlash(message, category) {
    var page = document.querySelector('.page-content') || document.body;
    var box = page.querySelector('.flash-messages');
    if (!box) {
      box = document.createElement('div');
      box.className = 'flash-messages';
      page.prepend(box);
      box = page.querySelector('.flash-messages');
    }
    var el = document.createElement('div');
    el.className = 'flash flash-' + category;
    el.textContent = (category === 'success' ? '✅ ' : '❌ ') + message;
    box.appendChild(el);
    setTimeout(function () { el.remove(); }, 4000);
  }

  function refreshStalePanels() {
    // On the dashboard the "worst 12" panel must re-rank after a correction —
    // reload. Elsewhere the cell is already updated in place.
    if (document.querySelector('[data-rob-autorefresh]')) {
      setTimeout(function () { window.location.reload(); }, 600);
    }
  }

  function save(cell, itemId, newValue, input) {
    var meta = document.querySelector('meta[name="csrf-token"]');
    fetch('/stores/adjust/' + itemId, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': meta ? meta.getAttribute('content') : ''
      },
      body: JSON.stringify({ quantity: newValue, reason: 'inline edit' })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok || !res.d.ok) {
          robFlash(res.d.error || 'Update failed', 'danger');
          input.focus();
          return;
        }
        // Update cell text and badge state
        var qtyEl = cell.querySelector('.rob-qty');
        var badge = cell.querySelector('.rob-low-badge');
        if (badge) { badge.remove(); }
        if (res.d.low) {
          var b = document.createElement('span');
          b.className = 'rob-low-badge';
          b.textContent = 'Low';
          qtyEl.after(b);
        }
        qtyEl.textContent = res.d.quantity;
        robFlash('ROB updated: ' + res.d.quantity, 'success');
        // Dashboard panel and low-ROB badge elsewhere can be stale — refresh
        refreshStalePanels();
      })
      .catch(function () {
        robFlash('Network error — quantity not saved', 'danger');
        input.focus();
      });
  }

  document.addEventListener('click', function (e) {
    var cell = e.target.closest('.rob-cell');
    if (!cell || cell.dataset.editing === '1') { return; }

    var itemId = cell.dataset.id;
    if (!itemId) { return; }

    // Clicks on the pencil open the editor; clicking elsewhere in the cell too.
    if (!e.target.closest('.rob-edit-btn') && !e.target.closest('.rob-qty')) { return; }

    e.preventDefault();
    cell.dataset.editing = '1';
    var current = cell.querySelector('.rob-qty').textContent.trim();
    cell.dataset.prev = current;

    var wrap = document.createElement('span');
    wrap.className = 'rob-editor';
    wrap.innerHTML =
      '<input type="number" class="rob-input form-control" min="0" step="1" value="' + current + '">' +
      '<button type="button" class="rob-save-btn btn btn-sm btn-primary" title="Save">✓</button>' +
      '<button type="button" class="rob-cancel-btn btn btn-sm btn-outline" title="Cancel">✕</button>';

    var qtyEl = cell.querySelector('.rob-qty');
    var badge = cell.querySelector('.rob-low-badge');
    [qtyEl, badge].forEach(function (el) { if (el) { el.style.display = 'none'; }; });
    qtyEl.after(wrap);
    var input = wrap.querySelector('.rob-input');
    input.focus();
    input.select();

    function closeEditor() {
      wrap.remove();
      cell.dataset.editing = '';
      [qtyEl, badge].forEach(function (el) { if (el) { el.style.display = ''; }; });
    }

    wrap.querySelector('.rob-cancel-btn').addEventListener('click', closeEditor);

    wrap.querySelector('.rob-save-btn').addEventListener('click', function () {
      var v = input.value.trim();
      if (v === '' || parseInt(v, 10) < 0 || !/^-?\d+$/.test(v)) {
        robFlash('Enter a whole number ≥ 0', 'danger');
        input.focus();
        return;
      }
      save(cell, itemId, v, input);
      closeEditor();
    });

    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        wrap.querySelector('.rob-save-btn').click();
      } else if (ev.key === 'Escape') {
        closeEditor();
      }
    });
  });
})();
