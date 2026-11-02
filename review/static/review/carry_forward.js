/*
 * Evaluation page: "Copy into this term" under last term's text.
 *
 * Copies the exact stored text (from the sibling <template>) into this term's
 * box. Nothing is saved until the user presses Save. If the box already holds
 * something different, it asks before replacing it. An input event is fired so
 * the unsaved-changes warning and the word counter see the change.
 */
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var buttons = document.querySelectorAll('.evaluation-previous-copy');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].hidden = false;
      buttons[i].addEventListener('click', copyIn);
    }
  });

  function copyIn(event) {
    var button = event.currentTarget;
    var source = button.parentNode.querySelector('.evaluation-previous-source');
    var target = document.getElementById(button.getAttribute('data-copy-into'));
    if (!source || !target) return;

    var text = source.content.textContent;
    if (target.value === text) return;
    if (target.value.replace(/\s+/g, '') !== '' &&
        !window.confirm('Replace what is already in this box with last term\'s text?')) {
      return;
    }
    target.value = text;
    target.dispatchEvent(new Event('input', { bubbles: true }));
    target.focus();
  }
})();
