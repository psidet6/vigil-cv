const DISPATCH_STATE = {
  auth: null,
  items: [],
  selected: new Set(),
  currentId: '',
  history: { dispatch_records: [], sms_records: [] },
  defaults: {
    sms_mobile: '',
    sms_template: '',
    ywfzr: '',
    ywfzrlxdh: ''
  }
};

function dispatchEscapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function dispatchFormatTs(ts) {
  var value = Number(ts || 0);
  if (!value) return '--';
  try {
    return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false });
  } catch (e) {
    return '--';
  }
}

function dispatchStatusMeta(status) {
  var map = {
    authenticated: { label: '已认证', badge: 'bg-emerald-100 text-emerald-700 ring-emerald-200' },
    pending: { label: '未认证', badge: 'bg-slate-100 text-slate-600 ring-slate-200' },
    expired: { label: '已过期', badge: 'bg-amber-100 text-amber-700 ring-amber-200' },
    error: { label: '认证失败', badge: 'bg-rose-100 text-rose-700 ring-rose-200' },
    success: { label: '成功', badge: 'bg-emerald-100 text-emerald-700 ring-emerald-200' },
    failed: { label: '失败', badge: 'bg-rose-100 text-rose-700 ring-rose-200' },
    need_phone: { label: '待补联系方式', badge: 'bg-amber-100 text-amber-700 ring-amber-200' }
  };
  return map[status] || map.pending;
}

function getDispatchSelectedQueueIds() {
  return Array.from(DISPATCH_STATE.selected);
}

function getCurrentDispatchItem() {
  var currentId = DISPATCH_STATE.currentId;
  if (!currentId && DISPATCH_STATE.items[0]) {
    currentId = DISPATCH_STATE.items[0].id;
  }
  for (var i = 0; i < DISPATCH_STATE.items.length; i++) {
    if (DISPATCH_STATE.items[i].id === currentId) return DISPATCH_STATE.items[i];
  }
  return null;
}

function collectDispatchOverrides() {
  return {
    zlbt: (document.getElementById('dispatchTitle').value || '').trim(),
    zlnr: (document.getElementById('dispatchContent').value || '').trim(),
    kssj: (document.getElementById('dispatchStartTime').value || '').trim(),
    jzsj: (document.getElementById('dispatchEndTime').value || '').trim(),
    qssx: (document.getElementById('dispatchQssx').value || '').trim(),
    fksx: (document.getElementById('dispatchFksx').value || '').trim(),
    ywfzr: (document.getElementById('dispatchManager').value || '').trim(),
    ywfzrlxdh: (document.getElementById('dispatchManagerPhone').value || '').trim(),
    dzmc: (document.getElementById('dispatchAddress').value || '').trim()
  };
}

function getDispatchPayloadEditorText() {
  var el = document.getElementById('dispatchPayloadEditor');
  return el ? (el.value || '').trim() : '';
}

function setDispatchPayloadEditor(value) {
  var el = document.getElementById('dispatchPayloadEditor');
  if (!el) return;
  if (typeof value === 'string') {
    el.value = value;
    return;
  }
  el.value = JSON.stringify(value, null, 2);
}

function parseDispatchPayloadEditor(queueIds) {
  var text = getDispatchPayloadEditorText();
  if (!text || text.indexOf('请选择左侧待推送对象') === 0) {
    return null;
  }
  var parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error('Payload JSON 格式不正确，请先修正后再试。');
  }
  if (!Array.isArray(parsed) && queueIds && queueIds.length > 1) {
    return null;
  }
  var payloadItems = Array.isArray(parsed) ? parsed : [parsed];
  if (queueIds && queueIds.length && payloadItems.length !== queueIds.length) {
    throw new Error('Payload 条数必须与当前选中的待推送对象数量一致。');
  }
  return payloadItems;
}

