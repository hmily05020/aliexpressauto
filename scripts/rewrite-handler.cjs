// Rewrite the entire writeCategory handler from scratch
let fs = require('fs');
let cp = require('child_process');
let mainPath = 'C:/Users/我是好人/Documents/aliexpress/electron/main.cjs';
let main = fs.readFileSync(mainPath, 'utf8');

// Find the handler boundaries
let handlerStart = main.indexOf('ipcMain.handle("chrome:writeCategory"');
if (handlerStart < 0) { console.log('handler not found'); process.exit(1); }

// Find where this handler closes (the next '  });' after the handler)
// The handler ends with '  });' before the next handler or closing brace
let scanStart = main.indexOf('ipcMain.handle("chrome:scanDropdownOptions"', handlerStart);
let handlerEnd;
if (scanStart > 0) {
  // Find the '  });' before scanDropdownOptions
  handlerEnd = main.lastIndexOf('  });', scanStart);
} else {
  // Fallback: find before function createMainWindow
  handlerEnd = main.lastIndexOf('  });', main.indexOf('function createMainWindow'));
}

console.log('handler from', handlerStart, 'to', handlerEnd);
console.log('Old handler preview:', main.substring(handlerStart, handlerStart + 100));

// Build the new handler
// Using split strings to avoid template literal issues
let NL = '\n';
let T2 = '      ';
let T3 = '        ';
let T4 = '          ';
let T5 = '            ';

