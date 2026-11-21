// 해봄 체험 페이지의 동작.
// 첫 화면에서 비어 있는 폰을 고르면 그 폰이 내 것이 되고(시연 API가 쿠키로 기억합니다), 폰을 쓰는 화면으로 넘어갑니다.
// 폰 화면은 Cuttlefish의 웹 클라이언트를 그대로 끼워 넣은 것입니다(터치, 키보드, 소리, 마이크가 WebRTC로 오갑니다).
// 이 스크립트는 "안내 시작"을 보내고 진행 기록을 받아 옆에 그립니다. 화면을 누르는 것은 보는 사람입니다.
(function () {
  'use strict';
  // 주소에 아이디와 비밀번호를 넣어 연 경우 상대 경로 fetch가 막히므로 절대 주소를 씁니다.
  var API = location.origin + '/haebom/api/';
  var $ = function (id) { return document.getElementById(id); };
  var lobby = $('lobby'), session = $('session'), rack = $('rack'), notice = $('lobby-notice');
  var frame = $('device'), cover = $('device-cover'), coverNote = $('device-note');
  var tasksBox = $('tasks'), stepsBox = $('steps'), runLine = $('run-line'), summary = $('summary');
  var btnStop = $('btn-stop'), btnReset = $('btn-reset'), btnSound = $('btn-sound'), btnMic = $('btn-mic');

  var SOURCE = { manual: '매뉴얼', check: '폰 설정값', model: 'AI', wait: '기다림', rule: '첫 단계' };
  // 시니어가 실제로 할 만한 일을 앞에 둡니다. 나머지 매뉴얼은 그 뒤에 나옵니다.
  var FIRST = ['font-size', 'alarm-8'];
  var HINT = { 'font-size': '설정에서 글자를 한 단계 키웁니다', 'alarm-8': '시계 앱에서 오전 8시 알람을 맞춥니다', 'bluetooth': '설정의 블루투스 화면까지 갑니다' };
  var ENDED = {
    idle: '10분 동안 누른 것이 없어서 폰을 반납했어요. 다시 쓰려면 폰을 골라 주세요.',
    gone: '페이지가 닫혀 있어서 폰을 반납했어요. 다시 쓰려면 폰을 골라 주세요.',
    moved: '다른 폰으로 옮겨서 이 폰은 반납했어요.'
  };

  var view = '';                 // 'lobby' | 'session'
  var timers = { lobby: 0, state: 0, events: 0 };
  var run = -1, after = 0, steps = {}, guideState = 'idle', loaded = '', tasksKey = '', active = true, hooked = null, misses = 0;

  function api(path, body) {
    var opt = body === undefined ? { cache: 'no-store', credentials: 'same-origin' }
      : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    return fetch(API + path, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, body: j }; });
    });
  }
  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
  function seconds(ms) { return ms < 1000 ? ms + 'ms' : (ms / 1000).toFixed(1) + '초'; }
  function say(text) { notice.textContent = text || ''; notice.hidden = !text; }

  // 맨 위의 실시간 표시: 서버에서 상태가 올 때마다 한 번 뜁니다. 닿지 못하면 빨간 점이 됩니다.
  var live = $('live'), liveText = $('live-text');
  function clock() { var d = new Date(); return [d.getHours(), d.getMinutes(), d.getSeconds()].map(function (n) { return (n < 10 ? '0' : '') + n; }).join(':'); }
  function heard(what) {
    live.className = 'live on';
    void live.offsetWidth;                       // restart the beat
    live.className = 'live on pulse';
    liveText.replaceChildren(document.createTextNode(what + ' '), el('b', '', clock()));
  }
  function deaf() { live.className = 'live off'; liveText.textContent = '서버에 닿지 못하고 있어요. 다시 잇는 중'; }

  // ================================================================ 첫 화면: 폰 고르기

  // 폰 목록은 서버가 바뀔 때마다 밀어 줍니다(누가 폰을 고르거나 반납하면 바로). 그 길이 끊겨도 5초마다 다시 읽습니다.
  var feed = null;
  function openFeed() {
    if (feed || !window.EventSource) return;
    feed = new EventSource(API + 'devices/stream');
    feed.onmessage = function (ev) {
      if (view !== 'lobby') return;
      try { drawRack(JSON.parse(ev.data).devices); heard('서버와 실시간 연결'); } catch (e) {}
    };
    feed.onerror = function () { if (view === 'lobby') deaf(); };
  }
  function closeFeed() { if (feed) { feed.close(); feed = null; } }

  // 폰을 쓰는 동안 서버와 연결 하나를 열어 둡니다. 서버는 이 연결이 살아 있는 것으로 "아직 쓰고 있다"를 압니다.
  // 페이지의 타이머가 느려져도(창이 가려지거나 최소화될 때) 잠금이 풀리지 않게 하려는 것입니다. 끊기면 브라우저가 다시 잇습니다.
  var hold = null;
  function openHold() {
    if (hold || !window.EventSource) return;
    hold = new EventSource(API + 'hold');
    hold.onmessage = function (ev) { if (ev.data === 'ended' && view === 'session') { closeHold(); pollState(); } };
  }
  function closeHold() { if (hold) { hold.close(); hold = null; } }

  function showLobby(text) {
    view = 'lobby';
    clearTimeout(timers.state); clearTimeout(timers.events);
    frame.src = 'about:blank'; loaded = ''; hooked = null;   // 폰 화면과의 연결(WebRTC)을 끊습니다
    closeHold();
    session.hidden = true; lobby.hidden = false;
    say(text);
    openFeed();
    pollLobby();
  }

  function drawRack(list) {
    var free = list.filter(function (d) { return d.state === 'idle'; }).length;
    var count = $('lobby-count');
    if (list.some(function (d) { return d.mine; })) count.textContent = '쓰던 폰이 있어요. 이어서 쓰거나 다른 폰을 고를 수 있어요.';
    else if (free) count.replaceChildren(document.createTextNode('폰 ' + list.length + '대 가운데 '), el('b', '', free + '대'), document.createTextNode('가 비어 있어요.'));
    else if (list.some(function (d) { return d.state === 'busy'; })) count.textContent = '지금은 모두 쓰는 중이에요. 자리가 나면 여기에 바로 표시돼요.';
    else count.textContent = '폰이 켜지는 중이에요. 잠시만 기다려 주세요.';

    var nodes = list.map(function (d) {
      var kind = d.mine ? 'mine' : d.state;                    // idle | busy | offline | mine
      var li = el('li', 'slot ' + kind);
      var b = el('button'); b.type = 'button';
      var handset = el('span', 'handset'), glass = el('span', 'glass');
      handset.setAttribute('aria-hidden', 'true');
      glass.append(el('span', 'ring'), el('span', 'busy-mark', '사용 중'), el('span', 'wait-mark')); handset.append(glass);
      var state = kind === 'mine' ? '내가 쓰는 중' : kind === 'idle' ? '비어 있어요'
        : kind === 'busy' ? (d.minutes ? d.minutes + '분째 사용 중' : '방금 사용을 시작했어요') : (d.note || '켜지는 중');
      var act = kind === 'mine' ? '이어서 쓰기' : kind === 'idle' ? '이 폰으로 해 보기' : kind === 'busy' ? '사용 중' : '준비 중';
      b.append(handset, el('span', 'slot-name', '폰 ' + d.n), el('span', 'slot-state', state), el('span', 'slot-act', act));
      b.disabled = !(kind === 'idle' || kind === 'mine');
      b.setAttribute('aria-label', '폰 ' + d.n + ', ' + state + (b.disabled ? '' : ', ' + act));
      b.onclick = function () { claim(d, li); };
      li.append(b);
      return li;
    });
    rack.replaceChildren.apply(rack, nodes);
  }

  function pollLobby() {
    clearTimeout(timers.lobby);
    if (view !== 'lobby') return;
    api('devices').then(function (r) { if (r.ok && view === 'lobby') { drawRack(r.body.devices); heard('서버와 실시간 연결'); } })
      .catch(function () { $('lobby-count').textContent = '체험 서버에 닿지 못하고 있어요.'; deaf(); })
      .finally(function () { timers.lobby = setTimeout(pollLobby, 5000); });
  }

  function claim(d, li) {
    li.classList.add('wait');
    li.querySelector('button').disabled = true;
    li.querySelector('.slot-act').textContent = '폰을 여는 중';
    api('claim', { device: d.id }).then(function (r) {
      if (r.ok) return showSession(r.body);
      say(r.body.error || '폰을 열지 못했어요. 다시 골라 주세요.');
      pollLobby();
    }).catch(function () { say('체험 서버에 닿지 못했어요.'); pollLobby(); });
  }

  // ================================================================ 폰 한 대를 쓰는 화면

  function showSession(mine) {
    view = 'session';
    clearTimeout(timers.lobby);
    closeFeed();
    lobby.hidden = true; session.hidden = false;
    $('bar-phone').textContent = '폰 ' + mine.n;
    $('idle-warn').hidden = true;
    cover.hidden = false; coverNote.textContent = '폰을 여는 중이에요';
    lastFrames = null; showLink('기다리는 중', '–', '–', '–', false);
    run = -1; after = 0; steps = {}; guideState = 'idle'; tasksKey = ''; active = true;
    stepsBox.replaceChildren(); summary.hidden = true;
    runLine.textContent = '아직 시작한 안내가 없어요. 위에서 하나를 골라 보세요.';
    window.scrollTo(0, 0);
    openHold();
    pollState(); pollEvents();
  }

  // 폰이 내 것이 아니게 됐다는 답(410)이 오면 첫 화면으로 돌아가 까닭을 알립니다.
  function lost(r) {
    if (r.status !== 410 || view !== 'session') return false;
    showLobby(ENDED[r.body.reason] || '');
    return true;
  }

  function showState(s) {
    var d = s.device || {};
    $('bar-phone').textContent = '폰 ' + d.n;
    var src = '/devices/' + encodeURIComponent(d.id) + '/files/client.html?embed=1';
    if (d.ready && loaded !== src) { frame.src = src; loaded = src; }
    cover.hidden = !!d.ready;
    coverNote.textContent = d.ready ? '' : (d.preparing ? '폰을 처음 상태로 돌리는 중이에요' : (d.note || '폰을 준비하고 있어요'));

    var left = (s.lease || {}).idle_left;
    var warn = typeof left === 'number' && left <= 60 && d.ready;
    $('idle-warn').hidden = !warn;
    if (warn) $('idle-text').textContent = '누른 것이 없어서 ' + left + '초 뒤에 폰을 반납해요.';

    var health = [
      ['폰', d.online], ['해봄 앱', d.app && d.service],
      ['매뉴얼 서버', s.front && s.front.ok], ['음성 서버', s.tts && s.tts.ok]
    ];
    $('health').replaceChildren.apply($('health'), health.map(function (h) { return el('li', h[1] ? 'ok' : 'bad', h[0] + (h[1] ? ' 준비됨' : ' 준비 안 됨')); }));

    var manuals = (s.front && s.front.manuals) || [];
    var key = manuals.map(function (m) { return m.id; }).join(',') + '|' + !!d.ready;
    if (key !== tasksKey) {
      tasksKey = key;
      manuals.sort(function (a, b) { var x = FIRST.indexOf(a.id), y = FIRST.indexOf(b.id); return (x < 0 ? 99 : x) - (y < 0 ? 99 : y); });
      var nodes = manuals.map(function (m) {
        var label = (m.aliases && m.aliases[0]) || m.task;
        var b = el('button', 'task'); b.type = 'button'; b.disabled = !d.ready;
        var hint = HINT[m.id] || (m.task !== label ? m.task : '');
        b.append(el('span', 't', label));
        if (hint) b.append(el('span', 's', hint));
        b.append(el('span', 'c', '매뉴얼 ' + m.steps + '단계'));
        b.onclick = function () { start(label); };
        return b;
      });
      if (!nodes.length) nodes = [el('p', 'empty', '검증된 매뉴얼이 아직 없어요. 아래에 직접 적으면 AI가 안내합니다.')];
      tasksBox.replaceChildren.apply(tasksBox, nodes);
    }
    document.querySelector('#free button').disabled = !d.ready;
    btnReset.disabled = !d.ready && !btnReset.dataset.busy;

    var p = s.phone || {};
    $('fact-font').textContent = p.font_scale == null ? '–' : (p.font_scale === 1 ? '기본 (1.0)' : p.font_scale + '배');
    $('fact-alarm').textContent = !p.alarms_on ? '–' : (p.alarms_on.length ? p.alarms_on.map(function (t) {
      var h = Number(t.slice(0, 2)); return (h < 12 ? '오전 ' : '오후 ') + (h % 12 || 12) + ':' + t.slice(3);
    }).join(', ') : '없음');
    hookFrame();
  }

  function pollState() {
    clearTimeout(timers.state);
    if (view !== 'session') return;
    var was = active; active = false;
    api('state?active=' + (was ? 1 : 0)).then(function (r) {
      misses = 0; if (lost(r)) return;
      if (r.ok) { showState(r.body); heard('서버와 실시간 연결'); }
    })
      // 한두 번 닿지 못한 것으로 폰 화면을 가리지 않습니다. 폰 화면은 서버와 따로 이어져 있습니다.
      .catch(function () { if (++misses >= 4) { cover.hidden = false; coverNote.textContent = '체험 서버에 닿지 못하고 있어요'; deaf(); } })
      .finally(function () { if (view === 'session') timers.state = setTimeout(pollState, 3000); });
  }

  // 폰 화면 아래의 숫자: 끼워 넣은 폰 화면(같은 주소의 페이지)이 연 WebRTC 연결의 통계를 1초마다 읽습니다.
  // 녹화가 아니라 지금 받고 있는 화면이라는 것을 숫자로 보여 줍니다: 초당 장 수, 해상도, 폰까지의 왕복 시간.
  var link = $('link'), lastFrames = null, lastAt = 0;
  function showLink(state, fps, size, rtt, flowing) {
    $('link-state').textContent = state; $('link-fps').textContent = fps; $('link-size').textContent = size; $('link-rtt').textContent = rtt;
    link.classList.toggle('flowing', !!flowing);
  }
  function readLink() {
    if (view !== 'session') return;
    var pcs; try { pcs = frame.contentWindow && frame.contentWindow.__pcs; } catch (e) { pcs = null; }
    if (!pcs || !pcs.length) { showLink(loaded ? '연결하는 중' : '기다리는 중', '–', '–', '–', false); return; }
    var pc = pcs[pcs.length - 1];
    pc.getStats().then(function (st) {
      var v = null, pair = null;
      st.forEach(function (r) {
        if (r.type === 'inbound-rtp' && r.kind === 'video') v = r;
        if (r.type === 'candidate-pair' && r.nominated && r.state === 'succeeded') pair = r;
      });
      if (!v || !v.framesDecoded) { showLink('연결하는 중', '–', '–', '–', false); return; }
      var now = performance.now(), fps = v.framesPerSecond;
      if (fps == null && lastFrames != null && now > lastAt) fps = (v.framesDecoded - lastFrames) * 1000 / (now - lastAt);
      var moving = lastFrames == null || v.framesDecoded > lastFrames;
      lastFrames = v.framesDecoded; lastAt = now;
      var rtt = pair && pair.currentRoundTripTime != null ? Math.round(pair.currentRoundTripTime * 1000) + 'ms' : '–';
      // 화면이 그대로면 폰은 새 장을 보내지 않습니다. 그때는 0장이어도 연결은 살아 있습니다.
      showLink(pc.connectionState === 'connected' ? '실시간' : '다시 잇는 중', fps != null ? Math.round(fps) + '장' : '–',
        v.frameWidth ? v.frameWidth + '×' + v.frameHeight : '–', rtt, pc.connectionState === 'connected' && (moving || fps === 0));
    }).catch(function () {});
  }
  setInterval(readLink, 1000);

  // 페이지나 폰 화면을 누르거나 키를 치면 "쓰고 있다"고 서버에 알립니다(다음 state 요청에 실어서).
  function touched() { active = true; }
  ['pointerdown', 'keydown', 'wheel'].forEach(function (t) { document.addEventListener(t, touched, { passive: true, capture: true }); });
  function hookFrame() {
    var w; try { w = frame.contentWindow; if (!w || !w.document || w.location.href === 'about:blank') return; } catch (e) { return; }
    if (hooked === w.document) return;
    hooked = w.document;
    ['pointerdown', 'mousedown', 'touchstart', 'keydown', 'wheel'].forEach(function (t) { w.document.addEventListener(t, touched, { passive: true, capture: true }); });
  }
  $('btn-stay').onclick = function () { active = true; $('idle-warn').hidden = true; pollState(); };
  $('btn-leave').onclick = function () {
    $('btn-leave').disabled = true;
    api('release', {}).catch(function () {}).finally(function () { $('btn-leave').disabled = false; showLobby('폰을 반납했어요. 써 주셔서 고맙습니다.'); });
  };

  // ---------------------------------------------------------------- 안내 진행 기록

  function face(name, alt) { var i = el('img'); i.src = 'img/haebomi-' + name + '.png'; i.alt = alt; i.width = 32; i.height = 32; return i; }

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
    var n = li.querySelector('.n');
    if (end) n.replaceChildren(face('done', '다 했어요'));
    else if (s.kind === 'Guide' && !done) n.replaceChildren(face('guide', '안내 중'));
    else n.textContent = done && !minor ? '✓' : s.step;
    li.querySelector('.title').textContent = s.bubble || s.title || s.target || '안내를 준비하는 중';
    var sub = '';
    if (s.kind === 'Guide') sub = s.outcome === 'met' ? '직접 하신 것을 확인했어요' : s.outcome ? '다시 확인하는 중' : '폰 화면에 표시된 곳을 눌러 보세요';
    if (end) sub = s.source === 'check' ? '폰의 실제 값으로 확인했어요' : '';
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
    var head = r.task ? '“' + r.task + '”' : '폰에서 시작한 안내';
    runLine.replaceChildren(el('b', '', head), document.createTextNode(
      r.state === 'running' ? ' 안내 중, ' + Math.round(r.elapsed || 0) + '초' : r.state === 'done' ? ' 끝났어요' : ' 멈췄어요'));
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
    clearTimeout(timers.events);
    if (view !== 'session') return;
    api('events?after=' + after + '&run=' + run).then(function (r) {
      if (lost(r) || !r.ok) return;
      var b = r.body;
      if (b.run !== run) { run = b.run; steps = {}; stepsBox.replaceChildren(); }
      after = b.next;
      b.events.forEach(function (e) { if (e.type === 'step') { drawStep(e); steps[e.step].__s = e; } });
      showRun(b);
    }).catch(function () {}).finally(function () { if (view === 'session') timers.events = setTimeout(pollEvents, guideState === 'running' ? 600 : 1200); });
  }

  // ---------------------------------------------------------------- 버튼

  function start(task) {
    runLine.textContent = '“' + task + '” 요청을 보냈어요…';
    api('start', { task: task }).then(function (r) { if (lost(r)) return; if (!r.ok) runLine.textContent = r.body.error || '시작하지 못했어요.'; })
      .catch(function () { runLine.textContent = '체험 서버에 닿지 못했어요.'; });
  }
  $('free').onsubmit = function (ev) {
    ev.preventDefault();
    var t = $('free-text').value.trim();
    if (t) { start(t); $('free-text').value = ''; }
  };
  btnStop.onclick = function () { api('stop', {}); };
  btnReset.onclick = function () {
    btnReset.disabled = true; btnReset.dataset.busy = '1'; btnReset.textContent = '되돌리는 중…';
    api('reset', {}).catch(function () {}).finally(function () { btnReset.disabled = false; delete btnReset.dataset.busy; btnReset.textContent = '처음 상태로'; });
  };

  // 소리와 마이크는 끼워 넣은 폰 화면(Cuttlefish 웹 클라이언트) 안의 것을 직접 다룹니다. 같은 주소에서 온 페이지라 그 안을 볼 수 있습니다.
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
    if (view !== 'session') return;
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

  // ================================================================ 들어올 때

  // 쓰던 폰이 있으면(새로 고침, 같은 브라우저의 다른 탭) 그 폰으로 바로 돌아갑니다.
  api('devices').then(function (r) {
    var mine = r.ok && r.body.devices.filter(function (d) { return d.mine; })[0];
    if (mine) showSession(mine); else showLobby('');
  }).catch(function () { showLobby(''); });
})();
