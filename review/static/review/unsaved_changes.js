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

    function markDirty() {
      if (!isSubmitting) isDirty = true;
    }

    formEl.addEventListener('input', markDirty, true);
    formEl.addEventListener('change', markDirty, true);

    formEl.addEventListener('submit', function () {
      isSubmitting = true;
      isDirty = false;
    });

    window.addEventListener('beforeunload', function (event) {
      if (!isDirty || isSubmitting) return;
      event.preventDefault();
      // Most browsers ignore custom text; returning an empty string triggers the native prompt.
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
