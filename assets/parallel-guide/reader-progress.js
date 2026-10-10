(function () {
  'use strict';
  const data = window.guideData;
  const copy = value => JSON.parse(JSON.stringify(value));
  function hydrateProgress(saved) {
    const first = data.phases.find(phase => data.detailGuides[phase.id].length);
    const result = {completedById: {}, current: {phaseId: first.id, index: 0, stepId: data.detailGuides[first.id][0].id}};
    for (const phase of data.phases) {
      const ids = new Set(data.detailGuides[phase.id].map(step => step.id));
      result.completedById[phase.id] = Array.isArray(saved?.completedById?.[phase.id])
        ? [...new Set(saved.completedById[phase.id].filter(id => ids.has(id)))] : [];
    }
    const current = saved?.current;
    const items = data.detailGuides[current?.phaseId];
    if (items?.length) {
      const found = items.findIndex(step => step.id === current.stepId);
      const index = found >= 0 ? found : Math.max(0, Math.min(Number.isInteger(current.index) ? current.index : 0, items.length - 1));
      result.current = {phaseId: current.phaseId, index, stepId: items[index].id};
    }
    return result;
  }
  function orderedImages(visual) {
    const items = ['shot', 'map'].flatMap(type => (visual[type === 'shot' ? 'shots' : 'maps'] || [])
      .map((image, index) => ({type, index, id: image.visualId})));
    return (visual.visualOrder || items.map(item => item.id)).map(id => items.find(item => item.id === id)).filter(Boolean);
  }
  // The reader stores only each recipient's progress. Guide content is bundled and frozen.
  window.guideReader = Object.freeze({hydrateProgress, progressForStorage: copy, orderedImages});
})();