function renderDispatchAuth() {
  var auth = DISPATCH_STATE.auth || { status: 'pending', authenticated: false, expires_in: 0, last_error: '' };
  var meta = dispatchStatusMeta(auth.status);
  var badge = document.getElementById('dispatchAuthStatusBadge');
  var text = document.getElementById('dispatchAuthStatusText');
  if (badge) {
    badge.textContent = meta.label + (auth.is_mock ? ' / Mock' : '');
    badge.className = 'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ' + meta.badge;
  }
  if (text) {
    var msg = auth.authenticated
      ? '认证账号：' + (auth.username || '--') + '，剩余有效期约 ' + (auth.expires_in || 0) + ' 秒。'
      : '当前尚未认证外部平台，请先完成平台登录。';
    if (auth.last_error) {
      msg += ' 最近错误：' + auth.last_error;
    }
    text.textContent = msg;
  }
}

function renderDispatchQueue() {
  var box = document.getElementById('dispatchQueueList');
  var summary = document.getElementById('dispatchQueueSummary');
  if (!box || !summary) return;

  summary.textContent = '待推送 ' + DISPATCH_STATE.items.length + ' 条，已选 ' + DISPATCH_STATE.selected.size + ' 条。';
  if (!DISPATCH_STATE.items.length) {
    box.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">当前暂无待推送对象。完成人脸识别后，命中人员会自动流转到这里。</div>';
    return;
  }

  box.innerHTML = DISPATCH_STATE.items.map(function (item) {
    var checked = DISPATCH_STATE.selected.has(item.id);
    var active = DISPATCH_STATE.currentId === item.id;
    var dispatchMeta = dispatchStatusMeta(item.dispatch_status);
    var smsMeta = dispatchStatusMeta(item.sms_status);
    return (
      '<div class="rounded-3xl border ' + (active ? 'border-teal-300 ring-4 ring-teal-100' : 'border-slate-200') + ' bg-white p-4 shadow-sm shadow-slate-200/60">' +
        '<div class="flex items-start justify-between gap-3">' +
          '<label class="flex min-w-0 flex-1 items-start gap-3">' +
            '<input type="checkbox" class="mt-1 h-4 w-4 rounded border-slate-300 text-teal-600 focus:ring-teal-500" ' + (checked ? 'checked ' : '') + 'onchange="toggleDispatchSelection(\'' + item.id + '\', this.checked)">' +
            '<div class="min-w-0 flex-1">' +
              '<div class="truncate text-sm font-semibold text-slate-900">' + dispatchEscapeHtml(item.person_name || '未命名对象') + ' / ' + dispatchEscapeHtml(item.person_id_no || '') + '</div>' +
              '<div class="mt-1 text-xs leading-6 text-slate-500">来源：' + dispatchEscapeHtml(item.source_name || item.source_type || '--') + ' · 风险类型：' + dispatchEscapeHtml(item.illegal_type || '--') + '</div>' +
              '<div class="mt-1 text-xs leading-6 text-slate-500">联系电话：' + dispatchEscapeHtml(item.person_phone || '待补充') + ' · 相似度：' + dispatchEscapeHtml(item.similarity_score || 0) + '</div>' +
            '</div>' +
          '</label>' +
          '<button type="button" class="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50" onclick="selectDispatchItem(\'' + item.id + '\')">查看草稿</button>' +
        '</div>' +
        '<div class="mt-4 flex flex-wrap gap-2">' +
          '<span class="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ' + dispatchMeta.badge + '">任务：' + dispatchMeta.label + '</span>' +
          '<span class="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ' + smsMeta.badge + '">短信：' + smsMeta.label + '</span>' +
        '</div>' +
        (item.last_error ? '<div class="mt-3 text-xs leading-6 text-rose-600">' + dispatchEscapeHtml(item.last_error) + '</div>' : '') +
      '</div>'
    );
  }).join('');
}

