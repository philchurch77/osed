// Live-preview the band a new risk will score as impact/likelihood are chosen.
// The mapping is not duplicated here: it is rendered into data-matrix from
// review/risk.py, so the page and the server can never disagree.
document.addEventListener('DOMContentLoaded', function () {
  var form = document.querySelector('.risk-add-form');
  if (!form) { return; }

  var preview = document.getElementById('risk-band-preview');
  var impact = form.querySelector('[name="impact"]');
  var likelihood = form.querySelector('[name="likelihood"]');
  if (!preview || !impact || !likelihood) { return; }

  var matrix;
  try {
    matrix = JSON.parse(form.getAttribute('data-matrix') || '{}');
  } catch (e) {
    return;
  }

  function update() {
    var row = matrix[impact.value];
    var cell = row ? row[likelihood.value] : null;
    preview.className = 'risk-preview';
    if (!cell) {
      preview.textContent = '—';
      return;
    }
    preview.textContent = cell.band + ' · ' + cell.rag;
    preview.classList.add('risk-preview--' + cell.css);
  }

  impact.addEventListener('change', update);
  likelihood.addEventListener('change', update);
  update();
});
