    const TRAIN_DATASET_STATE = { items: [], loading: false, importing: false };
    const RESULT_IMPORT_STATE = { prefix: '', assetIds: [], submitting: false };

    function setTrainDatasetFeedback(message, tone) {
      var box = document.getElementById('trainDatasetFeedback');
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

    function setTrainImportFeedback(message, tone) {
      var box = document.getElementById('trainImportFeedback');
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

    function setResultImportFeedback(message, tone) {
      var box = document.getElementById('resultImportFeedback');
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

    function summarizeTrainDatasets(items) {
      var summary = {
        dataset_count: items.length,
        image_count: 0,
        labeled_count: 0,
        reviewed_count: 0,
        version_count: 0
      };
      (items || []).forEach(function (item) {
        summary.image_count += Number(item.image_count || 0);
        summary.labeled_count += Number(item.labeled_count || 0);
        summary.reviewed_count += Number(item.reviewed_count || 0);
        summary.version_count += Number(item.version_count || 0);
      });
      return summary;
    }

    function getDatasetItem(datasetId) {
      for (var i = 0; i < TRAIN_DATASET_STATE.items.length; i++) {
        if (TRAIN_DATASET_STATE.items[i].id === datasetId) return TRAIN_DATASET_STATE.items[i];
      }
      return null;
    }

    function mergeTrainDataset(dataset) {
      if (!dataset || !dataset.id) return;
      var merged = false;
      TRAIN_DATASET_STATE.items = TRAIN_DATASET_STATE.items.map(function (item) {
        if (item.id === dataset.id) {
          merged = true;
          return Object.assign({}, item, dataset);
        }
        return item;
      });
      if (!merged) {
        TRAIN_DATASET_STATE.items.unshift(dataset);
      }
      renderTrainSummary(summarizeTrainDatasets(TRAIN_DATASET_STATE.items));
      renderTrainDatasetOptions(TRAIN_DATASET_STATE.items);
      renderResultImportDatasetOptions(TRAIN_DATASET_STATE.items);
      if (typeof renderTrainRunDatasetOptions === 'function') {
        renderTrainRunDatasetOptions(TRAIN_DATASET_STATE.items);
      }
      renderTrainDatasets(TRAIN_DATASET_STATE.items);
    }

    function renderTrainSummary(summary) {
      var data = summary || {};
      var metrics = {
        trainMetricDatasets: data.dataset_count || 0,
        trainMetricImages: data.image_count || 0,
        trainMetricLabeled: data.labeled_count || 0,
        trainMetricReviewed: data.reviewed_count || 0
      };
      Object.keys(metrics).forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.textContent = metrics[id];
      });
    }

    function renderTrainDatasetOptions(items) {
      var select = document.getElementById('trainImportDataset');
      var fileInput = document.getElementById('trainImportFile');
      var submitBtn = document.getElementById('trainImportSubmit');
      if (!select) return;

      var previousValue = select.value;
      var hasItems = !!(items && items.length);
      if (!hasItems) {
        select.innerHTML = '<option value="">请先创建数据集</option>';
        select.disabled = true;
        if (fileInput) {
          fileInput.disabled = true;
          fileInput.value = '';
        }
        if (submitBtn) submitBtn.disabled = true;
        renderResultImportDatasetOptions([]);
        if (typeof renderTrainRunDatasetOptions === 'function') {
          renderTrainRunDatasetOptions([]);
        }
        return;
      }

      select.innerHTML = items.map(function (item) {
        return '<option value="' + escapeHtml(item.id || '') + '">' + escapeHtml(item.name || item.id || '') + '</option>';
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
      if (fileInput) fileInput.disabled = false;
      if (submitBtn) submitBtn.disabled = TRAIN_DATASET_STATE.importing;
      renderResultImportDatasetOptions(items);
      if (typeof renderTrainRunDatasetOptions === 'function') {
        renderTrainRunDatasetOptions(items);
      }
    }

    function renderResultImportDatasetOptions(items) {
      var select = document.getElementById('resultImportDatasetSelect');
      var submitBtn = document.getElementById('resultImportSubmitBtn');
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
        return '<option value="' + escapeHtml(item.id || '') + '">' + escapeHtml(item.name || item.id || '') + '</option>';
      }).join('');

      var matched = items.some(function (item) {
        return item.id === previousValue;
      });
      if (matched) {
        select.value = previousValue;
      } else {
        var datasetSelect = document.getElementById('trainImportDataset');
        if (datasetSelect && datasetSelect.value && items.some(function (item) { return item.id === datasetSelect.value; })) {
          select.value = datasetSelect.value;
        } else if (items[0]) {
          select.value = items[0].id;
        }
      }

      select.disabled = false;
      if (submitBtn) submitBtn.disabled = RESULT_IMPORT_STATE.submitting || TRAIN_DATASET_STATE.loading;
    }

    function renderTrainDatasets(items) {
      var box = document.getElementById('trainDatasetList');
      if (!box) return;
      if (!items || !items.length) {
        box.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">暂无数据集。先创建一个数据集，再继续做 ZIP 导入、历史结果回流和标注。</div>';
        return;
      }

      box.innerHTML = items.map(function (item) {
        var classBadges = (item.class_names || []).map(function (name) {
          return '<span class="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 ring-1 ring-inset ring-slate-200">' + escapeHtml(name) + '</span>';
        }).join('');
        if (!classBadges) {
          classBadges = '<span class="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500 ring-1 ring-inset ring-slate-200">未设置类别</span>';
        }

        var recentAssets = item.recent_assets || [];
        var previewGrid = recentAssets.map(function (asset) {
          var imageUrl = asset.asset_url || '#';
          var assetName = asset.origin_name || asset.filename || 'image';
          return (
            '<a href="' + escapeHtml(imageUrl) + '" target="_blank" rel="noreferrer" class="group overflow-hidden rounded-2xl border border-slate-200 bg-white transition hover:-translate-y-0.5 hover:border-teal-200 hover:shadow-sm">' +
              '<div class="aspect-[4/3] overflow-hidden bg-slate-100">' +
                '<img src="' + escapeHtml(imageUrl) + '" alt="' + escapeHtml(assetName) + '" loading="lazy" class="h-full w-full object-cover transition duration-200 group-hover:scale-[1.02]" />' +
              '</div>' +
              '<div class="px-3 py-3">' +
                '<div class="truncate text-sm font-medium text-slate-800">' + escapeHtml(assetName) + '</div>' +
                '<div class="mt-1 text-xs text-slate-500">' + escapeHtml(asset.width || 0) + ' × ' + escapeHtml(asset.height || 0) + ' · ' + escapeHtml(formatBytes(asset.size_bytes || 0)) + '</div>' +
              '</div>' +
            '</a>'
          );
        }).join('');

        var updatedAt = item.updated_ts ? new Date(item.updated_ts * 1000).toLocaleString('zh-CN') : '--';
        return (
          '<div class="rounded-3xl border border-slate-200 bg-white/90 p-5 shadow-sm shadow-slate-200/60">' +
            '<div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">' +
              '<div class="min-w-0 flex-1">' +
                '<div class="flex flex-wrap items-center gap-2">' +
                  '<div class="truncate text-base font-semibold text-slate-900">' + escapeHtml(item.name || item.id || '') + '</div>' +
                  '<span class="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700 ring-1 ring-inset ring-amber-200">' + escapeHtml(item.status || 'draft') + '</span>' +
                '</div>' +
                '<div class="mt-2 break-all font-mono text-xs text-slate-400">' + escapeHtml(item.id || '') + '</div>' +
                '<div class="mt-3 flex flex-wrap gap-2">' + classBadges + '</div>' +
              '</div>' +
              '<div class="grid min-w-[260px] grid-cols-2 gap-3 text-sm">' +
                '<div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3"><div class="text-xs text-slate-400">图片数</div><div class="mt-1 font-semibold text-slate-800">' + escapeHtml(item.image_count || 0) + '</div></div>' +
                '<div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3"><div class="text-xs text-slate-400">已标注</div><div class="mt-1 font-semibold text-slate-800">' + escapeHtml(item.labeled_count || 0) + '</div></div>' +
                '<div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3"><div class="text-xs text-slate-400">已复核</div><div class="mt-1 font-semibold text-slate-800">' + escapeHtml(item.reviewed_count || 0) + '</div></div>' +
                '<div class="rounded-2xl border border-slate-200 bg-slate-50/80 px-3 py-3"><div class="text-xs text-slate-400">版本数</div><div class="mt-1 font-semibold text-slate-800">' + escapeHtml(item.version_count || 0) + '</div></div>' +
              '</div>' +
            '</div>' +
            (item.notes ? '<div class="mt-4 rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3 text-sm leading-6 text-slate-600">' + escapeHtml(item.notes) + '</div>' : '') +
            '<div class="mt-4 flex flex-col gap-2 text-xs text-slate-400 sm:flex-row sm:items-center sm:justify-between">' +
              '<span>更新时间：' + escapeHtml(updatedAt) + '</span>' +
              '<span class="break-all">目录：' + escapeHtml(item.root_dir || '') + '</span>' +
            '</div>' +
            '<div class="mt-5 border-t border-slate-100 pt-5">' +
              '<div class="flex flex-wrap items-center justify-between gap-3">' +
                '<div>' +
                  '<div class="text-sm font-semibold text-slate-800">最近导入</div>' +
                  '<div class="mt-1 text-xs text-slate-400">显示最近 ' + escapeHtml(recentAssets.length || 0) + ' 张</div>' +
                '</div>' +
                '<div class="flex flex-wrap gap-2">' +
                  '<button type="button" class="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-50" onclick="openDatasetWorkspace(\'' + escapeHtml(item.id || '') + '\', \'browse\')">浏览图片</button>' +
                  '<button type="button" class="rounded-full bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-slate-700" onclick="openDatasetWorkspace(\'' + escapeHtml(item.id || '') + '\', \'annotate\')">开始标注</button>' +
                '</div>' +
              '</div>' +
              (previewGrid
                ? '<div class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">' + previewGrid + '</div>'
                : '<div class="mt-4 rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-5 text-sm text-slate-500">还没有导入图片，可从上方选择 ZIP 包导入。</div>') +
            '</div>' +
          '</div>'
        );
      }).join('');
    }

    function applyTrainDatasetPayload(payload) {
      TRAIN_DATASET_STATE.items = payload.items || [];
      renderTrainSummary(payload.summary || {});
      renderTrainDatasetOptions(TRAIN_DATASET_STATE.items);
      renderResultImportDatasetOptions(TRAIN_DATASET_STATE.items);
      if (typeof renderTrainRunDatasetOptions === 'function') {
        renderTrainRunDatasetOptions(TRAIN_DATASET_STATE.items);
      }
      renderTrainDatasets(TRAIN_DATASET_STATE.items);
    }

    function refreshTrainDatasets() {
      var box = document.getElementById('trainDatasetList');
      TRAIN_DATASET_STATE.loading = true;
      setTrainDatasetFeedback('', '');
      setTrainImportFeedback('', '');
      if (box && !TRAIN_DATASET_STATE.items.length) {
        box.innerHTML = '<div class="rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-4 py-6 text-sm text-slate-500">正在加载数据集...</div>';
      }

      fetch('/train/datasets')
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
          if (!data.ok) {
            throw new Error(data.error || '加载数据集失败');
          }
          applyTrainDatasetPayload(data);
        })
        .catch(function (err) {
          if (box && !TRAIN_DATASET_STATE.items.length) {
            box.innerHTML = '<div class="rounded-2xl border border-dashed border-rose-200 bg-rose-50 px-4 py-6 text-sm text-rose-700">' + escapeHtml(err.message || '加载数据集失败') + '</div>';
          }
        })
        .finally(function () {
          TRAIN_DATASET_STATE.loading = false;
        });
    }

    function createTrainDataset(event) {
      if (event) event.preventDefault();
      var nameInput = document.getElementById('trainDatasetName');
      var classesInput = document.getElementById('trainDatasetClasses');
      var notesInput = document.getElementById('trainDatasetNotes');
      var submitBtn = document.getElementById('trainDatasetSubmit');
      if (!nameInput || !classesInput || !submitBtn) return false;

      var payload = {
        name: nameInput.value.trim(),
        class_names: classesInput.value.trim(),
        notes: notesInput ? notesInput.value.trim() : ''
      };

      submitBtn.disabled = true;
      setTrainDatasetFeedback('', '');

      fetch('/train/datasets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
        .then(function (resp) {
          return resp.text().then(function (text) {
            var data = {};
            try {
              data = text ? JSON.parse(text) : {};
            } catch (e) {
              data = {};
            }
            data.__http_ok = resp.ok;
            data.__http_status = resp.status;
            return data;
          });
        })
        .then(function (data) {
          if (!data.ok || data.__http_ok === false) {
            throw new Error(data.error || ('创建数据集失败，HTTP ' + (data.__http_status || 'unknown')));
          }
          applyTrainDatasetPayload(data);
          document.getElementById('trainDatasetForm').reset();
          if (data.dataset_id) {
            var datasetSelect = document.getElementById('trainImportDataset');
            if (datasetSelect) datasetSelect.value = data.dataset_id;
          }
          setTrainImportFeedback('', '');
          setTrainDatasetFeedback('数据集已创建，可继续导入 ZIP 图片。', 'success');
        })
        .catch(function (err) {
          setTrainDatasetFeedback(err.message || '创建数据集失败', 'error');
        })
        .finally(function () {
          submitBtn.disabled = false;
        });
      return false;
    }

    function importTrainZip(event) {
      if (event) event.preventDefault();
      var datasetSelect = document.getElementById('trainImportDataset');
      var fileInput = document.getElementById('trainImportFile');
      var submitBtn = document.getElementById('trainImportSubmit');
      if (!datasetSelect || !fileInput || !submitBtn) return false;

      var datasetId = datasetSelect.value;
      var file = fileInput.files && fileInput.files[0];
      if (!datasetId) {
        setTrainImportFeedback('请先选择一个数据集。', 'error');
        return false;
      }
      if (!file) {
        setTrainImportFeedback('请选择要导入的 ZIP 文件。', 'error');
        return false;
      }

      TRAIN_DATASET_STATE.importing = true;
      submitBtn.disabled = true;
      setTrainImportFeedback('', '');

      var formData = new FormData();
      formData.append('file', file);

      fetch('/train/datasets/' + encodeURIComponent(datasetId) + '/import-zip', {
        method: 'POST',
        body: formData
      })
        .then(function (resp) {
          return resp.text().then(function (text) {
            var data = {};
            try {
              data = text ? JSON.parse(text) : {};
            } catch (e) {
              data = {};
            }
            data.__http_ok = resp.ok;
            data.__http_status = resp.status;
            return data;
          });
        })
        .then(function (data) {
          if (!data.ok || data.__http_ok === false) {
            throw new Error(data.error || ('ZIP 导入失败，HTTP ' + (data.__http_status || 'unknown')));
          }
          applyTrainDatasetPayload(data);
          document.getElementById('trainImportForm').reset();
          if (data.dataset_id) {
            var select = document.getElementById('trainImportDataset');
            if (select) select.value = data.dataset_id;
          }
          setTrainDatasetFeedback('', '');
          setTrainImportFeedback(data.message || 'ZIP 导入完成', 'success');
        })
        .catch(function (err) {
          setTrainImportFeedback(err.message || 'ZIP 导入失败', 'error');
        })
        .finally(function () {
          TRAIN_DATASET_STATE.importing = false;
          renderTrainDatasetOptions(TRAIN_DATASET_STATE.items);
        });
      return false;
    }

    function refreshTrainTab() {
      refreshTrainDatasets();
      if (typeof refreshTrainJobs === 'function') {
        refreshTrainJobs();
      }
      return false;
    }

    function closeResultImportModal() {
      RESULT_IMPORT_STATE.prefix = '';
      RESULT_IMPORT_STATE.assetIds = [];
      RESULT_IMPORT_STATE.submitting = false;
      var overlay = document.getElementById('resultImportOverlay');
      var drawer = document.getElementById('resultImportDrawer');
      if (overlay) overlay.classList.add('hidden');
      if (drawer) drawer.classList.add('translate-x-full');
      setResultImportFeedback('', '');
      renderResultImportDatasetOptions(TRAIN_DATASET_STATE.items);
    }

    function openResultImportModal(prefix, encodedAssetId) {
      var state = FACE_RESULT_STATE[prefix];
      if (!state || !state.jobId) {
        alert('当前没有可导入的数据');
        return;
      }

      var assetIds = [];
      if (encodedAssetId) {
        assetIds = [decodeURIComponent(encodedAssetId)];
      } else {
        assetIds = Array.from(state.selected);
      }
      if (!assetIds.length) {
        alert('请先勾选至少一张结果图');
        return;
      }

      RESULT_IMPORT_STATE.prefix = prefix;
      RESULT_IMPORT_STATE.assetIds = assetIds;
      RESULT_IMPORT_STATE.submitting = false;
      setResultImportFeedback('', '');
      renderResultImportDatasetOptions(TRAIN_DATASET_STATE.items);
      if (!TRAIN_DATASET_STATE.items.length && !TRAIN_DATASET_STATE.loading) {
        refreshTrainDatasets();
      }

      var title = document.getElementById('resultImportTitle');
      var meta = document.getElementById('resultImportMeta');
      if (title) {
        title.textContent = assetIds.length === 1 ? '导入当前结果图' : '批量导入结果图';
      }
      if (meta) {
        meta.textContent = (prefix === 'database' ? '数据库检测结果' : '本地上传检测结果') +
          ' · 任务 ' + state.jobId +
          ' · 已选择 ' + assetIds.length + ' 张结果图';
      }

      var overlay = document.getElementById('resultImportOverlay');
      var drawer = document.getElementById('resultImportDrawer');
      if (overlay) overlay.classList.remove('hidden');
      if (drawer) drawer.classList.remove('translate-x-full');
    }

    function submitResultImport() {
      var prefix = RESULT_IMPORT_STATE.prefix;
      var state = FACE_RESULT_STATE[prefix];
      var datasetSelect = document.getElementById('resultImportDatasetSelect');
      var submitBtn = document.getElementById('resultImportSubmitBtn');
      if (!prefix || !state || !state.jobId) {
        setResultImportFeedback('当前没有可导入的数据。', 'error');
        return;
      }
      if (!datasetSelect || !datasetSelect.value) {
        setResultImportFeedback('请先选择一个目标数据集。', 'error');
        return;
      }
      if (!RESULT_IMPORT_STATE.assetIds.length) {
        setResultImportFeedback('请先选择至少一张结果图。', 'error');
        return;
      }

      RESULT_IMPORT_STATE.submitting = true;
      if (submitBtn) submitBtn.disabled = true;
      setResultImportFeedback('', '');

      fetch('/train/datasets/' + encodeURIComponent(datasetSelect.value) + '/import-results', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          job_id: state.jobId,
          asset_ids: RESULT_IMPORT_STATE.assetIds
        })
      })
        .then(function (resp) {
          return resp.text().then(function (text) {
            var data = {};
            try {
              data = text ? JSON.parse(text) : {};
            } catch (e) {
              data = {};
            }
            data.__http_ok = resp.ok;
            data.__http_status = resp.status;
            return data;
          });
        })
        .then(function (data) {
          if (!data.ok || data.__http_ok === false) {
            throw new Error(data.error || ('导入失败，HTTP ' + (data.__http_status || 'unknown')));
          }
          applyTrainDatasetPayload(data);
          setTrainDatasetFeedback('', '');
          setTrainImportFeedback(data.message || '结果图已加入数据集。', 'success');
          setResultImportFeedback(data.message || '结果图已加入数据集。', 'success');
          window.setTimeout(function () {
            closeResultImportModal();
          }, 600);
        })
        .catch(function (err) {
          setResultImportFeedback(err.message || '结果图导入失败', 'error');
        })
        .finally(function () {
          RESULT_IMPORT_STATE.submitting = false;
          renderResultImportDatasetOptions(TRAIN_DATASET_STATE.items);
        });
    }
