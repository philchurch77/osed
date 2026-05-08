(function () {
  function deferMicrotask(callback) {
    if (typeof queueMicrotask === 'function') {
      queueMicrotask(callback);
      return;
    }

    Promise.resolve().then(callback);
  }

  function trimText(value) {
    return (value || '').replace(/^\s+|\s+$/g, '');
  }

  function closestByClass(startEl, className) {
    var el = startEl;
    while (el && el !== document) {
      if (el.classList && el.classList.contains(className)) return el;
      el = el.parentNode;
    }
    return null;
  }

  function removeAllClasses(el, classes) {
    if (!el || !el.classList) return;
    for (var i = 0; i < classes.length; i += 1) {
      el.classList.remove(classes[i]);
    }
  }

  function closeDetails(detailsEl) {
    if (!detailsEl) return;
    detailsEl.removeAttribute('open');
    if (typeof detailsEl.open !== 'undefined') {
      detailsEl.open = false;
    }
  }

  function closeOtherPickers(activeDetailsEl) {
    var openEls = document.querySelectorAll('details.rag-picker[open]');
    for (var i = 0; i < openEls.length; i += 1) {
      if (openEls[i] !== activeDetailsEl) closeDetails(openEls[i]);
    }
  }

  function triggerChange(inputEl) {
    if (!inputEl) return;

    // Keep compatibility with older browsers that don't support `new Event()`.
    var ev;
    if (typeof Event === 'function') {
      try {
        ev = new Event('change', { bubbles: true });
      } catch (e) {
        ev = null;
      }
    }

    if (!ev && document.createEvent) {
      ev = document.createEvent('HTMLEvents');
      ev.initEvent('change', true, false);
    }

    if (ev) inputEl.dispatchEvent(ev);
  }

  function updatePickerSummary(detailsEl) {
    var summaryTextEl = detailsEl.querySelector('.rag-current');
    if (!summaryTextEl) return;

    var checked = detailsEl.querySelector('input[type="radio"]:checked');
    var value = checked ? checked.value : null;

    var labelText = '';
    if (checked) {
      var pillEl = closestByClass(checked, 'rag-pill');
      if (pillEl) {
        var labelEl = pillEl.querySelector('.rag-pill-label');
        labelText = labelEl ? trimText(labelEl.textContent) : '';
      }
    }

    removeAllClasses(summaryTextEl, [
      'rag-current--1',
      'rag-current--2',
      'rag-current--3',
      'rag-current--4',
      'rag-current--5',
      'rag-current--blank',
    ]);

    if (!value) {
      summaryTextEl.classList.add('rag-current--blank');
      summaryTextEl.textContent = 'Select rating';
      return;
    }

    summaryTextEl.classList.add('rag-current--' + value);
    summaryTextEl.textContent = labelText ? '(' + value + ') ' + labelText : '(' + value + ')';
  }

  function setupRagPicker(detailsEl) {
    // Close other open pickers when one opens.
    if (detailsEl.addEventListener) {
      detailsEl.addEventListener('toggle', function () {
        if (!detailsEl.open) return;
        closeOtherPickers(detailsEl);
      });

      // Keep summary synced on close.
      detailsEl.addEventListener('toggle', function () {
        if (detailsEl.open) return;
        updatePickerSummary(detailsEl);
      });
    }

    // Fallback: some environments don't reliably fire `toggle`.
    var summaryEl = detailsEl.querySelector('summary');
    if (summaryEl && summaryEl.addEventListener) {
      summaryEl.addEventListener('click', function () {
        deferMicrotask(function () {
          if (!detailsEl.open) return;
          closeOtherPickers(detailsEl);
        });
      });
    }

    // Keep summary in sync + auto-close after selection.
    var inputs = detailsEl.querySelectorAll('input[type="radio"]');
    for (var i = 0; i < inputs.length; i += 1) {
      (function (inputEl) {
        inputEl.addEventListener('change', function () {
          updatePickerSummary(detailsEl);
          if (inputEl.checked) closeDetails(detailsEl);
        });
      })(inputs[i]);
    }

    // Also close + sync on pill click (covers label interaction timing).
    var pills = detailsEl.querySelectorAll('.rag-pill');
    for (var j = 0; j < pills.length; j += 1) {
      (function (pillEl) {
        var inputEl = pillEl.querySelector('input[type="radio"]');
        var wasCheckedBeforeClick = false;

        function recordWasChecked() {
          wasCheckedBeforeClick = !!(inputEl && inputEl.checked);
        }

        // Record state BEFORE the default label/radio toggle happens.
        if (pillEl.addEventListener) {
          pillEl.addEventListener('pointerdown', recordWasChecked);
          pillEl.addEventListener('mousedown', recordWasChecked);
          pillEl.addEventListener('keydown', function (event) {
            var key = event && (event.key || event.code);
            if (key === 'Enter' || key === ' ' || key === 'Spacebar' || key === 'Space') {
              recordWasChecked();
            }
          });
        }

        pillEl.addEventListener('click', function (event) {
          // Click again to clear only if it was already selected beforehand.
          if (inputEl && wasCheckedBeforeClick) {
            if (event && event.preventDefault) event.preventDefault();
            if (event && event.stopPropagation) event.stopPropagation();

            inputEl.checked = false;
            triggerChange(inputEl);

            deferMicrotask(function () {
              updatePickerSummary(detailsEl);
              closeDetails(detailsEl);
            });
            wasCheckedBeforeClick = false;
            return;
          }

          deferMicrotask(function () {
            updatePickerSummary(detailsEl);
            var nowChecked = detailsEl.querySelector('input[type="radio"]:checked');
            if (nowChecked) closeDetails(detailsEl);
          });

          wasCheckedBeforeClick = false;
        });
      })(pills[j]);
    }

    updatePickerSummary(detailsEl);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var pickers = document.querySelectorAll('details.rag-picker');
    for (var j = 0; j < pickers.length; j += 1) setupRagPicker(pickers[j]);
  });
})();
