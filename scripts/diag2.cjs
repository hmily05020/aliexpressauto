let http = require('http');
let ws = require('ws');

function httpGet(path) {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:9222' + path, (res) => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => resolve(JSON.parse(d)));
    }).on('error', reject);
  });
}

async function main() {
  let tabs = await httpGet('/json/list');
  let tab = tabs.find(t => t.type === 'page' && /dianxiaomi.*edit/i.test(t.url));
  console.log('Tab:', tab.title);

  let cdp = new ws(tab.webSocketDebuggerUrl);
  await new Promise((r,e) => { cdp.on('open', r); cdp.on('error', e); });

  let id = 0, pending = new Map();
  cdp.on('message', (data) => {
    let msg = JSON.parse(data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  });

  function send(method, params = {}) {
    return new Promise(resolve => {
      id++;
      pending.set(id, resolve);
      cdp.send(JSON.stringify({id, method, params}));
    });
  }

  await send('Runtime.enable');

  // The expression as a regular JS string with proper unicode escapes
  let expr = `
(() => new Promise(async (resolve) => {
  try {
    let n = (v) => (v || '').replace(/\\s+/g, ' ').trim();
    let slp = (ms) => new Promise(d => setTimeout(d, ms));
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
    let attrCard = cards.find(c => n(c.querySelector('h4')?.innerText || '').includes('属性信息'));

    if (!attrCard) { resolve({error:'attr card not found'}); return; }

    let allSelects = Array.from(attrCard.querySelectorAll('.ant-select'));
    let tmplSelect = attrCard.querySelector('.in-selector .ant-select,.d-selector .ant-select')
      || Array.from(allSelects).find(s => !s.closest('.ant-form-item'));

    if (!tmplSelect) { resolve({error:'tmpl select not found',selectCount:allSelects.length}); return; }

    // Close existing
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    document.body.click();
    await slp(300);

    let trigger = tmplSelect.querySelector('.ant-select-selector') || tmplSelect;
    clk(trigger);
    await slp(1500);

    let dd = document.querySelector('.ant-select-dropdown:not(.ant-select-dropdown-hidden)');

    if (!dd) { resolve({error:'dropdown did not open'}); return; }

    let holder = dd.querySelector('.rc-virtual-list-holder');
    let sh = holder ? holder.scrollHeight : dd.scrollHeight;
    let ch = holder ? holder.clientHeight : dd.clientHeight;

    // Top
    if (holder) holder.scrollTop = 0; else dd.scrollTop = 0;
    await slp(300);
    let top = Array.from(dd.querySelectorAll('.ant-select-item-option')).map(o => n(o.innerText || o.textContent));

    // Bottom
    if (holder) holder.scrollTop = sh; else dd.scrollTop = sh;
    await slp(500);
    let bottom = Array.from(dd.querySelectorAll('.ant-select-item-option')).map(o => n(o.innerText || o.textContent));

    // Middle positions
    let middle = [];
    if (sh > ch) {
      for (let pct of [0.3, 0.5, 0.7]) {
        if (holder) holder.scrollTop = Math.floor(sh * pct);
        else dd.scrollTop = Math.floor(sh * pct);
        await slp(300);
        Array.from(dd.querySelectorAll('.ant-select-item-option')).forEach(o => {
          let t = n(o.innerText || o.textContent);
          if (!middle.includes(t)) middle.push(t);
        });
      }
    }

    let all = [...new Set([...top, ...bottom, ...middle])];

    resolve({
      hasHolder: !!holder, scrollH: sh, clientH: ch,
      top: top, bottom: bottom, middle: middle,
      allCount: all.length, all: all
    });
  } catch(e) {
    resolve({error: e.message || String(e), stack: e.stack});
  }
})())
`;

  try {
    let r2 = await send('Runtime.evaluate', {expression: expr, awaitPromise: true, returnByValue: true});
    if (r2.result?.exceptionDetails) {
      let d = r2.result.exceptionDetails;
      console.log('JS ERROR:', d.exception?.description || d.text);
      console.log('At line', d.lineNumber, 'col', d.columnNumber);
    } else {
      let val = r2.result?.result?.value;
      console.log('RESULT:');
      console.log(JSON.stringify(val, null, 2));
    }
  } catch(e) {
    console.log('EVAL ERROR:', e.message);
  }

  cdp.close();
}
main().catch(e => console.log('FATAL:', e));
