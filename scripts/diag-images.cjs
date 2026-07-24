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

  let e = `(function(){
    var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
    var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};

    // Find product info card
    var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);
    var prodCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('产品信息')>=0});

    if(!prodCard) return '产品信息 card not found';

    // Find all images
    var imgs=Array.from(prodCard.querySelectorAll('img')).filter(vis);
    var imgInfo=imgs.map(function(img,i){
      var r=img.getBoundingClientRect();
      return {
        i:i,
        src:img.src.substring(0,120),
        naturalW:img.naturalWidth,
        naturalH:img.naturalHeight,
        w:Math.round(r.width),
        h:Math.round(r.height),
        x:Math.round(r.x),
        y:Math.round(r.y),
        alt:img.alt||'',
        parentCls:(img.parentElement?.className||'').substring(0,60)
      };
    });

    // Find file inputs
    var fileInputs=Array.from(prodCard.querySelectorAll('input[type=file]'));
    var inputInfo=fileInputs.map(function(inp,i){
      var r=inp.getBoundingClientRect();
      return {i:i, id:inp.id||'', name:inp.name||'', accept:inp.accept||'', cls:(inp.className||'').substring(0,80), visible:vis(inp), rect:{w:Math.round(r.width),h:Math.round(r.height)}};
    });

    // Get the card's text content (first 1000 chars)
    var txt=n(prodCard.innerText||prodCard.textContent||'').substring(0,1000);

    // Find ALL buttons
    var btns=Array.from(prodCard.querySelectorAll('button')).filter(vis).map(function(b,i){
      return {i:i,text:n(b.innerText||b.textContent),cls:(b.className||'').substring(0,60)};
    });

    return JSON.stringify({
      cardFound:true,
      imageCount:imgs.length,
      images:imgInfo,
      fileInputCount:fileInputs.length,
      fileInputs:inputInfo,
      buttons:btns,
      cardText:txt
    });
  })()`;

  let r = await S('Runtime.evaluate', {expression: e, returnByValue: true});
  console.log(r.result?.result?.value);

  c.close();
})();