function renderDispatchHistory() {
  var box = document.getElementById('dispatchHistoryRecords');
  if (!box) return;
  var items = [];
  (DISPATCH_STATE.history.dispatch_records || []).forEach(function (item) {
    items.push({
      kind: '任务推送',
      status: item.status || 'pending',
      title: item.queue_id || '',
      detail: (item.response_payload && (item.response_payload.message || item.response_payload.errorMessage)) || item.error_message || '',
      ts: item.created_ts || 0
    });
  });
  (DISPATCH_STATE.history.sms_records || []).forEach(function (item) {
    items.push({
      kind: '短信提醒',
      status: item.status || 'pending',
      title: item.mobile || '',
      detail: item.content || item.error_message || '',
      ts: item.created_ts || 0
    });
  });
  items.sort(function (a, b) { return (b.ts || 0) - (a.ts || 0); });
  if (!items.length) {
    box.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">暂无推送记录。</div>';
    return;
  }
  box.innerHTML = items.slice(0, 20).map(function (item) {
    var meta = dispatchStatusMeta(item.status);
    return (
      '<div class="rounded-2xl border border-slate-200 bg-slate-50/80 p-4">' +
        '<div class="flex items-start justify-between gap-3">' +
          '<div>' +
            '<div class="text-sm font-semibold text-slate-900">' + dispatchEscapeHtml(item.kind) + ' / ' + dispatchEscapeHtml(item.title || '--') + '</div>' +
            '<div class="mt-2 text-xs leading-6 text-slate-500">' + dispatchEscapeHtml(item.detail || '--') + '</div>' +
          '</div>' +
          '<div class="text-right">' +
            '<span class="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ' + meta.badge + '">' + meta.label + '</span>' +
            '<div class="mt-2 text-xs text-slate-400">' + dispatchFormatTs(item.ts) + '</div>' +
          '</div>' +
        '</div>' +
      '</div>'
    );
  }).join('');
}

function renderDispatchSmsLocally() {
  var item = getCurrentDispatchItem();
  var box = document.getElementById('dispatchSmsPreviewText');
  if (!box) return;
  if (!item) {
    box.textContent = '请选择左侧待推送对象后预览短信内容';
    return;
  }
  var template = document.getElementById('dispatchSmsTemplate').value || '';
  var deadline = document.getElementById('dispatchEndTime').value || '';
  var station = item.zbpcs_mc || '';
  var managerPhone = document.getElementById('dispatchManagerPhone').value || '';
  var text = template
    .replace(/\{xm\}/g, item.person_name || '')
    .replace(/\{zjhm\}/g, item.person_id_no || '')
    .replace(/\{illegal_type\}/g, item.illegal_type || '')
    .replace(/\{deadline\}/g, deadline)
    .replace(/\{zbpcsmc\}/g, station)
    .replace(/\{ywfzrlxdh\}/g, managerPhone)
    .replace(/\{source_name\}/g, item.source_name || '');
  box.textContent = text;
}

function fillDispatchForm(item) {
  var payload = item && item.recommended_payload ? item.recommended_payload : (item && item.draft_payload ? item.draft_payload : {});
  document.getElementById('dispatchSelectedHint').textContent = item
    ? ('当前对象：' + (item.person_name || '--') + ' / ' + (item.person_id_no || '--'))
    : '请选择左侧待推送对象后，再编辑任务内容和推送草稿。';
  document.getElementById('dispatchTitle').value = payload.zlbt || '';
  document.getElementById('dispatchContent').value = payload.zlnr || '';
  document.getElementById('dispatchStartTime').value = payload.kssj || '';
  document.getElementById('dispatchEndTime').value = payload.jzsj || '';
  document.getElementById('dispatchQssx').value = payload.qssx || '';
  document.getElementById('dispatchFksx').value = payload.fksx || '';
  document.getElementById('dispatchManager').value = payload.ywfzr || DISPATCH_STATE.defaults.ywfzr || '';
  document.getElementById('dispatchManagerPhone').value = payload.ywfzrlxdh || DISPATCH_STATE.defaults.ywfzrlxdh || '';
  document.getElementById('dispatchCity').value = ((item && item.sssj_dm) || payload.sssjDm || '') + ' / ' + ((item && item.sssj_mc) || payload.sssjMc || '');
  document.getElementById('dispatchBranch').value = ((item && item.ssfj_dm) || payload.ssfjDm || '') + ' / ' + ((item && item.ssfj_mc) || payload.ssfjMc || '');
  document.getElementById('dispatchStation').value = ((item && item.zbpcs_dm) || payload.zbpcsdm || '') + ' / ' + ((item && item.zbpcs_mc) || payload.zbpcsmc || '');
  document.getElementById('dispatchAddress').value = payload.dzmc || item.dzmc || '';
  document.getElementById('dispatchSmsMobile').value = item.person_phone || DISPATCH_STATE.defaults.sms_mobile || '';
  document.getElementById('dispatchSmsTemplate').value = DISPATCH_STATE.defaults.sms_template || '';
  setDispatchPayloadEditor(payload || {});
  renderDispatchSmsLocally();
}

