
document.documentElement.classList.add('js');
document.querySelectorAll('[data-stepper]').forEach(function (box) {
  var steps = Array.prototype.slice.call(box.querySelectorAll('.step'));
  if (steps.length < 2) return;
  var n = steps.length, i = 0;
  var ctl = document.createElement('div');
  ctl.className = 'stepctl';
  ctl.setAttribute('role', 'group');
  ctl.setAttribute('aria-label', 'Replay the wording, step by step');
  ctl.innerHTML = '<button type="button" data-a="prev">← Previous</button>' +
    '<div class="rangebox"><input type="range" min="0" max="' + (n - 1) + '" value="0" aria-label="Step"><div class="ticks" aria-hidden="true"></div></div>' +
    '<button type="button" data-a="next">Next →</button><span class="pos" aria-live="polite"></span>' +
    '<label><input type="checkbox" data-a="del" checked> show removed words</label>' +
    '<label><input type="checkbox" data-a="all"> show all steps</label>';
  box.insertBefore(ctl, box.firstChild);
  var range = ctl.querySelector('input[type=range]'), pos = ctl.querySelector('.pos'), ticks = ctl.querySelector('.ticks');
  steps.forEach(function (s) { var t = document.createElement('span'); t.className = 't-' + (s.getAttribute('data-kind') || ''); ticks.appendChild(t); });
  var tk = ticks.children;
  function show(k) {
    i = Math.max(0, Math.min(n - 1, k));
    steps.forEach(function (s, j) { s.classList.toggle('cur', j === i); tk[j].classList.toggle('on', j === i); });
    range.value = i;
    pos.textContent = (i === 0 ? 'Start' : 'Step ' + i + ' of ' + (n - 1));
    ctl.querySelector('[data-a=prev]').disabled = i === 0;
    ctl.querySelector('[data-a=next]').disabled = i === n - 1;
  }
  ctl.addEventListener('click', function (ev) {
    var a = ev.target.getAttribute('data-a');
    if (a === 'prev') show(i - 1); else if (a === 'next') show(i + 1);
  });
  range.addEventListener('input', function () { show(parseInt(range.value, 10)); });
  ctl.querySelector('[data-a=del]').addEventListener('change', function (ev) { box.classList.toggle('hide-del', !ev.target.checked); });
  ctl.querySelector('[data-a=all]').addEventListener('change', function (ev) { box.classList.toggle('all', ev.target.checked); });
  show(0);
});
