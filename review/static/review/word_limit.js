/* Client-side word limit guard with live counter (ES5).
   - Default: 300 words (matches server-side MAX_TEXTAREA_WORDS).
   - Override per field: data-max-words="150".
   - Opt out (no limit, no counter): data-max-words="0".
*/

(function () {
  "use strict";

  var DEFAULT_MAX_WORDS = 300;

  function parseMaxWords(textarea) {
    var raw = textarea.getAttribute("data-max-words");
    if (raw === null || raw === "") return DEFAULT_MAX_WORDS;
    var max = parseInt(raw, 10);
    return isNaN(max) ? DEFAULT_MAX_WORDS : max;
  }

  function getWords(value) {
    if (!value) return [];
    var matches = value.trim().match(/\S+/g);
    return matches ? matches : [];
  }

  // Cut after the maxWords-th word, keeping the text before it exactly as
  // typed (line breaks included) rather than re-joining the words with spaces.
  function trimToMaxWords(value, maxWords) {
    var words = getWords(value);
    if (words.length <= maxWords) return value;
    var re = /\S+/g;
    var match = null;
    for (var n = 0; n < maxWords; n++) {
      match = re.exec(value);
    }
    return match ? value.slice(0, match.index + match[0].length) : "";
  }

  function enforce(textarea, maxWords) {
    var next = trimToMaxWords(textarea.value, maxWords);
    if (next !== textarea.value) textarea.value = next;
  }

  function createCounter(textarea) {
    var counter = document.createElement("span");
    counter.className = "word-counter";
    textarea.parentNode.insertBefore(counter, textarea.nextSibling);
    return counter;
  }

  function updateCounter(counter, textarea, maxWords) {
    var count = getWords(textarea.value).length;
    counter.textContent = count + " / " + maxWords + " words";
    if (count >= maxWords) {
      counter.className = "word-counter word-counter--limit";
    } else if (count >= Math.ceil(maxWords * 0.85)) {
      counter.className = "word-counter word-counter--near";
    } else {
      counter.className = "word-counter";
    }
  }

  function init() {
    var textareas = document.getElementsByTagName("textarea");
    for (var i = 0; i < textareas.length; i++) {
      (function (el) {
        if (el.disabled || el.readOnly) return;
        var maxWords = parseMaxWords(el);
        if (!maxWords || maxWords <= 0) return;

        // No enforce() here: trimming on load would cut stored text that is
        // already over the limit (entered via the admin or an import, or under
        // a higher limit) and collapse its newlines, and the next Save would
        // persist the trim. Leave the stored text exactly as it is. Where the
        // form validates the limit (_validate_max_words) an over-limit save is
        // refused with the text intact; where it does not, the text is saved
        // as it stands, which loses nothing.
        var counter = createCounter(el);
        updateCounter(counter, el, maxWords);

        // Stored text that arrives over the limit is never trimmed in the
        // browser, not even on the next keystroke: the counter shows it is
        // over, and nothing the user did not delete is removed.
        var loadedOverLimit = getWords(el.value).length > maxWords;

        el.addEventListener("input", function () {
          if (!loadedOverLimit) enforce(el, maxWords);
          updateCounter(counter, el, maxWords);
        });

        el.addEventListener("paste", function () {
          setTimeout(function () {
            if (!loadedOverLimit) enforce(el, maxWords);
            updateCounter(counter, el, maxWords);
          }, 0);
        });
      })(textareas[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
