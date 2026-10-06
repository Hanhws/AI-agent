/* 판단 기록 페이지. 2단이 돈 턴마다 쓴 도구 · 순서 · 본 것 · 결론을 최근 것부터 보여 줘요 (README 3-1).
   주소에 ?turn=<id>를 붙이면 그 역의 기록만, ?project=<id>면 그 프로젝트만. 가닥이 새로 확인하면 저절로 늘어나요. */
(function () {
  'use strict';
  var G = window.Gadak, el = G.el;
  var params = new URLSearchParams(location.search);
  var S = { turn: params.get('turn'), project: params.get('project') || '', projects: [], rev: -1, sig: null };
  var POLL = 3000;
  var TRIGGER = { missing: '빠진 요청 후보', unasked: '요청 외 변경 후보', handoff: '새 대화' };
  var KIND = { missing: '빠진 요청', unasked: '요청 외 변경', handoff: '이어 가기' };
  var ENDED = { finish: '결론을 냈어요', limit: '걸음 한도에 닿아 멈췄어요', odd: '엔진의 답을 읽지 못해 멈췄어요' };
  var root = document.getElementById('trace');

  function api(path) { return fetch(path).then(function (r) { if (!r.ok) throw new Error(String(r.status)); return r.json(); }); }

  function when(iso) {
    var d = new Date(iso), now = new Date();
    var hm = ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2);
    return (d.toDateString() === now.toDateString() ? '오늘' : (d.getMonth() + 1) + '/' + d.getDate()) + ' ' + hm;
  }
  function argText(step, run) {
    if (step.tool === 'list_open_items') return '';
    if (step.tool === 'search_decisions') return step.arg ? '“' + step.arg + '”' : '최근 것부터';
    return !step.arg || step.arg === run.turn.id ? '이 역' : '역 ' + step.arg;
  }

  function top() {
    var t = el('div', 'top'), brand = el('div', 'brand');
    var mark = G.makeMark(26, 10); brand.appendChild(mark.svg); brand.appendChild(el('b', null, '가닥')); brand.appendChild(el('span', null, '판단 기록'));
    t.appendChild(brand);
    var back = el('a', 'btn sm', '가닥 창으로'); back.href = './'; t.appendChild(back);
    setTimeout(function () { G.playMark(mark); }, 200);
    return t;
  }
  function bar() {
    var b = el('div', 'bar');
    if (S.turn) {
      b.appendChild(el('span', null, '한 역의 기록만 보고 있어요.'));
      var all = el('a', null, '모두 보기'); all.href = 'trace'; b.appendChild(all);
      return b;
    }
    if (S.projects.length < 2) return b;
    var sel = el('select'); sel.setAttribute('aria-label', '프로젝트');
    [['', '모든 프로젝트']].concat(S.projects.map(function (p) { return [p.id, p.name]; })).forEach(function (o) {
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
    var more = el('details'); more.appendChild(el('summary', null, '본 것 펼치기'));
    more.appendChild(el('pre', null, JSON.stringify(step.data, null, 2)));
    more.addEventListener('toggle', function () { more.firstChild.textContent = more.open ? '본 것 접기' : '본 것 펼치기'; });
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
    var why = el('div', 'why'); why.appendChild(el('span', null, '확인한 까닭'));
    run.trigger.forEach(function (t) { why.appendChild(el('span', 'chip', TRIGGER[t] || t)); });
    c.appendChild(why);
    if (run.steps.length) {
      var ol = el('ol', 'steps'); ol.setAttribute('aria-label', '쓴 도구');
      run.steps.forEach(function (s, i) { ol.appendChild(stepItem(s, i, run)); });
      c.appendChild(ol);
    }
    var end = el('div', 'end');
    if (run.think) end.appendChild(el('div', 'think', run.think));
    (run.items || []).forEach(function (it) { end.appendChild(got('todo', KIND[it.kind] || it.kind, it.text)); });
    (run.missing || []).forEach(function (m) { end.appendChild(got('todo', KIND.missing, '“' + m.t + '” 답이 안 왔어요')); });
    (run.dropped || []).forEach(function (d) { end.appendChild(got('drop', '버린 결론', (KIND[d.kind] || d.kind) + ' · ' + d.why)); });
    if (!(run.items || []).length && !(run.missing || []).length) end.appendChild(el('div', 'none', '한마디를 만들지 않았어요.'));
    var meta = ['엔진 호출 ' + run.calls + '번'];
    if (run.engine) meta.push(run.engine + (run.model ? ' · ' + run.model : ''));
    meta.push(ENDED[run.ended] || run.ended);
    end.appendChild(el('div', 'meta', meta.join(' · ')));
    c.appendChild(end);
    return c;
  }

  function render(runs) {
    root.innerHTML = '';
    root.appendChild(top());
    root.appendChild(el('p', 'lead', '빠진 요청이나 요청 외 변경이 의심되는 턴, 새 대화의 첫 턴에서 가닥이 기록을 다시 읽어 확인해요. 어떤 도구를 어떤 순서로 썼고 무엇을 보고 결론 냈는지 여기 남겨요.'));
    root.appendChild(bar());
    if (!runs.length) {
      var e = el('div', 'empty'); e.appendChild(el('b', null, '아직 판단 기록이 없어요.'));
      e.appendChild(el('span', null, '확인할 턴이 오면 가닥이 살펴보고 여기에 남겨요.'));
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
