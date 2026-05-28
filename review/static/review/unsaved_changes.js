(function () {
  function closestAnchor(target) {
    var el = target;
    while (el && el !== document) {
      if (el.tagName && el.tagName.toLowerCase() === 'a' && el.getAttribute('href')) return el;
      el = el.parentNode;
    }
    return null;
  }

  function setupUnsavedWarning(formEl) {
    var isDirty = false;
    var isSubmitting = false;

    // Insert a hidden indicator into the .actions bar next to the Save button.
    var indicator = null;
    var actionsEl = formEl.querySelector('.actions');
    if (actionsEl) {
      indicator = document.createElement('span');
      indicator.className = 'unsaved-indicator';
      indicator.setAttribute('aria-live', 'polite');
      indicator.textContent = 'Unsaved changes';
      actionsEl.insertBefore(indicator, actionsEl.firstChild);
    }

    function markDirty() {
      if (isSubmitting) return;
      isDirty = true;
      if (indicator) indicator.classList.add('unsaved-indicator--visible');
    }

    formEl.addEventListener('input', markDirty, true);
    formEl.addEventListener('change', markDirty, true);

    formEl.addEventListener('submit', function () {
      isSubmitting = true;
      isDirty = false;
      if (indicator) indicator.classList.remove('unsaved-indicator--visible');
    });

    window.addEventListener('beforeunload', function (event) {
      if (!isDirty || isSubmitting) return;
      event.preventDefault();
      event.returnValue = '';
    });

    document.addEventListener('click', function (event) {
      if (!isDirty || isSubmitting) return;

      var link = closestAnchor(event.target);
      if (!link) return;

      var href = link.getAttribute('href') || '';
      if (href.indexOf('#') === 0) return;

      var proceed = window.confirm('You have unsaved changes. Leave this page without saving?');
      if (!proceed) {
        event.preventDefault();
        event.stopPropagation();
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var formEl = document.querySelector('form[method="post"]');
    if (formEl) setupUnsavedWarning(formEl);
  });
})();
