const TASK_QUEUE_DIAGNOSTICS = {
  timer: null,
  lastPayload: null
};

function diagEscapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function diagFormatTs(ts) {
  var value = Number(ts || 0);
  if (!value) return '--';
  try {
    return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false });
  } catch (e) {
    return '--';
  }
}

function diagFormatDuration(seconds) {
  var value = Number(seconds || 0);
  if (!value) return '--';
  if (value < 60) return value + ' 秒';
  if (value < 3600) return Math.floor(value / 60) + ' 分 ' + (value % 60) + ' 秒';
  return Math.floor(value / 3600) + ' 小时 ' + Math.floor((value % 3600) / 60) + ' 分';
}

function diagStatusMeta(status, stale) {
  if (stale) {
    return { label: '陈旧运行', badge: 'bg-amber-100 text-amber-700 ring-amber-200' };
  }
  var map = {
    pending: { label: '等待中', badge: 'bg-slate-100 text-slate-700 ring-slate-200' },
    running: { label: '运行中', badge: 'bg-sky-100 text-sky-700 ring-sky-200' },
    completed: { label: '已完成', badge: 'bg-emerald-100 text-emerald-700 ring-emerald-200' },
    failed: { label: '失败', badge: 'bg-rose-100 text-rose-700 ring-rose-200' }
  };
  return map[status] || { label: status || '--', badge: 'bg-slate-100 text-slate-700 ring-slate-200' };
}

function diagSetText(id, value) {
  var el = document.getElementById(id);
  if (el) el.textContent = value;
}

function diagSetRemediation(message, tone) {
  var el = document.getElementById('diagRemediation');
  if (!el) return;
  if (!message) {
    el.classList.add('hidden');
    el.textContent = '';
    return;
  }
  var classes = {
    warning: 'mt-5 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-7 text-amber-800',
    error: 'mt-5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-7 text-rose-700',
    neutral: 'mt-5 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-600'
  };
  el.className = classes[tone] || classes.neutral;
  el.textContent = message;
}

function diagRenderDistribution(id, items, formatter) {
  var box = document.getElementById(id);
  if (!box) return;
  if (!items || !items.length) {
    box.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-4 text-sm text-slate-500">暂无数据</div>';
    return;
  }
  box.innerHTML = items.map(function (item) {
    return (
      '<div class="flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3">' +
        '<span class="text-sm font-semibold text-slate-700">' + diagEscapeHtml(formatter(item)) + '</span>' +
        '<span class="font-mono text-sm text-slate-500">' + diagEscapeHtml(item.count || 0) + '</span>' +
      '</div>'
    );
  }).join('');
}

function diagRenderHealth(payload) {
  var health = payload.health || {};
  var taskQueue = health.task_queue || {};
  var badge = document.getElementById('diagHealthBadge');
  var details = document.getElementById('diagHealthDetails');
  var staleCount = Number(taskQueue.stale_running_count || 0);
  if (badge) {
    var ok = health.ok && taskQueue.ok !== false;
    badge.textContent = ok ? '正常' : '需关注';
    badge.className = 'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ' + (ok ? 'bg-emerald-100 text-emerald-700 ring-emerald-200' : 'bg-amber-100 text-amber-700 ring-amber-200');
  }
  if (details) {
    details.innerHTML =
      '<div>运行中：' + diagEscapeHtml(taskQueue.running_count || 0) + ' 个</div>' +
      '<div>陈旧运行：' + diagEscapeHtml(staleCount) + ' 个</div>' +
      '<div>陈旧阈值：' + diagFormatDuration(taskQueue.stale_after_seconds || payload.stale_after_seconds || 0) + '</div>' +
      ((taskQueue.sample_task_ids || []).length
        ? '<div class="mt-2 break-all text-amber-700">样例：' + diagEscapeHtml((taskQueue.sample_task_ids || []).join(', ')) + '</div>'
        : '') +
      (staleCount > 0
        ? '<div class="mt-2 text-amber-700">处理建议：先确认 worker.py 或 Docker worker 是否仍在运行，再查看 Worker 日志；本页保持只读，不会自动重置任务。</div>'
        : '') +
      (taskQueue.error
        ? '<div class="mt-2 text-rose-600">健康检查错误：' + diagEscapeHtml(taskQueue.error) + '</div>'
        : '');
  }
}

function diagRenderTasks(tasks, payload) {
  var body = document.getElementById('diagTaskRows');
  if (!body) return;
  if (!tasks || !tasks.length) {
    var totals = (payload && payload.totals) || {};
    var message = Number(totals.total || 0) === 0
      ? '队列为空：当前没有 pending、running、completed 或 failed 任务。若业务任务一直排队，请确认 worker.py 或 Docker worker 已启动。'
      : '暂无符合筛选条件的队列任务。可清空筛选条件或调大数量后再刷新。';
    body.innerHTML = '<tr><td colspan="6" class="px-4 py-8 text-center text-sm text-slate-500">' + diagEscapeHtml(message) + '</td></tr>';
    return;
  }
  body.innerHTML = tasks.map(function (task) {
    var meta = diagStatusMeta(task.status, task.stale);
    var owner = task.owner_key || task.owner_ip || '--';
    var elapsed = task.status === 'running' ? task.run_seconds : task.total_seconds;
    return (
      '<tr class="align-top">' +
        '<td class="px-4 py-3">' +
          '<div class="font-mono text-xs font-semibold text-slate-900">' + diagEscapeHtml(task.task_id || '') + '</div>' +
          '<div class="mt-1 text-xs text-slate-500">' + diagEscapeHtml(task.task_type || '') + ' · retries ' + diagEscapeHtml(task.retries || 0) + '</div>' +
          '<div class="mt-1 text-xs text-slate-400">' + diagEscapeHtml(diagFormatTs(task.created_ts)) + '</div>' +
        '</td>' +
        '<td class="px-4 py-3"><span class="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ' + meta.badge + '">' + meta.label + '</span></td>' +
        '<td class="px-4 py-3 font-mono text-xs text-slate-600">' + diagEscapeHtml(task.job_id || '--') + '</td>' +
        '<td class="px-4 py-3 text-xs text-slate-600">' +
          '<div>等待：' + diagFormatDuration(task.wait_seconds) + '</div>' +
          '<div>执行：' + diagFormatDuration(elapsed) + '</div>' +
        '</td>' +
        '<td class="px-4 py-3 font-mono text-xs text-slate-500">' + diagEscapeHtml(owner) + '</td>' +
        '<td class="max-w-[260px] px-4 py-3 text-xs leading-6 text-rose-600">' + diagEscapeHtml(task.error || '') + '</td>' +
      '</tr>'
    );
  }).join('');
}