function selectDispatchItem(queueId) {
  DISPATCH_STATE.currentId = queueId;
  if (!DISPATCH_STATE.selected.size) {
    DISPATCH_STATE.selected = new Set([queueId]);
  }
  renderDispatchQueue();
  var current = getCurrentDispatchItem();
  fillDispatchForm(current);
}

function toggleDispatchSelection(queueId, checked) {
  if (checked) {
    DISPATCH_STATE.selected.add(queueId);
    DISPATCH_STATE.currentId = queueId;
  } else {
    DISPATCH_STATE.selected.delete(queueId);
    if (DISPATCH_STATE.currentId === queueId) {
      DISPATCH_STATE.currentId = getDispatchSelectedQueueIds()[0] || '';
    }
  }
  renderDispatchQueue();
  fillDispatchForm(getCurrentDispatchItem());
}

function refreshDispatchTab() {
  fetch('/dispatch/queue')
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) return;
      DISPATCH_STATE.auth = data.auth || null;
      DISPATCH_STATE.items = Array.isArray(data.items) ? data.items : [];
      DISPATCH_STATE.history = data.history || { dispatch_records: [], sms_records: [] };
      DISPATCH_STATE.defaults = data.defaults || DISPATCH_STATE.defaults;
      var existing = new Set();
      DISPATCH_STATE.items.forEach(function (item) { existing.add(item.id); });
      DISPATCH_STATE.selected = new Set(getDispatchSelectedQueueIds().filter(function (item) { return existing.has(item); }));
      if ((!DISPATCH_STATE.currentId || !existing.has(DISPATCH_STATE.currentId)) && DISPATCH_STATE.items[0]) {
        DISPATCH_STATE.currentId = DISPATCH_STATE.items[0].id;
      }
      renderDispatchAuth();
      renderDispatchQueue();
      renderDispatchHistory();
      fillDispatchForm(getCurrentDispatchItem());
    })
    .catch(function () {});
}

function refreshDispatchQueue() {
  refreshDispatchTab();
}

function refreshDispatchRegionContext() {
  var ids = getDispatchSelectedQueueIds();
  if (!ids.length && DISPATCH_STATE.currentId) {
    ids = [DISPATCH_STATE.currentId];
  }
  if (!ids.length) {
    alert('请先选择待推送对象。');
    return;
  }
  fetch('/dispatch/queue/refresh-region', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ queue_ids: ids })
  })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) {
        alert(data.error || '重查归属失败。');
        return;
      }
      alert(data.message || '归属信息已更新。');
      refreshDispatchTab();
    })
    .catch(function () {
      alert('重查归属请求失败。');
    });
}

function authenticateDispatch(event) {
  if (event) event.preventDefault();
  var username = (document.getElementById('dispatchUsername').value || '').trim();
  var password = (document.getElementById('dispatchPassword').value || '').trim();
  fetch('/dispatch/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: username, password: password })
  })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) {
        alert(data.error || '外部平台认证失败。');
        return;
      }
      DISPATCH_STATE.auth = data.auth || null;
      renderDispatchAuth();
      alert('外部平台认证成功。');
    })
    .catch(function () {
      alert('外部平台认证请求失败。');
    });
  return false;
}

function previewDispatchPayload() {
  var ids = getDispatchSelectedQueueIds();
  if (!ids.length && DISPATCH_STATE.currentId) {
    ids = [DISPATCH_STATE.currentId];
  }
  if (!ids.length) {
    alert('请先选择待推送对象。');
    return;
  }
  var payloadItems = null;
  try {
    payloadItems = parseDispatchPayloadEditor(ids);
  } catch (error) {
    alert(error.message || 'Payload JSON 格式不正确。');
    return;
  }
  fetch('/dispatch/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      queue_ids: ids,
      overrides: collectDispatchOverrides(),
      payload_items: payloadItems,
      payload_mode: 'minimal'
    })
  })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) {
        alert(data.error || '生成草稿失败。');
        return;
      }
      setDispatchPayloadEditor(data.items.length === 1 ? data.items[0] : data.items);
    })
    .catch(function () {
      alert('生成草稿请求失败。');
    });
}

