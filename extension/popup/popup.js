/* 확장 아이콘을 누르면 뜨는 작은 창: 가닥이 켜져 있는지, 이 탭에서 무엇을 읽었는지, 읽기 켜고 끄기.
   문구는 기획 담당 확인 전이에요 (docs/changes-detail.md 11번). */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var TAB_TEXT = {
    paused: 'Reading is off.',
    nochat: 'Open a chat and it starts reading.',
    wait: 'Reading…',
    off: 'This chat will be sent once Gadak is on.',
    old: 'The running Gadak is an older version. Restart Gadak.',
    empty: 'Could not find the chat text. The site may have changed. Let us know with Copy diagnostics below.'
  };
  var NOT_HERE = 'Try it on a Claude or ChatGPT chat page.';
  var tabId = null;

  function line(el, text, cls) { el.textContent = text; el.className = 'line' + (cls ? ' ' + cls : ''); }

  function showTab(s) {
    if (!s) { line($('tab'), NOT_HERE); $('diag').disabled = true; return; }
    $('diag').disabled = false;
    if (s.status === 'ok') line($('tab'), 'Read ' + s.turns + ' stations from this chat.', 'on');
    else if (s.status === 'error') line($('tab'), 'Gadak did not receive it (' + (s.error || 'unknown') + ').', 'hot');
    else line($('tab'), TAB_TEXT[s.status] || TAB_TEXT.wait, s.status === 'empty' || s.status === 'old' ? 'hot' : '');
  }

  function ask(type, done) {
    if (tabId == null) { done(null); return; }
    chrome.tabs.sendMessage(tabId, { type: type }, function (r) { done(chrome.runtime.lastError ? null : r); });
  }

  chrome.runtime.sendMessage({ type: 'alive' }, function (r) {
    var ok = !chrome.runtime.lastError && r && r.ok;
    line($('app'), ok ? 'Connected to Gadak.' : 'Gadak is off. Turn it on and reading continues.', ok ? 'on' : 'hot');
  });
  chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
    tabId = tabs && tabs[0] ? tabs[0].id : null;
    ask('state', showTab);
  });

  chrome.storage.local.get({ reading: true }, function (saved) { $('reading').checked = saved.reading !== false; });
  $('reading').addEventListener('change', function () {
    chrome.storage.local.set({ reading: $('reading').checked }, function () { setTimeout(function () { ask('state', showTab); }, 300); });
  });

  /* 안 읽힐 때: 화면의 뼈대(태그 · 구조 속성 · 클래스 이름)만 복사해요. 대화 글은 들어 있지 않아요 */
  $('diag').addEventListener('click', function () {
    ask('diag', function (d) {
      if (!d) { $('done').textContent = 'Nothing to read in this tab.'; return; }
      navigator.clipboard.writeText(JSON.stringify(d, null, 1)).then(
        function () { $('done').textContent = 'Copied. It holds only the page structure, no text.'; },
        function () { $('done').textContent = 'Could not copy.'; });
    });
  });
})();