function renderTaskQueueDiagnostics(payload) {
  TASK_QUEUE_DIAGNOSTICS.lastPayload = payload;
  var totals = payload.totals || {};
  var total = Number(totals.total || 0);
  var stale = Number(totals.stale_running || 0);
  diagSetText('diagQueueTotal', totals.total || 0);
  diagSetText('diagQueuePending', totals.pending || 0);
  diagSetText('diagQueueRunning', totals.running || 0);
  diagSetText('diagQueueFailed', totals.failed || 0);
  diagSetText('diagQueueStale', totals.stale_running || 0);
  diagSetText('diagLastRefresh', '刷新时间：' + diagFormatTs(payload.generated_ts));
  diagRenderHealth(payload);
  diagRenderDistribution('diagByStatus', payload.by_status || [], function (item) {
    return item.status || '--';
  });
  diagRenderDistribution('diagByTypeStatus', payload.by_type_status || [], function (item) {
    return (item.task_type || '--') + ' / ' + (item.status || '--');
  });
  diagRenderTasks(payload.tasks || [], payload);

  if (stale > 0) {
    diagSetRemediation('发现陈旧 running 任务：先确认 Worker 是否存活，再查看 worker.py 日志和 Docker worker 容器日志。当前版本只读展示，不会在页面里重置或重试。', 'warning');
  } else if ((payload.health || {}).ok === false) {
    diagSetRemediation('健康检查未通过：优先查看 /healthz 返回内容，确认模型文件、SQLite 路径、输出目录和任务队列是否可访问。', 'warning');
  } else if (total === 0) {
    diagSetRemediation('队列为空：这是干净状态。新建数据库检测、上传检测、训练或人脸库任务后，这里会出现 pending/running/completed/failed 记录。', 'neutral');
  } else {
    diagSetRemediation('', 'neutral');
  }
}

function refreshTaskQueueDiagnostics(btn) {
  if (btn && btn.classList) btn.classList.add('mr-btn--loading');
  var params = new URLSearchParams();
  var typeEl = document.getElementById('diagTaskTypeFilter');
  var statusEl = document.getElementById('diagStatusFilter');
  var limitEl = document.getElementById('diagLimitFilter');
  if (typeEl && typeEl.value) params.set('task_type', typeEl.value);
  if (statusEl && statusEl.value) params.set('status', statusEl.value);
  params.set('limit', (limitEl && limitEl.value) || '60');

  return fetch('/diagnostics/task-queue?' + params.toString())
    .then(function (resp) {
      return resp.json().then(function (payload) {
        payload.__http_ok = resp.ok;
        payload.__http_status = resp.status;
        return payload;
      });
    })
    .then(function (payload) {
      if (!payload.ok || payload.__http_ok === false) {
        throw new Error(payload.error || ('诊断接口返回 HTTP ' + (payload.__http_status || 'unknown')));
      }
      renderTaskQueueDiagnostics(payload);
    })
    .catch(function (error) {
      var body = document.getElementById('diagTaskRows');
      if (body) {
        body.innerHTML = '<tr><td colspan="6" class="px-4 py-8 text-center text-sm text-rose-600">' + diagEscapeHtml(error.message || '诊断加载失败') + '</td></tr>';
      }
      diagSetRemediation('诊断加载失败：请检查 Web 日志、SQLite 数据库路径和 /diagnostics/task-queue 接口返回。', 'error');
    })
    .finally(function () {
      if (btn && btn.classList) btn.classList.remove('mr-btn--loading');
    });
}

function setTaskQueueAutoRefresh(enabled) {
  if (TASK_QUEUE_DIAGNOSTICS.timer) {
    clearInterval(TASK_QUEUE_DIAGNOSTICS.timer);
    TASK_QUEUE_DIAGNOSTICS.timer = null;
  }
  if (enabled) {
    TASK_QUEUE_DIAGNOSTICS.timer = setInterval(refreshTaskQueueDiagnostics, 10000);
  }
}

function initTaskQueueDiagnostics() {
  ['diagTaskTypeFilter', 'diagStatusFilter', 'diagLimitFilter'].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener('change', refreshTaskQueueDiagnostics);
  });
  var auto = document.getElementById('diagAutoRefresh');
  if (auto) {
    auto.addEventListener('change', function () {
      setTaskQueueAutoRefresh(auto.checked && !document.getElementById('tabDiagnostics').classList.contains('hidden'));
    });
  }
}

window.addEventListener('load', initTaskQueueDiagnostics);
