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

  let results = {};

  // Step 1: Find and click logistics batch button
  let e1 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
    var prodCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("产品信息")>=0});
    var all=Array.from(prodCard.querySelectorAll("span,a,button"));
    var batchSpan=all.find(function(el){return n(el.innerText||el.textContent)==="批量"&&el.className.includes("link")&&vis(el)});
    if(!batchSpan)return JSON.stringify({step:"find-batch",ok:false,reason:"not found"});
    var r=batchSpan.getBoundingClientRect();
    return JSON.stringify({step:"find-batch",ok:true,tag:batchSpan.tagName,cls:batchSpan.className.substring(0,60),x:Math.round(r.x),y:Math.round(r.y),w:Math.round(r.width),h:Math.round(r.height),text:n(batchSpan.innerText||batchSpan.textContent)});
  })()`;
  let r1 = await S('Runtime.evaluate', {expression: e1, returnByValue: true});
  results.batch = JSON.parse(r1.result?.result?.value || '{}');
  console.log('1. Batch button:', results.batch);

  if (!results.batch.ok) { console.log('BATCH NOT FOUND'); c.close(); return; }

  // Step 2: Click the batch button
  let e2 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var clk=function(el){el.scrollIntoView({block:"center"});var r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};
    var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
    var prodCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("产品信息")>=0});
    var all=Array.from(prodCard.querySelectorAll("span,a,button"));
    var batchSpan=all.find(function(el){return n(el.innerText||el.textContent)==="批量"&&el.className.includes("link")&&vis(el)});
    if(!batchSpan)return"not found";
    document.body.click();
    clk(batchSpan);
    return"clicked";
  })()`;
  await S('Runtime.evaluate', {expression: e2, returnByValue: true});
  await slp(1500);

  // Step 3: Check if modal opened
  let e3 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var modal=document.querySelector(".batch-edit-modal");
    if(!modal)return JSON.stringify({step:"modal",ok:false,reason:"no modal",allModals:document.querySelectorAll(".ant-modal").length});
    var style=modal.getAttribute("style")||"";
    var isHidden=style.indexOf("display: none")>=0||style.indexOf("display:none")>=0;
    var checkboxes=Array.from(modal.querySelectorAll(".ant-checkbox-wrapper")).map(function(cb,i){return{i:i,text:n(cb.innerText||cb.textContent)}});
    var btns=Array.from(modal.querySelectorAll("button")).map(function(b,i){return{i:i,text:n(b.innerText||b.textContent)}});
    return JSON.stringify({step:"modal",ok:true,isHidden:isHidden,checkboxCount:checkboxes.length,checkboxes:checkboxes,btns:btns});
  })()`;
  let r3 = await S('Runtime.evaluate', {expression: e3, returnByValue: true});
  results.modal = JSON.parse(r3.result?.result?.value || '{}');
  console.log('3. Modal:', results.modal);

  if (!results.modal.ok || results.modal.isHidden) {
    // Try clicking the button element instead of span
    console.log('Modal not open or hidden, trying button click...');
    let e2b = `(function(){
      var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
      var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
      var clk=function(el){el.scrollIntoView({block:"center"});var r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};
      var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
      var prodCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("产品信息")>=0});
      // Find the logistics batch button - it's an ant-btn-link
      var btns=Array.from(prodCard.querySelectorAll("button")).filter(vis);
      var batchBtn=btns.find(function(b){return n(b.innerText||b.textContent)==="批量"&&b.className.includes("ant-btn-link")});
      if(!batchBtn)return"no btn";
      document.body.click();
      clk(batchBtn);
      return"clicked button";
    })()`;
    await S('Runtime.evaluate', {expression: e2b, returnByValue: true});
    await slp(1500);
    // Re-check modal
    let r3b = await S('Runtime.evaluate', {expression: e3, returnByValue: true});
    results.modal = JSON.parse(r3b.result?.result?.value || '{}');
    console.log('3b. Modal after button click:', results.modal);
  }

  if (!results.modal.ok || results.modal.isHidden) {
    console.log('MODAL STILL NOT OPEN'); c.close(); return;
  }

  // Step 4: Click 普货 checkbox
  let e4 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var clk=function(el){el.scrollIntoView({block:"center"});var r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};
    var modal=document.querySelector(".batch-edit-modal");
    var wrappers=Array.from(modal.querySelectorAll(".ant-checkbox-wrapper"));
    var cargo=null;
    for(var i=0;i<wrappers.length;i++){
      if(n(wrappers[i].innerText||wrappers[i].textContent)==="普货"){cargo=wrappers[i];break}
    }
    if(!cargo)return JSON.stringify({step:"cargo",ok:false,allWrappers:wrappers.map(function(w){return n(w.innerText||w.textContent)})});
    // Click the checkbox input
    var inp=cargo.querySelector(".ant-checkbox-input")||cargo.querySelector("input[type=checkbox]")||cargo;
    var wasChecked=inp.checked;
    clk(inp);
    return JSON.stringify({step:"cargo",ok:true,wasChecked:wasChecked,nowChecked:inp.checked,clicked:n(inp.parentElement.innerText||"")});
  })()`;
  let r4 = await S('Runtime.evaluate', {expression: e4, returnByValue: true});
  results.cargo = JSON.parse(r4.result?.result?.value || '{}');
  console.log('4. Cargo click:', results.cargo);
  await slp(500);

  // Step 5: Click 确定
  let e5 = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var clk=function(el){el.scrollIntoView({block:"center"});var r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};
    var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var modal=document.querySelector(".batch-edit-modal");
    var btns=Array.from(modal.querySelectorAll("button")).filter(vis);
    var ok=btns.find(function(b){return n(b.innerText||b.textContent)==="确定"});
    if(!ok)return JSON.stringify({step:"confirm",ok:false,btns:btns.map(function(b){return n(b.innerText||b.textContent)})});
    clk(ok);
    return JSON.stringify({step:"confirm",ok:true});
  })()`;
  let r5 = await S('Runtime.evaluate', {expression: e5, returnByValue: true});
  results.confirm = JSON.parse(r5.result?.result?.value || '{}');
  console.log('5. Confirm:', results.confirm);

  await slp(500);

  // Step 6: Check final state
  let e6 = `(function(){
    var modal=document.querySelector(".batch-edit-modal");
    var isGone=!modal||(modal.getAttribute("style")||"").indexOf("display: none")>=0;
    return JSON.stringify({step:"final",modalGone:isGone});
  })()`;
  let r6 = await S('Runtime.evaluate', {expression: e6, returnByValue: true});
  results.final = JSON.parse(r6.result?.result?.value || '{}');
  console.log('6. Final:', results.final);

  console.log('\n=== FULL RESULTS ===');
  console.log(JSON.stringify(results, null, 2));
  c.close();
})();
