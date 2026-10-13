/* chatgpt.com 화면 읽기. 사이트가 화면을 바꾸면 이 위쪽 상수만 고치면 돼요.
   10/4: 로그인한 실제 화면에서 아직 확인하지 못했어요. 안 읽히면 팝업의 ‘진단 복사’로 화면의 뼈대를 받아 여기를 고쳐요. */
(function (R) {
  'use strict';
  var SEL = {
    message: '[data-message-author-role]',                          // 메시지 하나. 누구의 말인지와 data-message-id가 붙어 있어요
    userText: '.whitespace-pre-wrap',                               // 질문 글
    aiText: '.markdown',                                            // 답 글
    streaming: '[data-testid="stop-button"], .result-streaming'     // 답이 오는 중
  };
  var ROLE = 'data-message-author-role', MESSAGE_ID = 'data-message-id';
  var CHAT_PATH = /\/c\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\/|$)/;
  var PROJECT_PATH = /\/g\/g-p-[0-9a-f]+-([^/]+)\/c\//;             // 프로젝트 안의 대화: /g/g-p-<id>-<이름>/c/<대화 id>
  var TEMPORARY = /[?&]temporary-chat=true/;                        // 임시 채팅은 읽지 않아요
  var PLAIN_TITLES = ['ChatGPT', 'New chat', '새 채팅'];            // 아직 제목이 없을 때 탭에 보이는 말
  var TITLE_TAIL = /\s[-|]\s*ChatGPT$/;
  var ID_OK = /^[A-Za-z0-9_-]{1,80}$/;

  R.site = {
    name: 'chatgpt',

    chatId: function () {
      if (TEMPORARY.test(location.search)) return null;
      var m = CHAT_PATH.exec(location.pathname);
      return m ? m[1] : null;
    },

    title: function () {
      var t = (document.title || '').replace(TITLE_TAIL, '').trim();
      return !t || PLAIN_TITLES.indexOf(t) >= 0 ? null : t;
    },

    project: function () {
      var m = PROJECT_PATH.exec(location.pathname);
      if (!m) return null;
      try { return decodeURIComponent(m[1]).replace(/-/g, ' ').trim() || null; } catch (e) { return null; }
    },

    /* 화면에 보이는 차례대로. id는 질문 메시지의 것만 써요 (역 하나 = 질문 하나 + 그 답) */
    messages: function () {
      var out = [];
      Array.prototype.forEach.call(document.querySelectorAll(SEL.message), function (el) {
        var role = el.getAttribute(ROLE), id = el.getAttribute(MESSAGE_ID) || '';
        if (role === 'user') out.push({ role: 'user', el: el, id: ID_OK.test(id) ? id : null });
        else if (role === 'assistant') out.push({ role: 'ai', el: el, id: null });
      });
      return out;
    },

    textOf: function (m) {
      var parts = m.el.querySelectorAll(m.role === 'user' ? SEL.userText : SEL.aiText);
      return R.text(parts.length === 1 ? parts[0] : m.el, m.role === 'user');
    },

    streaming: function () { return !!document.querySelector(SEL.streaming); },

    /* 진단: 셀렉터마다 몇 개 찾았는지 (글은 없어요) */
    counts: function () {
      var c = { streaming: this.streaming() };
      ['message', 'userText', 'aiText'].forEach(function (k) { c[k] = document.querySelectorAll(SEL[k]).length; });
      return c;
    }
  };
})(GadakRead);
