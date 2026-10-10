(function(root){
  'use strict';
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number=(v,min,max)=>typeof v==='number'&&Number.isFinite(v)&&v>=min&&v<=max;
  const numberSymbol=n=>n<=20?String.fromCodePoint(0x2460+n-1):n<=35?String.fromCodePoint(0x3251+n-21):n<=50?String.fromCodePoint(0x32b1+n-36):`（${n}）`;
  const nextNumber=a=>Math.min(99,Math.max(0,...a.elements.filter(e=>e.type==='number').map(e=>e.number))+1);
  const anchors=e=>e.type==='text'||e.type==='number'?[[e.x,e.y]]:e.points;
  function validate(a){
    if(!a||a.version!==1||!Number.isInteger(a.width)||!Number.isInteger(a.height)||!number(a.width,1,30000)||!number(a.height,1,30000)||!Array.isArray(a.elements)||a.elements.length>200)throw new Error('图片标注格式不正确。');
    let count=0;
    for(const e of a.elements){
      if(!e||!['path','line','arrow','text','number'].includes(e.type)||!/^#[0-9a-f]{6}$/i.test(e.color)||!number(e.width,1,24))throw new Error('标注的工具、颜色或线宽不正确。');
      if(e.type==='text'){
        if(!number(e.x,0,1)||!number(e.y,0,1)||!number(e.size,12,96)||typeof e.text!=='string'||!e.text.trim()||e.text.length>500||e.text.split('\n').length>20)throw new Error('标注文字或位置不正确。');
      }else if(e.type==='number'){
        if(!number(e.x,0,1)||!number(e.y,0,1)||!number(e.size,12,96)||!Number.isInteger(e.number)||!number(e.number,1,99))throw new Error('顺序编号或位置不正确，请使用 1—99。');
      }else{
        if(!Array.isArray(e.points)||e.points.length<2||e.points.length>5000||(['line','arrow'].includes(e.type)&&e.points.length!==2)||e.points.some(p=>!Array.isArray(p)||p.length!==2||!number(p[0],0,1)||!number(p[1],0,1)))throw new Error('路线或箭头的位置不正确。');
        count+=e.points.length;
      }
    }
    if(count>20000)throw new Error('标注节点太多，请减少线路数量。');
    return JSON.parse(JSON.stringify(a));
  }
  function elementSvg(e,a,index,editable,selected){
    const scale=a.width/900,stroke=e.width*scale,points=(e.points||[]).map(p=>[p[0]*a.width,p[1]*a.height]);
    let shape='';
    if(e.type==='text'){
      const x=e.x*a.width,y=e.y*a.height,size=e.size*scale;
      const lines=e.text.split('\n'),textWidth=Math.max(...lines.map(line=>[...line].reduce((n,c)=>n+(/[\x00-\xff]/.test(c)?.65:1),0)))*size;
      if(editable)shape+=`<rect x="${x}" y="${y}" width="${Math.max(size,textWidth)}" height="${size*lines.length*1.35}" fill="transparent"/>`;
      shape+=`<text x="${x}" y="${y}" font-size="${size}" font-family="Microsoft YaHei,system-ui,sans-serif" font-weight="700" fill="${e.color}" stroke="white" stroke-width="${Math.max(1,scale*3)}" paint-order="stroke" dominant-baseline="hanging">${lines.map((line,i)=>`<tspan x="${x}" dy="${i?size*1.35:0}">${escape(line)}</tspan>`).join('')}</text>`;
    }else if(e.type==='number'){
      const x=e.x*a.width,y=e.y*a.height,r=e.size*scale/2;
      shape=`<circle cx="${x}" cy="${y}" r="${r}" fill="white" stroke="${e.color}" stroke-width="${Math.max(2,scale*3)}"/><text x="${x}" y="${y}" text-anchor="middle" dominant-baseline="central" fill="${e.color}" font-size="${r*(e.number>9?1.05:1.4)}" font-family="Microsoft YaHei,system-ui,sans-serif" font-weight="800">${e.number}</text>`;
    }else{
      const value=points.map(p=>p.join(',')).join(' ');
      if(editable)shape+=`<polyline points="${value}" fill="none" stroke="transparent" stroke-width="${Math.max(stroke*4,scale*20)}"/>`;
      shape+=`<polyline points="${value}" fill="none" stroke="${e.color}" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round"/>`;
      if(e.type==='arrow'){
        const [from,to]=points,angle=Math.atan2(to[1]-from[1],to[0]-from[0]),length=Math.max(stroke*4,scale*18),wing=length*.45;
        const base=[to[0]-Math.cos(angle)*length,to[1]-Math.sin(angle)*length];
        shape+=`<polygon points="${to.join(',')} ${base[0]-Math.sin(angle)*wing},${base[1]+Math.cos(angle)*wing} ${base[0]+Math.sin(angle)*wing},${base[1]-Math.cos(angle)*wing}" fill="${e.color}"/>`;
      }
    }
    return `<g ${editable?`data-markup-element="${index}" role="button" tabindex="0" aria-label="选择标注 ${index+1}：${escape(e.type==='text'?e.text:e.type==='number'?numberSymbol(e.number):{path:'路线',line:'直线',arrow:'箭头'}[e.type])}"`:''} class="${selected?'markup-selected':''}">${shape}</g>`;
  }
  function svg(a,{editable=false,selected=-1,extra=[],hiddenIndex=-1}={}){
    if(!a)return '';
    return `<svg class="image-markup-overlay" viewBox="0 0 ${a.width} ${a.height}" ${editable?'role="group" aria-label="图片标注对象"':'role="img" aria-label="自己添加的线路、箭头、文字和顺序编号"'}>${[...a.elements,...extra].map((e,i)=>i===hiddenIndex?'':elementSvg(e,a,i,editable,i===selected)).join('')}</svg>`;
  }
  const api={validate,svg,numberSymbol,nextNumber,anchors};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.ImageMarkupCore=api;
})(typeof window==='object'?window:this);
