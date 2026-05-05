const FACE_LIBRARY_TASK_STATE = { id: '', status: '', message: '', action: '', processed: 0, total: 0 };
const FACE_LIBRARY_STATE = { library: null };

function getFaceLibraryDom() {
  return {
    status: document.getElementById('faceLibraryStatusGlobal'),
    task: document.getElementById('faceLibraryTaskGlobal')
  };
}

function isFaceLibraryTaskActive(task) {
  return task && (task.status === 'queued' || task.status === 'running');
}

function setFaceLibraryTask(task) {
  if (!task) {
    FACE_LIBRARY_TASK_STATE.id = '';
    FACE_LIBRARY_TASK_STATE.status = '';
    FACE_LIBRARY_TASK_STATE.message = '';
    FACE_LIBRARY_TASK_STATE.action = '';
    FACE_LIBRARY_TASK_STATE.processed = 0;
    FACE_LIBRARY_TASK_STATE.total = 0;
  } else {
    FACE_LIBRARY_TASK_STATE.id = task.id || '';
    FACE_LIBRARY_TASK_STATE.status = task.status || '';
    FACE_LIBRARY_TASK_STATE.message = task.message || '';
    FACE_LIBRARY_TASK_STATE.action = task.action || '';
    FACE_LIBRARY_TASK_STATE.processed = task.processed || 0;
    FACE_LIBRARY_TASK_STATE.total = task.total || 0;
  }
  renderLibraryTaskState();
}

function renderLibraryTaskState() {
  var globalDom = getFaceLibraryDom();
  if (globalDom.task) {
    if (!FACE_LIBRARY_TASK_STATE.id) {
      globalDom.task.textContent = '';
    } else {
      var globalText = '人脸库任务：' + (FACE_LIBRARY_TASK_STATE.action === 'sync' ? '同步' : '重建特征') + ' · ' +
        (FACE_LIBRARY_TASK_STATE.message || FACE_LIBRARY_TASK_STATE.status || '运行中');
      if (FACE_LIBRARY_TASK_STATE.total) {
        globalText += ' · ' + FACE_LIBRARY_TASK_STATE.processed + '/' + FACE_LIBRARY_TASK_STATE.total;
      }
      globalDom.task.textContent = globalText;
    }
  }
  ['database', 'upload'].forEach(function (prefix) {
    var dom = getResultDom(prefix);
    if (!dom.task) return;
    if (!FACE_LIBRARY_TASK_STATE.id) {
      dom.task.textContent = '';
      return;
    }
    var text = '人脸库任务：' + (FACE_LIBRARY_TASK_STATE.action === 'sync' ? '同步' : '重建特征') + ' · ' +
      (FACE_LIBRARY_TASK_STATE.message || FACE_LIBRARY_TASK_STATE.status || '运行中');
    if (FACE_LIBRARY_TASK_STATE.total) {
      text += ' · ' + FACE_LIBRARY_TASK_STATE.processed + '/' + FACE_LIBRARY_TASK_STATE.total;
    }
    dom.task.textContent = text;
  });
}

function pollFaceLibraryTask(taskId) {
  if (!taskId) return;
  fetch('/face/library/task/' + taskId)
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) return;
      var task = data.task || {};
      setFaceLibraryTask(task);
      if (isFaceLibraryTaskActive(task)) {
        window.setTimeout(function () { pollFaceLibraryTask(taskId); }, 1200);
        return;
      }
      refreshFaceLibraryStatus('database');
      refreshFaceLibraryStatus('upload');
      if (task.status === 'done') {
        alert(task.action === 'sync' ? '人脸库同步完成。' : '人脸特征重建完成。');
      } else if (task.status === 'error') {
        alert(task.error || task.message || '人脸库任务执行失败。');
      }
      window.setTimeout(function () { setFaceLibraryTask(null); }, 1500);
    })
    .catch(function () {
      window.setTimeout(function () { pollFaceLibraryTask(taskId); }, 2000);
    });
}

function renderLibraryStatus(prefix) {
  var dom = getResultDom(prefix);
  var state = FACE_RESULT_STATE[prefix];
  if (!dom.library) return;
  if (!state.library) {
    dom.library.textContent = '正在读取人脸库状态...';
    return;
  }
  var lib = state.library;
  dom.library.textContent =
    '人脸库：' + (lib.ready ? '已就绪' : '未就绪') +
    ' · 有效人员 ' + (lib.valid_person_count || 0) +
    ' · 底库照片 ' + (lib.photo_count || 0) +
    ' · 特征文件 ' + (lib.feature_count || 0);
}

