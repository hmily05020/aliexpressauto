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

  // Check dropdown structure (dropdown should still be open from previous test)
  let e = '(function(){var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};var dd=document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");if(!dd)return"no dropdown open";var info={ddClass:dd.className.substring(0,100),ddRect:{w:Math.round(dd.getBoundingClientRect().width),h:Math.round(dd.getBoundingClientRect().height)},ddScrollH:dd.scrollHeight,ddClientH:dd.clientHeight};var holder=dd.querySelector(".rc-virtual-list-holder");if(holder)info.holder={rect:{w:Math.round(holder.getBoundingClientRect().width),h:Math.round(holder.getBoundingClientRect().height)},scrollH:holder.scrollHeight,clientH:holder.clientHeight,style:holder.getAttribute("style")||"no-style"};var menu=dd.querySelector(".ant-select-dropdown-menu");if(menu)info.menu={scrollH:menu.scrollHeight,clientH:menu.clientHeight};info.optionCount=dd.querySelectorAll(".ant-select-item-option").length;return JSON.stringify(info)})()';

  let r = await S('Runtime.evaluate', {expression: e, returnByValue: true});
  console.log('Dropdown structure:', r.result?.result?.value);

  // If dropdown not open, open it first
  if (r.result?.result?.value === 'no dropdown open') {
    let eOpen = '(function(){var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);var attrCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("属性信息")>=0});var sel=attrCard.querySelector(".in-selector .ant-select,.d-selector .ant-select");if(!sel)sel=Array.from(attrCard.querySelectorAll(".ant-select")).filter(vis).find(function(s){return !s.closest(".ant-form-item")});if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();document.body.click();var trigger=sel.querySelector(".ant-select-selector")||sel;var rt=trigger.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){trigger.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:rt.left+rt.width/2,clientY:rt.top+rt.height/2}))});return"opened"})()';
    await S('Runtime.evaluate', {expression: eOpen, returnByValue: true});
    await slp(1500);
    r = await S('Runtime.evaluate', {expression: e, returnByValue: true});
    console.log('After open:', r.result?.result?.value);
  }

  // Now try: directly find "钥匙包" by traversing the DOM
  let eFind = '(function(){var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};var dd=document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");if(!dd)return"no dd";var all=dd.querySelectorAll("*");var results=[];for(var i=0;i<all.length;i++){var el=all[i];if(el.children.length===0){var t=n(el.textContent||el.innerText||"");if(t.indexOf("钥匙")>=0&&t.length<40){results.push({tag:el.tagName,cls:el.className.substring(0,60),txt:t,parentTag:el.parentElement.tagName,parentCls:el.parentElement.className.substring(0,60)})}}}return JSON.stringify({found:results.length,items:results.slice(0,10)})})()';

  let r2 = await S('Runtime.evaluate', {expression: eFind, returnByValue: true});
  console.log('Search "钥匙":', r2.result?.result?.value);

  c.close();
})();
