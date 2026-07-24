// Test the logistics expression via CDP (file-based to avoid bash escaping issues)
let http=require('http'),ws=require('ws');
(async()=>{
let tabs=await new Promise(r=>http.get('http://127.0.0.1:9222/json/list',res=>{let d='';res.on('data',c=>d+=c);res.on('end',()=>r(JSON.parse(d)))}));
let tab=tabs.find(t=>/edit/.test(t.url));
let c=new ws(tab.webSocketDebuggerUrl);await new Promise(r=>c.on('open',r));
let id=0,p=new Map();c.on('message',d=>{let m=JSON.parse(d);if(m.id&&p.has(m.id))p.get(m.id)(m);p.delete(m.id)});
let S=(m,pr)=>new Promise(r=>{id++;p.set(id,r);c.send(JSON.stringify({id,method:m,params:pr||{}}))});
await S('Runtime.enable');let slp=ms=>new Promise(r=>setTimeout(r,ms));

// Simple proven expression
let expr = "(() => new Promise(async (resolve) => {" +
"try{" +
"var n=function(v){return(v||'').replace(/\\s+/g,' ').trim()};" +
"var slp=function(ms){return new Promise(function(d){setTimeout(d,ms)})};" +
"var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};" +
"var clk=function(el){el.scrollIntoView({block:'center'});var r=el.getBoundingClientRect();['mouseover','mousedown','mouseup','click'].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};" +
"var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);" +
"var prodCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('产品信息')>=0});" +
"if(!prodCard){resolve({ok:false,reason:'no card'});return}" +
"var spans=Array.from(prodCard.querySelectorAll('span.link'));" +
"var logSpan=spans.find(function(s){return n(s.innerText||s.textContent)==='批量'&&vis(s)});" +
"if(!logSpan){resolve({ok:false,reason:'no span',count:spans.length,texts:spans.map(function(s){return n(s.innerText||s.textContent)})});return}" +
"document.body.click();await slp(300);clk(logSpan);await slp(1200);" +
"var modal=document.querySelector('.batch-edit-modal');" +
"if(!modal){resolve({ok:false,reason:'no modal'});return}" +
"modal.style.display='';modal.style.removeProperty('display');await slp(500);" +
"var wrappers=Array.from(modal.querySelectorAll('.ant-checkbox-wrapper'));" +
"var cargo=wrappers.find(function(w){return n(w.innerText||w.textContent)==='普货'});" +
"if(!cargo){resolve({ok:false,reason:'no cargo',wrappers:wrappers.length});return}" +
"var cb=cargo.querySelector('input[type=checkbox]')||cargo.querySelector('.ant-checkbox-input');" +
"clk(cb||cargo);await slp(400);" +
"var btns=Array.from(modal.querySelectorAll('button')).filter(vis);" +
"var ok=btns.find(function(b){return n(b.innerText||b.textContent)==='确定'});" +
"if(ok){clk(ok);await slp(500)}" +
"resolve({ok:true,modalFound:!!modal,cargoFound:!!cargo,okClicked:!!ok});" +
"}catch(e){resolve({ok:false,error:e.message||String(e)})}" +
"}))()";

let r=await S('Runtime.evaluate',{expression:expr,awaitPromise:true,returnByValue:true});
let result=r.result?.result?.value;
console.log('RESULT:',JSON.stringify(result,null,2));
if(r.result?.exceptionDetails){
  console.log('JS ERROR:',r.result.exceptionDetails.exception?.description);
  console.log('At line:',r.result.exceptionDetails.lineNumber,'col:',r.result.exceptionDetails.columnNumber);
}

if(result&&result.ok){
  console.log('SUCCESS! Logistics attribute set.');
} else if(result){
  console.log('FAILED:',result.reason||result.error);
}
c.close()})();
