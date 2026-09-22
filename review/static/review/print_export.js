/*
 * "Save as PDF" — opens the browser's own print dialog, and makes what prints
 * complete.
 *
 * A printed <textarea> shows only what fits in its box, and cannot break
 * across pages. So on beforeprint every textarea gets a plain sibling
 * div.print-mirror holding its text (styles.css hides the textarea and shows
 * the mirror in print), and on afterprint the mirrors go away.
 *
 * This file only ever READS field state. It never assigns to .value,
 * .checked, .defaultValue or .defaultChecked, and the mirror is filled with
 * textContent, so nothing stored can be altered and nothing typed can run as
 * markup. PrintExportTests greps for this.
 *
 * It also works for Ctrl+P, since it listens for the print events rather
 * than the button click.
 */
(function () {
  var MIRROR_CLASS = 'print-mirror';
  var savedTitle = null;

  function exportButton() {
    return document.querySelector('.export-pdf');
  }

  function hasUnsavedChanges(root) {
    var i;
    // A rejected save re-renders the typed text as the default, so the
    // comparison below cannot see it; the template flags it instead.
    var btn = exportButton();
    if (btn && btn.getAttribute('data-unsaved') === '1') return true;
    var areas = root.querySelectorAll('textarea');
    for (i = 0; i < areas.length; i++) {
      if (areas[i].value !== areas[i].defaultValue) return true;
    }
    var boxes = root.querySelectorAll('input[type="radio"], input[type="checkbox"]');
    for (i = 0; i < boxes.length; i++) {
      if (boxes[i].checked !== boxes[i].defaultChecked) return true;
    }
    return false;
  }

  function beforePrint() {
    var root = document.querySelector('main') || document.body;

    var btn = exportButton();
    if (btn && btn.getAttribute('data-print-title')) {
      // Guarded: if a browser skipped afterprint, the title still holds the
      // print title, and saving it again would lose the real one.
      if (savedTitle === null) savedTitle = document.title;
      document.title = btn.getAttribute('data-print-title');
    }

    removeMirrors();
    var areas = root.querySelectorAll('textarea');
    for (var i = 0; i < areas.length; i++) {
      var mirror = document.createElement('div');
      mirror.className = MIRROR_CLASS;
      var text = areas[i].value;
      if (text.replace(/\s+/g, '') === '') {
        mirror.className += ' print-mirror--empty';
        mirror.textContent = 'Nothing recorded.';
      } else {
        mirror.textContent = text;
      }
      areas[i].parentNode.insertBefore(mirror, areas[i].nextSibling);
    }

    var note = root.querySelector('.print-unsaved');
    if (note) {
      note.textContent = hasUnsavedChanges(root)
        ? 'This copy includes changes that have not been saved.'
        : '';
    }
  }

  function removeMirrors() {
    var mirrors = document.querySelectorAll('.' + MIRROR_CLASS);
    for (var i = 0; i < mirrors.length; i++) {
      mirrors[i].parentNode.removeChild(mirrors[i]);
    }
  }

  function afterPrint() {
    removeMirrors();
    if (savedTitle !== null) {
      document.title = savedTitle;
      savedTitle = null;
    }
  }

  window.addEventListener('beforeprint', beforePrint);
  window.addEventListener('afterprint', afterPrint);

  document.addEventListener('DOMContentLoaded', function () {
    var btn = exportButton();
    if (!btn) return;
    var bar = btn.closest('.export-pdf-bar');
    if (bar) bar.hidden = false;
    btn.addEventListener('click', function () { window.print(); });
  });
})();
