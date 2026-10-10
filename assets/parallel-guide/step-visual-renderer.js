(function attachStepVisualRenderer() {
  const data = window.guideData;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const colors = {entry:'#087c85',exit:'#087c85',story:'#2358a5',heal:'#2358a5',item:'#7958a5',goal:'#b82e39',battle:'#b82e39',switch:'#925800'};
  const version = map => map.version || (/ HGSS\.png$/.test(map.file) ? '心金／魂银地形' : / (?:Pt|DPPt)\.png$/.test(map.file) ? '白金地形' : / FRLG\.png$/.test(map.file) ? '火红／叶绿地形' : / (?:E|SE|RSE)\.png$/.test(map.file) ? '绿宝石地形' : '黑／白地形');
  const noteFor = (phaseId, step, mapId) => data.stepMapNotes?.[phaseId]?.[step]?.[mapId] || data.mapNotes?.[mapId] || {points:[]};
  const mapInfo = (phaseId, step, mapIndex) => {
    const visual = data.stepVisuals[phaseId]?.[step];
    const ref = visual?.maps[mapIndex];
    let map = ref && (ref.custom || data.atlas[ref.id]);
    if (!map) return null;
    if(ref.annotation)map={...map,annotation:ref.annotation};
    let note = ref.custom ? {points:[],mode:'步骤配图'} : noteFor(phaseId,step,ref.id);
    if(!ref.custom&&ref.landmarks!==undefined)note={...note,points:ref.landmarks.filter(point=>!point.hidden)};
    if (ref.description !== undefined) { note = {...note,note:ref.description}; map = {...map,description:ref.description}; }
    return {ref,map,note,item:data.detailGuides[phaseId][step]};
  };
  function overlay(map, note, instance) {
    const radius = Math.max(map.width,map.height)/60;
    const paths = (note.paths || []).map(route => {
      const points = route.points.map(([x,y]) => `${x*map.width/100},${y*map.height/100}`).join(' ');
      const color = route.kind === 'optional' ? '#3879dc' : '#04e1cf';
      return `<polyline points="${points}" fill="none" stroke="#102b38" stroke-width="${radius*.38}" stroke-linejoin="round" stroke-linecap="round"/><polyline points="${points}" fill="none" stroke="${color}" stroke-width="${radius*.22}" ${route.kind === 'optional' ? `stroke-dasharray="${radius*.55} ${radius*.3}"` : ''} stroke-linejoin="round" stroke-linecap="round" marker-end="url(#arrow-${instance}-${route.kind})"/>`;
    }).join('');
    const points = (note.points || []).map(point => {
      const x=(point.labelX ?? point.x)*map.width/100, y=(point.labelY ?? point.y)*map.height/100;
      const anchor=point.labelX!==undefined || point.labelY!==undefined ? `<path d="M ${point.x*map.width/100} ${point.y*map.height/100} L ${x} ${y}" stroke="white" stroke-width="${radius*.12}"/><circle cx="${point.x*map.width/100}" cy="${point.y*map.height/100}" r="${radius*.2}" fill="${colors[point.kind]}" stroke="white" stroke-width="${radius*.1}"/>` : '';
      return `<g data-map-point="${escape(point.id)}"><title>${escape(point.id+' · '+point.label)}</title>${anchor}<circle cx="${x}" cy="${y}" r="${radius}" fill="${colors[point.kind] || colors.story}" stroke="white" stroke-width="${radius*.13}"/><text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="central" fill="white" font-size="${radius*(point.id.length>1 ? 1.0 : 1.3)}" font-family="system-ui,sans-serif" font-weight="800">${escape(point.id)}</text></g>`;
    }).join('');
    if (!points && !paths) return '';
    return `<svg class="atlas-overlay" viewBox="0 0 ${map.width} ${map.height}" role="img" aria-label="${escape(note.mode || '地图标注')}：${escape((note.points || []).map(p=>p.id+' '+p.label).join('；'))}"><defs>${['route','optional'].map(kind=>`<marker id="arrow-${instance}-${kind}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${kind==='optional'?'#3879dc':'#04e1cf'}"/></marker>`).join('')}</defs>${paths}${points}</svg>`;
  }
  const board = (map,note,instance) => `<span class="atlas-board" style="aspect-ratio:${map.width}/${map.height};--map-ratio:${map.width/map.height}"><img src="${escape(map.src)}" width="${map.width}" height="${map.height}" loading="lazy" alt="${escape(map.file || map.description || '分层路线图')}">${overlay(map,note,instance)}${window.ImageMarkupCore?.svg(map.annotation)||''}</span>`;
  const mapSource = (map,ref,full=false) => ref.custom ? '' : `${escape(full?map.credit:version(map))} · <a href="${escape(map.source)}" target="_blank" rel="noreferrer">${full?'地图原始来源':'地图来源'} ↗</a>`;
  const pointText = point => `<span class="atlas-action-text"><strong>${escape(point.label)}</strong>${point.detail && point.detail !== point.label ? `<span>${escape(point.detail)}</span>` : ''}</span>`;
  const actionList = (points, attrs, dialogView = false) => points?.length ? `<ol class="${dialogView ? 'atlas-point-list' : 'atlas-landmarks'}" aria-label="地图节点动作顺序">${points.map(point => `<li><button type="button" ${dialogView ? `data-select-point="${escape(point.id)}" aria-pressed="false"` : `${attrs} data-visual-point="${escape(point.id)}"`}><b style="background:${colors[point.kind]||colors.story}">${escape(point.id)}</b>${pointText(point)}</button></li>`).join('')}</ol>` : '';
  const mapDescription = (map,note) => note.note || map.description || '';
  function renderMapCard(phaseId,step,mapIndex) {
    const info = mapInfo(phaseId,step,mapIndex);
    if (!info) return '';
    const {map,note,ref} = info;
    const attrs = `data-open-map="true" data-visual-phase="${phaseId}" data-visual-step="${step}" data-visual-map="${mapIndex}"`;
    const description=mapDescription(map,note);
    return `<figure class="atlas-card"><figcaption class="atlas-card-heading"><strong>${escape(ref.title)}</strong><span>${escape(note.mode || (map.preAnnotated?'社区分层路线图':'地形全图参考'))}</span></figcaption><button type="button" class="atlas-preview" ${attrs} aria-label="放大图解：${escape(ref.title)}">${board(map,note,`${phaseId}-${step}-${mapIndex}`)}<span class="atlas-enlarge">放大图解 ⤢</span></button><div class="atlas-card-info">${description ? `<p>${escape(description)}</p>` : ''}${actionList(note.points,attrs)}<small>${mapSource(map,ref)}</small></div></figure>`;
  }
  function renderStep(phase,index) {
    const visual = data.stepVisuals[phase.id]?.[index];
    if (!visual || (!visual.shots.length && !visual.maps.length)) return '';
    const shots = visual.shots.map((shot,i)=>{const preview=`<span class="image-markup-preview"><img src="${escape(shot.src)}" loading="lazy" alt="${escape(shot.kind)}">${window.ImageMarkupCore?.svg(shot.annotation)||''}</span>`;return `<figure class="key-shot">${shot.annotation?`<button type="button" class="image-shot-open" data-open-shot data-visual-phase="${phase.id}" data-visual-step="${index}" data-visual-shot="${i}" aria-label="放大截图：${escape(shot.kind)}">${preview}</button>`:`<a href="${escape(shot.src)}" target="_blank" rel="noreferrer" aria-label="放大截图：${escape(shot.kind)}"><img src="${escape(shot.src)}" loading="lazy" alt="${escape(shot.kind)}"></a>`}<figcaption><strong>${escape(shot.kind)}</strong>${escape(shot.caption)}</figcaption></figure>`;});
    const maps = visual.maps.map((_,i)=>renderMapCard(phase.id,index,i));
    const more = (items,start,label,cls) => items.length>start ? `<details class="visual-more"><summary>${label}（${items.length-start} 张）</summary><div class="${cls}">${items.slice(start).join('')}</div></details>` : '';
    const instructions = visual.maps.filter(ref=>!ref.custom).map(ref=>noteFor(phase.id,index,ref.id)).filter(n=>n?.walkthrough);
    const ordered=visual.visualOrder?window.guideReader.orderedImages(visual).map(item=>item.type==='shot'?shots[item.index]:maps[item.index]):null;
    const images=ordered?`<div class="ordered-visuals">${ordered.slice(0,4).join('')}</div>${more(ordered,4,'展开其余图片／楼层','ordered-visuals')}`:`${shots.length?`<div class="key-shots">${shots.slice(0,2).join('')}</div>${more(shots,2,'其余场景图','key-shots')}`:''}<div class="step-atlas">${maps.slice(0,2).join('')}</div>${more(maps,2,'展开其余楼层／区域全图','step-atlas')}`;
    return `<section class="step-visuals" aria-label="第 ${index+1} 步图解">${images}${instructions.length?`<div class="map-walkthrough"><strong>按图走 · 分段动作</strong>${instructions.map(n=>`<ol>${n.walkthrough.map(line=>`<li>${escape(line)}</li>`).join('')}</ol><a href="${escape(n.source)}" target="_blank" rel="noreferrer">走法依据 ↗</a>`).join('')}</div>`:''}</section>`;
  }
  let dialog, current, zoom=1, baseWidth=0, returnFocus;
  function ensureDialog() {
    if (dialog) return;
    dialog = document.createElement('dialog'); dialog.className='atlas-dialog'; dialog.id='atlasDialog';
    dialog.setAttribute('aria-labelledby','atlasDialogTitle'); document.body.append(dialog);
    dialog.addEventListener('close',()=>{returnFocus?.focus({preventScroll:true});current=null;});
  }
  function resizeBoard() {
    const viewport=dialog.querySelector('.atlas-dialog-viewport');
    const map=current.map;
    baseWidth=Math.min(viewport.clientWidth-24,(viewport.clientHeight-24)*map.width/map.height);
    const canvas=viewport.querySelector('.atlas-board');canvas.style.width=`${Math.max(80,baseWidth*zoom)}px`;
    dialog.querySelector('[data-visual-zoom-value]').textContent=`${Math.round(zoom*100)}%`;
  }
  function selectPoint(id) {
    const point=current?.note.points?.find(p=>p.id===id);
    if (!point) return;
    dialog.querySelectorAll('[data-map-point]').forEach(node=>node.classList.toggle('is-selected',node.dataset.mapPoint===id));
    dialog.querySelectorAll('[data-select-point]').forEach(node=>node.setAttribute('aria-pressed',String(node.dataset.selectPoint===id)));
    const status = dialog.querySelector('.atlas-point-detail');
    status.hidden=false;
    status.textContent=`${point.id} · ${point.detail || point.label}`;
    if(zoom>1){const viewport=dialog.querySelector('.atlas-dialog-viewport');const canvas=viewport.querySelector('.atlas-board');viewport.scrollTo({left:canvas.offsetLeft+canvas.clientWidth*point.x/100-viewport.clientWidth/2,top:canvas.offsetTop+canvas.clientHeight*point.y/100-viewport.clientHeight/2});}
  }
  function openMap(target) {
    const pid=target.dataset.visualPhase,step=Number(target.dataset.visualStep),shot=target.hasAttribute('data-open-shot')?data.stepVisuals[pid]?.[step]?.shots[Number(target.dataset.visualShot)]:null;
    const info=shot?.annotation?{ref:{title:shot.kind,custom:true},map:{src:shot.src,width:shot.annotation.width,height:shot.annotation.height,annotation:shot.annotation,version:'场景截图'},note:{points:[],mode:'图片标注',note:shot.caption},item:data.detailGuides[pid][step]}:mapInfo(pid,step,Number(target.dataset.visualMap));
    if(!info)return;ensureDialog();current=info;zoom=1;returnFocus=target;
    const {map,note,ref,item}=info;
    const description=mapDescription(map,note);
    dialog.innerHTML=`<div class="atlas-dialog-head"><div><h2 id="atlasDialogTitle">${escape(ref.title)}</h2><p>${escape(item.place)} · ${escape(version(map))}</p></div><button type="button" data-close-atlas aria-label="关闭地图图解">关闭 ×</button></div><div class="atlas-dialog-tools"><button type="button" data-visual-zoom="out" aria-label="缩小图解">−</button><output data-visual-zoom-value>100%</output><button type="button" data-visual-zoom="in" aria-label="放大图解">＋</button><button type="button" data-visual-zoom="fit">适合窗口</button>${!ref.custom ? '<button type="button" data-toggle-annotations aria-pressed="true">显示标注</button>' : ''}<a href="${map.src}" target="_blank" rel="noreferrer">查看原图 ↗</a></div><div class="atlas-dialog-body"><div class="atlas-dialog-viewport" style="--map-ratio:${map.width/map.height}" tabindex="0" aria-label="地图画布；放大后可滚动查看">${board(map,note,'dialog')}</div><aside class="atlas-dialog-notes"><h3>${escape(note.mode || '本步地形参考')}</h3>${description ? `<p>${escape(description)}</p>` : ''}${actionList(note.points,'',true)}${!note.points?.length && !description ? `<p>${escape(item.action)}</p>` : ''}<p class="atlas-point-detail" role="status" hidden></p>${note.walkthrough?`<ol class="atlas-dialog-directions">${note.walkthrough.map(line=>`<li>${escape(line)}</li>`).join('')}</ol>`:''}<div class="atlas-dialog-source">${!ref.custom ? `<a href="${escape(map.source)}" target="_blank" rel="noreferrer">地图原始来源 ↗</a>` : ''}${note.source?`<a href="${escape(note.source)}" target="_blank" rel="noreferrer">走法依据 ↗</a>`:''}${note.secondarySource?`<a href="${escape(note.secondarySource)}" target="_blank" rel="noreferrer">地形交叉核对 ↗</a>`:''}<small>${ref.custom?'步骤配图':`${escape(map.credit)} · ${map.preAnnotated?'社区路线供寻路参考':'原版地图供地形参考，战斗配置以 PokeMMO 为准'}`}</small></div></aside></div>`;
    dialog.showModal();resizeBoard();selectPoint(target.dataset.visualPoint);
    dialog.querySelector('[data-close-atlas]').focus();
  }
  document.addEventListener('click',event=>{
    const opener=event.target.closest('[data-open-map],[data-open-shot]');if(opener){openMap(opener);return;}
    if(!dialog?.open)return;
    if(event.target.closest('[data-close-atlas]')){dialog.close();return;}
    const point=event.target.closest('[data-select-point]');if(point){selectPoint(point.dataset.selectPoint);return;}
    const svgPoint=event.target.closest('[data-map-point]');if(svgPoint&&dialog.contains(svgPoint)){selectPoint(svgPoint.dataset.mapPoint);return;}
    const zoomButton=event.target.closest('[data-visual-zoom]');if(zoomButton){zoom=zoomButton.dataset.visualZoom==='fit'?1:Math.max(1,Math.min(6,zoom+(zoomButton.dataset.visualZoom==='in'?.5:-.5)));resizeBoard();return;}
    const toggle=event.target.closest('[data-toggle-annotations]');if(toggle){const show=toggle.getAttribute('aria-pressed')!=='true';toggle.setAttribute('aria-pressed',String(show));toggle.textContent=show?'显示标注':'标注已隐藏';dialog.querySelector('.atlas-board').classList.toggle('annotations-off',!show);}
  });
  window.addEventListener('resize',()=>{if(dialog?.open)resizeBoard();});
  window.guideVisuals={renderStep};
})();
