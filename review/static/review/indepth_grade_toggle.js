/**
 * In-depth review rating toggles.
 *
 * Highlights the selected RAG button within each judgement-area card, and the
 * selected button in the overall-grade selector. CSS :has() handles modern
 * browsers; this adds an explicit --selected class as a fallback.
 */
(function () {
  'use strict';

  function syncGroup(container, btnSelector, selectedClass) {
    var checked = container.querySelector('input[type="radio"]:checked');
    var value = checked ? checked.value : '';
    container.querySelectorAll(btnSelector).forEach(function (btn) {
      var own = btn.querySelector('input[type="radio"]');
      btn.classList.toggle(selectedClass, !!own && own.checked && !!value);
    });
  }

  function initGroup(container, btnSelector, selectedClass) {
    syncGroup(container, btnSelector, selectedClass);
    container.querySelectorAll('input[type="radio"]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        syncGroup(container, btnSelector, selectedClass);
      });
    });
  }

  // Per judgement-area RAG ratings
  document.querySelectorAll('[data-judgement] .indepth-rag-options').forEach(function (group) {
    initGroup(group, '.indepth-rag-btn', 'indepth-rag-btn--selected');
  });

  // Overall area grade selector
  document.querySelectorAll('.indepth-overall .indepth-grade-options').forEach(function (group) {
    initGroup(group, '.indepth-grade-btn', 'indepth-grade-btn--selected');
  });
})();
