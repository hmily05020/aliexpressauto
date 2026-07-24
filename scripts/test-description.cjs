let http=require('http'),ws=require('ws');
(async()=>{
let tabs=await new Promise(r=>http.get('http://127.0.0.1:9222/json/list',res=>{let d='';res.on('data',c=>d+=c);res.on('end',()=>r(JSON.parse(d)))}));
let tab=tabs.find(t=>/edit/.test(t.url));
let c=new ws(tab.webSocketDebuggerUrl);await new Promise(r=>c.on('open',r));
let id=0,p=new Map();c.on('message',d=>{let m=JSON.parse(d);if(m.id&&p.has(m.id))p.get(m.id)(m);p.delete(m.id)});
let S=(m,pr)=>new Promise(r=>{id++;p.set(id,r);c.send(JSON.stringify({id,method:m,params:pr||{}}))});
await S('Runtime.enable');let slp=ms=>new Promise(r=>setTimeout(r,ms));

// Step 1: Click 使用老版编辑器 label and check for modal
let e1=`(async function(){
var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};
var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};
var clk=function(el){el.scrollIntoView({block:"center"});var r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};
var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
var descCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("描述信息")>=0});
var labels=Array.from(descCard.querySelectorAll(".ant-radio-wrapper"));
var oldEditor=labels.find(function(l){return n(l.innerText||l.textContent)==="使用老版编辑器"});
if(!oldEditor)return"no old editor";
// Check if already selected
var radio=oldEditor.querySelector(".ant-radio");
var isChecked=radio&&radio.className.indexOf("ant-radio-checked")>=0;
// Click it
clk(oldEditor);
await new Promise(function(r){setTimeout(r,1000)});
// Check for modal
var modals=document.querySelectorAll(".ant-modal");
var modalInfo=Array.from(modals).filter(vis).map(function(m){return{cls:m.className.substring(0,60),text:n(m.innerText||m.textContent||"").substring(0,200),btns:Array.from(m.querySelectorAll("button")).filter(vis).map(function(b){return n(b.innerText||b.textContent)})}});
return JSON.stringify({isChecked:isChecked,modalCount:modals.length,modals:modalInfo});
})()`;
let r1=await S('Runtime.evaluate',{expression:e1,awaitPromise:true,returnByValue:true});
let result1=JSON.parse(r1.result?.result?.value||'{}');
console.log('Step1:',result1);

// Step 2: If modal has 确定, click it
if(result1.modals&&result1.modals.length>0){
  let modal=result1.modals[0];
  if(modal.btns&&modal.btns.includes("确定")){
    let e2=`(function(){var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};var clk=function(el){el.scrollIntoView({block:"center"});var r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};var btns=Array.from(document.querySelectorAll(".ant-modal button")).filter(vis);var ok=btns.find(function(b){return n(b.innerText||b.textContent)==="确定"});if(ok){clk(ok);return"clicked ok"}return"no ok"})()`;
    await S('Runtime.evaluate',{expression:e2,returnByValue:true});
    await slp(500);
    console.log('Step2: clicked 确定');
  }
}

// Step 3: Click 一键生成 span.link
let e3=`(async function(){var n=function(v){return(v||"").replace(/\\s+/g," ").trim()};var vis=function(el){var r=el.getBoundingClientRect();return r.width>0&&r.height>0};var clk=function(el){el.scrollIntoView({block:"center"});var r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};var cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);var descCard=cards.find(function(c){return n(c.querySelector("h4")?c.querySelector("h4").innerText:"").indexOf("描述信息")>=0});var spans=Array.from(descCard.querySelectorAll("span.link"));var genBtn=spans.find(function(s){return n(s.innerText||s.textContent)==="一键生成"&&vis(s)});if(!genBtn)return"no gen btn";clk(genBtn);await new Promise(function(r){setTimeout(r,2000)});return"clicked gen"})()`;
let r3=await S('Runtime.evaluate',{expression:e3,awaitPromise:true,returnByValue:true});
console.log('Step3:',r3.result?.result?.value);

c.close()})();