function renderGlobalFaceLibraryStatus() {
  var dom = getFaceLibraryDom();
  if (!dom.status) return;
  if (!FACE_LIBRARY_STATE.library) {
    dom.status.textContent = '正在读取人脸库状态...';
    return;
  }
  var lib = FACE_LIBRARY_STATE.library;
  var text =
    '人脸库：' + (lib.ready ? '已就绪' : '未就绪') +
    ' · 有效人员 ' + (lib.valid_person_count || 0) +
    ' · 底库照片 ' + (lib.photo_count || 0) +
    ' · 特征文件 ' + (lib.feature_count || 0);
  if (!lib.sql_configured) {
    text += ' · 未配置私有网络数据库连接';
  }
  dom.status.textContent = text;
}

function refreshFaceLibraryStatus(prefix) {
  var targetPrefixes = FACE_RESULT_STATE[prefix] ? [prefix] : ['database', 'upload'];
  fetch('/face/library/status')
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) return;
      targetPrefixes.forEach(function (itemPrefix) {
        FACE_RESULT_STATE[itemPrefix].library = data.library || null;
        renderLibraryStatus(itemPrefix);
      });
      FACE_LIBRARY_STATE.library = data.library || null;
      if (data.task) {
        var shouldPoll = isFaceLibraryTaskActive(data.task) && FACE_LIBRARY_TASK_STATE.id !== data.task.id;
        setFaceLibraryTask(data.task);
        if (shouldPoll) pollFaceLibraryTask(data.task.id);
      }
      renderGlobalFaceLibraryStatus();
      renderFaceTabStatus();
      renderFaceTabTask();
    })
    .catch(function () {
      var fallbackLibrary = { ready: false, valid_person_count: 0, photo_count: 0, feature_count: 0 };
      targetPrefixes.forEach(function (itemPrefix) {
        FACE_RESULT_STATE[itemPrefix].library = fallbackLibrary;
        renderLibraryStatus(itemPrefix);
      });
      FACE_LIBRARY_STATE.library = fallbackLibrary;
      renderGlobalFaceLibraryStatus();
    });
}

function runFaceLibraryAction(prefix, action) {
  var url = action === 'sync' ? '/face/library/sync' : '/face/library/rebuild';
  var tips = action === 'sync'
    ? '确认开始同步人脸库？如果当前环境无法连接私有网络 SQL，会返回失败提示。'
    : '确认开始重建本地人脸特征？';
  if (!confirm(tips)) return;
  fetch(url, { method: 'POST' })
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) {
        alert(data.error || '操作失败。');
        return;
      }
      var task = data.task || null;
      if (task) {
        setFaceLibraryTask(task);
        if (data.started === false) {
          alert('当前已有正在运行的人脸库任务，已切换为查看现有进度。');
        }
        pollFaceLibraryTask(task.id);
      } else {
        refreshFaceLibraryStatus('database');
        refreshFaceLibraryStatus('upload');
      }
    })
    .catch(function () {
      alert('请求失败，请稍后重试。');
    });
}

function initUploadDragDrop() {
  var label = document.getElementById('uploadDropZone');
  if (!label) return;
  label.addEventListener('dragover', function (e) {
    e.preventDefault();
    label.classList.add('border-teal-400', 'bg-teal-50');
  });
  label.addEventListener('dragleave', function () {
    label.classList.remove('border-teal-400', 'bg-teal-50');
  });
  label.addEventListener('drop', function (e) {
    e.preventDefault();
    label.classList.remove('border-teal-400', 'bg-teal-50');
    var files = e.dataTransfer && e.dataTransfer.files;
    if (files && files[0]) {
      try {
        var dt = new DataTransfer();
        dt.items.add(files[0]);
        document.getElementById('uploadFile').files = dt.files;
      } catch (ex) {}
      onUploadFileChange(document.getElementById('uploadFile'));
    }
  });
}

const PERSON_STATE = { page: 1, pages: 1, total: 0, keyword: '', items: [] };
let _personSearchTimer = null;

function debouncePersonSearch() {
  clearTimeout(_personSearchTimer);
  _personSearchTimer = setTimeout(function () {
    PERSON_STATE.keyword = (document.getElementById('personSearchInput').value || '').trim();
    loadPersonDirectory(1);
  }, 400);
}

function loadPersonDirectory(page) {
  page = page || 1;
  var keyword = PERSON_STATE.keyword || '';
  var url = '/face/library/persons?page=' + page + '&page_size=12';
  if (keyword) url += '&keyword=' + encodeURIComponent(keyword);
  fetch(url)
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) return;
      PERSON_STATE.page = data.page || 1;
      PERSON_STATE.pages = data.pages || 1;
      PERSON_STATE.total = data.total || 0;
      PERSON_STATE.items = data.items || [];
      renderPersonGrid();
    })
    .catch(function () {
      PERSON_STATE.items = [];
      renderPersonGrid();
    });
}

