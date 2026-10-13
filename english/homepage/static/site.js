/* 가닥 배포 사이트의 움직임: 낮 · 밤 스위치, 내 컴퓨터에 맞는 받기 버튼, 왼쪽 세로 노선(지금 보는 구간),
   기능 목록 접고 펴기, 데모 창 크기 맞추기, 확인 값 복사. 스크립트가 꺼져 있어도 글과 받기 주소는 그대로 보여요. */
(function () {
  'use strict';
  var G = window.GADAK || {};
  var root = document.documentElement;
  var reduce = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  function all(sel, from) { return Array.prototype.slice.call((from || document).querySelectorAll(sel)); }

  /* ---------- 낮 · 밤: 고른 것은 이 브라우저에 남고(gadak.theme), 고르지 않았으면 시스템 설정을 따라가요.
     데모 창(같은 주소의 가닥 창)도 같은 값을 읽어서 함께 바뀌어요 ---------- */
  var sw = document.getElementById('theme');
  function isDark() { return root.dataset.theme ? root.dataset.theme === 'dark' : !!(window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches); }
  function syncTheme() { if (sw) sw.setAttribute('aria-checked', String(isDark())); }
  if (sw) {
    sw.addEventListener('click', function () {
      var next = isDark() ? 'light' : 'dark';
      if (!reduce) { root.classList.add('theming'); setTimeout(function () { root.classList.remove('theming'); }, 500); }
      root.dataset.theme = next;
      try { localStorage.setItem('gadak.theme', next); } catch (e) {}
      syncTheme();
    });
    if (window.matchMedia) { var mq = matchMedia('(prefers-color-scheme: dark)'); if (mq.addEventListener) mq.addEventListener('change', syncTheme); }
    syncTheme();
  }

  /* ---------- 내 컴퓨터: Mac인지 Windows인지, Mac이면 Apple Silicon인지 Intel인지 ---------- */
  function detect() {
    var ua = navigator.userAgent || '', uad = navigator.userAgentData;
    var p = (uad && uad.platform) || navigator.platform || '';
    if (/Android|iPhone|iPad|iPod/i.test(ua) || (/Mac/i.test(p) && navigator.maxTouchPoints > 1)) return 'mobile';
    if (/Win/i.test(p) || /Windows/i.test(ua)) return 'win';
    if (/Mac/i.test(p) || /Macintosh/i.test(ua)) return 'mac';
    return 'other';
  }
  /* Mac의 칩은 브라우저가 잘 알려 주지 않아요. 알 수 있을 때만 알려요(크롬 계열은 직접, 그 밖에는 그래픽 장치 이름으로 짐작) */
  function macChip(done) {
    var uad = navigator.userAgentData;
    if (uad && uad.getHighEntropyValues) {
      uad.getHighEntropyValues(['architecture']).then(function (v) { done(v.architecture === 'arm' ? 'arm' : v.architecture === 'x86' ? 'intel' : guess()); }, function () { done(guess()); });
    } else done(guess());
    function guess() {
      try {
        var gl = document.createElement('canvas').getContext('webgl'), ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
        var name = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : '';
        if (/Apple M\d/i.test(name)) return 'arm';
        if (/Intel|AMD|Radeon|NVIDIA/i.test(name)) return 'intel';
      } catch (e) {}
      return null;
    }
  }
  var os = detect();
  root.dataset.os = os;

  // 첫 화면의 받기 버튼: ‘macOS용 받기’처럼 바꾸고 받기 쪽의 그 자리로 보내요
  all('[data-get]').forEach(function (a) {
    if (os !== 'mac' && os !== 'win') return;
    var label = a.querySelector('[data-get-label]');
    if (label && G.getFor && G.os) label.textContent = G.getFor.replace('{os}', G.os[os]);
    a.setAttribute('href', G.download + '#' + os);
  });
  all('[data-get-note]').forEach(function (note) {
    var text = os === 'mobile' ? note.getAttribute('data-mobile') : (os === 'mac' || os === 'win') ? note.getAttribute('data-detected') : '';
    if (text) { note.textContent = text; note.hidden = false; }
  });

  // 받기 쪽: 내 컴퓨터의 칸을 맨 위로 올리고 표시해요
  var mine = document.querySelector('.os[data-os="' + os + '"]');
  function badge(target) {
    if (!target || target.querySelector('.badge')) return;
    var b = document.createElement('span'); b.className = 'badge'; b.textContent = G.detected || '';
    target.appendChild(b);
  }
  if (mine) {
    mine.classList.add('mine');
    badge(mine.querySelector('h2'));
    if (os === 'win') { var setup = mine.querySelector('.file[data-file="win-setup"]'); if (setup) setup.classList.add('mine'); }
    if (os === 'mac') macChip(function (chip) {
      var card = chip && mine.querySelector('.file[data-file="' + (chip === 'arm' ? 'mac-arm64' : 'mac-x86_64') + '"]');
      if (card) { card.classList.add('mine'); badge(card.querySelector('h3')); }
    });
  }

  /* ---------- 왼쪽 세로 노선: 구간마다 역 하나. 지나온 구간은 검은 선, 지금 보는 구간은 빨간 점 ---------- */
  var rail = document.getElementById('rail');
  var secs = all('section[data-station]');
  if (rail && secs.length) {
    var ol = document.createElement('ol');
    var stops = secs.map(function (s) {
      var li = document.createElement('li'), a = document.createElement('a');
      a.href = '#' + s.id; a.textContent = s.getAttribute('data-station');
      li.appendChild(a); ol.appendChild(li);
      return li;
    });
    rail.appendChild(ol);
    var navLinks = all('.nav a'), waiting = false;
    var place = function () {
      waiting = false;
      var mark = window.innerHeight * 0.42, cur = -1;
      secs.forEach(function (s, i) { if (s.getBoundingClientRect().top <= mark) cur = i; });
      stops.forEach(function (li, i) { li.classList.toggle('past', i < cur); li.classList.toggle('now', i === cur); if (i === cur) li.firstChild.setAttribute('aria-current', 'true'); else li.firstChild.removeAttribute('aria-current'); });
      ol.style.setProperty('--done', cur < 0 ? 0 : secs.length > 1 ? cur / (secs.length - 1) : 1);
      var id = cur < 0 ? '' : secs[cur].id;
      navLinks.forEach(function (a) { if (id && a.getAttribute('href').split('#')[1] === id) a.setAttribute('aria-current', 'true'); else a.removeAttribute('aria-current'); });
    };
    var ask = function () { if (!waiting) { waiting = true; requestAnimationFrame(place); } };
    window.addEventListener('scroll', ask, { passive: true });
    window.addEventListener('resize', ask);
    place();
  }

  /* ---------- 기능: 하나를 펴면 나머지는 접히고, 오른쪽 그림이 따라 바뀌어요 ---------- */
  var feat = document.getElementById('feat');
  if (feat) {
    var items = all('.feat-item', feat), figs = all('.feat-media figure', feat);
    items.forEach(function (item) {
      item.querySelector('button').addEventListener('click', function () {
        if (item.classList.contains('is-open')) return;
        items.forEach(function (other) {
          var on = other === item;
          other.classList.toggle('is-open', on);
          other.querySelector('button').setAttribute('aria-expanded', String(on));
        });
        figs.forEach(function (f) { f.classList.toggle('on', f.getAttribute('data-feat') === item.getAttribute('data-feat')); });
      });
    });
  }

  /* ---------- 데모 창: 가닥 창(1440 × 900)을 통째로 줄여 넣어요. 보일 때쯤 불러와요 ---------- */
  var body = document.getElementById('demo-body'), frame = document.getElementById('demo-frame');
  if (body && frame) {
    var W = 1440, H = 900;
    frame.style.width = W + 'px'; frame.style.height = H + 'px';
    var fit = function () {
      var k = body.clientWidth / W;
      if (!k) return;
      frame.style.transform = 'scale(' + k + ')';
      body.style.height = Math.round(H * k) + 'px';
    };
    var load = function () { if (!frame.getAttribute('src') && body.clientWidth) frame.setAttribute('src', frame.getAttribute('data-src')); };
    window.addEventListener('resize', function () { fit(); if (near) load(); });
    var near = false;
    if ('IntersectionObserver' in window) new IntersectionObserver(function (seen) { if (seen[0].isIntersecting) { near = true; fit(); load(); } }, { rootMargin: '600px 0px' }).observe(body.parentNode);
    else { near = true; load(); }
    fit();
  }

  /* ---------- 데모 쪽: 가닥 창 · 전체 지도 ---------- */
  var tabs = all('.demo-tabs button');
  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      tabs.forEach(function (other) {
        var on = other === tab, pane = document.getElementById(other.getAttribute('aria-controls'));
        other.setAttribute('aria-selected', String(on));
        if (pane) { pane.hidden = !on; if (on && !pane.getAttribute('src')) pane.setAttribute('src', pane.getAttribute('data-src')); }
      });
    });
  });

  // 전체 지도의 ‘닫기’나 노선을 누르면 가닥 창으로 돌아와요 (가닥 앱에서는 가닥 창이 이 말을 받아요)
  if (tabs.length) {
    var back = function () { tabs[0].click(); };
    window.gadakMapClose = back;
    window.addEventListener('message', function (e) { if (e.origin === location.origin && e.data && (e.data.gadakMap === 'close' || e.data.gadakOpen)) back(); });
  }

  /* ---------- 확인 값 복사 ---------- */
  all('[data-copy]').forEach(function (button) {
    var label = button.textContent;
    button.addEventListener('click', function () {
      var text = button.getAttribute('data-copy'), ok = function () { button.textContent = button.getAttribute('data-done') || label; setTimeout(function () { button.textContent = label; }, 1600); };
      var pick = function () {          // 복사가 막힌 곳에서는 글을 골라 줘요 (⌘C · Ctrl+C로 복사)
        var hash = button.parentNode.querySelector('.hash');
        if (hash && window.getSelection) { var r = document.createRange(); r.selectNodeContents(hash); var s = getSelection(); s.removeAllRanges(); s.addRange(r); }
      };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(ok, pick); else pick();
    });
  });
})();
