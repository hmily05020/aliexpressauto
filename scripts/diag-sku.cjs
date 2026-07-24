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

  let e = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
    var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
    var prodCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("产品信息")>=0});

    // All native selects
    var selects=Array.from(prodCard.querySelectorAll("select")).filter(vis).map(function(s,i){
      var r=s.getBoundingClientRect();
      var opts=Array.from(s.options).map(function(o){return o.text});
      return {i:i,options:opts,x:Math.round(r.x),y:Math.round(r.y)};
    });

    // Find "是否原箱" area - any element containing 是/否 near each other
    var yesEls=[];
    var all=Array.from(prodCard.querySelectorAll("*"));
    for(var i=0;i<all.length;i++){
      var el=all[i];
      var t=n(el.innerText||el.textContent||"");
      if(t==="是"&&el.children.length===0&&el.parentElement){
        var p=el.parentElement;
        yesEls.push({tag:el.tagName, cls:el.className.substring(0,40), parentTag:p.tagName, parentCls:p.className.substring(0,40), grandparentCls:(p.parentElement?.className||"").substring(0,40), outer:p.outerHTML.substring(0,300)});
      }
    }

    // Logistics 批量 button
    var btns=Array.from(prodCard.querySelectorAll("button,span.link,a")).filter(vis);
    var logisticsBtns=btns.filter(function(b){
      var t=n(b.innerText||b.textContent);
      return t==="批量" && b.parentElement && n(b.parentElement.innerText||"").indexOf("物流属性")>=0;
    }).map(function(b,i){
      var r=b.getBoundingClientRect();
      return {i:i,text:n(b.innerText||b.textContent),parentCls:b.parentElement?.className?.substring(0,60),x:Math.round(r.x),y:Math.round(r.y)};
    });

    return JSON.stringify({
      selectCount:selects.length, selects:selects,
      yesElements:yesEls.slice(0,10),
      logisticsBtns:logisticsBtns
    });
  })()`;

  let r = await S('Runtime.evaluate', {expression: e, returnByValue: true});
  console.log(r.result?.result?.value);
  c.close();
})();
