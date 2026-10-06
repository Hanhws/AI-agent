/* 백엔드와 통신. 확장이 무엇인가를 보내는 곳은 내 PC의 가닥(127.0.0.1:7311) 하나뿐이에요.
   대화 화면을 읽는 쪽(content/)은 다른 사이트 안에서 돌아서 내 PC로 바로 보낼 수 없어요. 여기를 거쳐요. */
'use strict';

var GADAK = 'http://127.0.0.1:7311';
var VERSION = chrome.runtime.getManifest().version;
var CHECK_EVERY = 60000;   // 그 자리에 있는 것이 가닥인지 다시 확인하는 간격(ms)
var checked = 0, alive = false;

function call(path, body) {
  var opt = { headers: { 'X-Gadak-Extension': VERSION } };
  if (body) { opt.method = 'POST'; opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body); }
  return fetch(GADAK + path, opt).then(function (r) {
    return r.json().then(function (d) { return d; }, function () { return null; })
      .then(function (data) { return { ok: r.ok, status: r.status, data: data }; });
  }, function () { return { ok: false, status: 0, data: null }; });   // 가닥이 꺼져 있어요
}

/* 그 포트에서 듣는 것이 가닥일 때만 대화를 보내요 (다른 프로그램이 같은 포트를 쓰고 있을 수 있어요) */
function isGadak(force) {
  if (!force && alive && Date.now() - checked < CHECK_EVERY) return Promise.resolve(true);
  return call('/health').then(function (r) {
    checked = Date.now(); alive = !!(r.ok && r.data && r.data.app === 'gadak');
    return alive;
  });
}

chrome.runtime.onMessage.addListener(function (msg, sender, reply) {
  if (!msg || sender.id !== chrome.runtime.id) return;
  if (msg.type === 'alive') { isGadak(true).then(function (ok) { reply({ ok: ok }); }); return true; }
  if (msg.type === 'page') {
    isGadak(false).then(function (ok) {
      if (!ok) return { ok: false, status: 0, data: null };
      return call('/pages', msg.body).then(function (r) { if (r.status === 0) alive = false; return r; });
    }).then(reply);
    return true;   // 답을 나중에 보내요
  }
});
