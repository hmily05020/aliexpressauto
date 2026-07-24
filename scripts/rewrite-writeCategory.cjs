const fs = require('fs');
const path = 'C:/Users/我是好人/Documents/aliexpress/electron/main.cjs';
let content = fs.readFileSync(path, 'utf8');

// Find the writeCategory handler's expression
let handlerStart = content.indexOf('ipcMain.handle("chrome:writeCategory"');
let evalStart = content.indexOf('const payloadBase64', handlerStart);
let exprStart = content.indexOf('const expression = `', evalStart);
let exprEnd = content.indexOf('))()` + '`;', exprStart);

console.log('Expression from', exprStart, 'to', exprEnd + 5);

// The payloadBase64 and expression are the parts to keep. We're replacing the expression.
let before = content.substring(0, exprStart);

// Build the new expression
let payloadLine = content.substring(evalStart, exprStart);
let newExpr = payloadLine + `const expression = \`(() => new Promise(async (resolve) => {
      const norm = (v) => (v || "").replace(/\\\\s+/g, " ").trim();
      const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
      const visible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;
      };
      const clickEl = (el) => {
        if (!el) return;
        el.scrollIntoView({ block: "center", inline: "center" });
        const r = el.getBoundingClientRect();
        const init = { bubbles: true, cancelable: true, view: window, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
        el.dispatchEvent(new MouseEvent("mouseover", init));
        el.dispatchEvent(new MouseEvent("mousedown", init));
        el.dispatchEvent(new MouseEvent("mouseup", init));
        el.dispatchEvent(new MouseEvent("click", init));
      };
      const uniq = (items) => Array.from(new Set(items.filter(Boolean)));

      const warnings = [];
      const selectedPath = [];
      const catPath = norm(payload.categoryPath || "");
      const parts = catPath.split(/[>\\u203a\\/\\\\\\\\]+/).filter(Boolean).map(norm);
      const leaf = parts[parts.length - 1] || "";

      if (!parts.length) {
        resolve({ ok: false, attemptedPath: [], selectedPath, currentValue: "", warnings: ["\\u8def\\u5f84\\u4e3a\\u7a7a"], url: location.href });
        return;
      }

      // Find \\u57fa\\u672c\\u4fe1\\u606f card
      const cards = Array.from(document.querySelectorAll(".form-card")).filter(visible);
      const basicCard = cards.find(c => {
        const t = norm(c.querySelector("h4")?.innerText || c.innerText || "");
        return t.includes("\\u57fa\\u672c\\u4fe1\\u606f");
      });

      if (!basicCard) {
        resolve({ ok: false, attemptedPath: parts, selectedPath, currentValue: "", warnings: ["\\u672a\\u627e\\u5230\\u57fa\\u672c\\u4fe1\\u606f\\u6a21\\u5757"], url: location.href });
        return;
      }

      // Find \\u4ea7\\u54c1\\u5206\\u7c7b form item
      const formItems = Array.from(basicCard.querySelectorAll(".ant-form-item,.el-form-item,.form-item,.form-group,.form-row,tr,li")).filter(visible);
      const catItem = formItems.find(item => {
        const t = norm(item.innerText || item.textContent || "");
        return /\\u4ea7\\u54c1\\u5206\\u7c7b|\\u4ea7\\u54c1\\u7c7b\\u76ee|\\u5546\\u54c1\\u5206\\u7c7b|\\u5546\\u54c1\\u7c7b\\u76ee/.test(t) && item.querySelector(".ant-select");
      });

      if (!catItem) {
        resolve({ ok: false, attemptedPath: parts, selectedPath, currentValue: "", warnings: ["\\u672a\\u627e\\u5230\\u4ea7\\u54c1\\u5206\\u7c7b\\u63a7\\u4ef6"], url: location.href });
        return;
      }

      // Close existing dropdowns
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
      document.body.click();
      await sleep(300);

      // Click the select to open
      const selector = catItem.querySelector(".ant-select-selector") || catItem.querySelector(".ant-select");
      clickEl(selector);
      await sleep(900);

      // Find opened dropdown
      const dropdown = document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
      if (!dropdown) {
        resolve({ ok: false, attemptedPath: parts, selectedPath, currentValue: "", warnings: ["\\u4e0b\\u62c9\\u6846\\u672a\\u6253\\u5f00"], url: location.href });
        return;
      }

      // Scroll virtual list to find leaf category
      let foundOption = null;
      const holder = dropdown.querySelector(".rc-virtual-list-holder");
      if (holder) {
        holder.scrollTop = 0;
        await sleep(100);
        let lastTop = -1;
        for (let s = 0; s < 40; s++) {
          if (holder.scrollTop === lastTop) break;
          lastTop = holder.scrollTop;
          const options = Array.from(dropdown.querySelectorAll(".ant-select-item-option,[role=option]")).filter(visible);
          foundOption = options.find(opt => {
            const text = norm(opt.innerText || opt.textContent);
            const cmp = norm(text).replace(/[()\\uff08\\uff09]/g, " ").toLowerCase();
            const cmpLeaf = norm(leaf).replace(/[()\\uff08\\uff09]/g, " ").toLowerCase();
            return text === leaf || cmp.indexOf(cmpLeaf) >= 0 || cmpLeaf.indexOf(cmp) >= 0 ||
                   text.indexOf(leaf.substring(0, 4)) >= 0;
          });
          if (foundOption) break;
          holder.scrollTop = Math.min(holder.scrollHeight, holder.scrollTop + Math.max(60, Math.floor(holder.clientHeight * 0.8)));
          await sleep(80);
        }
      } else {
        const options = Array.from(dropdown.querySelectorAll(".ant-select-item-option,[role=option]")).filter(visible);
        foundOption = options.find(opt => {
          const text = norm(opt.innerText || opt.textContent);
          const cmp = norm(text).replace(/[()\\uff08\\uff09]/g, " ").toLowerCase();
          const cmpLeaf = norm(leaf).replace(/[()\\uff08\\uff09]/g, " ").toLowerCase();
          return text === leaf || cmp.indexOf(cmpLeaf) >= 0 || cmpLeaf.indexOf(cmp) >= 0;
        });
      }

      if (foundOption) {
        clickEl(foundOption);
        selectedPath.push(leaf);
        await sleep(500);
      } else {
        const visibleOpts = Array.from(dropdown.querySelectorAll(".ant-select-item-option,[role=option]"))
          .filter(visible).map(opt => norm(opt.innerText || opt.textContent)).filter(Boolean).slice(0, 25);
        warnings.push("\\u672a\\u627e\\u5230\\u7c7b\\u76ee[" + leaf + "]\\uff0c\\u53ef\\u89c1\\uff1a" + visibleOpts.join(" | "));
      }

      const currentValue = norm(catItem.querySelector(".ant-select-selection-item")?.innerText || "");
      resolve({
        ok: selectedPath.length > 0,
        attemptedPath: parts,
        selectedPath,
        currentValue,
        warnings,
        url: location.href
      });
    }))()` + '`;';

let after = content.substring(exprEnd + 5);
content = before + newExpr + '\n' + after;
fs.writeFileSync(path, content, 'utf8');
console.log('DONE');
