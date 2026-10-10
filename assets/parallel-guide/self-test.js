(() => {
  try {
    const assert = (condition, message) => { if (!condition) throw new Error(message); };
    const data = window.guideData;
    assert(data.phases.length === 26, '阶段数量不正确');
    assert(Object.isFrozen(data) && Object.isFrozen(data.detailGuides.u1), '完成稿未冻结');
    assert(!document.querySelector('[contenteditable="true"], .editor-toolbar, #importGuideBtn'), '出现正文编辑入口');
    assert(!window.guideEditor && !window.guideEditCore, '加载了编辑组件');
    assert(getComputedStyle(document.querySelector('.search-wrap')).display !== 'none', '窄窗口隐藏了搜索入口');
    let steps = 0, images = 0, dialogs = 0;
    const imagePaths = new Set();
    for (const phase of data.phases) {
      document.querySelector(`#phaseNav [data-phase-id="${phase.id}"]`).click();
      const items = [...document.querySelectorAll('.guide-item')];
      assert(document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1, `页面横向溢出：${phase.id} (${innerWidth}/${document.documentElement.scrollWidth})`);
      assert(items.length === data.detailGuides[phase.id].length, `步骤缺失：${phase.id}`);
      for (const [index, item] of items.entries()) {
        assert(item.querySelector('.guide-action').textContent === data.detailGuides[phase.id][index].action, `正文不同：${phase.id}`);
      }
      for (const image of document.querySelectorAll('#appView img')) {
        const uri = new URL(image.src);
        assert(uri.host === location.host, '出现外部图片');
        imagePaths.add(decodeURIComponent(uri.pathname).slice(1));
        images++;
      }
      const map = document.querySelector('[data-open-map]');
      if (map) {
        map.click();
        const dialog = document.querySelector('dialog[open]');
        assert(dialog, '图片放大窗口未打开');
        dialog.querySelector('[data-visual-zoom="in"]').click();
        assert(dialog.querySelector('[data-visual-zoom-value]').textContent !== '100%', '图解缩放失败');
        dialog.querySelector('[data-close-atlas]').click();
        dialogs++;
      }
      steps += items.length;
    }
    assert(steps === 132, '完成稿步骤总数不正确');
    assert(dialogs > 0, '没有检查图解放大');
    const search = document.querySelector('#searchInput');
    search.value = '吹寄';
    search.dispatchEvent(new Event('input', {bubbles: true}));
    assert(document.querySelectorAll('.search-result').length > 0, '搜索失败');
    search.value = '';
    search.dispatchEvent(new Event('input', {bubbles: true}));
    document.querySelector('#phaseNav [data-phase-id="u1"]').click();
    document.querySelector('#resetProgressBtn').click();
    document.querySelector('[data-progress-toggle]').click();
    const saved = JSON.parse(localStorage.getItem('pokemmo-parallel-reader-progress-v1'));
    assert(saved.completedById.u1.length === 1, '完成勾选未保存');
    assert(Object.keys(saved).sort().join(',') === 'completedById,current', '保存了正文数据');
    return {ok: true, phases: data.phases.length, steps, rendered_images: images, map_dialogs: dialogs,
      image_paths: [...imagePaths], frozen_content: true, search: true, narrow_search: true, progress: true};
  } catch (error) { return {ok: false, error: error.stack}; }
})();
