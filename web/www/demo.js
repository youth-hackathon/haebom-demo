// 해봄 시연 페이지의 동작.
// 기기 화면은 Cuttlefish의 웹 클라이언트를 그대로 끼워 넣은 것이고(터치, 키보드, 소리, 마이크가 WebRTC로 오갑니다),
// 이 스크립트는 시연 API에 "안내 시작"을 보내고 진행 기록을 받아 옆에 그립니다. 화면을 누르는 것은 보는 사람입니다.
(function () {
  'use strict';
  // 주소에 아이디와 비밀번호를 넣어 연 경우 상대 경로 fetch가 막히므로 절대 주소를 씁니다.
  var API = location.origin + '/haebom/api/';
  var $ = function (id) { return document.getElementById(id); };
  var frame = $('device'), cover = $('device-cover'), coverNote = $('device-note');
  var tasksBox = $('tasks'), stepsBox = $('steps'), runLine = $('run-line'), summary = $('summary');
  var btnStop = $('btn-stop'), btnReset = $('btn-reset'), btnSound = $('btn-sound'), btnMic = $('btn-mic');

  var SOURCE = { manual: '매뉴얼', check: '폰 설정값', model: 'AI', wait: '기다림' };
  // 시니어가 실제로 할 만한 일을 앞에 둡니다. 나머지 매뉴얼은 그 뒤에 나옵니다.
  var FIRST = ['font-size', 'alarm-8'];
  var HINT = { 'font-size': '설정에서 글자를 한 단계 키웁니다', 'alarm-8': '시계 앱에서 오전 8시 알람을 맞춥니다', 'bluetooth': '설정의 블루투스 화면까지 갑니다' };

  var run = -1, after = 0, steps = {}, guideState = 'idle', deviceId = null, deviceReady = false, tasksKey = '';

  function api(path, body) {
    var opt = body === undefined ? { cache: 'no-store' } : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    return fetch(API + path, opt).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); });
  }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
  function seconds(ms) { return ms < 1000 ? ms + 'ms' : (ms / 1000).toFixed(1) + '초'; }

  // ---------------------------------------------------------------- 준비 상태와 고를 일

  function showState(s) {
    var d = s.device || {};
    deviceId = d.id;
    if (d.ready && !deviceReady) frame.src = '/devices/' + encodeURIComponent(d.id) + '/files/client.html?embed=1';
    deviceReady = !!d.ready;
    cover.hidden = deviceReady;
    coverNote.textContent = deviceReady ? '' : (d.note || '기기를 준비하고 있어요');

    var health = [
      ['기기', d.online], ['해봄 앱', d.app && d.service],
      ['매뉴얼 서버', s.front && s.front.ok], ['음성 서버', s.tts && s.tts.ok]
    ];
    $('health').replaceChildren.apply($('health'), health.map(function (h) { return el('li', h[1] ? 'ok' : 'bad', h[0] + (h[1] ? ' 준비됨' : ' 준비 안 됨')); }));

    var manuals = (s.front && s.front.manuals) || [];
    var key = manuals.map(function (m) { return m.id; }).join(',') + '|' + deviceReady;
    if (key !== tasksKey) {
      tasksKey = key;
      manuals.sort(function (a, b) { var x = FIRST.indexOf(a.id), y = FIRST.indexOf(b.id); return (x < 0 ? 99 : x) - (y < 0 ? 99 : y); });
      var nodes = manuals.map(function (m) {
        var label = (m.aliases && m.aliases[0]) || m.task;
        var b = el('button', 'task'); b.type = 'button'; b.disabled = !deviceReady;
        var hint = HINT[m.id] || (m.task !== label ? m.task : '');
        b.append(el('span', 't', label), el('span', 's', (hint ? hint + ' · ' : '') + '매뉴얼 ' + m.steps + '단계'));
        b.onclick = function () { start(label); };
        return b;
      });
      if (!nodes.length) nodes = [el('p', 'empty', '검증된 매뉴얼이 아직 없어요. 아래에 직접 적으면 AI가 안내합니다.')];
      tasksBox.replaceChildren.apply(tasksBox, nodes);
    }
    document.querySelector('#free button').disabled = !deviceReady;

    var p = s.phone || {};
    $('fact-font').textContent = p.font_scale == null ? '–' : (p.font_scale === 1 ? '기본 (1.0)' : p.font_scale + '배');
    $('fact-alarm').textContent = !p.alarms_on ? '–' : (p.alarms_on.length ? p.alarms_on.map(function (t) {
      var h = Number(t.slice(0, 2)); return (h < 12 ? '오전 ' : '오후 ') + (h % 12 || 12) + ':' + t.slice(3);
    }).join(', ') : '없음');
  }

  function pollState() {
    api('state').then(function (r) { if (r.ok) showState(r.body); }).catch(function () {
      cover.hidden = false; coverNote.textContent = '시연 서버에 닿지 못하고 있어요';
    }).finally(function () { setTimeout(pollState, 3000); });
  }

  // ---------------------------------------------------------------- 안내 진행 기록

  function drawStep(s) {
    var li = steps[s.step];
    if (!li) {
      li = steps[s.step] = el('li');
      li.append(el('span', 'n'), el('div', 'what'), el('div', 'who'));
      li.querySelector('.what').append(el('div', 'title'), el('div', 'sub'));
      stepsBox.append(li);
    }
    var minor = s.kind === 'Wait' || s.kind === 'Unaimable';
    var end = s.kind === 'Terminal';
    var done = !!s.outcome || end;
    li.className = minor ? 'minor' : end ? 'end ok' : done ? 'ok' : 'now';
    li.querySelector('.n').textContent = done && !minor ? '✓' : s.step;
    li.querySelector('.title').textContent = s.bubble || s.title || s.target || '안내를 준비하는 중';
    var sub = '';
    if (s.kind === 'Guide') sub = s.outcome === 'met' ? '직접 하신 것을 확인했어요' : s.outcome ? '다시 확인하는 중' : '폰 화면에 표시된 곳을 눌러 보세요';
    if (end) sub = '폰의 실제 값으로 확인했어요';
    li.querySelector('.sub').textContent = sub;
    var who = li.querySelector('.who');
    who.replaceChildren();
    if (s.source) who.append(el('span', 'chip ' + s.source, SOURCE[s.source] || s.source));
    who.append(el('span', 'ms', seconds(s.ms)));
  }

  function showRun(r) {
    guideState = r.state;
    btnStop.hidden = r.state !== 'running';
    if (r.state === 'idle') { runLine.textContent = '아직 시작한 안내가 없어요. 위에서 하나를 골라 보세요.'; summary.hidden = true; return; }
    var head = r.task ? '“' + r.task + '”' : '기기에서 시작한 안내';
    runLine.replaceChildren(el('b', '', head), document.createTextNode(
      r.state === 'running' ? ' 안내 중 · ' + Math.round(r.elapsed || 0) + '초' : r.state === 'done' ? ' 끝났어요' : ' 멈췄어요'));
    if (r.state === 'done') {
      var all = Object.keys(steps).map(function (k) { return steps[k].__s; }).filter(Boolean);
      var count = function (src) { return all.filter(function (s) { return s.source === src; }).length; };
      var last = all[all.length - 1];
      summary.replaceChildren(document.createTextNode('매뉴얼이 ' + count('manual') + '번, AI가 ' + count('model') + '번 답했어요.'),
        el('span', '', last && last.t ? ' 걸린 시간 ' + Math.round(last.t) + '초.' : ''));
      summary.hidden = false;
    } else summary.hidden = true;
  }

  function pollEvents() {
    api('events?after=' + after + '&run=' + run).then(function (r) {
      if (!r.ok) return;
      var b = r.body;
      if (b.run !== run) { run = b.run; steps = {}; stepsBox.replaceChildren(); }
      after = b.next;
      b.events.forEach(function (e) { if (e.type === 'step') { drawStep(e); steps[e.step].__s = e; } });
      showRun(b);
    }).catch(function () {}).finally(function () { setTimeout(pollEvents, guideState === 'running' ? 600 : 1200); });
  }

  // ---------------------------------------------------------------- 버튼

  function start(task) {
    runLine.textContent = '“' + task + '” 요청을 보냈어요…';
    api('start', { task: task }).then(function (r) { if (!r.ok) runLine.textContent = r.body.error || '시작하지 못했어요.'; })
      .catch(function () { runLine.textContent = '시연 서버에 닿지 못했어요.'; });
  }
  $('free').onsubmit = function (ev) {
    ev.preventDefault();
    var t = $('free-text').value.trim();
    if (t) { start(t); $('free-text').value = ''; }
  };
  btnStop.onclick = function () { api('stop', {}); };
  btnReset.onclick = function () {
    btnReset.disabled = true; btnReset.textContent = '되돌리는 중…';
    api('reset', {}).catch(function () {}).finally(function () { btnReset.disabled = false; btnReset.textContent = '처음 상태로'; });
  };

  // 소리와 마이크는 끼워 넣은 기기 화면(Cuttlefish 웹 클라이언트) 안의 것을 직접 다룹니다. 같은 주소에서 온 페이지라 그 안을 볼 수 있습니다.
  // - 소리: 클라이언트의 audio 요소를 재생하거나 멈춥니다. 브라우저는 사람이 한 번 눌러야 소리를 틀게 해 줍니다.
  // - 마이크: 클라이언트의 마이크 버튼은 누르고 있는 동안만 켜집니다(mousedown에 켜고 mouseup에 끔).
  //   켜 둔 채로 쓰도록 "눌림"만 보내 두고, 끌 때 "뗌"을 보냅니다.
  function inner() { try { return frame.contentDocument; } catch (e) { return null; } }
  function audios() { var d = inner(); return d ? Array.prototype.slice.call(d.querySelectorAll('audio.device-audio')) : []; }
  function micButton() { var d = inner(); return d ? d.getElementById('mic_btn') : null; }
  function soundOn() { var a = audios(); return a.length > 0 && a.every(function (x) { return !x.paused && !x.muted; }); }
  function micOn() { var m = micButton(); return !!m && m.textContent.trim() === 'mic'; }
  function press(node, type) { node.dispatchEvent(new frame.contentWindow.MouseEvent(type, { bubbles: true, cancelable: true })); }
  function syncMedia() {
    var a = audios(), m = micButton(), s = soundOn(), on = micOn();
    btnSound.disabled = !a.length; btnSound.textContent = s ? '소리 끄기' : '소리 켜기'; btnSound.setAttribute('aria-pressed', String(s));
    btnMic.disabled = !m || m.disabled || !window.isSecureContext; btnMic.textContent = on ? '마이크 끄기' : '마이크 켜기'; btnMic.setAttribute('aria-pressed', String(on));
    $('mic-hint').hidden = window.isSecureContext;
  }
  btnSound.onclick = function () {
    var on = !soundOn();
    audios().forEach(function (x) { if (on) { x.muted = false; var p = x.play(); if (p) p.catch(function () {}); } else x.pause(); });
    setTimeout(syncMedia, 200);
  };
  btnMic.onclick = function () {
    var m = micButton();
    if (!m) return;
    var on = micOn();
    press(m, 'mouseup');               // 앞서 켜려다 실패한 상태가 남아 있으면 지웁니다
    if (!on) press(m, 'mousedown');
    setTimeout(syncMedia, 300); setTimeout(syncMedia, 1500);
  };
  setInterval(syncMedia, 1000);

  pollState();
  pollEvents();
})();
