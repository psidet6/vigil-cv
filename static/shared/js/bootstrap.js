    function fetchDashboardStats() {
      fetch('/api/dashboard/stats')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data) return;
          var hit     = data.today_matched  ?? '--';
          var pending = data.pending_dispatch ?? '--';
          // 侧边栏主数字
          var el1 = document.getElementById('statTodayMatched');
          var el2 = document.getElementById('statPendingDispatch');
          if (el1) el1.textContent = hit;
          if (el2) el2.textContent = pending;
          // 右面板统计
          var ph = document.getElementById('panelStatHit');
          var pp = document.getElementById('panelStatPending');
          if (ph) ph.textContent = hit;
          if (pp) pp.textContent = pending;
          // 顶部状态栏
          var th = document.getElementById('topBarHit');
          var tp = document.getElementById('topBarPending');
          if (th) th.textContent = hit;
          if (tp) tp.textContent = pending;
          // 导航徽章
          var badge = document.getElementById('navBadgePending');
          if (badge) badge.textContent = (typeof pending === 'number' ? pending : data.pending_dispatch) || 0;
        })
        .catch(function () {});
    }

    window.addEventListener('load', function () {
      if (typeof initAppAuth === 'function') {
        initAppAuth();
      }
      document.getElementById('model_key').addEventListener('change', applyModelUI);
      document.getElementById('confRange').addEventListener('input', syncConfValue);
      applyModelUI();
      syncConfValue();
      refreshJobs();
      fetchDashboardStats();
      setInterval(fetchDashboardStats, 30000);

      populateUploadModelSelect();
      document.getElementById('uploadModelKey').addEventListener('change', applyUploadModelUI);
      document.getElementById('uploadConfRange').addEventListener('input', syncUploadConfValue);
      applyUploadModelUI();
      syncUploadConfValue();
      initUploadDragDrop();
      if (typeof renderTrainBaseModelOptions === 'function') {
        renderTrainBaseModelOptions();
      }
      if (typeof renderAutoAnnotationModelOptions === 'function') {
        renderAutoAnnotationModelOptions();
      }
      if (typeof applyTrainPreset === 'function') {
        applyTrainPreset();
      }

      var annotationImage = document.getElementById('annotationImage');
      var annotationOverlay = document.getElementById('annotationOverlay');
      var annotationClassSelect = document.getElementById('annotationClassSelect');
      var annotationSaveBtn = document.getElementById('annotationSaveBtn');
      var annotationRemoveBtn = document.getElementById('annotationRemoveBtn');
      var annotationClearBtn = document.getElementById('annotationClearBtn');
      var annotationMarkReviewedBtn = document.getElementById('annotationMarkReviewedBtn');
      var annotationMarkConfirmedBtn = document.getElementById('annotationMarkConfirmedBtn');
      var annotationClearReviewBtn = document.getElementById('annotationClearReviewBtn');
      var annotationPrevBtn = document.getElementById('annotationPrevBtn');
      var annotationNextBtn = document.getElementById('annotationNextBtn');
      var annotationPrevUnlabeledBtn = document.getElementById('annotationPrevUnlabeledBtn');
      var annotationNextUnlabeledBtn = document.getElementById('annotationNextUnlabeledBtn');
      var annotationOnlyUnlabeled = document.getElementById('annotationOnlyUnlabeled');
      var annotationOnlyLowQuality = document.getElementById('annotationOnlyLowQuality');
      var annotationReviewFilter = document.getElementById('annotationReviewFilter');
      var annotationZoomSelect = document.getElementById('annotationZoomSelect');
      var annotationFitBtn = document.getElementById('annotationFitBtn');
      var annotationAutoModel = document.getElementById('annotationAutoModel');
      var annotationAutoConf = document.getElementById('annotationAutoConf');
      var annotationKeepConf = document.getElementById('annotationKeepConf');
      var annotationKeepHighBtn = document.getElementById('annotationKeepHighBtn');
      var annotationAutoJobsRefreshBtn = document.getElementById('annotationAutoJobsRefreshBtn');
      var annotationAutoCurrentBtn = document.getElementById('annotationAutoCurrentBtn');
      var annotationAutoUnlabeledBtn = document.getElementById('annotationAutoUnlabeledBtn');
      var trainPresetSelect = document.getElementById('trainPresetSelect');
      if (annotationImage) {
        annotationImage.addEventListener('load', handleAnnotationImageLoad);
      }
      if (annotationOverlay) {
        annotationOverlay.addEventListener('pointerdown', handleAnnotationPointerDown);
        annotationOverlay.addEventListener('pointermove', handleAnnotationPointerMove);
        annotationOverlay.addEventListener('pointerup', handleAnnotationPointerUp);
        annotationOverlay.addEventListener('pointerleave', handleAnnotationPointerUp);
        annotationOverlay.addEventListener('pointercancel', function () {
          ANNOTATION_STATE.drawing = false;
          ANNOTATION_STATE.draftBox = null;
          renderAnnotationStage();
        });
      }
      if (annotationClassSelect) {
        annotationClassSelect.addEventListener('change', updateSelectedAnnotationClass);
      }
      if (annotationSaveBtn) {
        annotationSaveBtn.addEventListener('click', saveCurrentAnnotation);
      }
      if (annotationRemoveBtn) {
        annotationRemoveBtn.addEventListener('click', removeSelectedAnnotationBox);
      }
      if (annotationClearBtn) {
        annotationClearBtn.addEventListener('click', clearAllAnnotationBoxes);
      }
      if (annotationMarkReviewedBtn) {
        annotationMarkReviewedBtn.addEventListener('click', function () {
          updateCurrentAssetReviewStatus('reviewed');
        });
      }
      if (annotationMarkConfirmedBtn) {
        annotationMarkConfirmedBtn.addEventListener('click', function () {
          updateCurrentAssetReviewStatus('confirmed');
        });
      }
      if (annotationClearReviewBtn) {
        annotationClearReviewBtn.addEventListener('click', function () {
          updateCurrentAssetReviewStatus('pending');
        });
      }
      if (annotationPrevBtn) {
        annotationPrevBtn.addEventListener('click', function () {
          openAdjacentDatasetAsset(-1);
        });
      }
      if (annotationNextBtn) {
        annotationNextBtn.addEventListener('click', function () {
          openAdjacentDatasetAsset(1);
        });
      }
      if (annotationPrevUnlabeledBtn) {
        annotationPrevUnlabeledBtn.addEventListener('click', function () {
          openAdjacentUnlabeledAsset(-1);
        });
      }
      if (annotationNextUnlabeledBtn) {
        annotationNextUnlabeledBtn.addEventListener('click', function () {
          openAdjacentUnlabeledAsset(1);
        });
      }
      if (annotationOnlyUnlabeled) {
        annotationOnlyUnlabeled.addEventListener('change', function () {
          toggleOnlyUnlabeledFilter(annotationOnlyUnlabeled.checked);
        });
      }
      if (annotationOnlyLowQuality) {
        annotationOnlyLowQuality.addEventListener('change', function () {
          toggleOnlyLowQualityFilter(annotationOnlyLowQuality.checked);
        });
      }
      if (annotationReviewFilter) {
        annotationReviewFilter.addEventListener('change', function () {
          updateReviewFilter(annotationReviewFilter.value || 'all');
        });
      }
      if (annotationZoomSelect) {
        annotationZoomSelect.addEventListener('change', function () {
          updateAnnotationZoom(annotationZoomSelect.value || '25');
        });
      }
      if (annotationFitBtn) {
        annotationFitBtn.addEventListener('click', fitAnnotationToViewport);
      }
      if (annotationAutoModel) {
        annotationAutoModel.addEventListener('change', syncAutoAnnotationModelUI);
      }
      if (annotationAutoConf) {
        annotationAutoConf.addEventListener('input', function () {
          annotationAutoConf.dataset.touched = '1';
        });
      }
      if (annotationKeepConf) {
        annotationKeepConf.addEventListener('input', function () {
          updateAutoAnnotationButtons();
          if (DATASET_WORKSPACE_STATE.showOnlyLowQuality) {
            renderDatasetWorkspace();
          }
        });
      }
      if (annotationAutoCurrentBtn) {
        annotationAutoCurrentBtn.addEventListener('click', function () {
          runAutoAnnotation('current');
        });
      }
      if (annotationAutoJobsRefreshBtn) {
        annotationAutoJobsRefreshBtn.addEventListener('click', refreshAutoAnnotationJobs);
      }
      if (annotationKeepHighBtn) {
        annotationKeepHighBtn.addEventListener('click', removeLowConfidenceBoxes);
      }
      if (annotationAutoUnlabeledBtn) {
        annotationAutoUnlabeledBtn.addEventListener('click', function () {
          runAutoAnnotation('all-unlabeled');
        });
      }
      if (trainPresetSelect) {
        trainPresetSelect.addEventListener('change', applyTrainPreset);
      }
      window.addEventListener('resize', function () {
        renderAnnotationStage();
      });
      window.addEventListener('keydown', handleAnnotationHotkeys);

      resetResultState('database');
      resetResultState('upload');
      refreshFaceLibraryStatus('database');
      refreshFaceLibraryStatus('upload');

      try {
        var activeTab = localStorage.getItem('special_active_tab');
        if (activeTab === 'Upload') {
          switchTab('Upload');
        } else if (activeTab === 'Train') {
          switchTab('Train');
        } else if (activeTab === 'Dispatch') {
          switchTab('Dispatch');
        } else if (activeTab === 'Face') {
          switchTab('Face');
        } else if (activeTab === 'Diagnostics') {
          switchTab('Diagnostics');
        }
      } catch (e) {}

      try {
        var lastJob = localStorage.getItem('special_last_job');
        if (lastJob) {
          document.getElementById('progressBox').classList.remove('hidden');
          poll(lastJob);
        }
      } catch (e) {}

      try {
        var lastUploadJob = localStorage.getItem('special_upload_job');
        if (lastUploadJob) {
          switchTab('Upload');
          document.getElementById('uploadProgressBox').classList.remove('hidden');
          pollUpload(lastUploadJob);
        }
      } catch (e) {}

      if (typeof refreshTrainJobs === 'function') {
        refreshTrainJobs();
      }
      if (typeof refreshDispatchTab === 'function') {
        refreshDispatchTab();
      }
    });
