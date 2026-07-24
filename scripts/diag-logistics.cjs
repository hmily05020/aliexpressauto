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

  // Find "物流属性" area and the "批量" button
  let e = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
    var prodCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("产品信息")>=0});

    // Find all elements with text containing "物流"
    var logisticsEls=[];
    var all=Array.from(prodCard.querySelectorAll("*"));
    for(var i=0;i<all.length;i++){
      var el=all[i];
      var t=n(el.innerText||el.textContent||"");
      if(t.indexOf("物流")>=0 && el.children.length===0 && t.length<30){
        var p=el.parentElement;
        logisticsEls.push({tag:el.tagName,txt:t,parentTag:p.tagName,parentCls:p.className.substring(0,60),parentHTML:p.outerHTML.substring(0,400)});
      }
    }

    // Find ALL buttons with text "批量"
    var allBtns=Array.from(prodCard.querySelectorAll("button,span,a,[role=button]"));
    var batchBtns=[];
    for(var j=0;j<allBtns.length;j++){
      var b=allBtns[j];
      if(n(b.innerText||b.textContent)==="批量"&&vis(b)){
        var r=b.getBoundingClientRect();
        batchBtns.push({txt:n(b.innerText||b.textContent),cls:b.className.substring(0,60),x:Math.round(r.x),y:Math.round(r.y),parentCls:b.parentElement?.className?.substring(0,60)||"",outer:b.outerHTML.substring(0,300)});
      }
    }

    return JSON.stringify({logisticsEls:logisticsEls.slice(0,5), batchBtnCount:batchBtns.length, batchBtns:batchBtns});
  })()`;

  let r = await S('Runtime.evaluate', {expression: e, returnByValue: true});
  let result = JSON.parse(r.result?.result?.value || '{}');
  console.log('Result:', JSON.stringify(result, null, 2));

  // If batch button found, click it and see what modal opens
  if (result.batchBtns && result.batchBtns.length > 0) {
    let btn = result.batchBtns[0];
    console.log('Clicking batch button at', btn.x, btn.y);

    // Close first
    await S('Runtime.evaluate', {expression: 'document.body.click()', returnByValue: true});
    await slp(300);

    // Click the batch button
    let clickE = `(function(){
      var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
      var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
      var allBtns=Array.from(document.querySelectorAll("button,span,[role=button]"));
      var btn=Array.from(allBtns).filter(vis).find(function(b){return n(b.innerText||b.textContent)==="批量"&&b.parentElement&&n(b.parentElement.innerText||"").indexOf("物流属性")>=0});
      if(!btn) return "no btn";
      btn.scrollIntoView({block:"center"});
      var r=btn.getBoundingClientRect();
      ["mouseover","mousedown","mouseup","click"].forEach(function(t){btn.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))});
      return "clicked at "+Math.round(r.x)+","+Math.round(r.y);
    })()`;
    let cr = await S('Runtime.evaluate', {expression: clickE, returnByValue: true});
    console.log('Click:', cr.result?.result?.value);
    await slp(1500);

    // Check what opened
    let modalE = `(function(){
      var modals=document.querySelectorAll(".ant-modal,.ant-drawer,.ant-popover,.el-dialog");
      return JSON.stringify(Array.from(modals).map(function(m){return{cls:m.className.substring(0,80),text:(m.innerText||m.textContent||"").substring(0,200)}}));
    })()`;
    let mr = await S('Runtime.evaluate', {expression: modalE, returnByValue: true});
    console.log('Modals:', mr.result?.result?.value);
  }

  c.close();
})();