function renderPersonGrid() {
  var grid = document.getElementById('personGrid');
  var pageInfo = document.getElementById('personPageInfo');
  var prevBtn = document.getElementById('personPrevBtn');
  var nextBtn = document.getElementById('personNextBtn');
  if (!grid) return;

  pageInfo.textContent = '共 ' + PERSON_STATE.total + ' 人 · 第 ' + PERSON_STATE.page + ' / ' + PERSON_STATE.pages + ' 页';
  prevBtn.disabled = PERSON_STATE.page <= 1;
  nextBtn.disabled = PERSON_STATE.page >= PERSON_STATE.pages;

  if (!PERSON_STATE.items.length) {
    grid.innerHTML = '<div class="col-span-full rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">暂无人员数据。同步人脸库后可在此浏览。</div>';
    return;
  }

  var avatarColors = ['bg-teal-100 text-teal-700', 'bg-sky-100 text-sky-700', 'bg-amber-100 text-amber-700', 'bg-rose-100 text-rose-700', 'bg-violet-100 text-violet-700', 'bg-emerald-100 text-emerald-700'];
  grid.innerHTML = PERSON_STATE.items.map(function (p, i) {
    var ac = avatarColors[i % avatarColors.length];
    var initial = (p.name || '?')[0];
    var statusBadge = p.status === 'valid'
      ? '<span class="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">有效</span>'
      : '<span class="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700 ring-1 ring-inset ring-amber-200">特征缺失</span>';
    return (
      '<div class="cursor-pointer overflow-hidden rounded-3xl border border-slate-200 bg-white p-5 shadow-sm shadow-slate-200/60 transition hover:shadow-md hover:shadow-slate-200/80" onclick="openPersonDetail(\'' + escapeHtml(p.id || '') + '\')">' +
        '<div class="flex items-center gap-4">' +
          '<div class="flex h-[52px] w-[52px] flex-shrink-0 items-center justify-center rounded-full ' + ac + ' text-lg font-bold">' + escapeHtml(initial) + '</div>' +
          '<div class="min-w-0 flex-1">' +
            '<div class="truncate text-base font-semibold text-slate-900">' + escapeHtml(p.name || '') + '</div>' +
            '<div class="truncate text-xs text-slate-500">' + escapeHtml(p.id_number || '') + '</div>' +
          '</div>' +
        '</div>' +
        '<div class="mt-4 rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-2.5">' +
          '<div class="text-xs text-slate-500">照片 ' + (p.has_photo ? '有' : '无') + ' · 特征 ' + (p.has_feature ? '已提取' : '缺失') + '</div>' +
        '</div>' +
        '<div class="mt-4 flex items-center justify-between">' +
          statusBadge +
          '<button type="button" class="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50" onclick="event.stopPropagation();openPersonDetail(\'' + escapeHtml(p.id || '') + '\')">查看</button>' +
        '</div>' +
      '</div>'
    );
  }).join('');
}

function openPersonDetail(personId) {
  var person = null;
  for (var i = 0; i < PERSON_STATE.items.length; i++) {
    if (PERSON_STATE.items[i].id === personId) {
      person = PERSON_STATE.items[i];
      break;
    }
  }
  if (!person) return;

  document.getElementById('personDetailName').textContent = person.name || '';
  document.getElementById('personDetailFullName').textContent = person.name || '';
  document.getElementById('personDetailIdNumber').textContent = person.id_number || '';
  document.getElementById('personDetailAvatar').textContent = (person.name || '?')[0];
  document.getElementById('personDetailIdType').textContent = person.id_type || '--';
  document.getElementById('personDetailIdNum2').textContent = person.id_number || '--';

  var featureEl = document.getElementById('personDetailFeature');
  if (person.has_feature) {
    featureEl.textContent = '已提取';
    featureEl.className = 'font-medium text-emerald-600';
  } else {
    featureEl.textContent = '缺失';
    featureEl.className = 'font-medium text-amber-600';
  }
  document.getElementById('personDetailPhotoStatus').textContent = person.has_photo ? '有' : '无';

  var photoBox = document.getElementById('personDetailPhoto');
  if (person.has_photo) {
    photoBox.innerHTML = '<img src="/face/library/photo/' + encodeURIComponent(personId) + '" alt="底库照片" class="aspect-square rounded-2xl border border-slate-200 object-cover" style="min-height:160px" />';
  } else {
    photoBox.innerHTML = '<div class="col-span-2 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-center text-sm text-slate-500">暂无底库照片</div>';
  }

  document.getElementById('personDetailOverlay').classList.remove('hidden');
  document.getElementById('personDetailDrawer').classList.remove('translate-x-full');
}

function closePersonDetail() {
  document.getElementById('personDetailOverlay').classList.add('hidden');
  document.getElementById('personDetailDrawer').classList.add('translate-x-full');
}

function loadOperationHistory() {
  fetch('/face/library/tasks')
    .then(function (resp) { return resp.json(); })
    .then(function (data) {
      if (!data.ok) return;
      renderOperationHistory(data.tasks || []);
    })
    .catch(function () {});
}

