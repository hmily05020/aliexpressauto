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
  let slp = (ms) => new Promise(r => setTimeout(r, ms));

  // Find the clickable element around "钥匙包"
  let e1 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    // Find the "钥匙包" span in in-check-options
    var all=Array.from(document.querySelectorAll('*'));
    for(var i=0;i<all.length;i++){
      var el=all[i];
      if(el.children.length===0 && (el.textContent||'').trim()==='钥匙包'){
        // Walk up to find the clickable wrapper
        var p=el;
        var chain=[];
        for(var j=0;j<5;j++){
          if(!p)break;
          chain.push({tag:p.tagName,cls:(p.className||'').substring(0,60),id:p.id||'',text:(p.textContent||'').substring(0,30)});
          p=p.parentElement;
        }
        return JSON.stringify({found:true, rect:{x:Math.round(el.getBoundingClientRect().x),y:Math.round(el.getBoundingClientRect().y)}, chain:chain});
      }
    }
    return 'not found';
  })()`;

  let r1 = await S('Runtime.evaluate', {expression: e1, returnByValue: true});
  console.log('钥匙包 chain:', r1.result?.result?.value);

  // Now click the "钥匙包" parent (likely the in-check-options item div)
  let e2 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var all=Array.from(document.querySelectorAll('*'));
    for(var i=0;i<all.length;i++){
      var el=all[i];
      if(el.children.length===0 && (el.textContent||'').trim()==='钥匙包'){
        // Click the grandparent (the wrapper div with class containing 'item' or similar)
        var target = el.parentElement.parentElement; // span > div.in-check-options > wrapper
        if(!target)target=el.parentElement;
        var r=target.getBoundingClientRect();
        if(r.width===0||r.height===0){
          // Try parent
          target=el.parentElement;
          r=target.getBoundingClientRect();
        }
        ['mouseover','mousedown','mouseup','click'].forEach(function(t){
          target.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}));
        });
        return 'clicked <'+target.tagName+'> class="'+target.className.substring(0,60)+'" at x='+Math.round(r.x)+' y='+Math.round(r.y)+' w='+Math.round(r.width)+' h='+Math.round(r.height);
      }
    }
    return 'not found';
  })()`;

  let r2 = await S('Runtime.evaluate', {expression: e2, returnByValue: true});
  console.log('Click result:', r2.result?.result?.value);
  await slp(1500);

  // Check if the select now shows "钥匙包"
  let e3 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);
    var attrCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('属性信息')>=0});
    var dSelector=attrCard.querySelector('.d-selector');
    var curVal=n(dSelector?.querySelector('.ant-select-selection-item')?.innerText||'');
    return 'current template value: "'+curVal+'"';
  })()`;

  let r3 = await S('Runtime.evaluate', {expression: e3, returnByValue: true});
  console.log('After click:', r3.result?.result?.value);

  c.close();
})();
