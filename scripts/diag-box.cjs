let http = require('http'), ws = require('ws');
(async () => {
  let tabs = await new Promise(r => http.get('http://127.0.0.1:9222/json/list', res => {let d='';res.on('data',c=>d+=c);res.on('end',()=>r(JSON.parse(d)))}));
  let tab = tabs.find(t => /edit/.test(t.url));
  let c = new ws(tab.webSocketDebuggerUrl);
  await new Promise(r => c.on('open', r));
  let id=0, p=new Map();
  c.on('message', d => { let m=JSON.parse(d); if(m.id&&p.has(m.id)) p.get(m.id)(m); p.delete(m.id); });
  let S = (m,pr) => new Promise(r => { id++; p.set(id, r); c.send(JSON.stringify({id,method:m,params:pr||{}})); });
  await S('Runtime.enable');
  let slp = ms => new Promise(r => setTimeout(r, ms));

  // Find all selects and test setting one
  let e = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
    var prodCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("产品信息")>=0});

    // Find ALL selects with 是/否 options
    var selects=Array.from(prodCard.querySelectorAll("select"));
    var info=selects.map(function(s,i){
      var r=s.getBoundingClientRect();
      var opts=Array.from(s.options).map(function(o){return o.value+":"+o.text});
      return {i:i,value:s.value,opts:opts,visible:r.width>0,rect:{x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height)},outer:s.outerHTML.substring(0,300)};
    });
    return JSON.stringify({selectCount:selects.length,selects:info});
  })()`;
  let r = await S('Runtime.evaluate', {expression: e, returnByValue: true});
  console.log('Selects:', r.result?.result?.value);

  // Also find the 是否原箱 red error text
  let e2 = `(function(){
    var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
    var prodCard=cards.find(function(c){return(c.querySelector("h4")?.innerText||"").indexOf("产品信息")>=0});
    var errors=Array.from(prodCard.querySelectorAll(".text-red-500,[class*=error]")).filter(vis);
    return JSON.stringify(errors.map(function(e,i){return{i:i,tag:e.tagName,cls:e.className.substring(0,80),text:e.innerText?.substring(0,50),rect:{x:Math.round(e.getBoundingClientRect().x),y:Math.round(e.getBoundingClientRect().y)}}}));
  })()`;
  let r2 = await S('Runtime.evaluate', {expression: e2, returnByValue: true});
  console.log('Error texts:', r2.result?.result?.value);

  // Find logistics batch button and individual edit icons
  let e3 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
    var prodCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("产品信息")>=0});

    // Find elements with "批量" text that are in the SKU area
    var all=Array.from(prodCard.querySelectorAll("span,a,button,i"));
    var batchSpans=all.filter(function(el){return n(el.innerText||el.textContent)==="批量"&&vis(el)});
    var editIcons=all.filter(function(el){return el.className.indexOf("icon_edit")>=0&&vis(el)});

    return JSON.stringify({
      batchSpans:batchSpans.map(function(b,i){var r=b.getBoundingClientRect();return{i:i,tag:b.tagName,cls:b.className.substring(0,60),x:Math.round(r.x),y:Math.round(r.y),parentTag:b.parentElement.tagName,parentCls:b.parentElement.className.substring(0,60)}}),
      editIcons:editIcons.map(function(b,i){var r=b.getBoundingClientRect();return{i:i,tag:b.tagName,cls:b.className.substring(0,60),x:Math.round(r.x),y:Math.round(r.y)}})
    });
  })()`;
  let r3 = await S('Runtime.evaluate', {expression: e3, returnByValue: true});
  console.log('Batch/Edit:', r3.result?.result?.value);

  c.close();
})();