function restoreDispatchMinimalPayload() {
  var ids = getDispatchSelectedQueueIds();
  if (!ids.length && DISPATCH_STATE.currentId) {
    ids = [DISPATCH_STATE.currentId];
  }
  if (!ids.length) {
    alert('请先选择待推送对象。');
    return;
  }
  fetch('/dispatch/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      queue_ids: ids,
      overrides: collectDispatchOverrides(),
      payload_mode: 'minimal'
    })
  })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) {
        alert(data.error || '恢复精简草稿失败。');
        return;
      }
      setDispatchPayloadEditor(data.items.length === 1 ? data.items[0] : data.items);
    })
    .catch(function () {
      alert('恢复精简草稿请求失败。');
    });
}

function formatDispatchPayloadEditor() {
  try {
    var payloadItems = parseDispatchPayloadEditor([]);
    if (!payloadItems) return;
    setDispatchPayloadEditor(payloadItems.length === 1 ? payloadItems[0] : payloadItems);
  } catch (error) {
    alert(error.message || 'Payload JSON 格式不正确。');
  }
}

function sendDispatchTasks() {
  var ids = getDispatchSelectedQueueIds();
  if (!ids.length && DISPATCH_STATE.currentId) {
    ids = [DISPATCH_STATE.currentId];
  }
  if (!ids.length) {
    alert('请先选择待推送对象。');
    return;
  }
  var payloadItems = null;
  try {
    payloadItems = parseDispatchPayloadEditor(ids);
  } catch (error) {
    alert(error.message || 'Payload JSON 格式不正确。');
    return;
  }
  fetch('/dispatch/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      queue_ids: ids,
      overrides: collectDispatchOverrides(),
      payload_items: payloadItems,
      payload_mode: 'minimal'
    })
  })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) {
        alert(data.error || '任务推送失败。');
        return;
      }
      alert((data.mock_mode ? '当前为模拟模式，' : '') + '任务推送已完成，共处理 ' + (data.count || 0) + ' 条。');
      refreshDispatchTab();
    })
    .catch(function () {
      alert('任务推送请求失败。');
    });
}

function previewDispatchSms() {
  var current = getCurrentDispatchItem();
  if (!current) {
    alert('请先选择一个待推送对象。');
    return;
  }
  var mobile = (document.getElementById('dispatchSmsMobile').value || '').trim();
  var template = document.getElementById('dispatchSmsTemplate').value || '';
  fetch('/dispatch/sms/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ queue_id: current.id, mobile: mobile, template: template, overrides: collectDispatchOverrides() })
  })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) {
        alert(data.error || '短信预览失败。');
        return;
      }
      document.getElementById('dispatchSmsPreviewText').textContent = data.preview.content || '';
    })
    .catch(function () {
      alert('短信预览请求失败。');
    });
}

function sendDispatchSms() {
  var ids = getDispatchSelectedQueueIds();
  if (!ids.length && DISPATCH_STATE.currentId) {
    ids = [DISPATCH_STATE.currentId];
  }
  if (!ids.length) {
    alert('请先选择待推送对象。');
    return;
  }
  var mobile = (document.getElementById('dispatchSmsMobile').value || '').trim();
  var template = document.getElementById('dispatchSmsTemplate').value || '';
  fetch('/dispatch/sms/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ queue_ids: ids, mobile: mobile, template: template, overrides: collectDispatchOverrides() })
  })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) {
        alert(data.error || '短信发送失败。');
        return;
      }
      alert((data.mock_mode ? '当前为模拟模式，' : '') + '短信处理已完成，共处理 ' + ((data.items || []).length) + ' 条。');
      refreshDispatchTab();
    })
    .catch(function () {
      alert('短信发送请求失败。');
    });
}
