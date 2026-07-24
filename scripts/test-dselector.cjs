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

  // Close everything, then click the d-selector (not the ant-select inside it)
  let e1 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);
    var attrCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('属性信息')>=0});
    var dSelector=attrCard.querySelector('.d-selector');
    if(!dSelector)return 'no d-selector found';
    if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();
    document.body.click();
    // Click the d-selector itself
    var r=dSelector.getBoundingClientRect();
    ['mouseover','mousedown','mouseup','click'].forEach(function(t){dSelector.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))});
    return 'clicked d-selector at x='+Math.round(r.x)+' y='+Math.round(r.y)+' w='+Math.round(r.width)+' h='+Math.round(r.height);
  })()`;

  let r1 = await S('Runtime.evaluate', {expression: e1, returnByValue: true});
  console.log('Step1:', r1.result?.result?.value);
  await slp(2000);

  // What opened? Check for dropdowns, modals, drawers
  let e2 = `(function(){
    var dd=document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)');
    var modal=document.querySelector('.ant-modal:not(.ant-modal-hidden),.ant-drawer:not(.ant-drawer-closed)');
    var popover=document.querySelector('.ant-popover:not(.ant-popover-hidden)');
    var anything=document.querySelector('.d-selector-popup,.template-list,.in-check-options');

    var result={
      dropdown: dd?{w:Math.round(dd.getBoundingClientRect().width),h:Math.round(dd.getBoundingClientRect().height)}:null,
      modal: modal?modal.className.substring(0,60):null,
      popover: popover?popover.className.substring(0,60):null,
      anything: anything?'found: '+anything.className.substring(0,60):null
    };

    // Also check for any element with "钥匙包" text that's visible
    var all=Array.from(document.querySelectorAll('*'));
    var keyElements=[];
    for(var i=0;i<all.length;i++){
      var el=all[i];
      if(el.children.length===0){
        var t=(el.textContent||'').trim();
        if(t.indexOf('钥匙包')>=0 && t.length<40){
          var r=el.getBoundingClientRect();
          keyElements.push({tag:el.tagName,cls:el.className.substring(0,60),txt:t,x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)});
        }
      }
    }
    result.keyElements=keyElements.slice(0,5);

    return JSON.stringify(result);
  })()`;

  let r2 = await S('Runtime.evaluate', {expression: e2, returnByValue: true});
  console.log('Step2:', r2.result?.result?.value);

  // Try clicking the ant-select inside d-selector
  let e3 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);
    var attrCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('属性信息')>=0});
    var dSelector=attrCard.querySelector('.d-selector');
    if(!dSelector)return 'no d-selector';
    // Close first
    document.body.click();
    // Click the ant-select selector inside d-selector
    var sel=dSelector.querySelector('.ant-select-selector');
    if(!sel)sel=dSelector.querySelector('.ant-select');
    if(!sel)return 'no select inside d-selector';
    var r=sel.getBoundingClientRect();
    ['mouseover','mousedown','mouseup','click'].forEach(function(t){sel.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))});
    return 'clicked select at x='+Math.round(r.x)+' y='+Math.round(r.y);
  })()`;

  let r3 = await S('Runtime.evaluate', {expression: e3, returnByValue: true});
  console.log('Step3:', r3.result?.result?.value);
  await slp(2000);

  let r4 = await S('Runtime.evaluate', {expression: e2, returnByValue: true});
  console.log('Step4:', r4.result?.result?.value);

  c.close();
})();
