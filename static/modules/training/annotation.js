    const DATASET_WORKSPACE_STATE = {
      datasetId: '',
      mode: 'browse',
      loading: false,
      dataset: null,
      items: [],
      selectedAssetId: '',
      showOnlyUnlabeled: false,
      showOnlyLowQuality: false,
      reviewFilter: 'all'
    };

    const ANNOTATION_STATE = {
      datasetId: '',
      assetId: '',
      requestKey: '',
      loading: false,
      saving: false,
      dirty: false,
      boxes: [],
      selectedIndex: -1,
      drawing: false,
      draftBox: null,
      imageWidth: 0,
      imageHeight: 0
    };
    const ANNOTATION_ZOOM_MIN = 25;
    const ANNOTATION_ZOOM_MAX = 250;
    const ANNOTATION_ZOOM_DEFAULT = 25;
    const ANNOTATION_VIEW_STATE = {
      zoomPercent: ANNOTATION_ZOOM_DEFAULT
    };

    const AUTO_ANNOTATION_STATE = {
      running: false,
      jobId: '',
      pollTimer: null,
      jobsLoading: false,
      jobs: []
    };
    const AUTO_ANNOTATE_JOB_STATUS_UI = {
      queued: { label: '排队中', badge: 'bg-slate-100 text-slate-700 ring-slate-200' },
      running: { label: '进行中', badge: 'bg-sky-100 text-sky-700 ring-sky-200' },
      done: { label: '已完成', badge: 'bg-emerald-100 text-emerald-700 ring-emerald-200' },
      error: { label: '失败', badge: 'bg-rose-100 text-rose-700 ring-rose-200' }
    };
    const REVIEW_STATUS_UI = {
      pending: { label: '待复核', badge: 'bg-amber-50 text-amber-700 ring-amber-200' },
      reviewed: { label: '已复核', badge: 'bg-sky-50 text-sky-700 ring-sky-200' },
      confirmed: { label: '已确认', badge: 'bg-emerald-50 text-emerald-700 ring-emerald-200' }
    };
    const AUTO_ANNOTATION_MODEL_OPTIONS = Array.isArray(UPLOAD_MODEL_OPTIONS) ? UPLOAD_MODEL_OPTIONS.slice() : [];

    function setAnnotationFeedback(message, tone) {
      var box = document.getElementById('annotationFeedback');
      if (!box) return;
      if (!message) {
        box.className = 'mt-4 hidden';
        box.textContent = '';
        return;
      }
      box.textContent = message;
      box.className = 'mt-4 rounded-2xl border px-4 py-3 text-sm';
      if (tone === 'error') {
        box.classList.add('border-rose-200', 'bg-rose-50', 'text-rose-700');
      } else if (tone === 'success') {
        box.classList.add('border-emerald-200', 'bg-emerald-50', 'text-emerald-700');
      } else {
        box.classList.add('border-slate-200', 'bg-slate-50', 'text-slate-600');
      }
    }

    function setAutoAnnotationFeedback(message, tone) {
      var box = document.getElementById('annotationAutoFeedback');
      if (!box) return;
      if (!message) {
        box.className = 'mt-4 hidden';
        box.textContent = '';
        return;
      }
      box.textContent = message;
      box.className = 'mt-4 rounded-2xl border px-4 py-3 text-sm';
      if (tone === 'error') {
        box.classList.add('border-rose-200', 'bg-rose-50', 'text-rose-700');
      } else if (tone === 'success') {
        box.classList.add('border-emerald-200', 'bg-emerald-50', 'text-emerald-700');
      } else {
        box.classList.add('border-slate-200', 'bg-slate-50', 'text-slate-600');
      }
    }

    function resetAnnotationState() {
      ANNOTATION_STATE.datasetId = '';
      ANNOTATION_STATE.assetId = '';
      ANNOTATION_STATE.requestKey = '';
      ANNOTATION_STATE.loading = false;
      ANNOTATION_STATE.saving = false;
      ANNOTATION_STATE.dirty = false;
      ANNOTATION_STATE.boxes = [];
      ANNOTATION_STATE.selectedIndex = -1;
      ANNOTATION_STATE.drawing = false;
      ANNOTATION_STATE.draftBox = null;
      ANNOTATION_STATE.imageWidth = 0;
      ANNOTATION_STATE.imageHeight = 0;
    }

    function hasUnsavedAnnotationChanges() {
      return !!ANNOTATION_STATE.dirty;
    }

    function confirmAnnotationDiscard(message) {
      if (!hasUnsavedAnnotationChanges()) return true;
      return window.confirm(message || '当前图片有未保存的标注修改，确认放弃吗？');
    }

    function closeDatasetWorkspace() {
      if (!confirmAnnotationDiscard('当前图片有未保存的标注修改，关闭后会丢失，确认继续吗？')) {
        return false;
      }

      DATASET_WORKSPACE_STATE.datasetId = '';
      DATASET_WORKSPACE_STATE.mode = 'browse';
      DATASET_WORKSPACE_STATE.loading = false;
      DATASET_WORKSPACE_STATE.dataset = null;
      DATASET_WORKSPACE_STATE.items = [];
      DATASET_WORKSPACE_STATE.selectedAssetId = '';
      DATASET_WORKSPACE_STATE.showOnlyUnlabeled = false;
      DATASET_WORKSPACE_STATE.showOnlyLowQuality = false;
      DATASET_WORKSPACE_STATE.reviewFilter = 'all';
      clearAutoAnnotationPollTimer();
      AUTO_ANNOTATION_STATE.running = false;
      AUTO_ANNOTATION_STATE.jobId = '';
      AUTO_ANNOTATION_STATE.jobsLoading = false;
      AUTO_ANNOTATION_STATE.jobs = [];
      resetAnnotationState();
      setAnnotationFeedback('', '');
      setAutoAnnotationFeedback('', '');

      var overlay = document.getElementById('datasetWorkspaceOverlay');
      var drawer = document.getElementById('datasetWorkspaceDrawer');
      if (overlay) overlay.classList.add('hidden');
      if (drawer) drawer.classList.add('translate-x-full');
      renderDatasetWorkspace();
      return true;
    }

    function getSelectedDatasetAsset() {
      for (var i = 0; i < DATASET_WORKSPACE_STATE.items.length; i++) {
        if (DATASET_WORKSPACE_STATE.items[i].id === DATASET_WORKSPACE_STATE.selectedAssetId) {
          return DATASET_WORKSPACE_STATE.items[i];
        }
      }
      return null;
    }

    function getSelectedDatasetAssetIndex() {
      for (var i = 0; i < DATASET_WORKSPACE_STATE.items.length; i++) {
        if (DATASET_WORKSPACE_STATE.items[i].id === DATASET_WORKSPACE_STATE.selectedAssetId) {
          return i;
        }
      }
      return -1;
    }

    function getAnnotationDom() {
      return {
        classSelect: document.getElementById('annotationClassSelect'),
        saveBtn: document.getElementById('annotationSaveBtn'),
        removeBtn: document.getElementById('annotationRemoveBtn'),
        clearBtn: document.getElementById('annotationClearBtn'),
        markReviewedBtn: document.getElementById('annotationMarkReviewedBtn'),
        markConfirmedBtn: document.getElementById('annotationMarkConfirmedBtn'),
        clearReviewBtn: document.getElementById('annotationClearReviewBtn'),
        prevBtn: document.getElementById('annotationPrevBtn'),
        nextBtn: document.getElementById('annotationNextBtn'),
        prevUnlabeledBtn: document.getElementById('annotationPrevUnlabeledBtn'),
        nextUnlabeledBtn: document.getElementById('annotationNextUnlabeledBtn'),
        onlyUnlabeled: document.getElementById('annotationOnlyUnlabeled'),
        onlyLowQuality: document.getElementById('annotationOnlyLowQuality'),
        reviewFilter: document.getElementById('annotationReviewFilter'),
        position: document.getElementById('annotationPosition'),
        boxCount: document.getElementById('annotationBoxCount'),
        boxList: document.getElementById('annotationBoxList'),
        stats: document.getElementById('datasetWorkspaceStats'),
        previewBox: document.getElementById('datasetAssetPreviewBox'),
      previewMeta: document.getElementById('datasetAssetPreviewMeta'),
      stageWrapper: document.getElementById('annotationStageWrapper'),
      viewport: document.getElementById('annotationViewport'),
      stage: document.getElementById('annotationStage'),
      image: document.getElementById('annotationImage'),
      overlay: document.getElementById('annotationOverlay'),
      zoomSelect: document.getElementById('annotationZoomSelect')
    };
  }

    function getAutoAnnotationDom() {
      return {
        model: document.getElementById('annotationAutoModel'),
        conf: document.getElementById('annotationAutoConf'),
        imgsz: document.getElementById('annotationAutoImgsz'),
        prompts: document.getElementById('annotationAutoPrompts'),
        classMapping: document.getElementById('annotationAutoClassMapping'),
        overwrite: document.getElementById('annotationAutoOverwrite'),
        keepConf: document.getElementById('annotationKeepConf'),
        keepHighBtn: document.getElementById('annotationKeepHighBtn'),
        jobsRefreshBtn: document.getElementById('annotationAutoJobsRefreshBtn'),
        jobsList: document.getElementById('annotationAutoJobList'),
        currentBtn: document.getElementById('annotationAutoCurrentBtn'),
        unlabeledBtn: document.getElementById('annotationAutoUnlabeledBtn')
      };
    }

    function isAutoPromptModel(modelKey) {
      var item = UPLOAD_MODEL_MAP[modelKey];
      return !!(item && item.ui_mode === 'prompt');
    }

    function getDatasetClassNames() {
      var dataset = DATASET_WORKSPACE_STATE.dataset || getDatasetItem(DATASET_WORKSPACE_STATE.datasetId) || {};
      return Array.isArray(dataset.class_names) ? dataset.class_names.slice() : [];
    }

    function renderAutoAnnotationModelOptions() {
      var dom = getAutoAnnotationDom();
      if (!dom.model) return;

      var previousValue = dom.model.value;
      if (!AUTO_ANNOTATION_MODEL_OPTIONS.length) {
        dom.model.innerHTML = '<option value="">未发现可用模型</option>';
        dom.model.disabled = true;
        return;
      }

      dom.model.innerHTML = AUTO_ANNOTATION_MODEL_OPTIONS.map(function (item) {
        return '<option value="' + escapeHtml(item.value || '') + '">' + escapeHtml(item.label || item.value || '') + '</option>';
      }).join('');

      var matched = AUTO_ANNOTATION_MODEL_OPTIONS.some(function (item) {
        return item.value === previousValue;
      });
      if (matched) {
        dom.model.value = previousValue;
      } else {
        dom.model.value = (APP_CONFIG.uploadModelDefault || (AUTO_ANNOTATION_MODEL_OPTIONS[0] && AUTO_ANNOTATION_MODEL_OPTIONS[0].value) || '');
      }
      dom.model.disabled = false;
      syncAutoAnnotationModelUI();
    }

    function syncAutoAnnotationModelUI() {
      var dom = getAutoAnnotationDom();
      if (!dom.model) return;
      var modelKey = dom.model.value || '';
      var datasetClasses = getDatasetClassNames();
      var isPrompt = isAutoPromptModel(modelKey);

      if (dom.conf && !dom.conf.dataset.touched) {
        dom.conf.value = isPrompt ? '0.15' : '0.25';
      }
      if (dom.prompts) {
        dom.prompts.disabled = !isPrompt;
        dom.prompts.placeholder = isPrompt
          ? 'helmet, no_helmet, person, hard hat'
          : '闭集模型一般不需要提示词';
        if (isPrompt && !dom.prompts.value.trim() && datasetClasses.length) {
          dom.prompts.value = datasetClasses.join(', ');
        }
        if (!isPrompt) {
          dom.prompts.value = '';
        }
      }
    }

    function updateAutoAnnotationButtons() {
      var dom = getAutoAnnotationDom();
      if (!dom.currentBtn || !dom.unlabeledBtn) return;
      var hasAsset = !!getSelectedDatasetAsset();
      var unlabeledCount = DATASET_WORKSPACE_STATE.items.filter(function (item) { return !item.is_labeled; }).length;
      var hasDataset = !!DATASET_WORKSPACE_STATE.datasetId;
      var disabled = AUTO_ANNOTATION_STATE.running || !hasDataset;
      var hasConfidenceBoxes = ANNOTATION_STATE.boxes.some(function (box) {
        return typeof box.confidence === 'number' && !Number.isNaN(box.confidence);
      });

      if (dom.model) dom.model.disabled = disabled || !AUTO_ANNOTATION_MODEL_OPTIONS.length;
      if (dom.conf) dom.conf.disabled = disabled;
      if (dom.imgsz) dom.imgsz.disabled = disabled;
      if (dom.prompts) dom.prompts.disabled = disabled || !isAutoPromptModel(dom.model ? dom.model.value : '');
      if (dom.classMapping) dom.classMapping.disabled = disabled;
      if (dom.overwrite) dom.overwrite.disabled = disabled;
      if (dom.keepConf) dom.keepConf.disabled = AUTO_ANNOTATION_STATE.running;
      if (dom.keepHighBtn) dom.keepHighBtn.disabled = AUTO_ANNOTATION_STATE.running || !hasConfidenceBoxes;
      dom.currentBtn.disabled = disabled || !hasAsset;
      dom.unlabeledBtn.disabled = disabled || unlabeledCount <= 0;
    }

    function getLowQualityThreshold() {
      var dom = getAutoAnnotationDom();
      var threshold = Number(dom.keepConf && dom.keepConf.value ? dom.keepConf.value : 0.3);
      if (!Number.isFinite(threshold) || threshold <= 0) {
        return 0.3;
      }
      return threshold;
    }

    function isLowQualityAsset(asset) {
      if (!asset || typeof asset.min_confidence !== 'number') return false;
      return asset.min_confidence < getLowQualityThreshold();
    }

    function matchesReviewFilter(item, reviewFilter) {
      var filterValue = reviewFilter || 'all';
      if (filterValue === 'all') return true;
      return String(item && item.review_status ? item.review_status : 'pending') === filterValue;
    }

    function getFilteredDatasetItems(options) {
      options = options || {};
      var onlyUnlabeled = !!options.onlyUnlabeled;
      var onlyLowQuality = !!options.onlyLowQuality;
      var reviewFilter = options.reviewFilter || 'all';
      return DATASET_WORKSPACE_STATE.items.filter(function (item) {
        if (onlyUnlabeled && item.is_labeled) return false;
        if (onlyLowQuality && !isLowQualityAsset(item)) return false;
        if (!matchesReviewFilter(item, reviewFilter)) return false;
        return true;
      });
    }

    function getReviewStatusMeta(status) {
      return REVIEW_STATUS_UI[status] || REVIEW_STATUS_UI.pending;
    }

    function mergeAutoAnnotationJob(job) {
      if (!job || !job.id) return;
      var matched = false;
      AUTO_ANNOTATION_STATE.jobs = AUTO_ANNOTATION_STATE.jobs.map(function (item) {
        if (item.id === job.id) {
          matched = true;
          return Object.assign({}, item, job);
        }
        return item;
      });
      if (!matched) {
        AUTO_ANNOTATION_STATE.jobs.unshift(job);
      }
      AUTO_ANNOTATION_STATE.jobs = AUTO_ANNOTATION_STATE.jobs
        .filter(function (item) {
          return item && item.dataset_id === DATASET_WORKSPACE_STATE.datasetId;
        })
        .slice(0, 8);
    }

    function renderAutoAnnotationJobList() {
      var dom = getAutoAnnotationDom();
      var list = dom.jobsList;
      if (!list) return;

      if (!DATASET_WORKSPACE_STATE.datasetId) {
        list.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-5 text-sm text-slate-500">请选择一个数据集后查看预标注任务。</div>';
        return;
      }
      if (AUTO_ANNOTATION_STATE.jobsLoading) {
        list.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-5 text-sm text-slate-500">正在加载预标注任务...</div>';
        return;
      }
      if (!AUTO_ANNOTATION_STATE.jobs.length) {
        list.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-5 text-sm text-slate-500">当前数据集还没有预标注任务记录。</div>';
        return;
      }

      list.innerHTML = AUTO_ANNOTATION_STATE.jobs.map(function (job) {
        var meta = AUTO_ANNOTATE_JOB_STATUS_UI[job.status] || AUTO_ANNOTATE_JOB_STATUS_UI.queued;
        var createdAt = job.created_ts ? new Date(job.created_ts * 1000).toLocaleString('zh-CN') : '--';
        var total = Number(job.total || 0);
        var processed = Number(job.processed || 0);
        var updated = Number(job.updated || 0);
        var progress = total ? (processed + '/' + total) : '--';
        return (
          '<div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-4">' +
            '<div class="flex items-start justify-between gap-3">' +
              '<div class="min-w-0 flex-1">' +
                '<div class="truncate text-sm font-semibold text-slate-900">' + escapeHtml(job.model_key || '--') + '</div>' +
                '<div class="mt-1 break-all font-mono text-[11px] text-slate-400">' + escapeHtml(job.id || '') + '</div>' +
              '</div>' +
              '<span class="rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset ' + meta.badge + '">' + meta.label + '</span>' +
            '</div>' +
            '<div class="mt-3 text-xs leading-6 text-slate-600">' + escapeHtml(job.message || '--') + '</div>' +
            '<div class="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">' +
              '<span class="rounded-full bg-white px-2.5 py-1 ring-1 ring-inset ring-slate-200">处理进度 ' + escapeHtml(progress) + '</span>' +
              '<span class="rounded-full bg-white px-2.5 py-1 ring-1 ring-inset ring-slate-200">生成 ' + escapeHtml(updated) + ' 张</span>' +
              '<span class="rounded-full bg-white px-2.5 py-1 ring-1 ring-inset ring-slate-200">' + escapeHtml(createdAt) + '</span>' +
            '</div>' +
          '</div>'
        );
      }).join('');
    }

    function refreshAutoAnnotationJobs() {
      var datasetId = DATASET_WORKSPACE_STATE.datasetId;
      if (!datasetId) {
        AUTO_ANNOTATION_STATE.jobs = [];
        renderAutoAnnotationJobList();
        return;
      }
      AUTO_ANNOTATION_STATE.jobsLoading = true;
      renderAutoAnnotationJobList();
      fetch('/train/auto-annotate-jobs?limit=20')
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (!data.ok) {
            throw new Error(data.error || '加载预标注任务失败');
          }
          AUTO_ANNOTATION_STATE.jobs = (data.items || [])
            .filter(function (item) { return item.dataset_id === datasetId; })
            .slice(0, 8);
        })
        .catch(function (err) {
          setAutoAnnotationFeedback(err.message || '加载预标注任务失败', 'error');
          AUTO_ANNOTATION_STATE.jobs = [];
        })
        .finally(function () {
          AUTO_ANNOTATION_STATE.jobsLoading = false;
          renderAutoAnnotationJobList();
        });
    }

    function clearAutoAnnotationPollTimer() {
      if (AUTO_ANNOTATION_STATE.pollTimer) {
        window.clearTimeout(AUTO_ANNOTATION_STATE.pollTimer);
        AUTO_ANNOTATION_STATE.pollTimer = null;
      }
    }

    function buildAutoAnnotateJobMessage(job) {
      if (!job) return '批量预标注任务不存在。';
      var total = Number(job.total || 0);
      var processed = Number(job.processed || 0);
      var updated = Number(job.updated || 0);
      var skippedExisting = Number(job.skipped_existing || 0);
      var noDetection = Number(job.no_detection || 0);
      var summary = total
        ? ('已处理 ' + processed + '/' + total + ' 张，生成 ' + updated + ' 张预标注')
        : (job.message || '批量预标注处理中');
      if (skippedExisting) {
        summary += '，跳过已标注 ' + skippedExisting + ' 张';
      }
      if (noDetection) {
        summary += '，无命中 ' + noDetection + ' 张';
      }
      return summary;
    }

    function handleCompletedAutoAnnotateJob(job) {
      mergeAutoAnnotationJob(job);
      refreshDatasetWorkspace({ force: true });
      setAutoAnnotationFeedback(buildAutoAnnotateJobMessage(job), 'success');
      AUTO_ANNOTATION_STATE.jobId = '';
      renderAutoAnnotationJobList();
    }

    function pollAutoAnnotationJob(jobId) {
      if (!jobId) return;
      clearAutoAnnotationPollTimer();
      AUTO_ANNOTATION_STATE.jobId = jobId;
      fetch('/train/auto-annotate-jobs/' + encodeURIComponent(jobId))
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (!data.ok || !data.job) {
            throw new Error(data.error || '批量预标注任务不存在');
          }
          var job = data.job;
          mergeAutoAnnotationJob(job);
          renderAutoAnnotationJobList();
          if (job.status === 'queued' || job.status === 'running') {
            AUTO_ANNOTATION_STATE.running = true;
            setAutoAnnotationFeedback(buildAutoAnnotateJobMessage(job), 'info');
            updateAutoAnnotationButtons();
            AUTO_ANNOTATION_STATE.pollTimer = window.setTimeout(function () {
              pollAutoAnnotationJob(jobId);
            }, 1500);
            return;
          }

          AUTO_ANNOTATION_STATE.running = false;
          updateAutoAnnotationButtons();
          if (job.status === 'done') {
            handleCompletedAutoAnnotateJob(job);
            return;
          }

          AUTO_ANNOTATION_STATE.jobId = '';
          setAutoAnnotationFeedback(job.message || '批量预标注失败', 'error');
        })
        .catch(function (err) {
          AUTO_ANNOTATION_STATE.running = false;
          AUTO_ANNOTATION_STATE.jobId = '';
          updateAutoAnnotationButtons();
          setAutoAnnotationFeedback(err.message || '批量预标注任务轮询失败', 'error');
        });
    }

    function getVisibleDatasetItems() {
      return getFilteredDatasetItems({
        onlyUnlabeled: DATASET_WORKSPACE_STATE.showOnlyUnlabeled,
        onlyLowQuality: DATASET_WORKSPACE_STATE.showOnlyLowQuality,
        reviewFilter: DATASET_WORKSPACE_STATE.reviewFilter
      });
    }

    function getAssetIndexInItems(assetId, options) {
      var items = getFilteredDatasetItems(options);
      for (var i = 0; i < items.length; i++) {
        if (items[i].id === assetId) return i;
      }
      return -1;
    }

    function getVisibleUnlabeledDatasetItems() {
      return getFilteredDatasetItems({
        onlyUnlabeled: true,
        onlyLowQuality: DATASET_WORKSPACE_STATE.showOnlyLowQuality,
        reviewFilter: DATASET_WORKSPACE_STATE.reviewFilter
      });
    }

    function ensureSelectedAssetVisible() {
      var visibleItems = getVisibleDatasetItems();
      var selectedAssetId = DATASET_WORKSPACE_STATE.selectedAssetId;
      if (selectedAssetId && visibleItems.some(function (item) { return item.id === selectedAssetId; })) {
        return;
      }
      DATASET_WORKSPACE_STATE.selectedAssetId = visibleItems[0] ? visibleItems[0].id : '';
    }

    function mergeDatasetWorkspaceAsset(asset) {
      if (!asset || !asset.id) return;
      DATASET_WORKSPACE_STATE.items = DATASET_WORKSPACE_STATE.items.map(function (item) {
        return item.id === asset.id ? Object.assign({}, item, asset) : item;
      });
    }

    function normalizeAnnotationBox(rawBox) {
      return {
        class_index: Number(rawBox.class_index || 0),
        class_name: rawBox.class_name || '',
        confidence: rawBox.confidence === undefined || rawBox.confidence === null ? null : Number(rawBox.confidence),
        x1: Number(rawBox.x1 || 0),
        y1: Number(rawBox.y1 || 0),
        x2: Number(rawBox.x2 || 0),
        y2: Number(rawBox.y2 || 0)
      };
    }

    function getSelectedAnnotationClassIndex() {
      var select = document.getElementById('annotationClassSelect');
      if (!select || select.value === '') return 0;
      var value = Number(select.value);
      return Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0;
    }

    function syncAnnotationClassOptions() {
      var dom = getAnnotationDom();
      var select = dom.classSelect;
      if (!select) return;

      var dataset = DATASET_WORKSPACE_STATE.dataset || getDatasetItem(DATASET_WORKSPACE_STATE.datasetId) || {};
      var classes = Array.isArray(dataset.class_names) ? dataset.class_names : [];
      var selectedBox = ANNOTATION_STATE.selectedIndex >= 0 ? ANNOTATION_STATE.boxes[ANNOTATION_STATE.selectedIndex] : null;
      var previousValue = select.value;

      if (!classes.length) {
        select.innerHTML = '<option value="">当前数据集还没有配置类别</option>';
        select.disabled = true;
        return;
      }

      select.innerHTML = classes.map(function (name, index) {
        return '<option value="' + index + '">' + escapeHtml(name) + '</option>';
      }).join('');

      if (selectedBox && selectedBox.class_index >= 0 && selectedBox.class_index < classes.length) {
        select.value = String(selectedBox.class_index);
      } else if (previousValue !== '' && Number(previousValue) >= 0 && Number(previousValue) < classes.length) {
        select.value = previousValue;
      } else {
        select.value = '0';
      }

      select.disabled = DATASET_WORKSPACE_STATE.mode !== 'annotate' || ANNOTATION_STATE.loading || ANNOTATION_STATE.saving;
    }

    function updateAnnotationButtons() {
      var dom = getAnnotationDom();
      var dataset = DATASET_WORKSPACE_STATE.dataset || getDatasetItem(DATASET_WORKSPACE_STATE.datasetId) || {};
      var hasClasses = Array.isArray(dataset.class_names) && dataset.class_names.length > 0;
      var hasAsset = !!getSelectedDatasetAsset();
      var canEdit = DATASET_WORKSPACE_STATE.mode === 'annotate' && hasAsset && hasClasses && !ANNOTATION_STATE.loading && !ANNOTATION_STATE.saving;
      var hasBoxes = ANNOTATION_STATE.boxes.length > 0;
      var hasSelected = ANNOTATION_STATE.selectedIndex >= 0 && ANNOTATION_STATE.selectedIndex < ANNOTATION_STATE.boxes.length;
      var currentIndex = getAssetIndexInItems(DATASET_WORKSPACE_STATE.selectedAssetId, {
        onlyUnlabeled: DATASET_WORKSPACE_STATE.showOnlyUnlabeled,
        onlyLowQuality: DATASET_WORKSPACE_STATE.showOnlyLowQuality,
        reviewFilter: DATASET_WORKSPACE_STATE.reviewFilter
      });
      var totalItems = getVisibleDatasetItems().length;
      var currentUnlabeledIndex = getAssetIndexInItems(DATASET_WORKSPACE_STATE.selectedAssetId, {
        onlyUnlabeled: true,
        onlyLowQuality: DATASET_WORKSPACE_STATE.showOnlyLowQuality,
        reviewFilter: DATASET_WORKSPACE_STATE.reviewFilter
      });
      var unlabeledItems = getVisibleUnlabeledDatasetItems();

      if (dom.classSelect) dom.classSelect.disabled = !canEdit;
      if (dom.saveBtn) dom.saveBtn.disabled = !canEdit || !ANNOTATION_STATE.dirty;
      if (dom.removeBtn) dom.removeBtn.disabled = !canEdit || !hasSelected;
      if (dom.clearBtn) dom.clearBtn.disabled = !canEdit || !hasBoxes;
      if (dom.markReviewedBtn) dom.markReviewedBtn.disabled = !hasAsset || ANNOTATION_STATE.loading || ANNOTATION_STATE.saving;
      if (dom.markConfirmedBtn) dom.markConfirmedBtn.disabled = !hasAsset || ANNOTATION_STATE.loading || ANNOTATION_STATE.saving;
      if (dom.clearReviewBtn) dom.clearReviewBtn.disabled = !hasAsset || ANNOTATION_STATE.loading || ANNOTATION_STATE.saving;
      if (dom.prevBtn) dom.prevBtn.disabled = totalItems <= 1 || currentIndex <= 0;
      if (dom.nextBtn) dom.nextBtn.disabled = totalItems <= 1 || currentIndex < 0 || currentIndex >= totalItems - 1;
      if (dom.prevUnlabeledBtn) dom.prevUnlabeledBtn.disabled = unlabeledItems.length <= 1 || currentUnlabeledIndex <= 0;
      if (dom.nextUnlabeledBtn) dom.nextUnlabeledBtn.disabled = unlabeledItems.length <= 1 || currentUnlabeledIndex < 0 || currentUnlabeledIndex >= unlabeledItems.length - 1;
      if (dom.onlyUnlabeled) dom.onlyUnlabeled.checked = DATASET_WORKSPACE_STATE.showOnlyUnlabeled;
      if (dom.onlyLowQuality) dom.onlyLowQuality.checked = DATASET_WORKSPACE_STATE.showOnlyLowQuality;
      if (dom.reviewFilter) dom.reviewFilter.value = DATASET_WORKSPACE_STATE.reviewFilter;
      updateAutoAnnotationButtons();
    }

    function clamp(value, min, max) {
      return Math.max(min, Math.min(max, value));
    }

    function getAnnotationZoomPercent() {
      var value = Number(ANNOTATION_VIEW_STATE.zoomPercent || ANNOTATION_ZOOM_DEFAULT);
      if (!Number.isFinite(value)) {
        return ANNOTATION_ZOOM_DEFAULT;
      }
      return clamp(Math.round(value), ANNOTATION_ZOOM_MIN, ANNOTATION_ZOOM_MAX);
    }

    function getAnnotationZoomRatio() {
      return getAnnotationZoomPercent() / 100;
    }

    function applyAnnotationImageZoom() {
      var dom = getAnnotationDom();
      var image = dom.image;
      var zoomSelect = dom.zoomSelect;
      if (zoomSelect) {
        zoomSelect.value = String(getAnnotationZoomPercent());
      }
      if (!image) return;

      var naturalWidth = image.naturalWidth || ANNOTATION_STATE.imageWidth || 0;
      var naturalHeight = image.naturalHeight || ANNOTATION_STATE.imageHeight || 0;
      if (!naturalWidth || !naturalHeight) {
        image.style.width = '';
        image.style.height = '';
        return;
      }

      var ratio = getAnnotationZoomRatio();
      image.style.width = Math.max(320, Math.round(naturalWidth * ratio)) + 'px';
      image.style.height = Math.max(240, Math.round(naturalHeight * ratio)) + 'px';
    }

    function updateAnnotationZoom(value) {
      var numeric = Number(value);
      if (!Number.isFinite(numeric)) {
        numeric = ANNOTATION_ZOOM_DEFAULT;
      }
      ANNOTATION_VIEW_STATE.zoomPercent = clamp(Math.round(numeric), ANNOTATION_ZOOM_MIN, ANNOTATION_ZOOM_MAX);
      applyAnnotationImageZoom();
      renderAnnotationStage();
    }

    function fitAnnotationToViewport() {
      var dom = getAnnotationDom();
      var image = dom.image;
      var viewport = dom.viewport;
      if (!image || !viewport) return;

      var naturalWidth = image.naturalWidth || ANNOTATION_STATE.imageWidth || 0;
      var naturalHeight = image.naturalHeight || ANNOTATION_STATE.imageHeight || 0;
      if (!naturalWidth || !naturalHeight) return;

      var viewportWidth = Math.max(0, viewport.clientWidth - 24);
      var viewportHeight = Math.max(0, viewport.clientHeight - 24);
      if (!viewportWidth || !viewportHeight) return;

      var ratio = Math.min(viewportWidth / naturalWidth, viewportHeight / naturalHeight);
      if (!Number.isFinite(ratio) || ratio <= 0) return;

      var percent = clamp(Math.floor(ratio * 100), ANNOTATION_ZOOM_MIN, ANNOTATION_ZOOM_MAX);
      ANNOTATION_VIEW_STATE.zoomPercent = percent;
      applyAnnotationImageZoom();
      viewport.scrollTop = 0;
      viewport.scrollLeft = 0;
      renderAnnotationStage();
    }

    function getAnnotationImageMetrics() {
      var dom = getAnnotationDom();
      var image = dom.image;
      var overlay = dom.overlay;
      if (!image || !overlay) return null;

      var displayWidth = image.clientWidth || 0;
      var displayHeight = image.clientHeight || 0;
      var naturalWidth = image.naturalWidth || ANNOTATION_STATE.imageWidth || 0;
      var naturalHeight = image.naturalHeight || ANNOTATION_STATE.imageHeight || 0;
      if (!displayWidth || !displayHeight || !naturalWidth || !naturalHeight) {
        return null;
      }

      overlay.style.width = displayWidth + 'px';
      overlay.style.height = displayHeight + 'px';

      return {
        displayWidth: displayWidth,
        displayHeight: displayHeight,
        naturalWidth: naturalWidth,
        naturalHeight: naturalHeight,
        scaleX: naturalWidth / displayWidth,
        scaleY: naturalHeight / displayHeight
      };
    }

    function toImagePoint(event) {
      var dom = getAnnotationDom();
      var overlay = dom.overlay;
      var metrics = getAnnotationImageMetrics();
      if (!overlay || !metrics) return null;

      var rect = overlay.getBoundingClientRect();
      var displayX = clamp(event.clientX - rect.left, 0, rect.width);
      var displayY = clamp(event.clientY - rect.top, 0, rect.height);
      return {
        x: clamp(displayX * metrics.scaleX, 0, metrics.naturalWidth),
        y: clamp(displayY * metrics.scaleY, 0, metrics.naturalHeight)
      };
    }

    function setSelectedAnnotationBox(index) {
      if (typeof index !== 'number' || index < 0 || index >= ANNOTATION_STATE.boxes.length) {
        ANNOTATION_STATE.selectedIndex = -1;
      } else {
        ANNOTATION_STATE.selectedIndex = index;
      }
      syncAnnotationClassOptions();
      renderAnnotationBoxList();
      updateAnnotationButtons();
      renderAnnotationStage();
    }

    function renderAnnotationNavigator() {
      var dom = getAnnotationDom();
      if (!dom.position || !dom.boxCount) return;
      var visibleItems = getVisibleDatasetItems();
      var total = visibleItems.length;
      var index = getAssetIndexInItems(DATASET_WORKSPACE_STATE.selectedAssetId, {
        onlyUnlabeled: DATASET_WORKSPACE_STATE.showOnlyUnlabeled,
        onlyLowQuality: DATASET_WORKSPACE_STATE.showOnlyLowQuality,
        reviewFilter: DATASET_WORKSPACE_STATE.reviewFilter
      });
      dom.position.textContent = total ? ((index + 1) + ' / ' + total) : '0 / 0';
      dom.boxCount.textContent = ANNOTATION_STATE.boxes.length + ' 个框';
      if (dom.stats) {
        var labeled = DATASET_WORKSPACE_STATE.items.filter(function (item) { return !!item.is_labeled; }).length;
        var unlabeled = DATASET_WORKSPACE_STATE.items.length - labeled;
        var reviewed = DATASET_WORKSPACE_STATE.items.filter(function (item) { return !!item.is_reviewed; }).length;
        var lowQuality = DATASET_WORKSPACE_STATE.items.filter(function (item) { return isLowQualityAsset(item); }).length;
        var totalAssets = DATASET_WORKSPACE_STATE.items.length || 0;
        var progressText = totalAssets ? ('（' + Math.round((labeled / totalAssets) * 100) + '%）') : '';
        dom.stats.textContent = '已标注 ' + labeled + ' / ' + totalAssets + ' 张' + progressText + ' · 未标注 ' + unlabeled + ' 张 · 已复核 ' + reviewed + ' 张 · 低质量样本 ' + lowQuality + ' 张';
      }
      updateAnnotationButtons();
    }

    function renderAnnotationBoxList() {
      var dom = getAnnotationDom();
      var list = dom.boxList;
      if (!list) return;

      if (!ANNOTATION_STATE.boxes.length) {
        list.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-5 text-sm text-slate-500">当前图片还没有标注框。可以在右侧图片上拖拽创建第一个框。</div>';
        renderAnnotationNavigator();
        return;
      }

      list.innerHTML = ANNOTATION_STATE.boxes.map(function (box, index) {
        var className = box.class_name || ('类别 ' + box.class_index);
        var active = index === ANNOTATION_STATE.selectedIndex;
        var width = Math.max(0, box.x2 - box.x1).toFixed(1);
        var height = Math.max(0, box.y2 - box.y1).toFixed(1);
        var confidenceLine = '';
        if (typeof box.confidence === 'number' && !Number.isNaN(box.confidence)) {
          confidenceLine = '<div class="mt-1 text-xs text-slate-500">置信度：' + box.confidence.toFixed(4) + '</div>';
        }
        return (
          '<button type="button" class="w-full rounded-2xl border px-4 py-3 text-left transition ' +
            (active
              ? 'border-teal-300 bg-teal-50 ring-2 ring-teal-100'
              : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50') +
            '" onclick="setSelectedAnnotationBox(' + index + ')">' +
              '<div class="flex items-center justify-between gap-3">' +
                '<div class="text-sm font-semibold text-slate-900">人框 ' + (index + 1) + ' · ' + escapeHtml(className) + '</div>' +
                '<div class="text-xs text-slate-500">' + width + ' × ' + height + '</div>' +
              '</div>' +
              '<div class="mt-2 text-xs leading-6 text-slate-500">' +
                '坐标：[' + box.x1.toFixed(1) + ', ' + box.y1.toFixed(1) + '] → [' + box.x2.toFixed(1) + ', ' + box.y2.toFixed(1) + ']' +
              '</div>' +
              confidenceLine +
          '</button>'
        );
      }).join('');

      renderAnnotationNavigator();
    }

    function renderAnnotationStage() {
      var dom = getAnnotationDom();
      var overlay = dom.overlay;
      var image = dom.image;
      if (!overlay || !image) return;

      applyAnnotationImageZoom();
      var metrics = getAnnotationImageMetrics();
      overlay.innerHTML = '';
      if (!metrics) {
        renderAnnotationBoxList();
        updateAnnotationButtons();
        return;
      }

      ANNOTATION_STATE.imageWidth = metrics.naturalWidth;
      ANNOTATION_STATE.imageHeight = metrics.naturalHeight;

      ANNOTATION_STATE.boxes.forEach(function (box, index) {
        var left = clamp(box.x1 / metrics.scaleX, 0, metrics.displayWidth);
        var top = clamp(box.y1 / metrics.scaleY, 0, metrics.displayHeight);
        var width = clamp((box.x2 - box.x1) / metrics.scaleX, 0, metrics.displayWidth);
        var height = clamp((box.y2 - box.y1) / metrics.scaleY, 0, metrics.displayHeight);
        var isSelected = index === ANNOTATION_STATE.selectedIndex;
        var label = box.class_name || ((DATASET_WORKSPACE_STATE.dataset || {}).class_names || [])[box.class_index] || ('类别 ' + box.class_index);

        var button = document.createElement('button');
        button.type = 'button';
        button.className =
          'absolute border-2 text-left transition ' +
          (isSelected
            ? 'border-teal-500 bg-teal-500/10 ring-2 ring-teal-200'
            : 'border-amber-400 bg-amber-300/10 hover:border-amber-500');
        button.style.left = left + 'px';
        button.style.top = top + 'px';
        button.style.width = Math.max(width, 1) + 'px';
        button.style.height = Math.max(height, 1) + 'px';
        button.dataset.boxIndex = String(index);
        button.addEventListener('click', function (event) {
          event.preventDefault();
          event.stopPropagation();
          setSelectedAnnotationBox(index);
        });

        var badge = document.createElement('span');
        badge.className =
          'absolute -left-px -top-7 inline-flex max-w-full items-center rounded-full px-2.5 py-1 text-[11px] font-semibold shadow-sm ' +
          (isSelected ? 'bg-teal-600 text-white' : 'bg-amber-500 text-white');
        badge.textContent = label;
        button.appendChild(badge);
        overlay.appendChild(button);
      });

      if (ANNOTATION_STATE.draftBox) {
        var draft = ANNOTATION_STATE.draftBox;
        var draftBox = document.createElement('div');
        draftBox.className = 'absolute border-2 border-dashed border-sky-500 bg-sky-400/10';
        draftBox.style.left = clamp(draft.x1 / metrics.scaleX, 0, metrics.displayWidth) + 'px';
        draftBox.style.top = clamp(draft.y1 / metrics.scaleY, 0, metrics.displayHeight) + 'px';
        draftBox.style.width = Math.max((draft.x2 - draft.x1) / metrics.scaleX, 1) + 'px';
        draftBox.style.height = Math.max((draft.y2 - draft.y1) / metrics.scaleY, 1) + 'px';
        overlay.appendChild(draftBox);
      }

      renderAnnotationBoxList();
      updateAnnotationButtons();
    }

    function renderDatasetAssetPreview() {
      var dom = getAnnotationDom();
      if (!dom.previewBox || !dom.previewMeta || !dom.stageWrapper || !dom.image) return;

      syncAnnotationClassOptions();
      syncAutoAnnotationModelUI();
      renderAnnotationNavigator();

      var asset = getSelectedDatasetAsset();
      var dataset = DATASET_WORKSPACE_STATE.dataset || getDatasetItem(DATASET_WORKSPACE_STATE.datasetId) || {};
      if (!asset) {
        dom.previewBox.className = 'mt-4 rounded-3xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-10 text-center text-sm text-slate-500';
        dom.previewBox.textContent = '先从左侧选择一张图片，这里会加载预览并支持框标注。';
        dom.previewBox.classList.remove('hidden');
        dom.previewMeta.textContent = '';
        dom.stageWrapper.classList.add('hidden');
        renderAnnotationBoxList();
        updateAnnotationButtons();
        return;
      }

      dom.previewBox.classList.add('hidden');
      dom.stageWrapper.classList.remove('hidden');
      dom.image.src = asset.asset_url;
      dom.image.alt = asset.origin_name || asset.filename || '';
      dom.image.dataset.assetId = asset.id;
      applyAnnotationImageZoom();

      var sourceMap = {
        zip: 'ZIP 导入',
        database_result: 'PostgreSQL 结果图',
        upload_result: '上传结果图'
      };
      var lines = [
        '文件名：' + (asset.origin_name || asset.filename || '--'),
        '尺寸：' + (asset.width || 0) + ' × ' + (asset.height || 0),
        '大小：' + formatBytes(asset.size_bytes || 0),
        '来源：' + (sourceMap[asset.source_type] || asset.source_type || '未知来源'),
        '标注状态：' + (asset.is_labeled ? '已标注' : '未标注'),
        '复核状态：' + getReviewStatusMeta(asset.review_status).label,
        '当前框数：' + ANNOTATION_STATE.boxes.length + ' 个'
      ];
      if (asset.source_job_id) {
        lines.push('来源任务：' + asset.source_job_id);
      }
      if (typeof asset.min_confidence === 'number') {
        lines.push('最低分：' + asset.min_confidence.toFixed(4));
      }
      if (typeof asset.max_confidence === 'number') {
        lines.push('最高分：' + asset.max_confidence.toFixed(4));
      }
      if (asset.annotation_source) {
        lines.push('标注来源：' + asset.annotation_source);
      }
      if (asset.reviewed_ts) {
        lines.push('复核时间：' + new Date(asset.reviewed_ts * 1000).toLocaleString('zh-CN'));
      }
      if (Array.isArray(dataset.class_names) && dataset.class_names.length) {
        lines.push('类别数：' + dataset.class_names.length + ' 个');
      } else {
        lines.push('当前数据集还没有配置类别，暂时无法保存标注。');
      }

      dom.previewMeta.innerHTML = lines.map(function (line) {
        return '<div>' + escapeHtml(line) + '</div>';
      }).join('') +
      (asset.source_job_url
        ? '<div class="mt-2"><a href="' + asset.source_job_url + '" class="inline-flex items-center rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50" target="_blank">查看来源任务</a></div>'
        : '');

      renderAnnotationStage();
      updateAnnotationButtons();
    }

    function renderDatasetWorkspace() {
      var title = document.getElementById('datasetWorkspaceTitle');
      var modeEl = document.getElementById('datasetWorkspaceMode');
      var meta = document.getElementById('datasetWorkspaceMeta');
      var count = document.getElementById('datasetWorkspaceCount');
      var grid = document.getElementById('datasetWorkspaceGrid');
      var tips = document.getElementById('datasetWorkspaceAnnotationTips');
      var annotateBtn = document.getElementById('datasetWorkspaceAnnotateBtn');
      if (!title || !modeEl || !meta || !count || !grid || !tips || !annotateBtn) return;

      if (DATASET_WORKSPACE_STATE.loading) {
        title.textContent = '正在加载数据集...';
        modeEl.textContent = DATASET_WORKSPACE_STATE.mode === 'annotate' ? 'Annotation Workspace' : 'Dataset Browser';
        meta.textContent = '正在读取数据集信息和图片列表...';
        count.textContent = '图片 0 张';
        grid.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">正在加载图片...</div>';
        renderDatasetAssetPreview();
        renderAutoAnnotationJobList();
        return;
      }

      var dataset = DATASET_WORKSPACE_STATE.dataset || getDatasetItem(DATASET_WORKSPACE_STATE.datasetId);
      if (!dataset) {
        title.textContent = '未选择数据集';
        modeEl.textContent = 'Dataset Workspace';
        meta.textContent = '请选择一个数据集后再进入浏览或标注。';
        count.textContent = '图片 0 张';
        grid.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">暂无可显示内容。</div>';
        renderDatasetAssetPreview();
        renderAutoAnnotationJobList();
        return;
      }

      title.textContent = dataset.name || dataset.id || '数据集';
      modeEl.textContent = DATASET_WORKSPACE_STATE.mode === 'annotate' ? 'Annotation Workspace' : 'Dataset Browser';

      var classBadges = (dataset.class_names || []).map(function (name) {
        return '<span class="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-slate-700 ring-1 ring-inset ring-slate-200">' + escapeHtml(name) + '</span>';
      }).join('');
      meta.innerHTML =
        '<div class="text-sm font-semibold text-slate-900">' + escapeHtml(dataset.name || dataset.id || '') + '</div>' +
        '<div class="mt-2 text-sm leading-7 text-slate-600">' + escapeHtml(dataset.notes || '暂无备注') + '</div>' +
        '<div class="mt-3 flex flex-wrap gap-2">' + (classBadges || '<span class="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-slate-500 ring-1 ring-inset ring-slate-200">未配置类别</span>') + '</div>';

      var visibleItems = getVisibleDatasetItems();
      var totalAssets = DATASET_WORKSPACE_STATE.items.length || 0;
      var labeledCount = Number(dataset.labeled_count || 0);
      var progressText = totalAssets ? (' · 完成度 ' + Math.round((labeledCount / totalAssets) * 100) + '%') : '';
      var reviewPrefixMap = {
        pending: '待复核图片 ',
        reviewed: '已复核图片 ',
        confirmed: '已确认图片 '
      };
      var countPrefix = DATASET_WORKSPACE_STATE.showOnlyUnlabeled
        ? '未标注图片 '
        : (DATASET_WORKSPACE_STATE.showOnlyLowQuality ? '低质量样本 ' : (reviewPrefixMap[DATASET_WORKSPACE_STATE.reviewFilter] || '图片 '));
      count.textContent = (countPrefix + (visibleItems.length || 0) + ' 张 / 全部 ' + totalAssets + ' 张' + progressText);

      if (DATASET_WORKSPACE_STATE.mode === 'annotate') {
        tips.textContent = '框选方式：在右侧图片上按下并拖拽鼠标创建框，点击已有框可切换选中状态，再通过类别下拉修改分类并保存到 YOLO 标签文件。';
        annotateBtn.textContent = '切换为浏览';
        annotateBtn.onclick = function () {
          DATASET_WORKSPACE_STATE.mode = 'browse';
          setAnnotationFeedback('', '');
          renderDatasetWorkspace();
        };
      } else {
        tips.textContent = '当前为浏览模式，可核对图片来源、预览现有标注，并随时切换到标注模式继续画框。';
        annotateBtn.textContent = '进入标注';
        annotateBtn.onclick = function () {
          DATASET_WORKSPACE_STATE.mode = 'annotate';
          renderDatasetWorkspace();
        };
      }

      if (!DATASET_WORKSPACE_STATE.items.length) {
        grid.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">当前数据集还没有图片，可先从 ZIP 或检测结果中导入。</div>';
        renderDatasetAssetPreview();
        renderAutoAnnotationJobList();
        return;
      }

      if (!visibleItems.length) {
        var emptyTip = DATASET_WORKSPACE_STATE.showOnlyLowQuality
          ? '当前筛选下没有低质量样本，可以调高 Keep Conf 或关闭“只看低质量样本”查看全部图片。'
          : '当前筛选下没有未标注图片，可以关闭“只看未标注”查看全部图片。';
        grid.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">' + emptyTip + '</div>';
        renderDatasetAssetPreview();
        renderAutoAnnotationJobList();
        return;
      }

      grid.innerHTML = visibleItems.map(function (asset) {
        var active = DATASET_WORKSPACE_STATE.selectedAssetId === asset.id;
        var reviewMeta = getReviewStatusMeta(asset.review_status);
        var sourceMap = {
          zip: 'ZIP',
          database_result: 'PostgreSQL 结果',
          upload_result: '上传结果'
        };
        return (
          '<button type="button" class="overflow-hidden rounded-3xl border bg-white text-left shadow-sm shadow-slate-200/60 transition hover:-translate-y-0.5 ' + (active ? 'border-teal-400 ring-4 ring-teal-100' : 'border-slate-200') + '" onclick="selectDatasetAsset(\'' + encodeURIComponent(asset.id) + '\')">' +
            '<div class="aspect-[4/3] overflow-hidden bg-slate-100">' +
              '<img src="' + asset.asset_url + '" alt="' + escapeHtml(asset.origin_name || asset.filename || '') + '" class="h-full w-full object-cover" />' +
            '</div>' +
            '<div class="p-4">' +
              '<div class="truncate text-sm font-semibold text-slate-800">' + escapeHtml(asset.origin_name || asset.filename || '') + '</div>' +
              '<div class="mt-1 text-xs text-slate-400">' + escapeHtml(asset.filename || '') + '</div>' +
              '<div class="mt-3 flex flex-wrap items-center gap-2">' +
                '<span class="rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ring-inset ' + (asset.is_labeled ? 'bg-emerald-50 text-emerald-700 ring-emerald-200' : 'bg-amber-50 text-amber-700 ring-amber-200') + '">' + (asset.is_labeled ? '已标注' : '未标注') + '</span>' +
                '<span class="rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ring-inset ' + reviewMeta.badge + '">' + reviewMeta.label + '</span>' +
                '<span class="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-700 ring-1 ring-inset ring-slate-200">' + escapeHtml(sourceMap[asset.source_type] || asset.source_type || '未知来源') + '</span>' +
                '<span class="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-medium text-slate-700 ring-1 ring-inset ring-slate-200">' + escapeHtml(asset.width || 0) + ' × ' + escapeHtml(asset.height || 0) + '</span>' +
                (typeof asset.min_confidence === 'number'
                  ? '<span class="rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ring-inset ' + (isLowQualityAsset(asset) ? 'bg-rose-50 text-rose-700 ring-rose-200' : 'bg-sky-50 text-sky-700 ring-sky-200') + '">最低分 ' + escapeHtml(asset.min_confidence.toFixed(4)) + '</span>'
                  : '') +
              '</div>' +
            '</div>' +
          '</button>'
        );
      }).join('');

      renderDatasetAssetPreview();
      renderAutoAnnotationJobList();
    }

    function loadSelectedAssetAnnotation() {
      var datasetId = DATASET_WORKSPACE_STATE.datasetId;
      var asset = getSelectedDatasetAsset();
      if (!datasetId || !asset) {
        resetAnnotationState();
        renderDatasetAssetPreview();
        return;
      }

      ANNOTATION_STATE.datasetId = datasetId;
      ANNOTATION_STATE.assetId = asset.id;
      ANNOTATION_STATE.loading = true;
      ANNOTATION_STATE.saving = false;
      ANNOTATION_STATE.dirty = false;
      ANNOTATION_STATE.boxes = [];
      ANNOTATION_STATE.selectedIndex = -1;
      ANNOTATION_STATE.drawing = false;
      ANNOTATION_STATE.draftBox = null;
      ANNOTATION_STATE.requestKey = datasetId + ':' + asset.id + ':' + Date.now();

      setAnnotationFeedback('正在加载当前图片的标注...', 'info');
      renderDatasetAssetPreview();

      var requestKey = ANNOTATION_STATE.requestKey;
      fetch('/train/datasets/' + encodeURIComponent(datasetId) + '/assets/' + encodeURIComponent(asset.id) + '/annotation')
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (ANNOTATION_STATE.requestKey !== requestKey) return;
          if (!data.ok) {
            throw new Error(data.error || '加载标注失败');
          }

          if (data.dataset) {
            DATASET_WORKSPACE_STATE.dataset = data.dataset;
            mergeTrainDataset(data.dataset);
          }
          if (data.asset) {
            mergeDatasetWorkspaceAsset(data.asset);
          }

          ANNOTATION_STATE.loading = false;
          ANNOTATION_STATE.boxes = Array.isArray(data.boxes) ? data.boxes.map(normalizeAnnotationBox) : [];
          ANNOTATION_STATE.selectedIndex = ANNOTATION_STATE.boxes.length ? 0 : -1;
          ANNOTATION_STATE.dirty = false;

          if (ANNOTATION_STATE.boxes.length) {
            setAnnotationFeedback('已加载 ' + ANNOTATION_STATE.boxes.length + ' 个标注框，可继续修改后保存。', 'info');
          } else {
            setAnnotationFeedback('当前图片还没有标注，可以直接拖拽创建新框。', 'info');
          }
          renderDatasetAssetPreview();
        })
        .catch(function (err) {
          if (ANNOTATION_STATE.requestKey !== requestKey) return;
          ANNOTATION_STATE.loading = false;
          ANNOTATION_STATE.boxes = [];
          ANNOTATION_STATE.selectedIndex = -1;
          ANNOTATION_STATE.dirty = false;
          setAnnotationFeedback(err.message || '加载标注失败', 'error');
          renderDatasetAssetPreview();
        });
    }

    function selectDatasetAsset(encodedAssetId) {
      var nextAssetId = decodeURIComponent(encodedAssetId);
      if (DATASET_WORKSPACE_STATE.selectedAssetId === nextAssetId) return;
      if (!confirmAnnotationDiscard('当前图片有未保存的标注修改，切换图片后会丢失，确认继续吗？')) {
        return;
      }
      DATASET_WORKSPACE_STATE.selectedAssetId = nextAssetId;
      renderDatasetWorkspace();
      loadSelectedAssetAnnotation();
    }

    function openAdjacentDatasetAsset(offset) {
      var items = getVisibleDatasetItems();
      var currentIndex = getAssetIndexInItems(DATASET_WORKSPACE_STATE.selectedAssetId, {
        onlyUnlabeled: DATASET_WORKSPACE_STATE.showOnlyUnlabeled,
        onlyLowQuality: DATASET_WORKSPACE_STATE.showOnlyLowQuality,
        reviewFilter: DATASET_WORKSPACE_STATE.reviewFilter
      });
      if (currentIndex < 0) return;
      var nextIndex = currentIndex + offset;
      if (nextIndex < 0 || nextIndex >= items.length) return;
      selectDatasetAsset(encodeURIComponent(items[nextIndex].id));
    }

    function openAdjacentUnlabeledAsset(offset) {
      var unlabeledItems = getVisibleUnlabeledDatasetItems();
      var currentIndex = getAssetIndexInItems(DATASET_WORKSPACE_STATE.selectedAssetId, {
        onlyUnlabeled: true,
        onlyLowQuality: DATASET_WORKSPACE_STATE.showOnlyLowQuality,
        reviewFilter: DATASET_WORKSPACE_STATE.reviewFilter
      });
      if (currentIndex < 0) return;
      var nextIndex = currentIndex + offset;
      if (nextIndex < 0 || nextIndex >= unlabeledItems.length) return;
      selectDatasetAsset(encodeURIComponent(unlabeledItems[nextIndex].id));
    }

    function getAutoAnnotationAssetIds(mode) {
      if (mode === 'current') {
        return DATASET_WORKSPACE_STATE.selectedAssetId ? [DATASET_WORKSPACE_STATE.selectedAssetId] : [];
      }
      return DATASET_WORKSPACE_STATE.items
        .filter(function (item) { return !item.is_labeled; })
        .map(function (item) { return item.id; });
    }

    function runAutoAnnotation(mode) {
      var dom = getAutoAnnotationDom();
      if (!dom.model || !DATASET_WORKSPACE_STATE.datasetId) return;
      var currentAssetId = DATASET_WORKSPACE_STATE.selectedAssetId;

      var assetIds = getAutoAnnotationAssetIds(mode);
      if (!assetIds.length) {
        setAutoAnnotationFeedback(mode === 'current' ? '请先选择一张图片。' : '当前没有可预标注的未标注图片。', 'error');
        return;
      }
      if (!dom.model.value) {
        setAutoAnnotationFeedback('请先选择一个预标注模型。', 'error');
        return;
      }

      if ((mode === 'current' || mode === 'all-unlabeled') && !confirmAnnotationDiscard('预标注会刷新当前图片的标注框，未保存的人工修改会丢失，确认继续吗？')) {
        return;
      }

      AUTO_ANNOTATION_STATE.running = true;
      updateAutoAnnotationButtons();
      setAutoAnnotationFeedback(mode === 'current' ? '正在为当前图片生成候选框...' : '正在创建批量预标注任务...', 'info');

      if (mode === 'all-unlabeled') {
        fetch('/train/datasets/' + encodeURIComponent(DATASET_WORKSPACE_STATE.datasetId) + '/auto-annotate-jobs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            asset_ids: assetIds,
            model_key: dom.model.value,
            conf_thresh: Number(dom.conf && dom.conf.value ? dom.conf.value : 0.25),
            imgsz: Number(dom.imgsz && dom.imgsz.value ? dom.imgsz.value : 640),
            prompt_classes: dom.prompts ? dom.prompts.value.trim() : '',
            class_mapping: dom.classMapping ? dom.classMapping.value.trim() : '',
            overwrite: !!(dom.overwrite && dom.overwrite.checked)
          })
        })
          .then(function (resp) { return resp.json(); })
          .then(function (data) {
            if (!data.ok || !data.job) {
              throw new Error(data.error || '批量预标注任务创建失败');
            }
            setAutoAnnotationFeedback(data.message || '批量预标注任务已创建。', 'info');
            pollAutoAnnotationJob(data.job.id);
          })
          .catch(function (err) {
            AUTO_ANNOTATION_STATE.running = false;
            updateAutoAnnotationButtons();
            setAutoAnnotationFeedback(err.message || '批量预标注任务创建失败', 'error');
          });
        return;
      }

      fetch('/train/datasets/' + encodeURIComponent(DATASET_WORKSPACE_STATE.datasetId) + '/auto-annotate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          asset_ids: assetIds,
          model_key: dom.model.value,
          conf_thresh: Number(dom.conf && dom.conf.value ? dom.conf.value : 0.25),
          imgsz: Number(dom.imgsz && dom.imgsz.value ? dom.imgsz.value : 640),
          prompt_classes: dom.prompts ? dom.prompts.value.trim() : '',
          class_mapping: dom.classMapping ? dom.classMapping.value.trim() : '',
          overwrite: !!(dom.overwrite && dom.overwrite.checked)
        })
      })
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (!data.ok) {
            throw new Error(data.error || '预标注失败');
          }

          if (data.dataset) {
            DATASET_WORKSPACE_STATE.dataset = data.dataset;
            mergeTrainDataset(data.dataset);
          }
          (data.items || []).forEach(function (entry) {
            if (entry && entry.asset) {
              mergeDatasetWorkspaceAsset(entry.asset);
            }
          });
          setAutoAnnotationFeedback(data.message || '预标注完成。', 'success');

          var updatedCurrent = (data.items || []).some(function (entry) {
            return entry && entry.asset && entry.asset.id === currentAssetId;
          });
          if (updatedCurrent) {
            var currentEntry = (data.items || []).find(function (entry) {
              return entry && entry.asset && entry.asset.id === currentAssetId;
            });
            if (currentEntry && Array.isArray(currentEntry.boxes)) {
              ANNOTATION_STATE.boxes = currentEntry.boxes.map(normalizeAnnotationBox);
              ANNOTATION_STATE.selectedIndex = ANNOTATION_STATE.boxes.length ? 0 : -1;
              ANNOTATION_STATE.dirty = true;
            }
          }

          var nextAssetId = '';
          if (mode === 'current') {
            var currentIndex = DATASET_WORKSPACE_STATE.items.findIndex(function (item) {
              return item.id === currentAssetId;
            });
            for (var i = currentIndex + 1; i < DATASET_WORKSPACE_STATE.items.length; i++) {
              if (!DATASET_WORKSPACE_STATE.items[i].is_labeled) {
                nextAssetId = DATASET_WORKSPACE_STATE.items[i].id;
                break;
              }
            }
            if (!nextAssetId) {
              for (var j = 0; j < DATASET_WORKSPACE_STATE.items.length; j++) {
                if (!DATASET_WORKSPACE_STATE.items[j].is_labeled) {
                  nextAssetId = DATASET_WORKSPACE_STATE.items[j].id;
                  break;
                }
              }
            }
          } else if (mode === 'all-unlabeled') {
            var firstRemaining = DATASET_WORKSPACE_STATE.items.find(function (item) {
              return !item.is_labeled;
            });
            nextAssetId = firstRemaining ? firstRemaining.id : '';
          }

          renderDatasetWorkspace();
          if (nextAssetId && nextAssetId !== currentAssetId) {
            DATASET_WORKSPACE_STATE.selectedAssetId = nextAssetId;
            loadSelectedAssetAnnotation();
            setAutoAnnotationFeedback((data.message || '预标注完成。') + ' 已跳到下一张未标注图。', 'success');
          } else if (updatedCurrent) {
            renderDatasetAssetPreview();
          } else if (DATASET_WORKSPACE_STATE.selectedAssetId) {
            loadSelectedAssetAnnotation();
          } else {
            renderDatasetAssetPreview();
          }
        })
        .catch(function (err) {
          setAutoAnnotationFeedback(err.message || '预标注失败', 'error');
        })
        .finally(function () {
          AUTO_ANNOTATION_STATE.running = false;
          updateAutoAnnotationButtons();
        });
    }

    function removeLowConfidenceBoxes() {
      var dom = getAutoAnnotationDom();
      if (!dom.keepConf) return;

      var threshold = Number(dom.keepConf.value || 0.3);
      if (!Number.isFinite(threshold) || threshold <= 0) {
        setAutoAnnotationFeedback('请填写有效的置信度阈值。', 'error');
        return;
      }

      var before = ANNOTATION_STATE.boxes.length;
      var hasConfidence = false;
      ANNOTATION_STATE.boxes = ANNOTATION_STATE.boxes.filter(function (box) {
        if (typeof box.confidence === 'number' && !Number.isNaN(box.confidence)) {
          hasConfidence = true;
          return box.confidence >= threshold;
        }
        return true;
      });

      if (!hasConfidence) {
        setAutoAnnotationFeedback('当前图片没有可用于筛选的置信度信息。', 'error');
        return;
      }

      var removed = before - ANNOTATION_STATE.boxes.length;
      if (removed <= 0) {
        setAutoAnnotationFeedback('当前图片没有低于阈值的候选框。', 'info');
        return;
      }

      if (ANNOTATION_STATE.selectedIndex >= ANNOTATION_STATE.boxes.length) {
        ANNOTATION_STATE.selectedIndex = ANNOTATION_STATE.boxes.length ? ANNOTATION_STATE.boxes.length - 1 : -1;
      }
      ANNOTATION_STATE.dirty = true;
      setAutoAnnotationFeedback('已删除 ' + removed + ' 个低于阈值的候选框，记得保存。', 'success');
      renderDatasetAssetPreview();
    }

    function toggleOnlyUnlabeledFilter(checked) {
      var nextValue = !!checked;
      if (DATASET_WORKSPACE_STATE.showOnlyUnlabeled === nextValue) {
        renderDatasetWorkspace();
        return;
      }
      if (!confirmAnnotationDiscard('当前图片有未保存的标注修改，切换筛选后会丢失，确认继续吗？')) {
        var dom = getAnnotationDom();
        if (dom.onlyUnlabeled) dom.onlyUnlabeled.checked = DATASET_WORKSPACE_STATE.showOnlyUnlabeled;
        return;
      }

      DATASET_WORKSPACE_STATE.showOnlyUnlabeled = nextValue;
      ensureSelectedAssetVisible();

      renderDatasetWorkspace();
      if (DATASET_WORKSPACE_STATE.selectedAssetId) {
        loadSelectedAssetAnnotation();
      } else {
        resetAnnotationState();
        renderDatasetAssetPreview();
      }
    }

    function toggleOnlyLowQualityFilter(checked) {
      var nextValue = !!checked;
      if (DATASET_WORKSPACE_STATE.showOnlyLowQuality === nextValue) {
        renderDatasetWorkspace();
        return;
      }
      if (!confirmAnnotationDiscard('当前图片有未保存的标注修改，切换筛选后会丢失，确认继续吗？')) {
        var dom = getAnnotationDom();
        if (dom.onlyLowQuality) dom.onlyLowQuality.checked = DATASET_WORKSPACE_STATE.showOnlyLowQuality;
        return;
      }

      DATASET_WORKSPACE_STATE.showOnlyLowQuality = nextValue;
      ensureSelectedAssetVisible();

      renderDatasetWorkspace();
      if (DATASET_WORKSPACE_STATE.selectedAssetId) {
        loadSelectedAssetAnnotation();
      } else {
        resetAnnotationState();
        renderDatasetAssetPreview();
      }
    }

    function updateReviewFilter(reviewFilter) {
      var nextValue = reviewFilter || 'all';
      if (DATASET_WORKSPACE_STATE.reviewFilter === nextValue) {
        renderDatasetWorkspace();
        return;
      }
      if (!confirmAnnotationDiscard('当前图片有未保存的标注修改，切换筛选后会丢失，确认继续吗？')) {
        var dom = getAnnotationDom();
        if (dom.reviewFilter) dom.reviewFilter.value = DATASET_WORKSPACE_STATE.reviewFilter;
        return;
      }

      DATASET_WORKSPACE_STATE.reviewFilter = nextValue;
      ensureSelectedAssetVisible();

      renderDatasetWorkspace();
      if (DATASET_WORKSPACE_STATE.selectedAssetId) {
        loadSelectedAssetAnnotation();
      } else {
        resetAnnotationState();
        renderDatasetAssetPreview();
      }
    }

    function refreshDatasetWorkspace(options) {
      options = options || {};
      var datasetId = DATASET_WORKSPACE_STATE.datasetId;
      if (!datasetId) return false;
      if (!options.force && !confirmAnnotationDiscard('当前图片有未保存的标注修改，刷新后会丢失，确认继续吗？')) {
        return false;
      }

      DATASET_WORKSPACE_STATE.loading = true;
      renderDatasetWorkspace();
      fetch('/train/datasets/' + encodeURIComponent(datasetId))
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (!data.ok) {
            throw new Error(data.error || '加载数据集失败');
          }
          DATASET_WORKSPACE_STATE.dataset = data.dataset || getDatasetItem(datasetId);
          DATASET_WORKSPACE_STATE.items = data.items || [];
          if (!DATASET_WORKSPACE_STATE.selectedAssetId && DATASET_WORKSPACE_STATE.items[0]) {
            DATASET_WORKSPACE_STATE.selectedAssetId = DATASET_WORKSPACE_STATE.items[0].id;
          } else if (DATASET_WORKSPACE_STATE.selectedAssetId) {
            var exists = DATASET_WORKSPACE_STATE.items.some(function (item) {
              return item.id === DATASET_WORKSPACE_STATE.selectedAssetId;
            });
            if (!exists) {
              DATASET_WORKSPACE_STATE.selectedAssetId = DATASET_WORKSPACE_STATE.items[0] ? DATASET_WORKSPACE_STATE.items[0].id : '';
            }
          }
          ensureSelectedAssetVisible();
        })
        .catch(function (err) {
          setAnnotationFeedback(err.message || '加载数据集失败', 'error');
        })
        .finally(function () {
          DATASET_WORKSPACE_STATE.loading = false;
          renderDatasetWorkspace();
          refreshAutoAnnotationJobs();
          if (DATASET_WORKSPACE_STATE.selectedAssetId) {
            loadSelectedAssetAnnotation();
          } else {
            resetAnnotationState();
            renderDatasetAssetPreview();
          }
        });
      return true;
    }

    function openDatasetWorkspace(datasetId, mode) {
      if (
        DATASET_WORKSPACE_STATE.datasetId &&
        DATASET_WORKSPACE_STATE.datasetId !== datasetId &&
        !confirmAnnotationDiscard('当前图片有未保存的标注修改，切换数据集后会丢失，确认继续吗？')
      ) {
        return false;
      }

      DATASET_WORKSPACE_STATE.datasetId = datasetId;
      DATASET_WORKSPACE_STATE.mode = mode || 'browse';
      DATASET_WORKSPACE_STATE.dataset = getDatasetItem(datasetId);
      DATASET_WORKSPACE_STATE.items = [];
      DATASET_WORKSPACE_STATE.selectedAssetId = '';
      DATASET_WORKSPACE_STATE.showOnlyUnlabeled = false;
      DATASET_WORKSPACE_STATE.showOnlyLowQuality = false;
      DATASET_WORKSPACE_STATE.reviewFilter = 'all';
      clearAutoAnnotationPollTimer();
      AUTO_ANNOTATION_STATE.running = false;
      AUTO_ANNOTATION_STATE.jobId = '';
      AUTO_ANNOTATION_STATE.jobsLoading = false;
      AUTO_ANNOTATION_STATE.jobs = [];
      resetAnnotationState();
      setAnnotationFeedback('', '');
      setAutoAnnotationFeedback('', '');
      var overlay = document.getElementById('datasetWorkspaceOverlay');
      var drawer = document.getElementById('datasetWorkspaceDrawer');
      if (overlay) overlay.classList.remove('hidden');
      if (drawer) drawer.classList.remove('translate-x-full');
      refreshDatasetWorkspace({ force: true });
      return true;
    }

    function handleAnnotationImageLoad() {
      var image = document.getElementById('annotationImage');
      if (!image) return;
      ANNOTATION_STATE.imageWidth = image.naturalWidth || 0;
      ANNOTATION_STATE.imageHeight = image.naturalHeight || 0;
      applyAnnotationImageZoom();
      renderAnnotationStage();
    }

    function handleAnnotationPointerDown(event) {
      if (DATASET_WORKSPACE_STATE.mode !== 'annotate' || ANNOTATION_STATE.loading || ANNOTATION_STATE.saving) return;
      var dataset = DATASET_WORKSPACE_STATE.dataset || getDatasetItem(DATASET_WORKSPACE_STATE.datasetId) || {};
      if (!Array.isArray(dataset.class_names) || !dataset.class_names.length) {
        setAnnotationFeedback('当前数据集未配置类别，暂时无法创建标注框。', 'error');
        return;
      }

      var point = toImagePoint(event);
      if (!point) return;
      ANNOTATION_STATE.drawing = true;
      ANNOTATION_STATE.selectedIndex = -1;
      ANNOTATION_STATE.draftBox = {
        class_index: getSelectedAnnotationClassIndex(),
        class_name: '',
        x1: point.x,
        y1: point.y,
        x2: point.x,
        y2: point.y
      };
      var overlay = document.getElementById('annotationOverlay');
      if (overlay && overlay.setPointerCapture) {
        try {
          overlay.setPointerCapture(event.pointerId);
        } catch (err) {}
      }
      renderAnnotationStage();
    }

    function handleAnnotationPointerMove(event) {
      if (!ANNOTATION_STATE.drawing || !ANNOTATION_STATE.draftBox) return;
      var point = toImagePoint(event);
      if (!point) return;
      ANNOTATION_STATE.draftBox.x2 = point.x;
      ANNOTATION_STATE.draftBox.y2 = point.y;
      renderAnnotationStage();
    }

    function finishAnnotationDraft(event) {
      if (!ANNOTATION_STATE.drawing || !ANNOTATION_STATE.draftBox) return;
      var overlay = document.getElementById('annotationOverlay');
      if (overlay && overlay.releasePointerCapture && event && typeof event.pointerId !== 'undefined') {
        try {
          overlay.releasePointerCapture(event.pointerId);
        } catch (err) {}
      }

      var draft = ANNOTATION_STATE.draftBox;
      ANNOTATION_STATE.drawing = false;
      ANNOTATION_STATE.draftBox = null;

      var left = Math.min(draft.x1, draft.x2);
      var top = Math.min(draft.y1, draft.y2);
      var right = Math.max(draft.x1, draft.x2);
      var bottom = Math.max(draft.y1, draft.y2);
      if ((right - left) < 2 || (bottom - top) < 2) {
        renderAnnotationStage();
        return;
      }

      var dataset = DATASET_WORKSPACE_STATE.dataset || getDatasetItem(DATASET_WORKSPACE_STATE.datasetId) || {};
      var classNames = dataset.class_names || [];
      var classIndex = clamp(getSelectedAnnotationClassIndex(), 0, Math.max(classNames.length - 1, 0));
      ANNOTATION_STATE.boxes.push({
        class_index: classIndex,
        class_name: classNames[classIndex] || '',
        x1: Number(left.toFixed(2)),
        y1: Number(top.toFixed(2)),
        x2: Number(right.toFixed(2)),
        y2: Number(bottom.toFixed(2))
      });
      ANNOTATION_STATE.selectedIndex = ANNOTATION_STATE.boxes.length - 1;
      ANNOTATION_STATE.dirty = true;
      setAnnotationFeedback('已新增 1 个标注框，记得点击“保存标注”写入标签文件。', 'info');
      renderDatasetAssetPreview();
    }

    function handleAnnotationPointerUp(event) {
      finishAnnotationDraft(event);
    }

    function cancelAnnotationDrawing() {
      ANNOTATION_STATE.drawing = false;
      ANNOTATION_STATE.draftBox = null;
      renderAnnotationStage();
    }

    function updateSelectedAnnotationClass() {
      if (DATASET_WORKSPACE_STATE.mode !== 'annotate') return;
      var index = ANNOTATION_STATE.selectedIndex;
      if (index < 0 || index >= ANNOTATION_STATE.boxes.length) {
        updateAnnotationButtons();
        return;
      }
      var dataset = DATASET_WORKSPACE_STATE.dataset || getDatasetItem(DATASET_WORKSPACE_STATE.datasetId) || {};
      var classNames = dataset.class_names || [];
      var classIndex = clamp(getSelectedAnnotationClassIndex(), 0, Math.max(classNames.length - 1, 0));
      ANNOTATION_STATE.boxes[index].class_index = classIndex;
      ANNOTATION_STATE.boxes[index].class_name = classNames[classIndex] || '';
      ANNOTATION_STATE.dirty = true;
      setAnnotationFeedback('已更新选中框的类别，记得保存。', 'info');
      renderAnnotationStage();
      updateAnnotationButtons();
    }

    function saveCurrentAnnotation() {
      if (!ANNOTATION_STATE.datasetId || !ANNOTATION_STATE.assetId) return;
      if (ANNOTATION_STATE.loading || ANNOTATION_STATE.saving) return;

      ANNOTATION_STATE.saving = true;
      updateAnnotationButtons();
      setAnnotationFeedback('正在保存标注...', 'info');

      var payload = {
        boxes: ANNOTATION_STATE.boxes.map(function (box) {
          return {
            class_index: box.class_index,
            confidence: typeof box.confidence === 'number' ? box.confidence : null,
            x1: box.x1,
            y1: box.y1,
            x2: box.x2,
            y2: box.y2
          };
        })
      };

      fetch('/train/datasets/' + encodeURIComponent(ANNOTATION_STATE.datasetId) + '/assets/' + encodeURIComponent(ANNOTATION_STATE.assetId) + '/annotation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (!data.ok) {
            throw new Error(data.error || '保存标注失败');
          }

          if (data.dataset) {
            DATASET_WORKSPACE_STATE.dataset = data.dataset;
            mergeTrainDataset(data.dataset);
          }
          if (data.asset) {
            mergeDatasetWorkspaceAsset(data.asset);
          }

          ANNOTATION_STATE.boxes = Array.isArray(data.boxes) ? data.boxes.map(normalizeAnnotationBox) : [];
          if (ANNOTATION_STATE.selectedIndex >= ANNOTATION_STATE.boxes.length) {
            ANNOTATION_STATE.selectedIndex = ANNOTATION_STATE.boxes.length ? ANNOTATION_STATE.boxes.length - 1 : -1;
          }
          ANNOTATION_STATE.dirty = false;
          setAnnotationFeedback(data.message || '标注已保存。', 'success');
          ensureSelectedAssetVisible();
          if (DATASET_WORKSPACE_STATE.selectedAssetId && DATASET_WORKSPACE_STATE.selectedAssetId !== ANNOTATION_STATE.assetId) {
            renderDatasetWorkspace();
            loadSelectedAssetAnnotation();
            return;
          }
          renderDatasetWorkspace();
        })
        .catch(function (err) {
          setAnnotationFeedback(err.message || '保存标注失败', 'error');
        })
        .finally(function () {
          ANNOTATION_STATE.saving = false;
          updateAnnotationButtons();
        });
    }

    function updateCurrentAssetReviewStatus(reviewStatus) {
      if (!ANNOTATION_STATE.datasetId || !ANNOTATION_STATE.assetId) return;
      if (ANNOTATION_STATE.loading || ANNOTATION_STATE.saving) return;

      ANNOTATION_STATE.saving = true;
      updateAnnotationButtons();
      setAnnotationFeedback('正在更新复核状态...', 'info');

      fetch('/train/datasets/' + encodeURIComponent(ANNOTATION_STATE.datasetId) + '/assets/' + encodeURIComponent(ANNOTATION_STATE.assetId) + '/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ review_status: reviewStatus })
      })
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (!data.ok) {
            throw new Error(data.error || '更新复核状态失败');
          }

          if (data.dataset) {
            DATASET_WORKSPACE_STATE.dataset = data.dataset;
            mergeTrainDataset(data.dataset);
          }
          if (data.asset) {
            mergeDatasetWorkspaceAsset(data.asset);
          }
          if (Array.isArray(data.boxes)) {
            ANNOTATION_STATE.boxes = data.boxes.map(normalizeAnnotationBox);
            if (ANNOTATION_STATE.selectedIndex >= ANNOTATION_STATE.boxes.length) {
              ANNOTATION_STATE.selectedIndex = ANNOTATION_STATE.boxes.length ? ANNOTATION_STATE.boxes.length - 1 : -1;
            }
          }
          setAnnotationFeedback(data.message || '复核状态已更新。', 'success');
          ensureSelectedAssetVisible();
          if (DATASET_WORKSPACE_STATE.selectedAssetId && DATASET_WORKSPACE_STATE.selectedAssetId !== ANNOTATION_STATE.assetId) {
            renderDatasetWorkspace();
            loadSelectedAssetAnnotation();
            return;
          }
          renderDatasetWorkspace();
          renderDatasetAssetPreview();
        })
        .catch(function (err) {
          setAnnotationFeedback(err.message || '更新复核状态失败', 'error');
        })
        .finally(function () {
          ANNOTATION_STATE.saving = false;
          updateAnnotationButtons();
        });
    }

    function removeSelectedAnnotationBox() {
      var index = ANNOTATION_STATE.selectedIndex;
      if (index < 0 || index >= ANNOTATION_STATE.boxes.length) return;
      ANNOTATION_STATE.boxes.splice(index, 1);
      ANNOTATION_STATE.selectedIndex = ANNOTATION_STATE.boxes.length ? Math.min(index, ANNOTATION_STATE.boxes.length - 1) : -1;
      ANNOTATION_STATE.dirty = true;
      setAnnotationFeedback('已删除选中的标注框，记得保存。', 'info');
      renderDatasetAssetPreview();
    }

    function clearAllAnnotationBoxes() {
      if (!ANNOTATION_STATE.boxes.length) return;
      if (!window.confirm('确认清空当前图片的所有标注框吗？')) return;
      ANNOTATION_STATE.boxes = [];
      ANNOTATION_STATE.selectedIndex = -1;
      ANNOTATION_STATE.dirty = true;
      setAnnotationFeedback('已清空当前图片的所有标注框，记得保存。', 'info');
      renderDatasetAssetPreview();
    }

    function handleAnnotationHotkeys(event) {
      var drawer = document.getElementById('datasetWorkspaceDrawer');
      if (!drawer || drawer.classList.contains('translate-x-full')) return;

      var target = event.target || document.activeElement;
      var tagName = target && target.tagName ? target.tagName.toLowerCase() : '';
      if (tagName === 'input' || tagName === 'textarea' || tagName === 'select' || (target && target.isContentEditable)) {
        return;
      }

      if (event.ctrlKey || event.metaKey) {
        if (event.key && event.key.toLowerCase() === 's' && DATASET_WORKSPACE_STATE.mode === 'annotate') {
          event.preventDefault();
          saveCurrentAnnotation();
        }
        return;
      }

      if ((event.key === 'Delete' || event.key === 'Backspace') && DATASET_WORKSPACE_STATE.mode === 'annotate' && ANNOTATION_STATE.selectedIndex >= 0) {
        event.preventDefault();
        removeSelectedAnnotationBox();
        return;
      }

      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        openAdjacentDatasetAsset(-1);
        return;
      }

      if (event.key === 'ArrowRight') {
        event.preventDefault();
        openAdjacentDatasetAsset(1);
        return;
      }

      if (event.key === 'Escape') {
        if (ANNOTATION_STATE.drawing) {
          event.preventDefault();
          cancelAnnotationDrawing();
        } else if (ANNOTATION_STATE.selectedIndex >= 0) {
          event.preventDefault();
          setSelectedAnnotationBox(-1);
        }
      }
    }


