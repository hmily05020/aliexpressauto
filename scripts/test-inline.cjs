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

  // Step 1: Find the in-check-options inside attribute card and dump its children
  let e1 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);
    var attrCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('属性信息')>=0});

    // Find ALL in-check-options and d-selector children
    var dSelector=attrCard.querySelector('.d-selector');
    var inCheck=attrCard.querySelector('.in-check-options');

    var result={dSelectorFound:!!dSelector, inCheckFound:!!inCheck};

    if(dSelector){
      var dHtml=dSelector.outerHTML.substring(0,1000);
      var dRect=dSelector.getBoundingClientRect();
      result.dSelector={html:dHtml, rect:{w:Math.round(dRect.width),h:Math.round(dRect.height),x:Math.round(dRect.x),y:Math.round(dRect.y)}};

      // Get all children recursively up to 3 levels
      function tree(el,depth){
        if(depth>3||!el)return null;
        var node={tag:el.tagName,cls:(el.className||'').substring(0,60)};
        if(el.children.length>0){
          node.children=[];
          for(var i=0;i<Math.min(el.children.length,20);i++){
            var child=tree(el.children[i],depth+1);
            if(child)node.children.push(child);
          }
        }else{
          node.text=(el.textContent||'').substring(0,40);
        }
        var r=el.getBoundingClientRect();
        node.rect={w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.x),y:Math.round(r.y)};
        return node;
      }
      result.dSelector.tree=tree(dSelector,0);
    }

    return JSON.stringify(result);
  })()`;

  let r1 = await S('Runtime.evaluate', {expression: e1, returnByValue: true});
  console.log('d-selector tree:', r1.result?.result?.value);

  // Step 2: Try to make the template list visible (click the d-selector to expand)
  let e2 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);
    var attrCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('属性信息')>=0});
    var dSelector=attrCard.querySelector('.d-selector');
    if(!dSelector)return'no d-selector';

    // Try clicking the ant-select to expand the list
    var sel=dSelector.querySelector('.ant-select');
    if(sel){
      var trigger=sel.querySelector('.ant-select-selector')||sel;
      var r=trigger.getBoundingClientRect();
      ['mouseover','mousedown','mouseup','click'].forEach(function(t){trigger.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))});
      return 'clicked ant-select';
    }
    // Also try clicking the d-selector itself
    var r=dSelector.getBoundingClientRect();
    ['mouseover','mousedown','mouseup','click'].forEach(function(t){dSelector.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))});
    return 'clicked d-selector direct';
  })()`;

  await S('Runtime.evaluate', {expression: e2, returnByValue: true});
  await slp(1000);

  // Step 3: After clicking, find ALL elements with "钥匙包" AND check visible status
  let e3 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var all=Array.from(document.querySelectorAll('*'));
    var results=[];
    for(var i=0;i<all.length;i++){
      var el=all[i];
      if(el.children.length===0){
        var t=(el.textContent||'').trim();
        if((t.indexOf('钥匙包')>=0||t.indexOf('钥匙')>=0)&&t.length<80){
          var r=el.getBoundingClientRect();
          var s=getComputedStyle(el);
          results.push({
            tag:el.tagName,
            cls:el.className.substring(0,60),
            txt:t,
            visible:r.width>0&&r.height>0,
            rect:{w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.x),y:Math.round(r.y)},
            display:s.display,
            ancestor:((el.closest('.d-selector')||el.closest('.in-check-options')||el.closest('.ant-select-dropdown')||el.parentElement)||{}).className||''
          });
        }
      }
    }
    return JSON.stringify(results);
  })()`;

  let r3 = await S('Runtime.evaluate', {expression: e3, returnByValue: true});
  console.log('After click, 钥匙 elements:', r3.result?.result?.value);

  c.close();
})();
