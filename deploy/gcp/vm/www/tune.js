// Cuttlefish 웹 클라이언트에 끼워 넣는 조정 스크립트(nginx가 client.html에 넣습니다).
// WebRTC 수신 버퍼를 줄여 눌렀을 때의 반응을 빠르게 합니다.
// 주소 뒤에 ?jb=<ms> 를 붙이면 값을 바꿔 시험할 수 있습니다. ?jb=off 는 조정 없음.
(function () {
  var DEFAULT_JB = 'off';
  var q = new URLSearchParams(location.search).get('jb');
  var jb = q === null ? DEFAULT_JB : q;
  var O = window.RTCPeerConnection;
  window.__pcs = [];
  function apply(receiver) {
    if (jb === 'off') return;
    var ms = Number(jb);
    try { receiver.jitterBufferTarget = ms; } catch (e) {}
    try { receiver.playoutDelayHint = ms / 1000; } catch (e) {}
  }
  window.RTCPeerConnection = function (cfg, c) {
    var pc = new O(cfg, c);
    window.__pcs.push(pc);
    pc.addEventListener('track', function (e) { apply(e.receiver); });
    return pc;
  };
  window.RTCPeerConnection.prototype = O.prototype;
  window.__haebomJb = jb;
})();
