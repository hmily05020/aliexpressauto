const fs = require('fs');
const path = 'C:/Users/我是好人/Documents/aliexpress/electron/main.cjs';
let content = fs.readFileSync(path, 'utf8');

// ============================================================
// Fix: replace the broken section from writeCategory's attrExpression
// to before createMainWindow
// ============================================================

// Find the exact boundaries
const brokenStartMarker = '    if (result?.ok) {';
const brokenStart = content.indexOf(brokenStartMarker, content.indexOf('After writing category'));
const brokenEnd = content.indexOf('\nfunction createMainWindow()');

if (brokenStart < 0 || brokenEnd < 0) {
  console.log('ERROR: Cannot find boundaries');
  console.log('brokenStart:', brokenStart, 'brokenEnd:', brokenEnd);
  process.exit(1);
}

console.log('Replacing from', brokenStart, 'to', brokenEnd, '(length:', brokenEnd - brokenStart, ')');

const replacement = `    if (result?.ok) {
      try {
        const attrExpression = \`(() => new Promise(async (resolve) => {
          const norm = (value) => (value || "").replace(/\\\\s+/g, " ").trim();
          const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
          const visible = (el) => {
            if (!el || !el.getBoundingClientRect) return false;
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
          };
          const clickEl = (el) => {
            if (!el) return;
            el.scrollIntoView({ block: "center", inline: "center" });
            const rect = el.getBoundingClientRect();
            const init = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
            el.dispatchEvent(new MouseEvent("mouseover", init));
            el.dispatchEvent(new MouseEvent("mousedown", init));
            el.dispatchEvent(new MouseEvent("mouseup", init));
            el.dispatchEvent(new MouseEvent("click", init));
          };
          const closeDropdown = async () => {
            document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
            document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
            await sleep(120);
          };
          const uniq = (items) => Array.from(new Set(items.filter(Boolean)));
          const normalizeModuleName = (text) => {
            const value = norm(text).replace(/\\\\uff08.*?\\\\uff09|\\\\(.*?\\\\)/g, "");
            if (value.includes("\\\\u5c5e\\\\u6027\\\\u4fe1\\\\u606f")) return "\\\\u5c5e\\\\u6027\\\\u4fe1\\\\u606f";
            if (value.includes("\\\\u6a21\\\\u677f\\\\u4fe1\\\\u606f") || value.includes("\\\\u6a21\\\\u7248\\\\u4fe1\\\\u606f")) return "\\\\u6a21\\\\u677f\\\\u4fe1\\\\u606f";
            return "";
          };
          const moduleOf = (el) => normalizeModuleName(el.closest(".form-card")?.querySelector("h4.form-card-title")?.innerText || "");

          // Wait for page to refresh after category change
          await sleep(1500);

          // Find attribute template dropdowns only
          const controls = Array.from(document.querySelectorAll(".ant-select,.ant-cascader-picker,.el-select,.el-cascader"))
            .filter(visible)
            .slice(0, 60);

          const options = [];
          for (const control of controls) {
            const container = control.closest(".ant-form-item,.el-form-item,.form-item,.form-group,tr,li,.form-row") || control.parentElement;
            const module = moduleOf(control);
            const label = norm(container?.querySelector("label,.ant-form-item-label,.el-form-item__label,.label")?.innerText || "");
            const labelLower = norm(label).toLowerCase();
            const moduleLower = norm(module).toLowerCase();

            // Only scan attribute template — strict match
            const isAttrTemplate =
              (moduleLower.includes("\\\\u5c5e\\\\u6027\\\\u4fe1\\\\u606f") && /\\\\u5f15\\\\u7528\\\\u6a21\\\\u677f|\\\\u8bf7\\\\u9009\\\\u62e9\\\\u5f15\\\\u7528\\\\u6a21\\\\u677f|\\\\u5c5e\\\\u6027\\\\u6a21\\\\u677f/.test(labelLower)) ||
              /\\\\u5f15\\\\u7528\\\\u6a21\\\\u677f|\\\\u5c5e\\\\u6027\\\\u6a21\\\\u677f/.test(labelLower);

            if (!isAttrTemplate) continue;

            try {
              clickEl(control.querySelector(".ant-select-selector,.el-input,input") || control);
              await sleep(550);

              const optionSelector = [
                ".ant-select-item-option",
                ".ant-select-dropdown-menu-item",
                ".ant-cascader-menu-item",
                ".el-select-dropdown__item",
                ".el-cascader-node",
                "[role='option']"
              ].join(",");
              const collected = uniq(Array.from(document.querySelectorAll(optionSelector))
                .filter(visible)
                .map((opt) => norm(opt.innerText || opt.textContent))
                .filter((text) => text && text.length <= 120 && text !== "\\\\u6682\\\\u65e0\\\\u6570\\\\u636e" && text !== "\\\\u7ba1\\\\u7406\\\\u6a21\\\\u677f" && !/^cn\\\\d+[a-z0-9]*$/i.test(text)));

              options.push(...collected);
              await closeDropdown();
            } catch (e) {
              await closeDropdown();
            }
          }

          resolve({
            fieldKey: "attributeTemplate",
            options: uniq(options).slice(0, 80)
          });
        }))()\`;

        const attrResult = await evaluateInTab(editTab, attrExpression);
        attributeTemplateOptions = attrResult?.options || [];
        appendAutomationLog("writeCategory.attributeTemplateScan", {
          optionCount: attributeTemplateOptions.length,
          options: attributeTemplateOptions.slice(0, 10)
        });
      } catch (attrError) {
        appendAutomationLog("writeCategory.attributeTemplateScan.failed", {
          message: attrError instanceof Error ? attrError.message : String(attrError)
        });
      }
    }

    return { ...result, attributeTemplateOptions };
  });

  ipcMain.handle("chrome:scanDropdownOptions", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);

    if (!editTab) {
      throw new Error("\\\\u6ca1\\\\u6709\\\\u627e\\\\u5230\\\\u5e97\\\\u5c0f\\\\u79d8\\\\u7f16\\\\u8f91\\\\u9875\\\\uff0c\\\\u65e0\\\\u6cd5\\\\u626b\\\\u63cf\\\\u4e0b\\\\u62c9\\\\u6846\\\\u9009\\\\u9879\\\\u3002");
    }
    await waitForDxmEditContent(editTab);

    const expression = \`(() => new Promise(async (resolve) => {
      const norm = (value) => (value || "").replace(/\\\\s+/g, " ").trim();
      const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
      const uniq = (items) => Array.from(new Set(items.filter(Boolean)));
      const visible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const clickEl = (el) => {
        if (!el) return;
        el.scrollIntoView({ block: "center", inline: "center" });
        const rect = el.getBoundingClientRect();
        const init = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        el.dispatchEvent(new MouseEvent("mouseover", init));
        el.dispatchEvent(new MouseEvent("mousedown", init));
        el.dispatchEvent(new MouseEvent("mouseup", init));
        el.dispatchEvent(new MouseEvent("click", init));
      };

      // Robust close: Esc key + body click, verify closed
      const closeDropdown = async () => {
        for (let i = 0; i < 3; i++) {
          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
          document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
        }
        document.body.click();
        await sleep(250);
        // Verify — retry if dropdown still visible
        let retries = 0;
        while (retries < 5) {
          const open = document.querySelectorAll(
            ".ant-select-dropdown:not(.ant-select-dropdown-hidden),.ant-cascader-menus,.el-cascader__dropdown"
          );
          if (!open.length) break;
          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
          document.body.click();
          await sleep(150);
          retries++;
        }
      };

      const normalizeModuleName = (text) => {
        const value = norm(text).replace(/\\\\uff08.*?\\\\uff09|\\\\(.*?\\\\)/g, "");
        if (value.includes("\\\\u57fa\\\\u672c\\\\u4fe1\\\\u606f")) return "\\\\u57fa\\\\u672c\\\\u4fe1\\\\u606f";
        if (value.includes("\\\\u5e97\\\\u5c0f\\\\u79d8\\\\u4fe1\\\\u606f")) return "\\\\u5e97\\\\u5c0f\\\\u79d8\\\\u4fe1\\\\u606f";
        if (value.includes("\\\\u5c5e\\\\u6027\\\\u4fe1\\\\u606f")) return "\\\\u5c5e\\\\u6027\\\\u4fe1\\\\u606f";
        if (value.includes("\\\\u4ea7\\\\u54c1\\\\u4fe1\\\\u606f")) return "\\\\u4ea7\\\\u54c1\\\\u4fe1\\\\u606f";
        if (value.includes("\\\\u533a\\\\u57df\\\\u8c03\\\\u4ef7\\\\u4fe1\\\\u606f")) return "\\\\u533a\\\\u57df\\\\u8c03\\\\u4ef7\\\\u4fe1\\\\u606f";
        if (value.includes("\\\\u63cf\\\\u8ff0\\\\u4fe1\\\\u606f")) return "\\\\u63cf\\\\u8ff0\\\\u4fe1\\\\u606f";
        if (value.includes("\\\\u5305\\\\u88c5\\\\u4fe1\\\\u606f")) return "\\\\u5305\\\\u88c5\\\\u4fe1\\\\u606f";
        if (value.includes("\\\\u6a21\\\\u677f\\\\u4fe1\\\\u606f") || value.includes("\\\\u6a21\\\\u7248\\\\u4fe1\\\\u606f")) return "\\\\u6a21\\\\u677f\\\\u4fe1\\\\u606f";
        if (value.includes("\\\\u5176\\\\u4ed6\\\\u4fe1\\\\u606f")) return "\\\\u5176\\\\u4ed6\\\\u4fe1\\\\u606f";
        return "";
      };
      const moduleOf = (el) => normalizeModuleName(el.closest(".form-card")?.querySelector("h4.form-card-title")?.innerText || "");
      const labelOf = (el) => {
        const container = el.closest(".ant-form-item,.el-form-item,.form-item,.form-group,tr,li,.form-row") || el.parentElement;
        const label = norm(container?.querySelector("label,.ant-form-item-label,.el-form-item__label,.label")?.innerText || "");
        if (label) return label.replace(/[：:*\\\\s]+$/g, "");
        const text = norm(container?.innerText || container?.textContent || "");
        const current = norm(el.querySelector(".ant-select-selection-item,.ant-select-selection-placeholder,.el-input__inner,input")?.innerText || el.querySelector("input")?.value || "");
        return text.replace(current, "").slice(0, 80).replace(/[：:*\\\\s]+$/g, "") || "\\\\u672a\\\\u8bc6\\\\u522b\\\\u5b57\\\\u6bb5";
      };

      const classifyField = (control, label, module, currentValue) => {
        const labelLower = norm(label).toLowerCase();
        const moduleLower = norm(module).toLowerCase();
        const controlClass = norm(control.className || control.getAttribute("class") || "");
        const isCascader = controlClass.includes("cascader");

        // Skip 店铺名称
        if (/\\\\u5e97\\\\u94fa\\\\u540d\\\\u79f0|\\\\u5e97\\\\u94fa\\\\u540d|\\\\u5e97\\\\u94fa\\\\u5206\\\\u7c7b|shop.?name/.test(labelLower)) return "skip";

        // 基本信息: Category
        if (moduleLower.includes("\\\\u57fa\\\\u672c\\\\u4fe1\\\\u606f") || !moduleLower) {
          if (/\\\\u4ea7\\\\u54c1\\\\u7c7b\\\\u76ee|\\\\u4ea7\\\\u54c1\\\\u5206\\\\u7c7b|\\\\u5546\\\\u54c1\\\\u7c7b\\\\u76ee|\\\\u5546\\\\u54c1\\\\u5206\\\\u7c7b|\\\\u6240\\\\u5c5e\\\\u7c7b\\\\u76ee|\\\\u7c7b\\\\u76ee\\\\u8def\\\\u5f84|\\\\u9009\\\\u62e9\\\\u7c7b\\\\u76ee/.test(labelLower)) return "category";
          if (isCascader && /\\\\u7c7b\\\\u76ee|\\\\u5206\\\\u7c7b/.test(labelLower) && !/\\\\u5e97\\\\u94fa/.test(labelLower)) return "category";
        }

        // 属性信息: Attribute Template
        if (moduleLower.includes("\\\\u5c5e\\\\u6027\\\\u4fe1\\\\u606f")) {
          if (/\\\\u5f15\\\\u7528\\\\u6a21\\\\u677f|\\\\u8bf7\\\\u9009\\\\u62e9\\\\u5f15\\\\u7528\\\\u6a21\\\\u677f|\\\\u5c5e\\\\u6027\\\\u6a21\\\\u677f/.test(labelLower)) return "attributeTemplate";
        }

        // 模板信息: Freight / Service
        if (moduleLower.includes("\\\\u6a21\\\\u677f\\\\u4fe1\\\\u606f") || moduleLower.includes("\\\\u6a21\\\\u7248\\\\u4fe1\\\\u606f")) {
          if (/\\\\u8fd0\\\\u8d39\\\\u6a21\\\\u677f|\\\\u7269\\\\u6d41\\\\u6a21\\\\u677f/.test(labelLower)) return "freightTemplate";
          if (/\\\\u670d\\\\u52a1\\\\u6a21\\\\u677f/.test(labelLower)) return "serviceTemplate";
        }

        // 其他信息: EU / Brand
        if (moduleLower.includes("\\\\u5176\\\\u4ed6\\\\u4fe1\\\\u606f")) {
          if (/\\\\u6b27\\\\u76df\\\\u8d23\\\\u4efb\\\\u4eba|\\\\u6b27\\\\u4ee3|\\\\u6b27\\\\u76df\\\\u8d1f\\\\u8d23\\\\u4eba/.test(labelLower)) return "euResponsible";
          if (/\\\\u54c1\\\\u724c\\\\u5236\\\\u9020\\\\u5546|\\\\u5236\\\\u9020\\\\u5546\\\\u4fe1\\\\u606f/.test(labelLower)) return "brandManufacturer";
        }

        // Fallback: label-only
        if (/\\\\u8fd0\\\\u8d39\\\\u6a21\\\\u677f/.test(labelLower)) return "freightTemplate";
        if (/\\\\u670d\\\\u52a1\\\\u6a21\\\\u677f/.test(labelLower)) return "serviceTemplate";
        if (/\\\\u6b27\\\\u76df\\\\u8d23\\\\u4efb\\\\u4eba/.test(labelLower)) return "euResponsible";
        if (/\\\\u54c1\\\\u724c\\\\u5236\\\\u9020\\\\u5546/.test(labelLower)) return "brandManufacturer";

        return "unknown";
      };

      const isUsefulOption = (fieldKey, option) => {
        const value = norm(option);
        if (!value || value === "\\\\u4ece\\\\u9875\\\\u9762\\\\u9009\\\\u9879\\\\u586b\\\\u5165") return false;
        if (/^-+\\\\s*\\\\u8bf7\\\\u9009\\\\u62e9/.test(value) || value === "\\\\u6682\\\\u65e0\\\\u6570\\\\u636e" || value === "\\\\u7ba1\\\\u7406\\\\u6a21\\\\u677f") return false;
        if (/^cn\\\\d+[a-z0-9]*$/i.test(value)) return false;
        if (fieldKey === "category") {
          return /[\\\\u4e00-\\\\u9fff]/.test(value) || /\\\\(.+\\\\)/.test(value);
        }
        return true;
      };

      const currentValueOf = (el) => norm(
        el.querySelector(".ant-select-selection-item,.ant-select-selection-placeholder,.el-input__inner")?.innerText ||
        el.querySelector("input")?.value ||
        el.innerText ||
        ""
      );

      const optionSelector = [
        ".ant-select-item-option",
        ".ant-select-dropdown-menu-item",
        ".ant-cascader-menu-item",
        ".el-select-dropdown__item",
        ".el-cascader-node",
        "[role='option']"
      ].join(",");

      const collectAllOptions = async (fieldKey) => {
        const collected = [];
        const addVisible = () => {
          const dropdowns = Array.from(document.querySelectorAll(
            ".ant-select-dropdown:not(.ant-select-dropdown-hidden),.ant-cascader-menus,.el-select-dropdown,.el-cascader__dropdown"
          )).filter(visible);
          for (const dd of dropdowns) {
            Array.from(dd.querySelectorAll(optionSelector))
              .filter(visible)
              .map((opt) => norm(opt.innerText || opt.textContent))
              .filter((text) => text && text.length <= 120 && !/^\\\\s*$/.test(text))
              .forEach((text) => collected.push(text));
          }
        };
        addVisible();

        // Scroll through each scrollable container
        const scrollContainers = Array.from(document.querySelectorAll(
          ".rc-virtual-list-holder,.ant-select-dropdown-menu,.ant-cascader-menu,.el-select-dropdown__wrap,.el-cascader-menu__wrap"
        )).filter(visible).filter((el) => el.scrollHeight > el.clientHeight + 4);

        for (const container of scrollContainers) {
          container.scrollTop = 0;
          await sleep(80);
          addVisible();
          let lastTop = -1;
          for (let i = 0; i < 50; i++) {
            if (container.scrollTop === lastTop) break;
            lastTop = container.scrollTop;
            container.scrollTop = Math.min(
              container.scrollHeight,
              container.scrollTop + Math.max(60, Math.floor(container.clientHeight * 0.8))
            );
            await sleep(100);
            addVisible();
            if (container.scrollTop + container.clientHeight >= container.scrollHeight - 2) break;
          }
          container.scrollTop = 0;
        }
        return uniq(collected).slice(0, 240);
      };

      const controls = uniq(Array.from(document.querySelectorAll(".ant-select,.ant-cascader-picker,.el-select,.el-cascader"))
        .filter(visible)
        .map((el) => el))
        .slice(0, 60);
      const groups = [];
      const warnings = [];

      // Pre-scan: close any open dropdowns
      await closeDropdown();

      for (const control of controls) {
        try {
          // Close previous dropdown thoroughly first
          await closeDropdown();

          const label = labelOf(control);
          const module = moduleOf(control);
          const currentValue = currentValueOf(control);
          const fieldKey = classifyField(control, label, module, currentValue);
          if (fieldKey === "skip" || fieldKey === "unknown") {
            continue;
          }

          // Open this control
          const trigger = control.querySelector(".ant-select-selector,.el-input,input") || control;
          clickEl(trigger);
          await sleep(600);

          // Collect — scoped to currently visible dropdowns
          const options = (await collectAllOptions(fieldKey)).filter((option) => isUsefulOption(fieldKey, option));
          groups.push({ fieldKey, module, label, currentValue, options });

          await closeDropdown();
        } catch (error) {
          warnings.push((error && error.message) ? error.message : String(error));
          await closeDropdown();
        }
      }

      resolve({
        url: location.href,
        groups: groups.filter((group) => group.label || group.currentValue || group.options.length),
        warnings
      });
    }))()\`;

    const scanResult = await evaluateInTab(editTab, expression);
    appendAutomationLog("scanDropdownOptions.result", {
      url: scanResult?.url,
      groups: scanResult?.groups?.map((group) => ({
        fieldKey: group.fieldKey,
        module: group.module,
        label: group.label,
        currentValue: group.currentValue,
        optionCount: group.options?.length || 0
      })),
      warnings: scanResult?.warnings
    });
    return scanResult;
  });`;

const before = content.substring(0, brokenStart);
const after = content.substring(brokenEnd);

content = before + replacement + '\n' + after;

fs.writeFileSync(path, content, 'utf8');
console.log('DONE - Replaced', brokenEnd - brokenStart, 'chars with', replacement.length, 'chars');

// Verify syntax
try {
  require('child_process').execSync('node -c "' + path + '"', { encoding: 'utf8' });
  console.log('Syntax OK');
} catch (e) {
  console.log('SYNTAX ERROR:', e.stderr || e.message);
}
