    const APP_CONFIG = window.INDEX_PAGE_BOOTSTRAP || {};
    const APP_URLS = APP_CONFIG.urls || {};

    const MODEL_UI = {
      special: {
        label: '类别过滤',
        placeholder: '0,1,2 或类别名',
        help: '按索引或类别名过滤专项场景模型结果；留空表示不过滤。',
        uploadDefaultConf: 0.80,
        presets: []
      },
      general: {
        label: '检测提示词',
        placeholder: 'person, motorcycle, bicycle, car, bus, truck',
        help: '英文逗号分隔。适合做人员、车辆、摩托车等通用要素的快速粗筛。',
        uploadDefaultConf: 0.10,
        presets: [
          { label: '交通场景', value: 'person,motorcycle,bicycle,car,bus,truck' },
          { label: '摩托车', value: 'motorcycle' },
          { label: '未戴头盔', value: 'motorcycle, person, helmet' },
          { label: '人员', value: 'person' }
        ]
      }
    };

    const UPLOAD_MODEL_OPTIONS = Array.isArray(APP_CONFIG.uploadModels) ? APP_CONFIG.uploadModels : [];
    const UPLOAD_MODEL_MAP = Object.fromEntries(
      UPLOAD_MODEL_OPTIONS.map(function (item) {
        return [item.value, item];
      })
    );
    const UPLOAD_PROMPT_UI = {
      label: '检测提示词',
      placeholder: 'person, motorcycle, bicycle, car, bus, truck',
      help: '英文逗号分隔。适合对人员、车辆、摩托车等目标进行快速提示词筛查。',
      uploadDefaultConf: 0.10,
      defaultClasses: 'person,motorcycle,bicycle,car,bus,truck',
      presets: [
        { label: '交通场景', value: 'person,motorcycle,bicycle,car,bus,truck' },
        { label: '反光衣人员', value: 'person wearing reflective vest,worker in reflective vest,traffic police in reflective vest' },
        { label: '摩托车', value: 'motorcycle' },
        { label: '人员', value: 'person' }
      ]
    };
    const UPLOAD_FILTER_UI = {
      label: '类别过滤',
      placeholder: '0,1,2 或类别名',
      help: '自定义模型使用类别索引或类别名过滤，留空表示不过滤。',
      uploadDefaultConf: 0.80,
      defaultClasses: '',
      presets: []
    };

    const STATUS_UI = {
      queued: { label: '排队中', badge: 'bg-slate-100 text-slate-700 ring-slate-200', bar: 'bg-slate-400' },
      running: { label: '运行中', badge: 'bg-sky-100 text-sky-700 ring-sky-200', bar: 'bg-sky-500' },
      done: { label: '已完成', badge: 'bg-emerald-100 text-emerald-700 ring-emerald-200', bar: 'bg-emerald-500' },
      error: { label: '失败', badge: 'bg-rose-100 text-rose-700 ring-rose-200', bar: 'bg-rose-500' },
      canceled: { label: '已取消', badge: 'bg-slate-200 text-slate-700 ring-slate-300', bar: 'bg-slate-500' },
      interrupted: { label: '已中断', badge: 'bg-amber-100 text-amber-700 ring-amber-200', bar: 'bg-amber-500' }
    };

    function modelDisplay(modelKey) {
      if (UPLOAD_MODEL_MAP[modelKey] && UPLOAD_MODEL_MAP[modelKey].short_label) {
        return UPLOAD_MODEL_MAP[modelKey].short_label;
      }
      if (modelKey === 'special') return '专项风险事件识别';
      if (modelKey === 'general') return '通用人车要素识别';
      return modelKey || '识别模型';
    }

    function statusMeta(status) {
      return STATUS_UI[status] || STATUS_UI.running;
    }

    function checkAllHours(checked) {
      document.querySelectorAll('input[name="hours"]').forEach(function (box) {
        box.checked = checked;
      });
    }

    function syncConfValue() {
      const range = document.getElementById('confRange');
      const value = document.getElementById('confValue');
      value.textContent = Number(range.value).toFixed(2);
    }

    function applyModelUI() {
      const modelKey = document.getElementById('model_key').value;
      const config = MODEL_UI[modelKey] || MODEL_UI.general;
      const label = document.getElementById('classesLabel');
      const input = document.getElementById('classes');
      const help = document.getElementById('classesHelp');
      const panel = document.getElementById('presetPanel');
      const box = document.getElementById('presetButtons');

      label.textContent = config.label;
      input.placeholder = config.placeholder;
      input.disabled = false;
      help.textContent = config.help;

      if (config.presets.length === 0) {
        panel.classList.add('hidden');
        box.innerHTML = '';
        return;
      }

      panel.classList.remove('hidden');
      box.innerHTML = config.presets.map(function (preset) {
        return '<button type="button" class="rounded-full border border-teal-200 bg-white px-3 py-1 text-xs font-medium text-teal-700 transition hover:border-teal-400 hover:bg-teal-50" data-value="' + preset.value + '">' + preset.label + '</button>';
      }).join('');

      box.querySelectorAll('button[data-value]').forEach(function (button) {
        button.addEventListener('click', function () {
          input.value = button.getAttribute('data-value') || '';
          input.focus();
        });
      });
    }

    function getUploadModelConfig(modelKey) {
      var meta = UPLOAD_MODEL_MAP[modelKey] || null;
      var base = meta && meta.ui_mode === 'filter' ? UPLOAD_FILTER_UI : UPLOAD_PROMPT_UI;
      return {
        label: base.label,
        placeholder: base.placeholder,
        help: meta && meta.description ? meta.description : base.help,
        uploadDefaultConf: meta && typeof meta.default_conf === 'number' ? meta.default_conf : base.uploadDefaultConf,
        defaultClasses: meta && meta.default_classes ? meta.default_classes : base.defaultClasses,
        presets: base.presets || [],
        uiMode: meta && meta.ui_mode ? meta.ui_mode : 'prompt'
      };
    }

    function formatPercent(processed, total) {
      if (!total) return 0;
      return Math.min(100, Math.max(0, Math.floor(processed * 100 / total)));
    }

    function setProgressState(job) {
      const processed = job.processed || 0;
      const total = job.total || 0;
      const kept = job.kept || 0;
      const notfound = job.notfound || 0;
      const failed = job.failed || 0;
      const pct = formatPercent(processed, total);
      const meta = statusMeta(job.status || 'running');

      document.getElementById('progressText').textContent = '已处理 ' + processed + ' / ' + total;
      document.getElementById('progressSubtext').textContent =
        '模型：' + modelDisplay(job.model_key || 'general') + ' · 保留 ' + kept + ' · 404 ' + notfound + ' · 失败 ' + failed;

      const bar = document.getElementById('progressBar');
      bar.style.width = pct + '%';
      bar.className = 'h-3 rounded-full transition-all duration-300 ' + meta.bar;

      const badge = document.getElementById('progressStatus');
      badge.textContent = meta.label;
      badge.className = 'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ' + meta.badge;
    }

    function clearLastJob() {
      try {
        localStorage.removeItem('special_last_job');
      } catch (e) {}
    }

    function cancelJob(jobId) {
      if (!jobId) return;
      fetch((APP_URLS.cancelJob || '').replace('__J__', jobId), { method: 'POST' })
        .finally(function () {
          refreshJobs();
        });
    }

    function cancelCurrent() {
      let jobId = null;
      try {
        jobId = localStorage.getItem('special_last_job');
      } catch (e) {}
      if (!jobId) {
        alert('当前没有可取消的任务');
        return;
      }
      cancelJob(jobId);
    }

    function renderRunningJobs(items) {
      const box = document.getElementById('jobsInfo');
      if (!items || items.length === 0) {
        box.innerHTML =
          '<div class="task-item" style="opacity:0.5;">' +
            '<div class="task-indicator" style="background:#8aaac8;"></div>' +
            '<div class="task-item-body">' +
              '<div class="task-item-name">暂无运行中的任务</div>' +
              '<div class="task-item-meta">等待任务启动...</div>' +
            '</div>' +
          '</div>';
        return;
      }

      box.innerHTML = items.map(function (job) {
        const pct   = formatPercent(job.processed || 0, job.total || 0);
        const meta  = statusMeta(job.status || 'running');
        const isRun = (job.status === 'running');
        const dotColor = isRun ? '#3b82f6' : '#8aaac8';
        const spinClass = isRun ? ' spin' : '';
        return (
          '<div class="task-item">' +
            '<div class="task-indicator' + spinClass + '" style="background:' + dotColor + ';"></div>' +
            '<div class="task-item-body">' +
              '<div class="task-item-name">' + (job.id || '') + '</div>' +
              '<div class="task-item-meta">' + modelDisplay(job.model_key || 'general') + ' · ' + (job.processed || 0) + '/' + (job.total || 0) + '</div>' +
              '<div class="task-bar-outer">' +
                '<div class="task-bar-inner" style="width:' + pct + '%;"></div>' +
              '</div>' +
            '</div>' +
            '<div style="font-size:11px; color:#2563eb; font-weight:700; flex-shrink:0; padding-left:6px;">' + pct + '%</div>' +
          '</div>'
        );
      }).join('');
    }

    var _refreshTimer = null;
    function refreshJobs(btn) {
      if (btn && btn.classList) btn.classList.add('mr-btn--loading');
      if (_refreshTimer) clearTimeout(_refreshTimer);
      fetch(APP_URLS.listJobs || '/jobs')
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (!data.ok) return;
          // Update quick stats bar
          var running = data.running || [];
          var runningCount = data.running_count || running.length || 0;
          var qsRun  = document.getElementById('runningCount');
          if (qsRun)  qsRun.textContent  = runningCount;
          var qsDone   = document.getElementById('qs-done');
          var qsPend   = document.getElementById('qs-pending');
          var qsKept   = document.getElementById('qs-kept');
          var qsFailed = document.getElementById('qs-failed');
          if (qsDone   && data.done_count   !== undefined) qsDone.textContent   = data.done_count;
          if (qsPend   && data.queue_count  !== undefined) qsPend.textContent   = data.queue_count;
          if (qsKept   && data.kept_count   !== undefined) qsKept.textContent   = data.kept_count;
          if (qsFailed && data.failed_count !== undefined) qsFailed.textContent = data.failed_count;
          renderRunningJobs(running);
        })
        .catch(function () {})
        .finally(function () {
          if (btn && btn.classList) btn.classList.remove('mr-btn--loading');
          _refreshTimer = window.setTimeout(refreshJobs, 3000);
        });
    }

    function poll(jobId) {
      fetch((APP_URLS.jobProgress || '').replace('__J__', jobId))
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (!data.ok) return;
          const job = data.job || {};
          document.getElementById('progressBox').classList.remove('hidden');
          setProgressState(job);

          if (job.status === 'done') {
            const zipUrl = (APP_URLS.downloadZip || '').replace('__J__', jobId);
            const summaryUrl = (APP_URLS.downloadSummary || '').replace('__J__', jobId);
            document.getElementById('downloadLinks').classList.remove('hidden');
            document.getElementById('zipLink').href = zipUrl;
            document.getElementById('sumLink').href = summaryUrl;
            clearLastJob();
            loadResultGallery('database', jobId);
          } else if (job.status === 'canceled') {
            clearLastJob();
            alert('任务已取消');
          } else if (job.status === 'interrupted') {
            clearLastJob();
            alert('任务因服务重启而中断');
          } else if (job.status === 'error') {
            clearLastJob();
            alert('任务失败：' + (job.message || '未知错误'));
          } else {
            window.setTimeout(function () { poll(jobId); }, 1000);
          }
        })
        .catch(function () {
          window.setTimeout(function () { poll(jobId); }, 1500);
        });
    }

    function startJob(event) {
      if (event) event.preventDefault();
      const form = document.getElementById('jobForm');
      const data = new FormData(form);

      fetch(APP_URLS.startJob || '/start', {
        method: 'POST',
        body: data
      })
        .then(function (resp) { return resp.json(); })
        .then(function (payload) {
          if (!payload.ok) {
            alert(payload.error || '启动任务失败');
            return;
          }
          const jobId = payload.job_id;
          try {
            localStorage.setItem('special_last_job', jobId);
          } catch (e) {}
          document.getElementById('progressBox').classList.remove('hidden');
          document.getElementById('downloadLinks').classList.add('hidden');
          resetResultState('database');
          setProgressState({
            status: 'running',
            model_key: document.getElementById('model_key').value,
            total: payload.total || 0,
            processed: 0,
            kept: 0,
            notfound: 0,
            failed: 0
          });
          poll(jobId);
        })
        .catch(function () {
          alert('网络错误，任务未启动');
        });
      return false;
    }

    // ==================== UPLOAD TAB ====================

    var TAB_META = {
      Database:   { title: '数据监测与研判', subtitle: '查询 PostgreSQL 数据源，对已采集的目标图像执行 AI 检测与结果研判', btnLabel: '▶ 新建检测任务' },
      Upload:   { title: '现场素材研判',   subtitle: '上传视频或图片，直接在系统内执行 AI 检测分析', btnLabel: '▶ 上传素材' },
      Face:     { title: '人脸识别与人员核验', subtitle: '识别结果人员与底库交叉比对，后台自动触发流转', btnLabel: '同步人脸库' },
      Train:    { title: '模型自训练',     subtitle: '将业务结果数据回流训练集，沉淀自定义识别能力', btnLabel: '创建训练任务' },
      Dispatch: { title: '任务下发',       subtitle: '向现场管理单元推送通知，提高处置响应速度', btnLabel: '下发选中' },
      Diagnostics: { title: '任务队列诊断', subtitle: '查看 SQLite 持久化队列、Worker 执行状态和陈旧任务风险', btnLabel: '刷新诊断' }
    };

    function submitFormById(formId) {
      var form = document.getElementById(formId);
      if (!form) return false;
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
      return true;
    }

    function runTabPrimaryAction(tab) {
      if (tab === 'Database') return submitFormById('jobForm');
      if (tab === 'Upload') return submitFormById('uploadForm');
      if (tab === 'Train') return submitFormById('trainRunForm');
      if (tab === 'Face' && typeof runFaceLibraryAction === 'function') {
        runFaceLibraryAction('global', 'sync');
        return true;
      }
      if (tab === 'Dispatch' && typeof sendDispatchTasks === 'function') {
        sendDispatchTasks();
        return true;
      }
      if (tab === 'Diagnostics' && typeof refreshTaskQueueDiagnostics === 'function') {
        refreshTaskQueueDiagnostics();
        return true;
      }
      return false;
    }

    function switchTab(tab) {
      var panels = {
        Database: document.getElementById('tabDatabase'),
        Upload: document.getElementById('tabUpload'),
        Train: document.getElementById('tabTrain'),
        Dispatch: document.getElementById('tabDispatch'),
        Face: document.getElementById('tabFace'),
        Diagnostics: document.getElementById('tabDiagnostics')
      };
      var buttons = {
        Database: document.getElementById('tabBtnDatabase'),
        Upload: document.getElementById('tabBtnUpload'),
        Train: document.getElementById('tabBtnTrain'),
        Dispatch: document.getElementById('tabBtnDispatch'),
        Face: document.getElementById('tabBtnFace'),
        Diagnostics: document.getElementById('tabBtnDiagnostics')
      };
      Object.keys(panels).forEach(function (key) {
        if (panels[key]) panels[key].classList.add('hidden');
        if (buttons[key]) {
          buttons[key].classList.remove('active');
          buttons[key].setAttribute('aria-current', 'false');
        }
      });
      if (panels[tab]) panels[tab].classList.remove('hidden');
      if (buttons[tab]) {
        buttons[tab].classList.add('active');
        buttons[tab].setAttribute('aria-current', 'page');
      }
      // Update content header
      var meta = TAB_META[tab] || {};
      var titleEl = document.getElementById('contentTitle');
      var subEl   = document.getElementById('contentSubtitle');
      var btnEl   = document.getElementById('headerPrimaryBtn');
      if (titleEl) titleEl.textContent = meta.title || tab;
      if (subEl)   subEl.textContent   = meta.subtitle || '';
      if (btnEl) {
        btnEl.textContent = meta.btnLabel || '';
        btnEl.onclick = function () {
          runTabPrimaryAction(tab);
        };
      }
      if (tab === 'Face') {
        refreshFaceTab();
      } else if (tab === 'Train') {
        refreshTrainTab();
      } else if (tab === 'Dispatch' && typeof refreshDispatchTab === 'function') {
        refreshDispatchTab();
      } else if (tab === 'Diagnostics' && typeof refreshTaskQueueDiagnostics === 'function') {
        refreshTaskQueueDiagnostics();
      }
      if (typeof setTaskQueueAutoRefresh === 'function') {
        var auto = document.getElementById('diagAutoRefresh');
        setTaskQueueAutoRefresh(tab === 'Diagnostics' && (!auto || auto.checked));
      }
      try { localStorage.setItem('special_active_tab', tab); } catch (e) {}
    }

    function populateUploadModelSelect() {
      var select = document.getElementById('uploadModelKey');
      if (!select) return;
      if (!UPLOAD_MODEL_OPTIONS.length) {
        select.innerHTML = '<option value="" selected>未发现可用模型</option>';
        select.disabled = true;
        return;
      }
      select.disabled = false;
      select.innerHTML = UPLOAD_MODEL_OPTIONS.map(function (item) {
        return '<option value="' + item.value + '">' + item.label + '</option>';
      }).join('');
      var defaultValue = APP_CONFIG.uploadModelDefault || '';
      if (defaultValue && UPLOAD_MODEL_MAP[defaultValue]) {
        select.value = defaultValue;
      }
      if (!select.value && UPLOAD_MODEL_OPTIONS[0]) {
        select.value = UPLOAD_MODEL_OPTIONS[0].value;
      }
    }

    function applyUploadModelUI() {
      var modelKey = document.getElementById('uploadModelKey').value;
      var meta = UPLOAD_MODEL_MAP[modelKey] || null;
      var config = getUploadModelConfig(modelKey);
      var label = document.getElementById('uploadClassesLabel');
      var input = document.getElementById('uploadClasses');
      var help = document.getElementById('uploadClassesHelp');
      var modelHint = document.getElementById('uploadModelHint');
      if (!modelHint) {
        modelHint = document.createElement('p');
        modelHint.id = 'uploadModelHint';
        modelHint.className = 'mt-2 text-xs leading-6 text-slate-500';
        document.getElementById('uploadModelKey').insertAdjacentElement('afterend', modelHint);
      }
      var panel = document.getElementById('uploadPresetPanel');
      var box = document.getElementById('uploadPresetButtons');
      var confRange = document.getElementById('uploadConfRange');
      var confValue = document.getElementById('uploadConfValue');
      var previousMode = input.dataset.uiMode || '';
      var nextMode = config.uiMode || 'prompt';
      label.textContent = config.label;
      input.placeholder = config.placeholder;
      help.textContent = config.help;
      if (modelHint) {
        modelHint.textContent = meta && meta.description ? meta.description : '';
      }
      confRange.value = Number(config.uploadDefaultConf || 0.80).toFixed(2);
      confValue.textContent = confRange.value;
      if (nextMode === 'prompt') {
        if (!input.value.trim() || previousMode !== 'prompt') {
          input.value = config.defaultClasses || '';
        }
      } else if (previousMode !== 'filter') {
        input.value = '';
      }
      input.dataset.uiMode = nextMode;
      if (config.presets.length === 0) {
        panel.classList.add('hidden');
        box.innerHTML = '';
        return;
      }
      panel.classList.remove('hidden');
      box.innerHTML = config.presets.map(function (preset) {
        return '<button type="button" class="rounded-full border border-teal-200 bg-white px-3 py-1 text-xs font-medium text-teal-700 transition hover:border-teal-400 hover:bg-teal-50" data-value="' + preset.value + '">' + preset.label + '</button>';
      }).join('');
      box.querySelectorAll('button[data-value]').forEach(function (button) {
        button.addEventListener('click', function () {
          input.value = button.getAttribute('data-value') || '';
          input.focus();
        });
      });
    }

    function syncUploadConfValue() {
      document.getElementById('uploadConfValue').textContent = Number(document.getElementById('uploadConfRange').value).toFixed(2);
    }

    function onUploadFileChange(input) {
      var file = input.files && input.files[0];
      if (!file) return;
      var ext = file.name.split('.').pop().toLowerCase();
      var isVideo = ['mp4', 'avi', 'mov', 'mkv', 'mpg', 'mpeg'].includes(ext);
      document.getElementById('uploadFileName').textContent = file.name;
      document.getElementById('uploadFileSize').textContent = (file.size / 1024 / 1024).toFixed(1) + ' MB';
      document.getElementById('uploadFileInfo').classList.remove('hidden');
      document.getElementById('frameIntervalRow').classList.toggle('hidden', !isVideo);
    }

    function setUploadProgressState(job) {
      var processed = job.processed || 0;
      var total = job.total || 0;
      var kept = job.kept || 0;
      var pct = total ? Math.min(100, Math.floor(processed * 100 / total)) : 0;
      var meta = statusMeta(job.status || 'running');
      document.getElementById('uploadProgressText').textContent = '已处理 ' + processed + ' / ' + total;
      document.getElementById('uploadProgressSubtext').textContent =
        '模型：' + modelDisplay(job.model_key || 'general') + ' · 保留 ' + kept;
      var bar = document.getElementById('uploadProgressBar');
      bar.style.width = pct + '%';
      bar.className = 'h-3 rounded-full transition-all duration-300 ' + meta.bar;
      var badge = document.getElementById('uploadProgressStatus');
      badge.textContent = meta.label;
      badge.className = 'inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ring-1 ring-inset ' + meta.badge;
    }

    function pollUpload(jobId) {
      fetch('/upload/progress/' + jobId)
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (!data.ok) return;
          var job = data.job || {};
          document.getElementById('uploadProgressBox').classList.remove('hidden');
          setUploadProgressState(job);
          if (job.status === 'done') {
            document.getElementById('uploadDownloadLinks').classList.remove('hidden');
            document.getElementById('uploadZipLink').href = '/upload/download/' + jobId;
            try { localStorage.removeItem('special_upload_job'); } catch (e) {}
            loadResultGallery('upload', jobId);
          } else if (job.status === 'canceled') {
            try { localStorage.removeItem('special_upload_job'); } catch (e) {}
            alert('任务已取消');
          } else if (job.status === 'error') {
            try { localStorage.removeItem('special_upload_job'); } catch (e) {}
            alert('任务失败：' + (job.message || '未知错误'));
          } else {
            window.setTimeout(function () { pollUpload(jobId); }, 1000);
          }
        })
        .catch(function () { window.setTimeout(function () { pollUpload(jobId); }, 1500); });
    }

    function startUploadJob(event) {
      if (event) event.preventDefault();
      var fileInput = document.getElementById('uploadFile');
      var modelSelect = document.getElementById('uploadModelKey');
      if (!fileInput.files || !fileInput.files[0]) {
        alert('请先选择文件');
        return false;
      }
      if (!modelSelect || !modelSelect.value) {
        alert('未发现可用模型');
        return false;
      }
      var form = document.getElementById('uploadForm');
      var data = new FormData(form);
      document.getElementById('uploadProgressBox').classList.remove('hidden');
      document.getElementById('uploadDownloadLinks').classList.add('hidden');
      resetResultState('upload');
      setUploadProgressState({ status: 'running', total: 0, processed: 0, kept: 0, model_key: document.getElementById('uploadModelKey').value });
      fetch('/upload/start', { method: 'POST', body: data })
        .then(function (resp) {
          return resp.text().then(function (text) {
            var payload = {};
            try {
              payload = text ? JSON.parse(text) : {};
            } catch (e) {
              payload = {};
            }
            payload.__http_status = resp.status;
            payload.__http_ok = resp.ok;
            return payload;
          });
        })
        .then(function (payload) {
          if (!payload.ok || payload.__http_ok === false) {
            if (payload.__http_status === 413) {
              alert(payload.error || '上传文件过大，请压缩后重试或调大 MAX_UPLOAD_BYTES。');
              return;
            }
            alert(payload.error || ('启动失败，HTTP ' + (payload.__http_status || 'unknown')));
            return;
          }
          try { localStorage.setItem('special_upload_job', payload.job_id); } catch (e) {}
          pollUpload(payload.job_id);
        })
        .catch(function () { alert('网络错误，任务未启动'); });
      return false;
    }

    function cancelUploadJob() {
      var jobId = null;
      try { jobId = localStorage.getItem('special_upload_job'); } catch (e) {}
      if (!jobId) { alert('当前没有可取消的上传任务'); return; }
      fetch('/upload/cancel/' + jobId, { method: 'POST' }).catch(function () {});
    }


