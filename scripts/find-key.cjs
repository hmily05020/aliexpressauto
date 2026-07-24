let http = require('http'), ws = require('ws');

(async () => {
  let tabs = await new Promise(r => http.get('http://127.0.0.1:9222/json/list', res => {
    let d=''; res.on('data',c=>d+=c); res.on('end', ()=>r(JSON.parse(d)));
  }));
  let tab = tabs.find(t => /edit/.test(t.url));
  let c = new ws(tab.webSocketDebuggerUrl);
  await new Promise(r => c.on('open', r));

  let id=0, p=new Map();
  c.on('message', d => { let m=JSON.parse(d); if(m.id&&p.has(m.id)) p.get(m.id)(m); p.delete(m.id); });
  let S = (method, params) => new Promise(r => { id++; p.set(id, r); c.send(JSON.stringify({id,method,params:params||{}})); });
  await S('Runtime.enable');

  // Close any open dropdowns first
  await S('Runtime.evaluate', {expression: 'document.body.click();if(document.activeElement&&document.activeElement.blur)document.activeElement.blur()', returnByValue: true});

  // Search ENTIRE PAGE for "钥匙包" in leaf text nodes
  let e = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var results=[];
    function walk(el, path) {
      if(!el || !el.tagName) return;
      if(el.children.length===0 || (el.tagName==='SPAN' && el.children.length<=1)) {
        var t = n(el.textContent||el.innerText||"");
        if(t.indexOf("钥匙包")>=0 && t.length < 100) {
          var r=el.getBoundingClientRect();
          var parent=el.parentElement;
          var ancestor=el;
          for(var i=0;i<5;i++) ancestor=ancestor.parentElement||ancestor;
          results.push({
            tag: el.tagName,
            cls: (el.className||"").substring(0,80),
            txt: t.substring(0,60),
            rect: {x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)},
            visible: r.width>0&&r.height>0,
            parentTag: parent.tagName,
            parentCls: (parent.className||"").substring(0,80),
            ancestorTag: ancestor.tagName,
            ancestorCls: (ancestor.className||"").substring(0,80),
            ancestorId: ancestor.id||""
          });
        }
      }
      for(var j=0;j<el.children.length;j++) walk(el.children[j], path+'/'+el.tagName);
    }
    walk(document.body, '');
    // Deduplicate by text+tag
    var seen={},uniq=[];
    for(var k=0;k<results.length;k++) {
      var key=results[k].tag+results[k].txt+results[k].rect.y;
      if(!seen[key]){seen[key]=true;uniq.push(results[k])}
    }
    return JSON.stringify({total:uniq.length, items:uniq});
  })()`;

  let r = await S('Runtime.evaluate', {expression: e, returnByValue: true});
  let result = JSON.parse(r.result?.result?.value || '{}');
  console.log('Found', result.total, 'occurrences of "钥匙包"');
  result.items.forEach((item, i) => {
    console.log(`\n[${i}] <${item.tag}> class="${item.cls}"`);
    console.log(`    text: "${item.txt}"`);
    console.log(`    rect: x=${item.rect.x} y=${item.rect.y} w=${item.rect.w} h=${item.rect.h} visible=${item.visible}`);
    console.log(`    parent: <${item.parentTag}> class="${item.parentCls}"`);
    console.log(`    ancestor: <${item.ancestorTag}> id="${item.ancestorId}" class="${item.ancestorCls}"`);
  });

  // Now find ALL .ant-select on the page with their current value
  let e2 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var selects=Array.from(document.querySelectorAll('.ant-select')).filter(vis);
    return JSON.stringify(selects.map(function(s,i){
      var card=s.closest('.form-card');
      var cardTitle=card?n(card.querySelector('h4')?.innerText||'').substring(0,30):'no-card';
      var formItem=s.closest('.ant-form-item');
      var label=formItem?n(formItem.querySelector('label')?.innerText||''):'';
      var curVal=n(s.querySelector('.ant-select-selection-item')?.innerText||'');
      var placeholder=n(s.querySelector('.ant-select-selection-placeholder')?.innerText||'');
      var parentCls=(s.parentElement?.className||'').substring(0,60);
      return {i,cardTitle,label:label.substring(0,40),parentCls,curVal:curVal.substring(0,50),placeholder:placeholder.substring(0,50)};
    }));
  })()`;

  let r2 = await S('Runtime.evaluate', {expression: e2, returnByValue: true});
  let selects = JSON.parse(r2.result?.result?.value || '[]');
  console.log('\n\n=== ALL ANT-SELECTS ON PAGE ===');
  selects.forEach(s => {
    if (s.cardTitle || s.label || s.curVal || s.placeholder)
      console.log(`[${s.i}] card="${s.cardTitle}" label="${s.label}" parent="${s.parentCls}" cur="${s.curVal}" ph="${s.placeholder}"`);
  });

  c.close();
})();
