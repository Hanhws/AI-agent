/* 화면 읽기 (사이트 공통). 열어 둔 대화가 바뀌면 조금 기다렸다가, 지금 보이는 질문 · 답을 가닥으로 보내요.
   - 보내는 곳은 내 PC의 가닥뿐이에요 (background.js를 거쳐 127.0.0.1:7311). 화면은 읽기만 하고 고치지 않아요.
   - 대화를 처음 읽을 때는 있는 그대로 보내고(지난 턴), 지켜보는 동안 새로 생기거나 바뀐 턴은 fresh로 알려요.
     가닥은 fresh인 턴만 바로 정리하고, 지난 턴은 가닥 창에서 볼 때 정리해요.
   - 답이 오는 중인 마지막 턴은 open으로 한 번 알리고, 다 온 뒤에 한 번 더 보내요.
   가닥이 이 목록을 저장소의 역과 맞추는 방법은 backend/sources/pages.py에 있어요. */
(function () {
  'use strict';
  var R = self.GadakRead, site = R && R.site;
  if (!site || self.__gadakReading) return;
  self.__gadakReading = true;

  var QUIET = 900;          // 화면이 이만큼(ms) 조용하면 읽어요
  var MAX_WAIT = 3000;      // 계속 바뀌는 중이어도 이만큼 지나면 한 번은 읽어요 (새 질문이 바로 보이게)
  var SETTLE = 2500;        // 마지막 답이 이만큼 그대로면 다 온 것으로 봐요
  var DWELL = 1200;         // 주소가 바뀐 뒤 화면이 따라 바뀔 시간
  var HOLD = 8000;          // 주소는 바뀌었는데 화면이 앞 대화 그대로면 이만큼 기다려요
  var RETRY = 20000;        // 가닥이 꺼져 있으면 이만큼 뒤에 다시 물어요
  var URL_EVERY = 800;      // 주소가 바뀌었는지 보는 간격
  var EMPTY_AFTER = 10000;  // 대화 화면인데 이만큼 지나도 글을 못 찾으면 ‘못 찾음’
  var RECENT = 4;           // 끝에서 이만큼의 메시지는 길이가 같아도 내용을 다시 확인해요

  var on = true, dead = false, timer = null, due = 0;
  var changedAt = 0, firstChange = 0, href = location.href;
  var view = null;          // 지금 보고 있는 대화 화면
  var lastPrint = '';       // 마지막으로 읽은 화면의 지문 (주소만 바뀌고 화면은 그대로인 때를 알아보려고)
  var off = false, offUntil = 0, sending = false, again = false;
  var cache = new WeakMap();
  var info = { status: 'wait', turns: 0, sentAt: 0, error: null };

  function plan(ms) {
    if (dead) return;
    var at = Date.now() + ms;
    if (timer && due <= at) return;     // 더 이른 약속이 이미 있어요
    clearTimeout(timer); due = at; timer = setTimeout(tick, ms);
  }

  function stop() { dead = true; clearTimeout(timer); clearInterval(urlTimer); observer.disconnect(); }

  function post(msg, done) {
    try {
      chrome.runtime.sendMessage(msg, function (r) {
        if (chrome.runtime.lastError || !r) done({ ok: false, status: 0 }); else done(r);
      });
    } catch (e) { stop(); }             // 확장을 끄거나 다시 넣으면 이 탭의 읽기는 여기서 끝나요
  }

  /* 메시지의 글. 바뀌지 않은 메시지는 다시 뽑지 않아요 */
  function textOf(m, recent) {
    var raw = m.el.textContent || '', stamp = raw.length + (recent ? ':' + R.sig(raw) : '');
    var c = cache.get(m.el);
    if (c && c.stamp === stamp) return c.text;
    var text = site.textOf(m);
    cache.set(m.el, { stamp: stamp, text: text });
    return text;
  }

  /* 역 하나 = 질문 하나 + 그 뒤의 답들 (docs/schema.md) */
  function collect() {
    var list = site.messages(), turns = [], cur = null;
    list.forEach(function (m, i) {
      var text = textOf(m, i >= list.length - RECENT);
      if (m.role === 'user') { cur = { ref: m.id || null, user: text, ai: '' }; turns.push(cur); }
      else if (cur && text) cur.ai = cur.ai ? cur.ai + '\n\n' + text : text;
    });
    turns = turns.filter(function (t) { return t.user || t.ai; });
    turns.forEach(function (t) {
      t.user = R.fit(t.user); t.ai = R.fit(t.ai);
      t.sig = t.user.length + ':' + t.ai.length + ':' + R.sig(t.ai);
    });
    return turns;
  }

  function tick() {
    timer = null;
    if (dead) return;
    try { read(); } catch (e) { info.status = 'error'; info.error = String(e && e.message || e).slice(0, 120); }
  }

  function read() {
    var now = Date.now();
    if (firstChange && now - changedAt < QUIET && now - firstChange < MAX_WAIT) { plan(QUIET - (now - changedAt)); return; }
    firstChange = 0;
    if (!on) { info.status = 'paused'; return; }
    var chat = site.chatId();
    if (!chat) { view = null; info.status = 'nochat'; info.turns = 0; return; }
    if (!view || view.chat !== chat) view = { chat: chat, since: now, base: null, sent: {}, last: null, accepted: false, tail: null, grewAt: 0, marked: false, refused: 0 };
    if (now - view.since < DWELL) { plan(DWELL - (now - view.since)); return; }
    if (off) {                          // 가닥이 꺼져 있었어요. 켜졌는지만 가볍게 물어봐요
      if (now < offUntil) { plan(offUntil - now); return; }
      post({ type: 'alive' }, function (r) {
        if (r.ok) { off = false; plan(0); } else { offUntil = Date.now() + RETRY; plan(RETRY); }
      });
      return;
    }

    var turns = collect(), growing = site.streaming();
    if (!turns.length) { info.status = 'wait'; info.turns = 0; if (growing) plan(1500); return; }

    // 주소는 새 대화인데 화면이 아직 앞 대화 그대로면 기다려요. 오래도록 그대로면 정말 같은 내용인 거예요
    var print = turns.map(function (t) { return t.ref || t.user.slice(0, 40); }).join('\u0001');
    var stale = !view.accepted && !!lastPrint && print === lastPrint;
    if (stale && now - view.since < HOLD) { info.status = 'wait'; plan(1000); return; }
    view.accepted = true; lastPrint = print;

    // 처음 읽은 것이 기준이에요. 그 뒤에 새로 생기거나 달라진 턴이 fresh
    var first = !view.base, lastBase = -1, last = turns[turns.length - 1];
    if (first) view.base = {};
    turns.forEach(function (t, i) {
      t.k = t.ref || '#' + i;
      if (first) view.base[t.k] = t.sig; else if (t.k in view.base) lastBase = i;
    });
    turns.forEach(function (t, i) {
      if (first) t.fresh = false;
      else if (t.k in view.base) t.fresh = view.base[t.k] !== t.sig;
      else if (i < lastBase) { view.base[t.k] = t.sig; t.fresh = false; }     // 위쪽에 뒤늦게 나타난 지난 턴
      else t.fresh = true;
    });

    // 마지막 답이 아직 오는 중인가: 사이트의 표시가 있거나, 방금까지 글이 자라고 있었거나, 답이 아직 없거나
    if (last.sig !== view.tail) { view.tail = last.sig; view.grewAt = first ? 0 : now; }
    if (first && growing) last.fresh = true;
    if (growing) view.marked = true;    // 이 사이트의 ‘오는 중’ 표시가 듣는다는 뜻이에요. 그러면 표시가 사라질 때 바로 끝으로 봐요
    if (last.fresh && !growing && (!last.ai || (!view.marked && now - view.grewAt < SETTLE))) growing = true;
    if (growing) plan(1500);            // 답이 오는 동안에는 화면이 조용해도 다시 봐요
    var open = growing && last.fresh;

    var v = view, marks = {}, list = [];
    var body = { site: site.name, chat: { id: v.chat, title: site.title(), project: site.project() }, turns: [] };
    if (stale || (v.refused && now - v.since >= HOLD)) body.sure = true;
    turns.forEach(function (t, i) {
      var isOpen = open && i === turns.length - 1;
      var mark = isOpen ? t.user.length + ':open' : t.sig;     // 오는 중인 답은 한 번만 보내요
      marks[t.k] = mark;
      list.push(t.k + '=' + mark + (t.fresh ? '!' : ''));
      body.turns.push({ ref: t.ref, user: t.user, ai: !isOpen && v.sent[t.k] === mark ? null : t.ai, fresh: t.fresh, open: isOpen });
    });
    var all = list.join('\u0001') + '\u0001' + (body.chat.title || '') + '\u0001' + (body.chat.project || '');
    info.turns = turns.length;
    if (all === v.last) { if (info.status !== 'error') info.status = 'ok'; return; }   // 달라진 것이 없어요
    if (sending) { again = true; return; }
    sending = true;
    post({ type: 'page', body: body }, function (r) {
      sending = false;
      if (r.ok) { v.sent = marks; v.last = all; info.status = 'ok'; info.sentAt = Date.now(); info.error = null; }
      else if (r.status === 0 || r.status === 404) {       // 가닥이 꺼져 있거나, 받는 길이 없는 예전 가닥이에요
        off = true; offUntil = Date.now() + RETRY; info.status = r.status ? 'old' : 'off'; plan(RETRY);
      }
      else if (r.status === 409) { v.refused++; info.status = 'wait'; plan(2000); }   // 가닥이 보기에 아직 앞 대화예요
      else { v.last = all; info.status = 'error'; info.error = 'HTTP ' + r.status; }   // 같은 것을 다시 보내지 않아요
      if (again) { again = false; plan(0); }
    });
  }

  /* 팝업이 물어보는 것: 이 탭의 상태와, 안 읽힐 때 고치는 데 쓸 화면의 뼈대 */
  function report() {
    var s = on ? info.status : 'paused';
    if (s === 'wait' && view && !info.turns && Date.now() - view.since > EMPTY_AFTER) s = 'empty';
    return { site: site.name, status: s, turns: info.turns, sentAt: info.sentAt, error: info.error };
  }
  function shape(path) {                // 주소의 모양만. 대화 id와 프로젝트 이름은 빼요
    return path.split('/').map(function (p) {
      if (/^[0-9a-f]{8}-[0-9a-f-]{27}$/.test(p)) return ':id';
      if (/^g-p-/.test(p)) return ':project';
      return p.length > 20 ? ':x' : p;
    }).join('/');
  }
  function diag() {
    return {
      gadak: chrome.runtime.getManifest().version, site: site.name, page: shape(location.pathname),
      chat: !!site.chatId(), state: report(), counts: site.counts(),
      outline: R.outline(document.querySelector('main') || document.body, 260)
    };
  }
  chrome.runtime.onMessage.addListener(function (msg, sender, reply) {
    if (!msg || sender.id !== chrome.runtime.id) return;
    if (msg.type === 'state') reply(report());
    else if (msg.type === 'diag') reply(diag());
  });

  var observer = new MutationObserver(function () {
    changedAt = Date.now();
    if (!firstChange) firstChange = changedAt;
    plan(QUIET);
  });
  observer.observe(document.documentElement, {
    childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['data-is-streaming']
  });
  var urlTimer = setInterval(function () {      // 대화를 바꿔도 페이지는 새로 열리지 않아요. 주소를 봐요
    if (location.href !== href) { href = location.href; plan(DWELL); }
  }, URL_EVERY);

  /* 팝업의 ‘대화 읽기’를 끄면 읽지 않아요 */
  try {
    chrome.storage.local.get({ reading: true }, function (saved) { on = !saved || saved.reading !== false; plan(0); });
    chrome.storage.onChanged.addListener(function (changes, area) {
      if (area !== 'local' || !changes.reading) return;
      on = changes.reading.newValue !== false;
      if (on) plan(0); else info.status = 'paused';
    });
  } catch (e) { plan(0); }
})();
