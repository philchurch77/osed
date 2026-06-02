/**
 * In-depth review grade button toggle.
 *
 * Highlights the selected grade button within each sub-section card and
 * shows the matching grade descriptor text.
 */
(function () {
  'use strict';

  function updateSubSection(container) {
    var checked = container.querySelector('input[type="radio"]:checked');
    var selectedGrade = checked ? checked.value : '';

    // Update button active state
    container.querySelectorAll('.indepth-grade-btn').forEach(function (btn) {
      var grade = btn.getAttribute('data-grade');
      btn.classList.toggle('indepth-grade-btn--selected', grade === selectedGrade);
    });

    // Show/hide descriptors
    container.querySelectorAll('.indepth-grade-descriptor').forEach(function (desc) {
      var forGrade = desc.getAttribute('data-for-grade');
      desc.style.display = (forGrade === selectedGrade && selectedGrade) ? '' : 'none';
    });
  }

  function initSubSection(container) {
    updateSubSection(container);
    container.querySelectorAll('input[type="radio"]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        updateSubSection(container);
      });
    });
  }

  document.querySelectorAll('.indepth-subsection').forEach(initSubSection);
})();
