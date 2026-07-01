/**
 * In-depth review RAG ladder (page 1).
 *
 * Reveals the next rung as the user completes the current one and concludes the
 * self-evaluation grade live. This mirrors `conclude_indepth_grade` in views.py;
 * the server recomputes authoritatively on save, so this is purely UX.
 *
 * Ladder (non-safeguarding):
 *   Expected  all green -> reveal Strong | amber -> Expected Standard | red -> reveal Urgent Improvement
 *   Strong    all green -> reveal Exceptional | amber -> Strong Standard | red -> Expected Standard
 *   Exceptional  red -> Strong Standard | otherwise -> Exceptional
 *   Urgent Improvement (flipped: green = failing applies)
 *                all red -> Needs Attention | otherwise -> Urgent Improvement
 * Safeguarding: Met statements -> any red = Not Met, else Met.
 */
(function () {
  'use strict';

  var conclusion = document.getElementById('indepth-conclusion');
  if (!conclusion) {
    return;
  }
  var safeguarding = conclusion.dataset.safeguarding === '1';

  var LABELS = {
    not_met: 'Not Met',
    met: 'Met',
    urgent_improvement: 'Urgent Improvement',
    needs_attention: 'Needs Attention',
    expected_standard: 'Expected Standard',
    strong_standard: 'Strong Standard',
    exceptional: 'Exceptional'
  };

  function section(key) {
    return document.querySelector('.indepth-rung[data-rung="' + key + '"]');
  }

  function ragList(sec) {
    if (!sec) {
      return null;
    }
    var out = [];
    sec.querySelectorAll('[data-judgement]').forEach(function (j) {
      var checked = j.querySelector('input[type="radio"]:checked');
      out.push(checked ? checked.value : '');
    });
    return out;
  }

  function state(list) {
    if (list === null) {
      return 'absent';
    }
    if (list.length === 0 || list.indexOf('') >= 0) {
      return 'incomplete';
    }
    if (list.indexOf('red') >= 0) {
      return 'has_red';
    }
    if (list.indexOf('amber') >= 0) {
      return 'has_amber';
    }
    return 'all_green';
  }

  // Returns { grade: <key|''>, visible: { rungKey: true } }
  function evaluate() {
    var visible = {};
    var grade = '';

    if (safeguarding) {
      visible.met = true;
      var met = ragList(section('met'));
      var ms = state(met);
      if (ms !== 'absent' && ms !== 'incomplete') {
        grade = met.indexOf('red') >= 0 ? 'not_met' : 'met';
      }
      return { grade: grade, visible: visible };
    }

    visible.expected_standard = true;
    var expected = ragList(section('expected_standard'));
    var es = state(expected);

    if (es === 'has_red') {
      // Any red at Expected Standard concludes Needs Attention; the Urgent
      // Improvement rung is no longer shown or evaluated.
      grade = 'needs_attention';
    } else if (es === 'has_amber') {
      grade = 'expected_standard';
    } else if (es === 'all_green') {
      visible.strong_standard = true;
      var strong = ragList(section('strong_standard'));
      var ss = state(strong);
      if (ss === 'absent') {
        grade = 'expected_standard';
      } else if (ss === 'has_red') {
        grade = 'expected_standard';
      } else if (ss === 'has_amber') {
        grade = 'strong_standard';
      } else if (ss === 'all_green') {
        visible.exceptional = true;
        var exc = ragList(section('exceptional'));
        var xs = state(exc);
        if (xs === 'absent') {
          grade = 'strong_standard';
        } else if (xs !== 'incomplete') {
          grade = exc.indexOf('red') >= 0 ? 'strong_standard' : 'exceptional';
        }
      }
    }

    return { grade: grade, visible: visible };
  }

  function setVisible(sec, show, clearWhenHidden) {
    if (!sec) {
      return;
    }
    sec.classList.toggle('is-hidden', !show);
    if (!show && clearWhenHidden) {
      // Clear an abandoned branch so it neither submits nor persists.
      sec.querySelectorAll('input[type="radio"]').forEach(function (r) {
        if (!r.disabled) {
          r.checked = false;
        }
      });
      sec.querySelectorAll('.indepth-rag-btn--selected').forEach(function (b) {
        b.classList.remove('indepth-rag-btn--selected');
      });
    }
  }

  function paint(result, clearWhenHidden) {
    document.querySelectorAll('.indepth-rung').forEach(function (sec) {
      setVisible(sec, !!result.visible[sec.dataset.rung], clearWhenHidden);
    });

    var box = document.getElementById('indepth-grade-box');
    var badge = document.getElementById('indepth-grade-badge');
    if (!box || !badge) {
      return;
    }
    box.className = 'review-outcome';
    if (result.grade) {
      box.classList.add('review-outcome--' + result.grade);
      badge.className = 'review-outcome-badge review-outcome-badge--' + result.grade;
      badge.textContent = LABELS[result.grade] || result.grade;
    } else {
      box.classList.add('review-outcome--pending');
      badge.className = 'review-outcome-badge';
      badge.textContent = 'Complete the ratings to see your grade';
    }
  }

  // Initial paint reflects saved data; don't clear on load (avoids wiping a
  // legitimately-saved branch just by viewing the page).
  paint(evaluate(), false);

  document.querySelectorAll('.indepth-rung input[type="radio"]').forEach(function (radio) {
    radio.addEventListener('change', function () {
      paint(evaluate(), true);
    });
  });
})();
