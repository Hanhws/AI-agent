/* 판단 기록 페이지. 2단이 돈 턴마다 쓴 도구 · 순서 · 본 것 · 결론을 최근 것부터 보여 줘요 (README 3-1).
   주소에 ?turn=<id>를 붙이면 그 역의 기록만, ?project=<id>면 그 프로젝트만. 가닥이 새로 확인하면 저절로 늘어나요. */
(function () {
  'use strict';
  var G = window.Gadak, el = G.el;
  var params = new URLSearchParams(location.search);
  var S = { turn: params.get('turn'), project: params.get('project') || '', projects: [], rev: -1, sig: null };
  var POLL = 3000;
  var TRIGGER = { missing: 'Possible missed request', unasked: 'Possible unrequested change', handoff: 'New chat', ahead: 'Looking ahead' };
  var KIND = { missing: 'Missed request', unasked: 'Unrequested change', handoff: 'Carry on', next: 'Next step' };
  // 앞길 살피기(backend/agent/ahead.py): 살핀 까닭과 길의 종류
  var AHEAD_WHY = { decided: 'You just decided something', stage: 'The section changed', asked: 'You asked what to do next', button: 'You pressed Look ahead' };
  var PATH = { onward: 'Carry on', other: 'Another way', check: 'Prepare first' };
  var ENDED = { finish: 'Reached a conclusion', limit: 'Stopped at the step limit', odd: 'Stopped: could not read the engine’s answer' };
  var root = document.getElementById('trace');

  function api(path) { return fetch(path).then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); }); }

  function when(iso) {
    var d = new Date(iso), now = new Date();
    var hm = ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
    return (d.toDateString() === now.toDateString() ? 'Today' : (d.getMonth() + 1) + '/' + d.getDate()) + ' ' + hm;
  }
  function argText(step, run) {
    if (step.tool === 'list_open_items') return '';
    if (step.tool === 'search_decisions') return step.arg ? '“' + step.arg + '”' : 'newest first';
    if (step.tool === 'search_turns' || step.tool === 'search_files' || step.tool === 'look_up') return step.arg ? '“' + step.arg + '”' : '';
    if (step.tool === 'list_files' || step.tool === 'read_file') return step.arg || '';
    return !step.arg || step.arg === run.turn.id ? 'this station' : 'station ' + step.arg;
  }

  function top() {
    var t = el('div', 'top'), brand = el('div', 'brand');
    var mark = G.makeMark(26, 10); brand.appendChild(mark.svg); brand.appendChild(el('b', null, 'Gadak')); brand.appendChild(el('span', null, 'Decision trace'));
    t.appendChild(brand);
    var back = el('a', 'btn sm', 'Back to Gadak'); back.href = './'; t.appendChild(back);
    setTimeout(function () { G.playMark(mark); }, 200);
    return t;
  }
  function bar() {
    var b = el('div', 'bar');
    if (S.turn) {
      b.appendChild(el('span', null, 'Showing the trace for one station only.'));
      var all = el('a', null, 'Show all'); all.href = 'trace'; b.appendChild(all);
      return b;
    }
    if (S.projects.length < 2) return b;
    var sel = el('select'); sel.setAttribute('aria-label', 'Project');
    [['', 'All projects']].concat(S.projects.map(function (p) { return [p.id, p.name]; })).forEach(function (o) {
      var op = el('option', null, o[1]); op.value = o[0]; if (o[0] === S.project) op.selected = true; sel.appendChild(op);
    });
    sel.onchange = function () { S.project = sel.value; S.sig = null; load(); };
    b.appendChild(sel);
    return b;
  }

  function stepItem(step, i, run) {
    var li = el('li');
    li.appendChild(el('span', 'no', String(i + 1)));
    var what = el('div', 'what');
    what.appendChild(el('b', null, step.label));
    what.appendChild(el('code', null, step.tool + (argText(step, run) ? ' · ' + argText(step, run) : '')));
    what.appendChild(el('span', 'saw', step.saw));
    li.appendChild(what);
    if (step.think) li.appendChild(el('div', 'think', step.think));
    var more = el('details'); more.appendChild(el('summary', null, 'Show what it looked at'));
    more.appendChild(el('pre', null, JSON.stringify(step.data, null, 2)));
    more.addEventListener('toggle', function () { more.firstChild.textContent = more.open ? 'Hide what it looked at' : 'Show what it looked at'; });
    li.appendChild(more);
    return li;
  }
  function got(cls, kind, text) {
    var d = el('div', 'got' + (cls ? ' ' + cls : ''));
    d.appendChild(el('span', 'mk')); d.appendChild(el('span', 'k', kind)); d.appendChild(el('span', null, text));
    return d;
  }
  function runCard(run) {
    var c = el('article', 'run');
    var h = el('div', 'head');
    h.appendChild(el('b', null, run.turn.n + ' · ' + run.turn.title));
    h.appendChild(el('small', null, (run.turn.chat || '') + ' · ' + when(run.at)));
    c.appendChild(h);
    var why = el('div', 'why'); why.appendChild(el('span', null, 'Why it checked'));
    run.trigger.forEach(function (t) { why.appendChild(el('span', 'chip', TRIGGER[t] || t)); });
    if (run.why) why.appendChild(el('span', null, AHEAD_WHY[run.why] || run.why));
    c.appendChild(why);
    if (run.goal) { var goal = el('div', 'think'); goal.textContent = 'Where it thinks you are heading · ' + run.goal; c.appendChild(goal); }
    if (run.steps.length) {
      var ol = el('ol', 'steps'); ol.setAttribute('aria-label', 'Tools used');
      run.steps.forEach(function (s, i) { ol.appendChild(stepItem(s, i, run)); });
      c.appendChild(ol);
    }
    var end = el('div', 'end');
    if (run.think) end.appendChild(el('div', 'think', run.think));
    (run.items || []).forEach(function (it) { end.appendChild(got('todo', KIND[it.kind] || it.kind, it.text)); });
    (run.missing || []).forEach(function (m) { end.appendChild(got('todo', KIND.missing, 'No answer to “' + m.t + '”')); });
    (run.dropped || []).forEach(function (d) { end.appendChild(got('drop', 'Dropped conclusion', (KIND[d.kind] || PATH[d.kind] || d.kind) + ' · ' + d.why)); });
    if (!(run.items || []).length && !(run.missing || []).length) end.appendChild(el('div', 'none', 'Raised nothing.'));
    var meta = [run.calls + ' engine calls'];
    if (run.engine) meta.push(run.engine + (run.model ? ' · ' + run.model : ''));
    meta.push(ENDED[run.ended] || run.ended);
    end.appendChild(el('div', 'meta', meta.join(' · ')));
    c.appendChild(end);
    return c;
  }

  function render(runs) {
    root.innerHTML = '';
    root.appendChild(top());
    root.appendChild(el('p', 'lead', 'On turns that may have a missed request or an unrequested change, and on the first turn of a new chat, Gadak rereads the record to check. Turns where it looked ahead are kept here too. You can see which tools it used, in what order, and what it looked at before concluding.'));
    root.appendChild(bar());
    if (!runs.length) {
      var e = el('div', 'empty'); e.appendChild(el('b', null, 'No decision trace yet.'));
      e.appendChild(el('span', null, 'When a turn needs checking, Gadak looks into it and leaves the record here.'));
      root.appendChild(e); return;
    }
    runs.forEach(function (r) { root.appendChild(runCard(r)); });
  }

  function load() {
    var path = S.turn ? 'turns/' + encodeURIComponent(S.turn) + '/trace' : 'runs' + (S.project ? '?project=' + encodeURIComponent(S.project) : '');
    return api(path).then(function (d) {
      var sig = d.runs.map(function (r) { return r.id; }).join(',');
      if (sig === S.sig) return;
      S.sig = sig; render(d.runs);
    });
  }
  function tick() {
    return api('status').then(function (s) { if (s.rev !== S.rev) { S.rev = s.rev; return load(); } }, function () {});
  }

  api('projects').then(function (d) { S.projects = d.projects; }, function () {}).then(load).then(function () {
    setInterval(tick, POLL);
  }, function () { render([]); });
})();
