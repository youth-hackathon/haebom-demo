// Cuttlefish 웹 클라이언트(client.html)에 끼워 넣는 스크립트입니다. nginx가 넣습니다.
//
// 1. 주소에 ?embed=1 이 있으면 시연 페이지 안에 넣어 쓰는 모양으로 바꿉니다: 옆의 조작 버튼 줄과 정보 줄을 숨기고
//    기기 화면만 남깁니다. 소리와 마이크는 시연 페이지의 버튼이 다룹니다(demo.js). 터치, 키보드, 소리, 마이크는
//    그대로 WebRTC로 오갑니다.
// 2. WebRTC 수신 버퍼 조정: ?jb=<ms> 로 값을 바꿔 시험할 수 있습니다. 기본은 조정 없음(off).
// 3. 기기가 알려 주는 연결 주소(ICE candidate)는 컨테이너 안의 주소입니다(127.0.0.1, 172.x). 같은 컴퓨터에서는
//    127.0.0.1로 닿지만 다른 컴퓨터에서는 닿지 않습니다. 그래서 이 페이지를 연 주소의 같은 포트를 하나 더 알려 줍니다.
//    기기의 WebRTC 포트(15550-15599)는 컨테이너가 같은 번호로 밖에 열어 두므로 그 주소로 닿습니다.
(function () {
  var params = new URLSearchParams(location.search);

  if (params.get('embed')) {
    var css = [
      '#control-panel-default-buttons, #control-panel-custom-buttons, .display-control-buttons, .device-display-info { display: none !important; }',
      'html, body { margin: 0 !important; height: 100%; background: #05070c !important; overflow: hidden; }',
      '#device-connection, #controls-and-displays { height: 100%; }',
      '#device-displays { justify-content: center; align-items: center; height: 100%; }',
      '.device-display { margin: 0 !important; }',
      '.device-display-video { border: 0 !important; }'
    ].join('\n');
    var style = document.createElement('style');
    style.textContent = css;
    (document.head || document.documentElement).appendChild(style);
  }

  var DEFAULT_JB = 'off';
  var q = params.get('jb');
  var jb = q === null ? DEFAULT_JB : q;
  var O = window.RTCPeerConnection;
  window.__pcs = [];
  function apply(receiver) {
    if (jb === 'off') return;
    var ms = Number(jb);
    try { receiver.jitterBufferTarget = ms; } catch (e) {}
    try { receiver.playoutDelayHint = ms / 1000; } catch (e) {}
  }
  var host = location.hostname;
  var elsewhere = host !== 'localhost' && host !== '127.0.0.1' && host.indexOf(':') < 0;
  var told = {};
  function here(c) {
    // "candidate:<foundation> <component> <udp|tcp> <priority> <address> <port> typ host ..."
    var f = String((c && c.candidate) || '').split(' ');
    if (f.length < 8 || f[7] !== 'host' || !/^[0-9.]+$/.test(f[4])) return null;
    var key = f[1] + f[2] + f[5];
    if (told[key]) return null;
    told[key] = true;
    f[0] += '9'; f[4] = host;
    return new RTCIceCandidate({ candidate: f.join(' '), sdpMid: c.sdpMid, sdpMLineIndex: c.sdpMLineIndex, usernameFragment: c.usernameFragment });
  }
  window.RTCPeerConnection = function (cfg, c) {
    var pc = new O(cfg, c);
    window.__pcs.push(pc);
    pc.addEventListener('track', function (e) { apply(e.receiver); });
    if (elsewhere) {
      var add = pc.addIceCandidate.bind(pc);
      pc.addIceCandidate = function (cand) {
        var p = add.apply(null, arguments);
        try { var more = here(cand); if (more) add(more).catch(function () {}); } catch (e) {}
        return p;
      };
    }
    return pc;
  };
  window.RTCPeerConnection.prototype = O.prototype;
  window.__haebomJb = jb;
})();
