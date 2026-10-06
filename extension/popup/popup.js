/* 확장 아이콘을 누르면 뜨는 작은 창: 가닥이 켜져 있는지, 이 탭에서 무엇을 읽었는지, 읽기 켜고 끄기.
   문구는 기획 담당 확인 전이에요 (docs/changes-detail.md 11번). */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var TAB_TEXT = {
    paused: '읽기를 꺼 뒀어요.',
    nochat: '대화를 열면 읽기 시작해요.',
    wait: '읽는 중이에요…',
    off: '가닥이 켜지면 이 대화를 보내요.',
    old: '켜져 있는 가닥이 예전 것이에요. 가닥을 껐다 켜 주세요.',
    empty: '대화 글을 찾지 못했어요. 사이트 화면이 바뀐 것 같아요. 아래 ‘진단 복사’로 알려 주세요.'
  };
  var NOT_HERE = 'Claude · ChatGPT 대화 화면에서 눌러 보세요.';
  var tabId = null;

  function line(el, text, cls) { el.textContent = text; el.className = 'line' + (cls ? ' ' + cls : ''); }

  function showTab(s) {
    if (!s) { line($('tab'), NOT_HERE); $('diag').disabled = true; return; }
    $('diag').disabled = false;
    if (s.status === 'ok') line($('tab'), '이 대화에서 역 ' + s.turns + '개를 읽었어요.', 'on');
    else if (s.status === 'error') line($('tab'), '가닥이 받지 못했어요 (' + (s.error || '알 수 없음') + ').', 'hot');
    else line($('tab'), TAB_TEXT[s.status] || TAB_TEXT.wait, s.status === 'empty' || s.status === 'old' ? 'hot' : '');
  }

  function ask(type, done) {
    if (tabId == null) { done(null); return; }
    chrome.tabs.sendMessage(tabId, { type: type }, function (r) { done(chrome.runtime.lastError ? null : r); });
  }

  chrome.runtime.sendMessage({ type: 'alive' }, function (r) {
    var ok = !chrome.runtime.lastError && r && r.ok;
    line($('app'), ok ? '가닥에 연결됐어요.' : '가닥이 꺼져 있어요. 켜면 이어서 읽어요.', ok ? 'on' : 'hot');
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
      if (!d) { $('done').textContent = '이 탭에서는 읽을 것이 없어요.'; return; }
      navigator.clipboard.writeText(JSON.stringify(d, null, 1)).then(
        function () { $('done').textContent = '복사했어요. 글은 없고 화면의 뼈대만 있어요.'; },
        function () { $('done').textContent = '복사하지 못했어요.'; });
    });
  });
})();
