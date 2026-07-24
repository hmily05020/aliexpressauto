let http = require('http');
let WebSocket = require('ws'); // Try ws package

// First try with ws, fall back to raw WebSocket
let WS_IMPL = null;
try { WS_IMPL = require('ws'); } catch(e) {}

if (!WS_IMPL) {
  console.log('Installing ws...');
  require('child_process').execSync('npm install ws', {cwd: __dirname, stdio: 'ignore'});
  WS_IMPL = require('ws');
}

const PORT = 9222;

function httpGet(path) {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:' + PORT + path, (res) => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => resolve(JSON.parse(d)));
    }).on('error', reject);
  });
}

class CDP {
  constructor(wsUrl) {
    this.ws = new WS_IMPL(wsUrl);
    this.id = 0;
    this.pending = new Map();
    this.ws.on('message', (data) => {
      let msg = JSON.parse(data);
      if (msg.id && this.pending.has(msg.id)) {
        this.pending.get(msg.id)(msg);
        this.pending.delete(msg.id);
      }
    });
    this.ready = new Promise((resolve, reject) => {
      this.ws.on('open', resolve);
      this.ws.on('error', reject);
    });
  }

  async send(method, params = {}) {
    await this.ready;
    return new Promise((resolve) => {
      this.id++;
      this.pending.set(this.id, resolve);
      this.ws.send(JSON.stringify({ id: this.id, method, params }));
    });
  }

  async evaluate(expression, awaitPromise = true) {
    await this.send('Runtime.enable');
    let result = await this.send('Runtime.evaluate', {
      expression, awaitPromise, returnByValue: true
    });
    if (result.result?.exceptionDetails) {
      let d = result.result.exceptionDetails;
      throw new Error((d.exception?.description || d.text || 'JS error') + ' at ' + d.lineNumber + ':' + d.columnNumber);
    }
    return result.result?.result?.value;
  }

  close() { this.ws.close(); }
}

async function main() {
  // 1. Find the edit tab
  let tabs = await httpGet('/json/list');
  let editTab = tabs.find(t => t.type === 'page' && /dianxiaomi.*edit/i.test(t.url));
  if (!editTab) {
    console.log('No edit tab found. Available tabs:');
    tabs.filter(t => t.type === 'page').forEach(t => console.log(' -', t.title || t.url));
    process.exit(1);
  }
  console.log('Edit tab:', editTab.title, editTab.url.substring(0, 80));

  // 2. Connect
  let cdp = new CDP(editTab.webSocketDebuggerUrl);
  await cdp.ready;
  console.log('Connected to page');

  // 3. Run diagnostic
  let expr = `(() => new Promise(async (resolve) => {
    let n = (v) => (v || '').replace(/\\s+/g, ' ').trim();
    let slp = (ms) => new Promise((d) => setTimeout(d, ms));
    let vis = (el) => {
      if (!el || !el.getBoundingClientRect) return false;
      let r = el.getBoundingClientRect();
      let s = getComputedStyle(el);
      return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
    };
    let clk = (el) => {
      if (!el) return;
      el.scrollIntoView({ block: 'center' });
      let r = el.getBoundingClientRect();
      ['mouseover','mousedown','mouseup','click'].forEach(t =>
        el.dispatchEvent(new MouseEvent(t, {bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))
      );
    };

    let cards = Array.from(document.querySelectorAll('.form-card')).filter(vis);
    let attrCard = cards.find(c => n(c.querySelector('h4')?.innerText || '').indexOf('\\\\u5c5e\\\\u6027\\\\u4fe1\\\\u606f') >= 0);
    if (!attrCard) { resolve({error:'attr card not found'}); return; }

    let allSelects = Array.from(attrCard.querySelectorAll('.ant-select'));
    let selectInfo = allSelects.map((s, i) => {
      let parent = s.closest('.in-selector,.d-selector,.form-card-header,.ant-form-item') || s.parentElement;
      return {
        i, inFormItem: !!s.closest('.ant-form-item'),
        parentClass: (parent.className || '').substring(0, 80),
        curVal: n(s.querySelector('.ant-select-selection-item')?.innerText || ''),
        placeholder: n(s.querySelector('.ant-select-selection-placeholder')?.innerText || '')
      };
    });

    // Find the in-selector (template selector)
    let tmplSelect = attrCard.querySelector('.in-selector .ant-select,.d-selector .ant-select')
      || Array.from(attrCard.querySelectorAll('.ant-select')).find(s => !s.closest('.ant-form-item'));

    let dropdownInfo = null;
    if (tmplSelect) {
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
      document.body.click();
      await slp(300);

      let trigger = tmplSelect.querySelector('.ant-select-selector') || tmplSelect;
      clk(trigger);
      await slp(1200);

      let dd = document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)');
      if (dd) {
        // Check scroll container
        let holder = dd.querySelector('.rc-virtual-list-holder');
        let scrollH = holder ? holder.scrollHeight : dd.scrollHeight;
        let clientH = holder ? holder.clientHeight : dd.clientHeight;

        // Get initial options
        let initial = Array.from(dd.querySelectorAll('.ant-select-item-option')).map(o => ({
          text: n(o.innerText || o.textContent),
          selected: o.classList.contains('ant-select-item-option-selected')
        }));

        // Jump to bottom
        if (holder) { holder.scrollTop = scrollH; }
        else { dd.scrollTop = scrollH; }
        await slp(600);

        let afterBottom = Array.from(dd.querySelectorAll('.ant-select-item-option')).map(o =>
          n(o.innerText || o.textContent)
        );

        // Also try scrolling to middle positions
        let allTexts = [...afterBottom];
        if (scrollH > clientH) {
          let checkPoints = [0.25, 0.5, 0.75];
          for (let pct of checkPoints) {
            let pos = Math.floor(scrollH * pct);
            if (holder) holder.scrollTop = pos;
            else dd.scrollTop = pos;
            await slp(400);
            Array.from(dd.querySelectorAll('.ant-select-item-option')).forEach(o => {
              let t = n(o.innerText || o.textContent);
              if (!allTexts.includes(t)) allTexts.push(t);
            });
          }
        }

        dropdownInfo = {
          scrollH, clientH, hasHolder: !!holder,
          initialCount: initial.length,
          initial: initial,
          afterBottomCount: afterBottom.length,
          afterBottom: afterBottom,
          allUniqueCount: allTexts.length,
          allUnique: allTexts
        };
      } else {
        dropdownInfo = { error: 'dropdown did not open' };
      }
    }

    resolve({
      selectCount: allSelects.length,
      selects: selectInfo,
      tmplSelectFound: !!tmplSelect,
      dropdown: dropdownInfo
    });
  })())`;

  try {
    let diag = await cdp.evaluate(expr);
    console.log('\n=== DIAGNOSTIC RESULT ===');
    console.log(JSON.stringify(diag, null, 2));
  } catch(e) {
    console.log('ERROR:', e.message);
  }

  cdp.close();
}

main().catch(e => console.log('FATAL:', e.message));
