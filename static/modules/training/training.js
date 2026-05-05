    const TRAIN_BASE_MODEL_OPTIONS = Array.isArray(APP_CONFIG.trainBaseModels) ? APP_CONFIG.trainBaseModels : [];
    const TRAIN_JOB_STATE = { items: [], loading: false, submitting: false, pollTimer: null };
    const TRAIN_PRESETS = {
      quick: {
        label: '快速验证',
        epochs: 30,
        imgsz: 640,
        batchSize: 4,
        model: 'yolo26n.pt',
        hint: '适合先把训练链路跑通，优先验证数据集和标注质量。'
      },
      standard: {
        label: '标准训练',
        epochs: 80,
        imgsz: 640,
        batchSize: 8,
        model: 'yolo26s.pt',
        hint: '适合数据集较完整、需要兼顾精度和稳定性的专项模型训练。'
      },
      lowmem: {
        label: '低算力模式',
        epochs: 50,
        imgsz: 512,
        batchSize: 2,
        model: 'yolo26n.pt',
        hint: '适合私有网络低算力电脑，优先降低资源占用，先把流程稳定跑通。'
      }
    };
    const TRAIN_JOB_STATUS_UI = {
      queued: { label: '排队中', badge: 'bg-slate-100 text-slate-700 ring-slate-200' },
      running: { label: '准备中', badge: 'bg-sky-100 text-sky-700 ring-sky-200' },
      done: { label: '已生成', badge: 'bg-emerald-100 text-emerald-700 ring-emerald-200' },
      error: { label: '失败', badge: 'bg-rose-100 text-rose-700 ring-rose-200' }
    };

    function setTrainRunFeedback(message, tone) {
      var box = document.getElementById('trainRunFeedback');
      if (!box) return;
      if (!message) {
        box.className = 'hidden';
        box.textContent = '';
        return;
      }
      box.textContent = message;
      box.className = 'rounded-2xl border px-4 py-3 text-sm';
      if (tone === 'error') {
        box.classList.add('border-rose-200', 'bg-rose-50', 'text-rose-700');
      } else {
        box.classList.add('border-emerald-200', 'bg-emerald-50', 'text-emerald-700');
      }
    }

    function getTrainPresetConfig() {
      var select = document.getElementById('trainPresetSelect');
      var key = select && select.value ? select.value : 'quick';
      return TRAIN_PRESETS[key] || TRAIN_PRESETS.quick;
    }

    function getTrainBaseModelLabel(modelValue) {
      var matched = TRAIN_BASE_MODEL_OPTIONS.find(function (item) {
        return item.value === modelValue;
      });
      return matched && matched.label ? matched.label : (modelValue || '--');
    }

    function renderTrainBaseModelOptions() {
      var select = document.getElementById('trainBaseModel');
      if (!select) return;

      if (!TRAIN_BASE_MODEL_OPTIONS.length) {
        select.innerHTML = '<option value="">未发现可用训练底模</option>';
        select.disabled = true;
        return;
      }

      var previousValue = select.value;
      select.innerHTML = TRAIN_BASE_MODEL_OPTIONS.map(function (item) {
        return '<option value="' + escapeHtml(item.value || '') + '">' + escapeHtml(item.label || item.value || '') + '</option>';
      }).join('');

      var matched = TRAIN_BASE_MODEL_OPTIONS.some(function (item) {
        return item.value === previousValue;
      });
      if (matched) {
        select.value = previousValue;
      } else {
        var preset = getTrainPresetConfig();
        var preferred = preset.model || '';
        var exists = TRAIN_BASE_MODEL_OPTIONS.some(function (item) {
          return item.value === preferred;
        });
        select.value = exists ? preferred : (TRAIN_BASE_MODEL_OPTIONS[0].value || '');
      }
      select.disabled = false;
    }

    function renderTrainRunDatasetOptions(items) {
      var select = document.getElementById('trainRunDataset');
      var submitBtn = document.getElementById('trainRunSubmit');
      if (!select) return;

      var previousValue = select.value;
      var hasItems = !!(items && items.length);
      if (!hasItems) {
        select.innerHTML = '<option value="">请先创建数据集</option>';
        select.disabled = true;
        if (submitBtn) submitBtn.disabled = true;
        return;
      }

      select.innerHTML = items.map(function (item) {
        var labeled = Number(item.labeled_count || 0);
        var total = Number(item.image_count || 0);
        var reviewed = Number(item.reviewed_count || 0);
        var suffix = '（已标注 ' + labeled + '/' + total + ' · 已复核 ' + reviewed + '）';
        return '<option value="' + escapeHtml(item.id || '') + '">' + escapeHtml((item.name || item.id || '') + ' ' + suffix) + '</option>';
      }).join('');

      var matched = items.some(function (item) {
        return item.id === previousValue;
      });
      if (matched) {
        select.value = previousValue;
      } else if (items[0]) {
        select.value = items[0].id;
      }
      select.disabled = false;
      if (submitBtn) submitBtn.disabled = TRAIN_JOB_STATE.submitting || !TRAIN_BASE_MODEL_OPTIONS.length;
    }

    function applyTrainPreset() {
      var preset = getTrainPresetConfig();
      var epochs = document.getElementById('trainEpochs');
      var imgsz = document.getElementById('trainImgsz');
      var batch = document.getElementById('trainBatchSize');
      var hint = document.getElementById('trainPresetHint');
      var baseModel = document.getElementById('trainBaseModel');

      if (epochs) epochs.value = String(preset.epochs);
      if (imgsz) imgsz.value = String(preset.imgsz);
      if (batch) batch.value = String(preset.batchSize);
      if (hint) hint.textContent = preset.hint;
      if (baseModel && !baseModel.disabled) {
        var exists = TRAIN_BASE_MODEL_OPTIONS.some(function (item) {
          return item.value === preset.model;
        });
        if (exists) {
          baseModel.value = preset.model;
        }
      }
    }

    function renderTrainJobs(items) {
      var box = document.getElementById('trainJobList');
      if (!box) return;
      if (!items || !items.length) {
        box.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">当前还没有训练任务。完成标注后可以先创建一个训练任务骨架。</div>';
        return;
      }

      box.innerHTML = items.map(function (item) {
        var meta = TRAIN_JOB_STATUS_UI[item.status] || TRAIN_JOB_STATUS_UI.queued;
        var createdAt = item.created_ts ? new Date(item.created_ts * 1000).toLocaleString('zh-CN') : '--';
        var runDir = item.run_dir || '--';
        var message = item.message || '--';
        var confirmedBadge = item.confirmed_only
          ? '<span class="rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset bg-teal-50 text-teal-700 ring-teal-200">仅已确认样本</span>'
          : '';
        var reportAction = item.report_url
          ? '<a href="' + escapeHtml(item.report_url) + '" target="_blank" rel="noreferrer" class="inline-flex items-center justify-center rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50">查看评估</a>'
          : '';
        return (
          '<div class="rounded-3xl border border-slate-200 bg-white/90 p-4 shadow-sm shadow-slate-200/60">' +
            '<div class="flex items-start justify-between gap-3">' +
              '<div class="min-w-0 flex-1">' +
                '<div class="flex flex-wrap items-center gap-2">' +
                  '<div class="truncate text-sm font-semibold text-slate-900">' + escapeHtml(item.dataset_name || item.dataset_id || item.id || '') + '</div>' +
                  '<span class="rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset ' + meta.badge + '">' + meta.label + '</span>' +
                  confirmedBadge +
                '</div>' +
                '<div class="mt-2 break-all font-mono text-xs text-slate-400">' + escapeHtml(item.id || '') + '</div>' +
              '</div>' +
              '<div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-2 text-right text-xs text-slate-500">' +
                '<div>底模：' + escapeHtml(getTrainBaseModelLabel(item.base_model || '')) + '</div>' +
                '<div class="mt-1">预设：' + escapeHtml((TRAIN_PRESETS[item.preset_key || ''] || {}).label || item.preset_key || '--') + '</div>' +
              '</div>' +
            '</div>' +
            '<div class="mt-4 grid gap-3 sm:grid-cols-3">' +
              '<div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3"><div class="text-xs text-slate-400">Epochs</div><div class="mt-1 font-semibold text-slate-800">' + escapeHtml(item.epochs || 0) + '</div></div>' +
              '<div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3"><div class="text-xs text-slate-400">imgsz</div><div class="mt-1 font-semibold text-slate-800">' + escapeHtml(item.imgsz || 0) + '</div></div>' +
              '<div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3"><div class="text-xs text-slate-400">Batch</div><div class="mt-1 font-semibold text-slate-800">' + escapeHtml(item.batch_size || 0) + '</div></div>' +
            '</div>' +
            '<div class="mt-4 rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm leading-6 text-slate-600">' + escapeHtml(message) + '</div>' +
            '<div class="mt-4 space-y-2 text-xs text-slate-500">' +
              '<div>创建时间：' + escapeHtml(createdAt) + '</div>' +
              '<div class="break-all">运行目录：' + escapeHtml(runDir) + '</div>' +
              (reportAction ? '<div class="pt-2">' + reportAction + '</div>' : '') +
            '</div>' +
          '</div>'
        );
      }).join('');
    }

    function refreshTrainJobs() {
      var box = document.getElementById('trainJobList');
      if (TRAIN_JOB_STATE.pollTimer) {
        window.clearTimeout(TRAIN_JOB_STATE.pollTimer);
        TRAIN_JOB_STATE.pollTimer = null;
      }
      TRAIN_JOB_STATE.loading = true;
      if (box && !TRAIN_JOB_STATE.items.length) {
        box.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">正在加载训练任务...</div>';
      }

      fetch('/train/jobs')
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (!data.ok) {
            throw new Error(data.error || '加载训练任务失败');
          }
          TRAIN_JOB_STATE.items = data.items || [];
          renderTrainJobs(TRAIN_JOB_STATE.items);
          var hasPending = TRAIN_JOB_STATE.items.some(function (item) {
            return item.status === 'queued' || item.status === 'running';
          });
          if (hasPending) {
            TRAIN_JOB_STATE.pollTimer = window.setTimeout(refreshTrainJobs, 3000);
          }
        })
        .catch(function (err) {
          if (box && !TRAIN_JOB_STATE.items.length) {
            box.innerHTML = '<div class="rounded-2xl border border-dashed border-rose-200 bg-rose-50 px-4 py-6 text-sm text-rose-700">' + escapeHtml(err.message || '加载训练任务失败') + '</div>';
          }
        })
        .finally(function () {
          TRAIN_JOB_STATE.loading = false;
        });
    }

    function createTrainJob(event) {
      if (event) event.preventDefault();
      var datasetSelect = document.getElementById('trainRunDataset');
      var baseModel = document.getElementById('trainBaseModel');
      var presetSelect = document.getElementById('trainPresetSelect');
      var epochs = document.getElementById('trainEpochs');
      var imgsz = document.getElementById('trainImgsz');
      var batch = document.getElementById('trainBatchSize');
      var confirmedOnly = document.getElementById('trainConfirmedOnly');
      var submitBtn = document.getElementById('trainRunSubmit');

      if (!datasetSelect || !baseModel || !presetSelect || !epochs || !imgsz || !batch || !submitBtn) {
        return false;
      }
      if (!datasetSelect.value) {
        setTrainRunFeedback('请先选择一个已准备好的数据集。', 'error');
        return false;
      }
      if (!baseModel.value) {
        setTrainRunFeedback('当前没有可用的训练底模。', 'error');
        return false;
      }

      TRAIN_JOB_STATE.submitting = true;
      submitBtn.disabled = true;
      setTrainRunFeedback('', '');

      fetch('/train/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          dataset_id: datasetSelect.value,
          base_model: baseModel.value,
          preset_key: presetSelect.value || 'quick',
          epochs: Number(epochs.value || 0),
          imgsz: Number(imgsz.value || 0),
          batch_size: Number(batch.value || 0),
          confirmed_only: !!(confirmedOnly && confirmedOnly.checked)
        })
      })
        .then(function (resp) {
          return resp.text().then(function (text) {
            var payload = {};
            try {
              payload = text ? JSON.parse(text) : {};
            } catch (e) {
              payload = {};
            }
            payload.__http_ok = resp.ok;
            payload.__http_status = resp.status;
            return payload;
          });
        })
        .then(function (payload) {
          if (!payload.ok || payload.__http_ok === false) {
            throw new Error(payload.error || ('创建训练任务失败，HTTP ' + (payload.__http_status || 'unknown')));
          }
          if (payload.job) {
            TRAIN_JOB_STATE.items.unshift(payload.job);
          }
          renderTrainJobs(TRAIN_JOB_STATE.items);
          setTrainRunFeedback(payload.message || '训练任务骨架已创建。', 'success');
        })
        .catch(function (err) {
          setTrainRunFeedback(err.message || '创建训练任务失败', 'error');
        })
        .finally(function () {
          TRAIN_JOB_STATE.submitting = false;
          submitBtn.disabled = !TRAIN_BASE_MODEL_OPTIONS.length || !datasetSelect.value;
        });
      return false;
    }
