let http=require('http'),ws=require('ws');
(async()=>{
let tabs=await new Promise(r=>http.get('http://127.0.0.1:9222/json/list',res=>{let d='';res.on('data',c=>d+=c);res.on('end',()=>r(JSON.parse(d)))}));
let tab=tabs.find(t=>/edit/.test(t.url));
let c=new ws(tab.webSocketDebuggerUrl);await new Promise(r=>c.on('open',r));
let id=0,p=new Map();c.on('message',d=>{let m=JSON.parse(d);if(m.id&&p.has(m.id))p.get(m.id)(m);p.delete(m.id)});
let S=(m,pr)=>new Promise(r=>{id++;p.set(id,r);c.send(JSON.stringify({id,method:m,params:pr||{}}))});
await S('Runtime.enable');let slp=ms=>new Promise(r=>setTimeout(r,ms));

// Click old editor radio and debug modal
let e=`(async function(){
var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
var clk=function(el){el.scrollIntoView({block:"center"});var r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};
var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
var descCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("描述信息")>=0});
var labels=Array.from(descCard.querySelectorAll(".ant-radio-wrapper"));
var oldEditor=labels.find(function(l){return n(l.innerText||l.textContent)==="使用老版编辑器"});
if(!oldEditor)return"no label";
// Click the radio INPUT directly (not the label)
var radioInp=oldEditor.querySelector("input[type=radio]");
if(radioInp){clk(radioInp)}
else{clk(oldEditor)}
await new Promise(function(r){setTimeout(r,1500)});
// List all modals
var modals=document.querySelectorAll(".ant-modal");
var result=[];
for(var i=0;i<modals.length;i++){
  var m=modals[i];
  var style=m.getAttribute("style")||"";
  var displayNone=style.indexOf("display: none")>=0||style.indexOf("display:none")>=0;
  result.push({i:i,cls:m.className.substring(0,80),displayNone:displayNone,offsetParent:!!m.offsetParent,text:n(m.innerText||m.textContent||"").substring(0,300),btns:Array.from(m.querySelectorAll("button")).filter(vis).map(function(b){var r=b.getBoundingClientRect();return{text:n(b.innerText||b.textContent),rectW:r.width,rectH:r.height}})});
}
return JSON.stringify(result);
})()`;
let r=await S('Runtime.evaluate',{expression:e,awaitPromise:true,returnByValue:true});
console.log('Modals:',r.result?.result?.value);
c.close()})();
