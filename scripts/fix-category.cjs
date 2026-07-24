const fs = require('fs');
const path = 'C:/Users/我是新人/Documents/aliexpress/electron/main.cjs';
let content = fs.readFileSync(path, 'utf8');

// Fix 1: In scanDropdownOptions, replace the main loop to handle category-cascader specially
const oldLoopMarker = '      // Pre-scan: close any open dropdowns\n      await closeDropdown();\n\n      for (const control of controls) {';
const newCategoryLoop = `      // Pre-scan: close any open dropdowns
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

          // === CATEGORY CASCADER: special handling ===
          if (fieldKey === "category") {
            // Cascader trigger: click the input inside the cascader
            const cascaderInput = control.querySelector("input") || control.querySelector(".ant-cascader-picker") || control;
            // Scroll into view first
            control.scrollIntoView({ block: "center", inline: "nearest" });
            await sleep(300);

            // Click to open cascader menus
            const inputRect = cascaderInput.getBoundingClientRect();
            const init = { bubbles: true, cancelable: true, view: window, clientX: inputRect.left + inputRect.width / 2, clientY: inputRect.top + inputRect.height / 2 };
            cascaderInput.dispatchEvent(new MouseEvent("mouseover", init));
            cascaderInput.dispatchEvent(new MouseEvent("mousedown", init));
            cascaderInput.dispatchEvent(new MouseEvent("mouseup", init));
            cascaderInput.dispatchEvent(new MouseEvent("click", init));
            cascaderInput.focus();
            await sleep(800);

            // Cascader menus: collect from each column independently
            const catOptions = [];
            const menus = Array.from(document.querySelectorAll(".ant-cascader-menu"))
              .filter(visible);

            for (const menu of menus) {
              // Scroll this column to collect all items
              menu.scrollTop = 0;
              await sleep(100);
              let lastTop = -1;
              for (let s = 0; s < 30; s++) {
                if (menu.scrollTop === lastTop) break;
                lastTop = menu.scrollTop;
                // Collect visible items in this column
                Array.from(menu.querySelectorAll(".ant-cascader-menu-item"))
                  .filter(visible)
                  .map((opt) => norm(opt.innerText || opt.textContent))
                  .filter((text) => text && text.length <= 120 && !/^\\s*$/.test(text))
                  .forEach((text) => { if (!catOptions.includes(text)) catOptions.push(text); });

                menu.scrollTop = Math.min(menu.scrollHeight, menu.scrollTop + Math.max(60, Math.floor(menu.clientHeight * 0.8)));
                await sleep(100);
              }
            }

            groups.push({ fieldKey, module, label, currentValue, options: catOptions });
            await closeDropdown();
            continue;
          }

          // === OTHER DROPDOWNS: standard handling ===
          const trigger = control.querySelector(".ant-select-selector,.el-input,input") || control;
          clickEl(trigger);
          await sleep(600);

          const options = (await collectAllOptions(fieldKey)).filter((option) => isUsefulOption(fieldKey, option));
          groups.push({ fieldKey, module, label, currentValue, options });

          await closeDropdown();
        } catch (error) {
          warnings.push((error && error.message) ? error.message : String(error));
          await closeDropdown();
        }
      }`;

content = content.replace(oldLoopMarker, newCategoryLoop);
console.log('1. Category cascader special handling added to scan loop');

fs.writeFileSync(path, content, 'utf8');

// Verify syntax
const { execSync } = require('child_process');
try {
  execSync('node -c "' + path + '"', { encoding: 'utf8' });
  console.log('Syntax OK');
} catch (e) {
  console.log('SYNTAX ERROR:', e.stderr?.substring(0, 200) || e.message);
}