let newHandler = [
'  ipcMain.handle("chrome:writeCategory", async (_event, payload) => {',
'    const { tabs } = await getConnectedChromeTabs();',
'    const editTab = await pickBestDxmEditTab(tabs);',
'',
'    if (!editTab) {',
'      throw new Error("没有找到店小秘编辑页，无法写入类目。");',
'    }',
'    await waitForDxmEditContent(editTab);',
'',
'    const payloadBase64 = Buffer.from(JSON.stringify(payload || {}), "utf8").toString("base64");',
'    const expression = `(() => new Promise(async (resolve) => {',
'      const norm = (v) => (v || "").replace(/\\\\s+/g, " ").trim();',
'      const sleep = (ms) => new Promise((d) => setTimeout(d, ms));',
'      const visible = (el) => {',
'        if (!el || !el.getBoundingClientRect) return false;',
'        const r = el.getBoundingClientRect();',
'        const s = getComputedStyle(el);',
'        return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;',
'      };',
'      const clickEl = (el) => {',
'        if (!el) return;',
'        el.scrollIntoView({ block: "center", inline: "center" });',
'        const r = el.getBoundingClientRect();',
'        const init = { bubbles: true, cancelable: true, view: window, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };',
'        el.dispatchEvent(new MouseEvent("mouseover", init));',
'        el.dispatchEvent(new MouseEvent("mousedown", init));',
'        el.dispatchEvent(new MouseEvent("mouseup", init));',
'        el.dispatchEvent(new MouseEvent("click", init));',
'      };',
'',
'      // Decode payload from template literal',
'      const payload = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob("${payloadBase64}"), (c) => c.charCodeAt(0))));',
'',
'      const warnings = [];',
'      const selectedPath = [];',
'      const catPath = norm(payload.categoryPath || "");',
'      const parts = catPath.split(/[>\\u203a\\/\\\\\\\\]+/).filter(Boolean).map(norm);',
'      const leaf = parts[parts.length - 1] || "";',
'',
'      if (!parts.length) {',
'        resolve({ ok: false, attemptedPath: [], selectedPath, currentValue: "", warnings: ["\\u8def\\u5f84\\u4e3a\\u7a7a"], url: location.href });',
'        return;',
'      }',
'',
'      // Find \\u57fa\\u672c\\u4fe1\\u606f card',
'      const cards = Array.from(document.querySelectorAll(".form-card")).filter(visible);',
'      const basicCard = cards.find(c => {',
'        const t = norm(c.querySelector("h4")?.innerText || c.innerText || "");',
'        return t.includes("\\u57fa\\u672c\\u4fe1\\u606f");',
'      });',
'',
'      if (!basicCard) {',
'        resolve({ ok: false, attemptedPath: parts, selectedPath, currentValue: "", warnings: ["\\u672a\\u627e\\u5230\\u57fa\\u672c\\u4fe1\\u606f\\u6a21\\u5757"], url: location.href });',
'        return;',
'      }',
'',
'      // Find \\u4ea7\\u54c1\\u5206\\u7c7b form item',
'      const formItems = Array.from(basicCard.querySelectorAll(".ant-form-item,.el-form-item,.form-item,.form-group,.form-row,tr,li")).filter(visible);',
'      const catItem = formItems.find(item => {',
'        const t = norm(item.innerText || item.textContent || "");',
'        return /\\u4ea7\\u54c1\\u5206\\u7c7b|\\u4ea7\\u54c1\\u7c7b\\u76ee|\\u5546\\u54c1\\u5206\\u7c7b|\\u5546\\u54c1\\u7c7b\\u76ee/.test(t) && item.querySelector(".ant-select");',
'      });',
'',
'      if (!catItem) {',
'        resolve({ ok: false, attemptedPath: parts, selectedPath, currentValue: "", warnings: ["\\u672a\\u627e\\u5230\\u4ea7\\u54c1\\u5206\\u7c7b\\u63a7\\u4ef6"], url: location.href });',
'        return;',
'      }',
'',
'      // Close existing dropdowns, open ours',
'      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();',
'      document.body.click();',
'      await sleep(300);',
'',
'      const selector = catItem.querySelector(".ant-select-selector") || catItem.querySelector(".ant-select");',
'      clickEl(selector);',
'      await sleep(900);',
'',
'      const dropdown = document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");',
'      if (!dropdown) {',
'        resolve({ ok: false, attemptedPath: parts, selectedPath, currentValue: "", warnings: ["\\u4e0b\\u62c9\\u6846\\u672a\\u6253\\u5f00"], url: location.href });',
'        return;',
'      }',
'',
'      // Scroll virtual list to find leaf',
'      let foundOption = null;',
'      const holder = dropdown.querySelector(".rc-virtual-list-holder");',
'      if (holder) {',
'        holder.scrollTop = 0; await sleep(100);',
'        let lastTop = -1;',
'        for (let s = 0; s < 40; s++) {',
'          if (holder.scrollTop === lastTop) break;',
'          lastTop = holder.scrollTop;',
'          const opts = Array.from(dropdown.querySelectorAll(".ant-select-item-option,[role=option]")).filter(visible);',
'          foundOption = opts.find(o => {',
'            const t = norm(o.innerText || o.textContent);',
'            const cmp = norm(t).replace(/[()\\uff08\\uff09]/g, " ").toLowerCase();',
'            const cmpL = norm(leaf).replace(/[()\\uff08\\uff09]/g, " ").toLowerCase();',
'            return t === leaf || cmp.indexOf(cmpL) >= 0 || cmpL.indexOf(cmp) >= 0 || t.indexOf(leaf.substring(0,4)) >= 0;',
'          });',
'          if (foundOption) break;',
'          holder.scrollTop = Math.min(holder.scrollHeight, holder.scrollTop + Math.max(60, Math.floor(holder.clientHeight * 0.8)));',
'          await sleep(80);',
'        }',
'      } else {',
'        const opts = Array.from(dropdown.querySelectorAll(".ant-select-item-option,[role=option]")).filter(visible);',
'        foundOption = opts.find(o => {',
'          const t = norm(o.innerText || o.textContent);',
'          const cmp = norm(t).replace(/[()\\uff08\\uff09]/g, " ").toLowerCase();',
'          const cmpL = norm(leaf).replace(/[()\\uff08\\uff09]/g, " ").toLowerCase();',
'          return t === leaf || cmp.indexOf(cmpL) >= 0 || cmpL.indexOf(cmp) >= 0;',
'        });',
'      }',
'',
'      if (foundOption) {',
'        clickEl(foundOption);',
'        selectedPath.push(leaf);',
'        await sleep(500);',
'      } else {',
'        const vOpts = Array.from(dropdown.querySelectorAll(".ant-select-item-option,[role=option]")).filter(visible).map(o => norm(o.innerText || o.textContent)).filter(Boolean).slice(0,25);',
'        warnings.push("\\u672a\\u627e\\u5230\\u7c7b\\u76ee[" + leaf + "]\\uff0c\\u53ef\\u89c1\\uff1a" + vOpts.join(" | "));',
'      }',
'',
'      const currentValue = norm(catItem.querySelector(".ant-select-selection-item")?.innerText || "");',
'      resolve({ ok: selectedPath.length > 0, attemptedPath: parts, selectedPath, currentValue, warnings, url: location.href });',
'    }))()`;',
'',
'    const result = await evaluateInTab(editTab, expression);',
'    appendAutomationLog("writeCategory.result", result);',
'',
'    // Auto-scan attribute template after category write',
'    let attributeTemplateOptions = [];',
'    if (result?.ok) {',
'      try {',
'        const attrExpr = `(() => new Promise(async (resolve) => {',
'          const norm = (v) => (v || "").replace(/\\\\s+/g, " ").trim();',
'          const sleep = (ms) => new Promise((d) => setTimeout(d, ms));',
'          const visible = (el) => {',
'            if (!el || !el.getBoundingClientRect) return false;',
'            const r = el.getBoundingClientRect();',
'            const s = getComputedStyle(el);',
'            return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;',
'          };',
'          const clickEl = (el) => {',
'            if (!el) return;',
'            el.scrollIntoView({ block: "center" });',
'            const r = el.getBoundingClientRect();',
'            const init = { bubbles: true, cancelable: true, view: window, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };',
'            ["mouseover","mousedown","mouseup","click"].forEach(t => el.dispatchEvent(new MouseEvent(t, init)));',
'          };',
'          const uniq = (a) => [...new Set(a.filter(Boolean))];',
'          const closeDD = async () => { document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",code:"Escape",bubbles:true})); await sleep(150); };',
'          const moduleOf = (el) => { const t = norm(el.closest(".form-card")?.querySelector("h4")?.innerText || "").replace(/[\\uff08\\uff09].*|[()].*/g,""); if(t.includes("\\u5c5e\\u6027\\u4fe1\\u606f"))return"\\u5c5e\\u6027\\u4fe1\\u606f"; return""; };',
'',
'          await sleep(1500);',
'          const controls = Array.from(document.querySelectorAll(".ant-select")).filter(visible).slice(0,30);',
'          const options = [];',
'          for (const ctrl of controls) {',
'            const mod = moduleOf(ctrl);',
'            const lbl = norm(ctrl.closest(".ant-form-item")?.querySelector("label")?.innerText || "");',
'            const isAT = mod.includes("\\u5c5e\\u6027\\u4fe1\\u606f") && /\\u5f15\\u7528\\u6a21\\u677f|\\u5c5e\\u6027\\u6a21\\u677f/.test(lbl);',
'            if (!isAT) continue;',
'            try {',
'              clickEl(ctrl.querySelector(".ant-select-selector") || ctrl);',
'              await sleep(500);',
'              const allOpts = uniq(Array.from(document.querySelectorAll(".ant-select-item-option,[role=option]")).filter(visible).map(o=>norm(o.innerText||o.textContent)).filter(t=>t&&t.length<=120&&t!=="\\u6682\\u65e0\\u6570\\u636e"));',
'              options.push(...allOpts);',
'              await closeDD();',
'            } catch(e) { await closeDD(); }',
'          }',
'          resolve({ fieldKey: "attributeTemplate", options: uniq(options).slice(0,80) });',
'        }))()`;',
'        const attrResult = await evaluateInTab(editTab, attrExpr);',
'        attributeTemplateOptions = attrResult?.options || [];',
'      } catch (attrError) {}',
'    }',
'',
'    return { ...result, attributeTemplateOptions };',
'  });',
].join(NL);

let before = main.substring(0, handlerStart);
let after = main.substring(handlerEnd + '  });'.length);
let result = before + newHandler + NL + after;

fs.writeFileSync(mainPath, result, 'utf8');

try {
  cp.execSync('node -c "' + mainPath + '"', { encoding: 'utf8' });
  console.log('DONE - Syntax OK');
} catch(e) {
  console.log('SYNTAX ERROR:', e.stderr ? e.stderr.substring(0, 300) : e.message);
}
