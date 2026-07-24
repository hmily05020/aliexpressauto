let http=require('http'),ws=require('ws');
(async()=>{
let tabs=await new Promise(r=>http.get('http://127.0.0.1:9222/json/list',res=>{let d='';res.on('data',c=>d+=c);res.on('end',()=>r(JSON.parse(d)))}));
let tab=tabs.find(t=>/edit/.test(t.url));
let c=new ws(tab.webSocketDebuggerUrl);await new Promise(r=>c.on('open',r));
let id=0,p=new Map();c.on('message',d=>{let m=JSON.parse(d);if(m.id&&p.has(m.id))p.get(m.id)(m);p.delete(m.id)});
let S=(m,pr)=>new Promise(r=>{id++;p.set(id,r);c.send(JSON.stringify({id,method:m,params:pr||{}}))});
await S('Runtime.enable');let slp=ms=>new Promise(r=>setTimeout(r,ms));

// Step 1: Click 添加海关监管 button, then scan cascading selects
let e=`(async function(){
var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
var clk=function(el){el.scrollIntoView({block:"center"});var r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};
var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
var tmplCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("模板信息")>=0});
if(!tmplCard)return"no card";
// Click 添加海关监管 button
var btns=Array.from(tmplCard.querySelectorAll("button")).filter(vis);
var addBtn=btns.find(function(b){return n(b.innerText||b.textContent)==="添加海关监管"});
if(!addBtn)return"no add btn";
clk(addBtn);
await new Promise(function(r){setTimeout(r,1500)});
// Now check what appeared
var selects=Array.from(tmplCard.querySelectorAll(".ant-select,.ant-cascader,.ant-cascader-picker")).filter(vis);
var results=selects.map(function(s,i){
  var r=s.getBoundingClientRect();
  var cur=n(s.querySelector(".ant-select-selection-item")?.innerText||"");
  var ph=n(s.querySelector(".ant-select-selection-placeholder")?.innerText||"");
  var labelEl=s.closest(".ant-form-item");var label=labelEl?n(labelEl.querySelector("label")?.innerText||""):"";
  var isCascader=s.className.indexOf("cascader")>=0;
  return{i:i,label:label,current:cur,placeholder:ph,isCascader:isCascader,x:Math.round(r.x),y:Math.round(r.y)};
});
var newBtns=Array.from(tmplCard.querySelectorAll("button")).filter(vis).map(function(b,i){return{i:i,text:n(b.innerText||b.textContent)}});
var txt=n(tmplCard.innerText||tmplCard.textContent||"").substring(0,1000);
return JSON.stringify({selectCount:selects.length,selects:results,buttons:newBtns,text:txt});
})()`;
let r=await S('Runtime.evaluate',{expression:e,awaitPromise:true,returnByValue:true});
console.log('After add:',r.result?.result?.value);

// Step 2: If cascader found, open first one and scan levels
let result1=JSON.parse(r.result?.result?.value||'{}');
if(result1.selects&&result1.selects.some(function(s){return s.isCascader})){
  let e2=`(async function(){
var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
var clk=function(el){el.scrollIntoView({block:"center"});var r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};
var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
var tmplCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("模板信息")>=0});
var cascaders=Array.from(tmplCard.querySelectorAll(".ant-cascader,.ant-cascader-picker")).filter(vis);
if(!cascaders.length)return"no cascader";
var c1=cascaders[0];
clk(c1.querySelector("input")||c1);
await new Promise(function(r){setTimeout(r,1200)});
// Scan all cascader menu levels
var menus=Array.from(document.querySelectorAll(".ant-cascader-menu")).filter(vis);
var levels=menus.map(function(m,li){
  var items=Array.from(m.querySelectorAll(".ant-cascader-menu-item")).filter(vis).map(function(it){return n(it.innerText||it.textContent)});
  return{level:li,itemCount:items.length,items:items};
});
return JSON.stringify({menuCount:menus.length,levels:levels});
})()`;
  let r2=await S('Runtime.evaluate',{expression:e2,awaitPromise:true,returnByValue:true});
  console.log('Cascader scan:',r2.result?.result?.value);
}
c.close()})();
