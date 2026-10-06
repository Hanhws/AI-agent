/* 확장의 ‘화면 읽기’를 크롬에서 돌려 보는 틀 (tests/test_extension.py가 띄워요).
   chrome.* 를 흉내 내서, 읽는 쪽(extension/content/)이 가닥으로 무엇을 보내려 하는지만 모아요.
   화면은 내가 아는 대로 흉내 낸 것이고 대화는 전부 만든 것이에요. 실제 사이트 화면이 맞는지는 여기서 알 수 없어요. */
var H = (function () {
  'use strict';
  var t0 = Date.now(), posts = [], tries = 0, listeners = [], storeListeners = [], errors = [], checks = [];
  var state = { mode: 'on', reading: true };   // mode: on(받음) · off(가닥이 꺼짐) · refuse(가닥이 ‘다른 대화’라며 안 받음)
  function now() { return Date.now() - t0; }
  window.addEventListener('error', function (e) { errors.push(String(e.message)); });

  window.chrome = {
    runtime: {
      id: 'gadak-test', lastError: null,
      getManifest: function () { return { version: '0.0.0' }; },
      sendMessage: function (msg, done) {
        var reply = null;
        if (msg.type === 'alive') reply = { ok: state.mode !== 'off' };
        else if (msg.type === 'page') {
          tries++;
          if (state.mode === 'off') reply = { ok: false, status: 0, data: null };
          else if (state.mode === 'refuse' && !msg.body.sure) reply = { ok: false, status: 409, data: null };
          else { posts.push({ at: now(), body: JSON.parse(JSON.stringify(msg.body)) }); reply = { ok: true, status: 200, data: {} }; }
        }
        setTimeout(function () { done(reply); }, 5);
      },
      onMessage: { addListener: function (f) { listeners.push(f); } }
    },
    storage: {
      local: { get: function (defaults, done) { setTimeout(function () { done({ reading: state.reading }); }, 0); } },
      onChanged: { addListener: function (f) { storeListeners.push(f); } }
    }
  };

  function load(files, then) {
    (function next(i) {
      if (i === files.length) { if (then) then(); return; }
      var s = document.createElement('script'); s.src = files[i];
      s.onload = function () { next(i + 1); };
      s.onerror = function () { errors.push('못 불러옴: ' + files[i]); next(i + 1); };
      document.head.appendChild(s);
    })(0);
  }
  function at(ms, fn) { setTimeout(function () { try { fn(); } catch (e) { errors.push(ms + 'ms: ' + e.message); } }, ms); }
  function ask(type) {      // 팝업이 묻는 것처럼
    var out = null;
    listeners.forEach(function (f) { f({ type: type }, { id: 'gadak-test' }, function (r) { out = r; }); });
    return out;
  }
  function setReading(v) { state.reading = v; storeListeners.forEach(function (f) { f({ reading: { newValue: v } }, 'local'); }); }
  function check(name, ok, detail) {
    checks.push({ name: name, ok: !!ok, detail: ok ? '' : JSON.stringify(detail === undefined ? null : detail).slice(0, 900) });
  }
  function eq(name, got, want) { check(name, JSON.stringify(got) === JSON.stringify(want), { got: got, want: want }); }
  function brief(post) {    // 보낸 것 하나를 견주기 쉽게
    var b = post.body;
    return { chat: b.chat.id, title: b.chat.title, project: b.chat.project, sure: b.sure === true,
      turns: b.turns.map(function (t) { return [t.ref, t.user, t.ai, t.fresh, t.open]; }) };
  }
  function finish() {
    var pre = document.createElement('pre'); pre.id = 'result';
    pre.textContent = JSON.stringify({ checks: checks, errors: errors, posts: posts.length, tries: tries, at: posts.map(function (p) { return p.at; }) });
    document.body.appendChild(pre);
  }
  return { load: load, at: at, ask: ask, setReading: setReading, check: check, eq: eq, brief: brief, finish: finish,
    posts: posts, state: state, now: now, tries: function () { return tries; } };
})();
