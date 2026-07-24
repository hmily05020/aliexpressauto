const fs = require('fs');
const path = 'C:/Users/我是好人/Documents/aliexpress/electron/main.cjs';
let content = fs.readFileSync(path, 'utf8');

// 1. Replace closeDropdown
const closeDropMarker = 'const closeDropdown = async () => {';
const closeDropStart = content.indexOf(closeDropMarker);
if (closeDropStart < 0) { console.log('closeDropdown NOT FOUND'); process.exit(1); }
const closeDropEnd = content.indexOf('      };\n', closeDropStart) + 8;

const newCloseDrop = [
'      const closeDropdown = async () => {',
'        // Force-close ALL open dropdowns and cascader menus',
'        for (let i = 0; i < 3; i++) {',
'          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));',
'          document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));',
'        }',
'        document.body.click();',
'        await sleep(200);',
'        // Verify closed — retry if menus still visible',
'        let retries = 0;',
'        while (retries < 5 && document.querySelectorAll(',
'          ".ant-select-dropdown:not(.ant-select-dropdown-hidden),.ant-cascader-menus,.el-cascader__dropdown"',
'        ).length > 0) {',
'          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));',
'          document.body.click();',
'          await sleep(150);',
'          retries++;',
'        }',
'      };',
].join('\n');

content = content.substring(0, closeDropStart) + newCloseDrop + content.substring(closeDropEnd);
console.log('1. closeDropdown replaced');

// 2. Replace collectAllOptions
const collectMarker = 'const collectAllOptions = async () => {';
const collectStart = content.indexOf(collectMarker);
if (collectStart < 0) { console.log('collectAllOptions NOT FOUND'); process.exit(1); }
const collectEnd = content.indexOf('      };\n', collectStart) + 8;

const newCollect = [
'      const collectAllOptions = async (fieldKey) => {',
'        const collected = [];',
'        const addVisible = () => {',
'          // Only collect from currently-visible dropdown containers (not stale ones)',
'          const dropdowns = Array.from(document.querySelectorAll(',
'            ".ant-select-dropdown:not(.ant-select-dropdown-hidden),.ant-cascader-menus,.el-select-dropdown,.el-cascader__dropdown"',
'          )).filter(visible);',
'          for (const dd of dropdowns) {',
'            Array.from(dd.querySelectorAll(',
'              ".ant-select-item-option,.ant-select-dropdown-menu-item,.ant-cascader-menu-item,.el-select-dropdown__item,.el-cascader-node,[role=\\"option\\"]"',
'            ))',
'              .filter(visible)',
'              .map((opt) => norm(opt.innerText || opt.textContent))',
'              .filter((text) => text && text.length <= 120 && !/^\\\\s*$/.test(text))',
'              .forEach((text) => collected.push(text));',
'          }',
'        };',
'        addVisible();',
'        // Scroll each scrollable container to collect all options',
'        const scrollContainers = Array.from(document.querySelectorAll(',
'          ".rc-virtual-list-holder,.ant-select-dropdown-menu,.ant-cascader-menu,.el-select-dropdown__wrap,.el-cascader-menu__wrap"',
'        )).filter(visible).filter((el) => el.scrollHeight > el.clientHeight + 4);',
'        for (const container of scrollContainers) {',
'          container.scrollTop = 0;',
'          await sleep(80);',
'          addVisible();',
'          let lastTop = -1;',
'          for (let i = 0; i < 50; i++) {',
'            if (container.scrollTop === lastTop) break;',
'            lastTop = container.scrollTop;',
'            container.scrollTop = Math.min(',
'              container.scrollHeight,',
'              container.scrollTop + Math.max(60, Math.floor(container.clientHeight * 0.8))',
'            );',
'            await sleep(100);',
'            addVisible();',
'            if (container.scrollTop + container.clientHeight >= container.scrollHeight - 2) break;',
'          }',
'          container.scrollTop = 0;',
'        }',
'        return uniq(collected).slice(0, 240);',
'      };',
].join('\n');

content = content.substring(0, collectStart) + newCollect + content.substring(collectEnd);
console.log('2. collectAllOptions replaced');

// 3. Replace the main scanning loop to close BEFORE each control
const loopMarker = '      for (const control of controls) {';
const loopStart = content.indexOf(loopMarker);
if (loopStart < 0) { console.log('main loop NOT FOUND'); process.exit(1); }
// Find end of loop: after the last await closeDropdown(); }
// Search for the resolve that comes after the loop
const resolveMarker = '\n      resolve({';
const resolveIdx = content.indexOf(resolveMarker, loopStart);
// Back up from resolve to find the end of the for loop
let loopEnd = content.lastIndexOf('      }\n', resolveIdx);
if (loopEnd < 0) loopEnd = resolveIdx - 20;

const newLoop = [
'      // Pre-scan cleanup: ensure no stray dropdowns are open',
'      await closeDropdown();',
'',
'      for (const control of controls) {',
'        try {',
'          // Close any lingering dropdown before opening this one',
'          await closeDropdown();',
'',
'          const label = labelOf(control);',
'          const module = moduleOf(control);',
'          const currentValue = currentValueOf(control);',
'          const fieldKey = classifyField(control, label, module, currentValue);',
'          if (fieldKey === "skip" || fieldKey === "unknown") {',
'            continue;',
'          }',
'',
'          // Open this control\'s dropdown',
'          const trigger = control.querySelector(".ant-select-selector,.el-input,input") || control;',
'          clickEl(trigger);',
'          await sleep(600);',
'',
'          // Collect options (now scoped to visible dropdowns only)',
'          const options = (await collectAllOptions(fieldKey)).filter((option) => isUsefulOption(fieldKey, option));',
'          groups.push({ fieldKey, module, label, currentValue, options });',
'',
'          await closeDropdown();',
'        } catch (error) {',
'          warnings.push((error && error.message) ? error.message : String(error));',
'          await closeDropdown();',
'        }',
'      }',
].join('\n');

content = content.substring(0, loopStart) + newLoop + content.substring(loopEnd);
console.log('3. Main loop replaced');

fs.writeFileSync(path, content, 'utf8');
console.log('ALL DONE');
