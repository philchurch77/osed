/* Client-side word limit guard (ES5).
   Enforces a max word count on all <textarea> elements.

   - Default: 300 words.
   - Override per field: data-max-words="123".
   - Opt out: data-max-words="0".
*/

(function () {
  "use strict";

  var DEFAULT_MAX_WORDS = 300;

  function parseMaxWords(textarea) {
    var raw = textarea.getAttribute("data-max-words");
    if (raw === null || raw === "") {
      return DEFAULT_MAX_WORDS;
    }
    var max = parseInt(raw, 10);
    if (isNaN(max)) {
      return DEFAULT_MAX_WORDS;
    }
    return max;
  }

  function getWords(value) {
    if (!value) {
      return [];
    }
    var matches = value.trim().match(/\S+/g);
    return matches ? matches : [];
  }

  function trimToMaxWords(value, maxWords) {
    var words = getWords(value);
    if (words.length <= maxWords) {
      return value;
    }
    // Normalize spacing to a single space between words.
    return words.slice(0, maxWords).join(" ");
  }

  function enforce(textarea) {
    var maxWords = parseMaxWords(textarea);
    if (!maxWords || maxWords <= 0) {
      return;
    }

    var nextValue = trimToMaxWords(textarea.value, maxWords);
    if (nextValue !== textarea.value) {
      textarea.value = nextValue;
    }
  }

  function init() {
    var textareas = document.getElementsByTagName("textarea");
    for (var i = 0; i < textareas.length; i++) {
      (function (el) {
        // Enforce immediately (covers pre-filled values).
        enforce(el);

        el.addEventListener("input", function () {
          enforce(el);
        });

        el.addEventListener("paste", function () {
          // Some browsers fire input reliably after paste, but this keeps us safe.
          setTimeout(function () {
            enforce(el);
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
