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

  // Step 1: Find and click in-selector
  let e1 = '(function(){var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);var attrCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("属性信息")>=0});var sel=attrCard.querySelector(".in-selector .ant-select,.d-selector .ant-select");if(!sel)sel=Array.from(attrCard.querySelectorAll(".ant-select")).filter(vis).find(function(s){return !s.closest(".ant-form-item")});if(!sel)return "NOT_FOUND";if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();document.body.click();var trigger=sel.querySelector(".ant-select-selector")||sel;var r=trigger.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){trigger.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))});return "clicked";})()';

  let r1 = await S('Runtime.evaluate', {expression: e1, returnByValue: true});
  console.log('Step1:', r1.result?.result?.value);
  await slp(2000);

  // Step 2: Check dropdown
  let e2 = '(function(){var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};var dd=document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");if(!dd)return "NO_DROPDOWN";var holder=dd.querySelector(".rc-virtual-list-holder");var sh=holder?holder.scrollHeight:dd.scrollHeight;var ch=holder?holder.clientHeight:dd.clientHeight;if(holder)holder.scrollTop=sh;else dd.scrollTop=sh;return "scrollH="+sh+" clientH="+ch+" holder="+!!holder;})()';

  let r2 = await S('Runtime.evaluate', {expression: e2, returnByValue: true});
  console.log('Step2:', r2.result?.result?.value);
  await slp(800);

  // Step 3: Get all option texts
  let e3 = '(function(){var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};var dd=document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");if(!dd)return"no dd";var opts=Array.from(dd.querySelectorAll(".ant-select-item-option"));return JSON.stringify({count:opts.length,texts:opts.map(function(o){return n(o.innerText||o.textContent)})});})()';

  let r3 = await S('Runtime.evaluate', {expression: e3, returnByValue: true});
  console.log('Step3:', r3.result?.result?.value);

  // Step 4: If "钥匙包" not found, try scrolling to many positions and collecting
  let e4 = '(function(){var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};var dd=document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");if(!dd)return"no dd";var holder=dd.querySelector(".rc-virtual-list-holder");var target=holder||dd;var sh=target.scrollHeight;var allTexts=[];for(var pct=0;pct<=1.0;pct+=0.05){target.scrollTop=Math.floor(sh*pct);var now=Date.now();while(Date.now()-now<200){};Array.from(dd.querySelectorAll(".ant-select-item-option")).forEach(function(o){var t=n(o.innerText||o.textContent);if(allTexts.indexOf(t)<0)allTexts.push(t)});}return JSON.stringify({total:allTexts.length,all:allTexts});})()';

  let r4 = await S('Runtime.evaluate', {expression: e4, returnByValue: true});
  console.log('Step4 (all positions):', r4.result?.result?.value);

  c.close();
})();
