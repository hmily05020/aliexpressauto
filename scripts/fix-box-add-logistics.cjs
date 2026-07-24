let fs=require('fs'),cp=require('child_process');
let m=fs.readFileSync('C:/Users/我是好人/Documents/aliexpress/electron/main.cjs','utf8');

// Fix setOriginalBox - use prototype setter for Vue reactivity
let old='for(const sel of selects){const opts=Array.from(sel.options).map(o=>o.text);if(opts.includes("是")&&opts.includes("否")){sel.value="1";sel.dispatchEvent(new Event("change",{bubbles:true}));count++}}';
let nw='for(const sel of selects){const opts=Array.from(sel.options).map(o=>o.text);if(opts.includes("是")&&opts.includes("否")){const setter=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,"value")?.set;if(setter)setter.call(sel,"1");else sel.value="1";sel.dispatchEvent(new Event("input",{bubbles:true}));sel.dispatchEvent(new Event("change",{bubbles:true}));count++}}';

if(m.includes(old)){m=m.replace(old,nw);console.log('1. setOriginalBox Vue fix applied')}else{console.log('1. NOT FOUND')}

// Add setLogisticsAttribute
let cb=m.lastIndexOf('\n}',m.indexOf('function createMainWindow'));
let h=`\n  ipcMain.handle("chrome:setLogisticsAttribute", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const expression = \`(() => new Promise(async (resolve) => {
      const n=(v)=>(v||"").replace(/\\\\s+/g," ").trim();
      const slp=ms=>new Promise(d=>setTimeout(d,ms));
      const vis=(el)=>{if(!el||!el.getBoundingClientRect)return false;const r=el.getBoundingClientRect();return r.width>0&&r.height>0};
      const clk=(el)=>{el.scrollIntoView({block:"center"});const r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(t=>el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2})))};
      const cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
      const prodCard=cards.find(c=>n(c.querySelector("h4")?.innerText||"").includes("产品信息"));
      if(!prodCard){resolve({ok:false,reason:"未找到产品信息"});return}
      const all=Array.from(prodCard.querySelectorAll("span,a,button"));
      const batchSpan=all.find(el=>n(el.innerText||el.textContent)==="批量"&&el.className.includes("link")&&vis(el));
      if(!batchSpan){resolve({ok:false,reason:"未找到物流批量按钮"});return}
      document.body.click();await slp(300);
      clk(batchSpan);await slp(1200);
      const modal=document.querySelector(".batch-edit-modal");
      if(!modal){resolve({ok:false,reason:"弹窗未打开"});return}
      const modalEls=Array.from(modal.querySelectorAll("*"));
      let cargo=null;
      for(const el of modalEls){if(n(el.innerText||el.textContent)==="普货"&&el.children.length<=1){cargo=el.closest("label")||el.closest("div[class*=item]")||el;break}}
      if(cargo){clk(cargo);await slp(400)}
      const btns=Array.from(modal.querySelectorAll("button")).filter(vis);
      const ok=btns.find(b=>n(b.innerText||b.textContent)==="确定");
      if(ok){clk(ok);await slp(400)}
      resolve({ok:true,modalFound:!!modal,cargoFound:!!cargo,okClicked:!!ok});
    }))\`;`;
    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("setLogisticsAttribute", result);
    return result;
  });`;
m=m.substring(0,cb)+h+'\n'+m.substring(cb);
fs.writeFileSync('C:/Users/我是好人/Documents/aliexpress/electron/main.cjs',m,'utf8');
try{cp.execSync('node -c "C:/Users/我是好人/Documents/aliexpress/electron/main.cjs"',{encoding:'utf8'});console.log('2. OK - Syntax valid')}catch(e){console.log('2. ERR:',e.stderr?.substring(0,200))}