function renderOperationHistory(tasks) {
  var box = document.getElementById('faceHistoryRows');
  if (!box) return;
  if (!tasks.length) {
    box.innerHTML = '<div class="px-5 py-5 text-center text-sm text-slate-500">暂无操作记录。</div>';
    return;
  }
  box.innerHTML = tasks.map(function (t, index) {
    var actionLabel = t.action === 'sync' ? '同步人脸库' : '重建特征';
    var statusMap = {
      done: '<span class="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-inset ring-emerald-200">已完成</span>',
      running: '<span class="inline-flex items-center rounded-full bg-sky-100 px-2.5 py-1 text-xs font-semibold text-sky-700 ring-1 ring-inset ring-sky-200">运行中</span>',
      error: '<span class="inline-flex items-center rounded-full bg-rose-100 px-2.5 py-1 text-xs font-semibold text-rose-700 ring-1 ring-inset ring-rose-200">失败</span>'
    };
    var statusHtml = statusMap[t.status] || '<span class="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700">' + escapeHtml(t.status || '--') + '</span>';
    var timeStr = t.start_ts ? new Date(t.start_ts * 1000).toLocaleString('zh-CN') : '--';
    var countStr = (t.processed || 0) + ' / ' + (t.total || 0);
    var remark = t.error || t.message || '--';
    return (
      '<div class="grid grid-cols-12 items-center gap-3 border-t border-slate-100 px-5 py-3.5" style="' + (index % 2 === 1 ? 'background:rgba(248,250,252,0.6)' : '') + '">' +
        '<div class="col-span-2 text-sm font-medium text-slate-900">' + escapeHtml(actionLabel) + '</div>' +
        '<div class="col-span-2">' + statusHtml + '</div>' +
        '<div class="col-span-3 text-sm text-slate-600">' + escapeHtml(timeStr) + '</div>' +
        '<div class="col-span-2 text-sm text-slate-600">' + escapeHtml(countStr) + '</div>' +
        '<div class="col-span-3 text-sm text-slate-400">' + escapeHtml(remark) + '</div>' +
      '</div>'
    );
  }).join('');
}

function renderFaceTabStatus() {
  var lib = FACE_LIBRARY_STATE.library;
  if (!lib) return;
  var readyEl = document.getElementById('faceMetricReady');
  if (readyEl) {
    readyEl.textContent = lib.ready ? '已就绪' : '未就绪';
    readyEl.className = 'mt-2 text-xl font-bold ' + (lib.ready ? 'text-emerald-600' : 'text-amber-600');
  }
  var personsEl = document.getElementById('faceMetricPersons');
  if (personsEl) personsEl.textContent = lib.valid_person_count || 0;
  var photosEl = document.getElementById('faceMetricPhotos');
  if (photosEl) photosEl.textContent = lib.photo_count || 0;
  var featuresEl = document.getElementById('faceMetricFeatures');
  if (featuresEl) featuresEl.textContent = lib.feature_count || 0;
  var sqlEl = document.getElementById('faceMetricSql');
  if (sqlEl) {
    sqlEl.textContent = lib.sql_configured ? '已配置' : '未配置';
    sqlEl.className = 'mt-2 text-xl font-bold ' + (lib.sql_configured ? 'text-emerald-600' : 'text-amber-600');
  }
}

function renderFaceTabTask() {
  var section = document.getElementById('faceTaskSection');
  if (!section) return;
  if (!FACE_LIBRARY_TASK_STATE.id) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');
  var t = FACE_LIBRARY_TASK_STATE;
  var actionLabel = t.action === 'sync' ? '同步人脸库' : '重建特征';
  var meta = statusMeta(t.status || 'running');
  document.getElementById('faceTaskTitle').textContent = '人脸库任务：' + actionLabel;
  document.getElementById('faceTaskMessage').textContent = t.message || t.status || '';
  var badge = document.getElementById('faceTaskBadge');
  badge.textContent = meta.label;
  badge.className = 'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ' + meta.badge;
  var pct = t.total ? Math.min(100, Math.floor(t.processed * 100 / t.total)) : 0;
  document.getElementById('faceTaskBar').style.width = pct + '%';
  document.getElementById('faceTaskBar').className = 'h-3 rounded-full transition-all ' + meta.bar;
  document.getElementById('faceTaskPct').textContent = '进度 ' + pct + '%';
  document.getElementById('faceTaskCount').textContent = t.processed + ' / ' + t.total;
}

function refreshFaceTab() {
  refreshFaceLibraryStatus('database');
  setTimeout(function () {
    renderFaceTabStatus();
    renderFaceTabTask();
  }, 500);
  loadPersonDirectory(PERSON_STATE.page);
  loadOperationHistory();
}
