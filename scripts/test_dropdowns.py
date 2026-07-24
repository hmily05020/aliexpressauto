#!/usr/bin/env python3
"""
店小秘下拉框扫描测试工具
=========================
直接通过 Chrome DevTools Protocol (CDP) 连接浏览器，
测试下拉框扫描和类目写入逻辑，无需打包 Electron 应用。

使用方法：
  1. 先以调试模式启动 Chrome:
     chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\temp\chrome-debug"

  2. 在 Chrome 中打开店小秘编辑页:
     https://www.dianxiaomi.com/web/smt/smtProductList/draft
     然后点击某个商品的"编辑"

  3. 运行本脚本:
     python scripts/test_dropdowns.py

  4. 可选参数:
     python scripts/test_dropdowns.py --port 9222 --action scan
     python scripts/test_dropdowns.py --port 9222 --action write-category --category "汽车及零配件 > 内外饰配件 > 汽车钥匙包(Key Case for Car)"
     python scripts/test_dropdowns.py --port 9222 --action full
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from typing import Any

# Try to import websocket-client, install if missing
try:
    import websocket  # type: ignore
except ImportError:
    print("正在安装 websocket-client...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "websocket-client"])
    import websocket  # type: ignore


# ============================================================
# CDP Client
# ============================================================

class CDPClient:
    """Minimal Chrome DevTools Protocol client."""

    def __init__(self, port: int = 9222):
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self._msg_id = 0
        self._ws: Any = None
        self._pending: dict[int, Any] = {}

    # -- HTTP helpers --

    def _get_json(self, path: str) -> Any:
        try:
            with urllib.request.urlopen(f"{self.base}{path}", timeout=5) as resp:
                return json.loads(resp.read())
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"无法连接到 Chrome 调试端口 {self.port}。"
                f"请先用调试模式启动 Chrome:\n"
                f'  chrome.exe --remote-debugging-port={self.port}'
            ) from e

    def list_tabs(self) -> list[dict]:
        return self._get_json("/json/list")

    def find_dxm_edit_tab(self) -> dict | None:
        """Find the best 店小秘编辑页 tab."""
        tabs = self.list_tabs()
        # Prefer edit pages
        edit_tabs = [
            t for t in tabs
            if t.get("type") == "page"
            and "dianxiaomi.com" in t.get("url", "")
            and "/edit" in t.get("url", "")
        ]
        if edit_tabs:
            return edit_tabs[0]
        # Fallback: any dianxiaomi page
        dxm_tabs = [
            t for t in tabs
            if t.get("type") == "page"
            and "dianxiaomi.com" in t.get("url", "")
        ]
        return dxm_tabs[0] if dxm_tabs else None

    # -- WebSocket helpers --

    def connect(self, ws_url: str, timeout: int = 8):
        self._ws = websocket.create_connection(ws_url, timeout=timeout)

    def close(self):
        if self._ws:
            self._ws.close()
            self._ws = None
        self._pending.clear()

    def send(self, method: str, params: dict | None = None) -> Any:
        """Send a CDP command and wait for the result."""
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method, "params": params or {}}
        self._ws.send(json.dumps(msg))

        # Read responses until we get our id back
        while True:
            raw = self._ws.recv()
            if not raw:
                raise ConnectionError("WebSocket connection closed")
            resp = json.loads(raw)
            if resp.get("id") == self._msg_id:
                if "error" in resp:
                    raise RuntimeError(f"CDP Error: {resp['error']}")
                return resp.get("result", {})

    def evaluate(self, expression: str, await_promise: bool = False) -> Any:
        """Evaluate JavaScript in the page context."""
        self.send("Runtime.enable")
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": await_promise,
            "returnByValue": True,
        })
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            desc = details.get("exception", {}).get("description", details.get("text", "Unknown error"))
            raise RuntimeError(f"JS Exception: {desc}")
        return result.get("result", {}).get("value")


# ============================================================
# Scanner logic (mirrors the Electron main.cjs expressions)
# ============================================================

SCANNER_VERSION = "0.2.0-python-test"

DROPdown_SCAN_EXPRESSION = r"""
(() => new Promise(async (resolve) => {
  const norm = (value) => (value || "").replace(/\s+/g, " ").trim();
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
  const closeDropdown = async () => {
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
    await sleep(120);
  };

  const normalizeModuleName = (text) => {
    const value = norm(text).replace(/（.*?）|\(.*?\)/g, "");
    if (value.includes("基本信息")) return "基本信息";
    if (value.includes("店小秘信息")) return "店小秘信息";
    if (value.includes("属性信息")) return "属性信息";
    if (value.includes("产品信息")) return "产品信息";
    if (value.includes("区域调价信息")) return "区域调价信息";
    if (value.includes("描述信息")) return "描述信息";
    if (value.includes("包装信息")) return "包装信息";
    if (value.includes("模板信息") || value.includes("模版信息")) return "模板信息";
    if (value.includes("其他信息")) return "其他信息";
    return "";
  };
  const moduleOf = (el) => normalizeModuleName(el.closest(".form-card")?.querySelector("h4.form-card-title")?.innerText || "");

  const labelOf = (el) => {
    const container = el.closest(".ant-form-item,.el-form-item,.form-item,.form-group,tr,li,.form-row") || el.parentElement;
    const label = norm(container?.querySelector("label,.ant-form-item-label,.el-form-item__label,.label")?.innerText || "");
    if (label) return label.replace(/[：:*\s]+$/g, "");
    const text = norm(container?.innerText || container?.textContent || "");
    const current = norm(el.querySelector(".ant-select-selection-item,.ant-select-selection-placeholder,.el-input__inner,input")?.innerText || el.querySelector("input")?.value || "");
    return text.replace(current, "").slice(0, 80).replace(/[：:*\s]+$/g, "") || "未识别字段";
  };

  const classifyField = (control, label, module, currentValue) => {
    const container = control.closest(".ant-form-item,.el-form-item,.form-item,.form-group,tr,li,.form-row") || control.parentElement;
    const containerParent = container?.parentElement || container;
    const ownText = norm(String(module) + " " + String(label) + " " + String(currentValue)).toLowerCase();
    const containerText = norm(container?.innerText || container?.textContent || "").toLowerCase();
    const parentText = norm(containerParent?.innerText || containerParent?.textContent || "").toLowerCase();
    const aria = norm(control.getAttribute("aria-label") || control.getAttribute("title") || "");
    const placeholder = norm(control.querySelector("input,textarea")?.getAttribute("placeholder") || "");
    const combo = ownText + " " + containerText + " " + parentText + " " + aria + " " + placeholder;
    const controlClass = norm(control.className || control.getAttribute("class") || "");

    if (/店铺名称|店铺名|shop.?name|店铺分类/.test(combo)) return "skip";
    if (
      /产品分类|产品类目|商品分类|商品类目|商品所属类目|所属类目|选择类目|类目路径/.test(combo) ||
      (controlClass.includes("cascader") && /类目|分类/.test(combo)) ||
      (/请选择.*类目/.test(combo) && !/店铺/.test(combo))
    ) return "category";
    if (
      /引用模板|请选择引用模板|属性模板/.test(combo) ||
      (/属性信息/.test(module) && /引用模板|管理模板|属性模板|模板/.test(containerText)) ||
      /attribute.*template|template.*attribute/i.test(combo)
    ) return "attributeTemplate";
    if (
      /运费模板/.test(combo) ||
      (/模板信息/.test(module) && /运费模板|物流模板|请选择运费模板/.test(containerText)) ||
      /freight.*template/i.test(combo)
    ) return "freightTemplate";
    if (
      /服务模板/.test(combo) ||
      (/模板信息/.test(module) && /服务模板|请选择服务模板/.test(containerText)) ||
      /service.*template/i.test(combo)
    ) return "serviceTemplate";
    if (
      /欧盟责任人|责任人|欧代|欧盟负责人/.test(combo) ||
      /eu.*responsible|responsible.*person/i.test(combo)
    ) return "euResponsible";
    if (
      /品牌制造商|制造商信息|制造商|品牌/.test(combo) ||
      /brand.*manufacturer|manufacturer.*info/i.test(combo)
    ) return "brandManufacturer";
    return "unknown";
  };

  const isUsefulOption = (fieldKey, option) => {
    const value = norm(option);
    if (!value || value === "从页面选项填入") return false;
    if (/^-+\s*请选择/.test(value) || value === "暂无数据" || value === "管理模板") return false;
    if (/^cn\d+[a-z0-9]*$/i.test(value)) return false;
    if (fieldKey === "category") {
      return /[一-鿿]/.test(value) || /\(.+\)/.test(value);
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

  const collectVisibleOptions = () => Array.from(document.querySelectorAll(optionSelector))
    .filter(visible)
    .map((option) => norm(option.innerText || option.textContent))
    .filter((text) => text && text.length <= 120 && !/^\s*$/.test(text));

  const dropdownContainerSelector = [
    ".ant-select-dropdown:not(.ant-select-dropdown-hidden)",
    ".ant-cascader-menus",
    ".el-select-dropdown",
    ".el-cascader__dropdown"
  ].join(",");

  const scrollableSelector = [
    ".rc-virtual-list-holder",
    ".ant-select-dropdown .rc-virtual-list-holder",
    ".ant-select-dropdown-menu",
    ".ant-cascader-menu",
    ".el-select-dropdown__wrap",
    ".el-cascader-menu__wrap"
  ].join(",");

  const collectAllOptions = async () => {
    const collected = [];
    const addVisible = () => { collected.push(...collectVisibleOptions()); };
    addVisible();
    const containers = Array.from(document.querySelectorAll(dropdownContainerSelector + "," + scrollableSelector))
      .filter(visible)
      .filter((el) => el.scrollHeight > el.clientHeight + 4);
    for (const container of containers) {
      container.scrollTop = 0;
      await sleep(100);
      addVisible();
      let lastTop = -1;
      for (let index = 0; index < 40; index += 1) {
        if (container.scrollTop === lastTop) break;
        lastTop = container.scrollTop;
        container.scrollTop = Math.min(container.scrollHeight, container.scrollTop + Math.max(80, Math.floor(container.clientHeight * 0.8)));
        await sleep(120);
        addVisible();
        if (container.scrollTop + container.clientHeight >= container.scrollHeight - 2) break;
      }
    }
    return uniq(collected).slice(0, 240);
  };

  const controls = uniq(Array.from(document.querySelectorAll(".ant-select,.ant-cascader-picker,.el-select,.el-cascader"))
    .filter(visible)
    .map((el) => el))
    .slice(0, 60);

  const groups = [];
  const warnings = [];
  const skippedDebug = [];

  for (const control of controls) {
    try {
      const label = labelOf(control);
      const module = moduleOf(control);
      const currentValue = currentValueOf(control);
      const fieldKey = classifyField(control, label, module, currentValue);
      if (fieldKey === "skip") continue;
      if (fieldKey === "unknown") {
        skippedDebug.push({ label: label.slice(0, 60), module, currentValue: currentValue.slice(0, 40) });
        continue;
      }
      clickEl(control.querySelector(".ant-select-selector,.el-input,input") || control);
      await sleep(550);
      const options = (await collectAllOptions()).filter((option) => isUsefulOption(fieldKey, option));
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
    warnings,
    skippedDebug
  });
}))()
"""

# ============================================================
# Test actions
# ============================================================

def action_scan(cdp: CDPClient, tab: dict):
    """Scan all dropdowns on the current edit page."""
    print(f"\n{'='*60}")
    print("扫描编辑页下拉框")
    print(f"{'='*60}")
    print(f"当前页面: {tab.get('title', tab.get('url', 'unknown'))}")
    print(f"URL: {tab.get('url', 'unknown')}")

    print("\n正在连接 WebSocket...")
    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        print("❌ 无法获取 WebSocket URL，请确认页面已加载完成")
        return

    cdp.connect(ws_url)

    print("正在扫描下拉框（可能需要 10-30 秒）...")
    try:
        result = cdp.evaluate(DROPdown_SCAN_EXPRESSION, await_promise=True)

        if not result:
            print("❌ 扫描返回空结果")
            return

        groups = result.get("groups", [])
        warnings = result.get("warnings", [])
        skipped = result.get("skippedDebug", [])

        # Group by fieldKey
        grouped: dict[str, list] = {}
        for g in groups:
            key = g.get("fieldKey", "unknown")
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(g)

        print(f"\n{'─'*60}")
        print(f"扫描结果: {len(groups)} 个已分类下拉框, {len(warnings)} 个警告")
        print(f"{'─'*60}")

        ORDER = [
            ("category", "📂 产品类目"),
            ("attributeTemplate", "📋 引用模板（属性信息）"),
            ("freightTemplate", "🚚 运费模板"),
            ("serviceTemplate", "⚙️ 服务模板"),
            ("euResponsible", "🇪🇺 欧盟责任人"),
            ("brandManufacturer", "🏭 品牌制造商"),
            ("unknown", "❓ 未识别"),
        ]

        for key, title in ORDER:
            items = grouped.get(key, [])
            if not items:
                print(f"\n{title}: (未找到)")
                continue

            all_opts = list(set(
                opt for g in items
                for opt in g.get("options", [])
            ))

            print(f"\n{title}: {len(all_opts)} 个选项")
            for g in items:
                print(f"  模块: {g.get('module', '?')} | 字段: {g.get('label', '?')[:50]}")
                print(f"  当前值: {g.get('currentValue', '空')[:60]}")

            # Show first 10 options
            for opt in all_opts[:10]:
                print(f"    · {opt[:80]}")
            if len(all_opts) > 10:
                print(f"    ... 还有 {len(all_opts) - 10} 个选项")

        if skipped:
            print(f"\n{'─'*60}")
            print(f"已跳过 {len(skipped)} 个未识别控件（非目标字段）:")
            for s in skipped[:8]:
                print(f"  · {s.get('label', '?')[:50]} (模块: {s.get('module', '?')})")

        if warnings:
            print(f"\n⚠ 警告:")
            for w in warnings:
                print(f"  · {w}")

    finally:
        cdp.close()


def action_scan_category(cdp: CDPClient, tab: dict):
    """Only scan the category dropdown."""
    print(f"\n{'='*60}")
    print("扫描类目下拉框")
    print(f"{'='*60}")

    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        print("❌ 无法获取 WebSocket URL")
        return

    cdp.connect(ws_url)

    # Lightweight expression - just find and open the category dropdown
    expr = r"""
    (() => new Promise(async (resolve) => {
      const norm = (v) => (v || "").replace(/\s+/g, " ").trim();
      const visible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;
      };
      const click = (el) => {
        el.scrollIntoView({ block: "center" });
        const r = el.getBoundingClientRect();
        ["mouseover","mousedown","mouseup","click"].forEach(t =>
          el.dispatchEvent(new MouseEvent(t, {bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))
        );
      };
      const sleep = (ms) => new Promise(d => setTimeout(d, ms));
      const uniq = (a) => [...new Set(a.filter(Boolean))];

      // Find category controls
      const controls = Array.from(document.querySelectorAll(".ant-select,.ant-cascader-picker,.el-select,.el-cascader"))
        .filter(visible);

      const categoryControls = [];
      for (const c of controls) {
        const container = c.closest(".ant-form-item,.el-form-item,.form-item,.form-group,tr,li") || c.parentElement;
        const text = norm(container?.innerText || "").toLowerCase();
        const cls = norm(c.className || c.getAttribute("class") || "");
        if (
          /产品分类|产品类目|商品分类|商品类目|商品所属类目|所属类目|选择类目|类目路径/.test(text) ||
          (cls.includes("cascader") && /类目|分类/.test(text))
        ) {
          categoryControls.push(c);
        }
      }

      if (!categoryControls.length) {
        resolve({ found: false, reason: "未找到类目下拉框" });
        return;
      }

      const ctrl = categoryControls[0];
      const currentValue = norm(ctrl.querySelector(".ant-select-selection-item,.ant-select-selection-placeholder")?.innerText || "");
      click(ctrl.querySelector(".ant-select-selector,.el-input,input") || ctrl);
      await sleep(600);

      const opts = uniq(Array.from(document.querySelectorAll(
        ".ant-select-item-option,.ant-cascader-menu-item,.el-select-dropdown__item,.el-cascader-node,[role='option']"
      )).filter(visible).map(o => norm(o.innerText || o.textContent)).filter(t => t && t.length <= 120));

      document.dispatchEvent(new KeyboardEvent("keydown", {key:"Escape",code:"Escape",bubbles:true}));
      await sleep(120);

      resolve({ found: true, currentValue, options: opts.slice(0, 80), controlCount: categoryControls.length });
    }))()
    """

    try:
        result = cdp.evaluate(expr, await_promise=True)
        if result and result.get("found"):
            print(f"当前值: {result.get('currentValue', '空')}")
            print(f"类目控件数: {result.get('controlCount', 1)}")
            print(f"选项数: {len(result.get('options', []))}")
            print()
            for opt in result.get("options", [])[:20]:
                print(f"  · {opt}")
            if len(result.get("options", [])) > 20:
                print(f"  ... 还有 {len(result['options']) - 20} 个")
        else:
            print(f"❌ {result.get('reason', '未找到类目') if result else '无结果'}")

    finally:
        cdp.close()


def action_write_category(cdp: CDPClient, tab: dict, category_path: str):
    """Write a category path via cascading selector."""
    print(f"\n{'='*60}")
    print(f"写入类目: {category_path}")
    print(f"{'='*60}")

    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        print("❌ 无法获取 WebSocket URL")
        return

    cdp.connect(ws_url)

    # Encode the category path for the expression
    escaped = json.dumps(category_path)

    expr = f"""
    (() => new Promise(async (resolve) => {{
      const norm = (v) => (v || "").replace(/\\s+/g, " ").trim();
      const sleep = (ms) => new Promise(d => setTimeout(d, ms));
      const visible = (el) => {{
        if (!el || !el.getBoundingClientRect) return false;
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;
      }};
      const click = (el) => {{
        el.scrollIntoView({{ block: "center" }});
        const r = el.getBoundingClientRect();
        ["mouseover","mousedown","mouseup","click"].forEach(t =>
          el.dispatchEvent(new MouseEvent(t, {{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}}))
        );
      }};

      const path = {escaped};
      const parts = path.split(/[>›/\\\\]+/).map(norm).filter(Boolean);
      if (!parts.length) {{
        resolve({{ ok: false, reason: "路径为空" }});
        return;
      }}

      // Find category field
      const cards = Array.from(document.querySelectorAll(".form-card")).filter(visible);
      const basicCard = cards.find(c => {{
        const t = norm(c.innerText || c.textContent);
        return t.includes("\\u57fa\\u672c\\u4fe1\\u606f");
      }});

      if (!basicCard) {{
        resolve({{ ok: false, reason: "未找到基本信息模块" }});
        return;
      }}

      // Find the category control
      const area = el => {{
        const r = el.getBoundingClientRect();
        return r.width * r.height;
      }};

      const candidates = Array.from(basicCard.querySelectorAll(".ant-form-item,.el-form-item,.form-item,.form-group,.form-row,li,tr,div"))
        .filter(visible)
        .filter(item => {{
          const t = norm(item.innerText || item.textContent);
          return /产品分类|产品类目|商品分类|商品类目|类目|category/i.test(t) &&
                 !/店铺名称|店铺名|shop name/i.test(t) &&
                 item.querySelector(".ant-select,.ant-cascader-picker,.el-cascader,.el-select,input");
        }})
        .sort((a, b) => area(a) - area(b));

      const categoryField = candidates[0];
      const categoryControl = categoryField?.querySelector(".ant-cascader-picker,.ant-select,.el-cascader,.el-select");

      if (!categoryControl) {{
        const labels = Array.from(basicCard.querySelectorAll(".ant-form-item,.el-form-item,.form-item,.form-group,tr"))
          .filter(visible)
          .map(i => norm(i.innerText || i.textContent).slice(0, 60))
          .filter(Boolean)
          .slice(0, 10);
        resolve({{ ok: false, reason: "未找到分类控件", labels }});
        return;
      }}

      // Click to open the cascader
      click(categoryControl.querySelector(".ant-select-selector,.el-input,input") || categoryControl);
      await sleep(700);

      // For each level, find and click the matching option
      const selected = [];
      for (const part of parts) {{
        const optionSel = ".ant-cascader-menu-item,.ant-select-item-option,.ant-select-dropdown-menu-item,.el-cascader-node,.el-select-dropdown__item,[role='option']";
        const options = Array.from(document.querySelectorAll(optionSel)).filter(visible);
        const optText = o => norm(o.innerText || o.textContent);
        const comparable = v => norm(v).replace(/[()（）]/g, " ").toLowerCase();

        let match = options.find(o => optText(o) === part);
        if (!match) {{
          match = options.find(o => {{
            const t = comparable(optText(o));
            const p = comparable(part);
            return t.includes(p) || p.includes(t);
          }});
        }}

        if (!match) {{
          const visibleOpts = options.map(optText).slice(0, 15);
          break;
        }}

        click(match);
        selected.push(optText(match));
        await sleep(800);
      }}

      await sleep(600);

      // Click OK button if present
      const okBtn = Array.from(document.querySelectorAll(".ant-modal button,.ant-popover button,.el-dialog button,button"))
        .filter(visible)
        .find(b => ["\\u786e\\u5b9a","\\u786e\\u8ba4","OK","\\u4fdd\\u5b58"].some(w => norm(b.innerText || b.textContent).includes(w)));
      if (okBtn && selected.length > 0) {{
        click(okBtn);
        await sleep(700);
      }}

      const currentValue = norm(categoryField?.innerText || categoryControl?.innerText || "");
      resolve({{
        ok: selected.length > 0,
        attemptedPath: parts,
        selectedPath: selected,
        currentValue,
        url: location.href
      }});
    }})())
    """

    try:
        result = cdp.evaluate(expr, await_promise=True)
        if result and result.get("ok"):
            print(f"✅ 类目写入成功")
            print(f"  目标路径: {result.get('attemptedPath', [])}")
            print(f"  已选择: {result.get('selectedPath', [])}")
            print(f"  当前值: {result.get('currentValue', '')}")
        else:
            reason = result.get("reason", "未知错误") if result else "无结果"
            print(f"❌ 写入失败: {reason}")
            if result and result.get("labels"):
                print(f"  可见字段: {result['labels']}")

    finally:
        cdp.close()


def action_full(cdp: CDPClient, tab: dict, category_path: str | None = None):
    """Full flow: scan dropdowns, optionally write category, rescan."""
    print(f"\n{'='*60}")
    print("完整测试流程")
    print(f"{'='*60}")

    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        print("❌ 无法获取 WebSocket URL")
        return

    cdp.connect(ws_url)

    try:
        # Step 1: Scan existing dropdowns
        print("\n[Step 1/3] 扫描当前页面下拉框...")
        scan_result = cdp.evaluate(DROPdown_SCAN_EXPRESSION, await_promise=True)
        groups = scan_result.get("groups", []) if scan_result else []

        # Show what we found
        for g in groups:
            key = g.get("fieldKey", "?")
            opts = g.get("options", [])
            print(f"  {key}: {len(opts)} 个选项 | 当前值: {g.get('currentValue', '空')[:40]}")

        # Check if category options were found
        cat_groups = [g for g in groups if g.get("fieldKey") == "category"]
        attr_groups = [g for g in groups if g.get("fieldKey") == "attributeTemplate"]

        if cat_groups:
            cat_opts = list(set(opt for g in cat_groups for opt in g.get("options", [])))
            print(f"\n  类目选项 ({len(cat_opts)} 个):")
            for opt in cat_opts[:10]:
                print(f"    · {opt}")
        else:
            print("\n  ⚠ 未找到类目下拉框选项")

        # Step 2: Write category if requested
        if category_path:
            print(f"\n[Step 2/3] 写入类目: {category_path}")

            # Need to reconnect because the previous evaluate might have left dropdowns open
            cdp.close()
            cdp.connect(ws_url)
            action_write_category(cdp, tab, category_path)
            cdp.close()
            cdp.connect(ws_url)

        # Step 3: Show attribute template status
        print(f"\n[Step 3/3] 属性模板选项状态:")
        if attr_groups:
            attr_opts = list(set(opt for g in attr_groups for opt in g.get("options", [])))
            print(f"  找到 {len(attr_opts)} 个属性模板选项:")
            for opt in attr_opts[:10]:
                print(f"    · {opt}")
        else:
            print("  ⚠ 未找到属性模板选项（可能类目未选择，或因类目选择后才能显示）")
            print("  提示: 先写入类目，然后重新扫描下拉框获取属性模板")

    finally:
        cdp.close()


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="店小秘下拉框扫描测试工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python test_dropdowns.py --action scan
  python test_dropdowns.py --action scan-category
  python test_dropdowns.py --action write-category --category "汽车及零配件 > 内外饰配件 > 汽车钥匙包"
  python test_dropdowns.py --action full
  python test_dropdowns.py --port 9223 --action scan
        """
    )
    parser.add_argument("--port", type=int, default=9222, help="Chrome 调试端口 (默认: 9222)")
    parser.add_argument(
        "--action",
        choices=["scan", "scan-category", "write-category", "full"],
        default="scan",
        help="执行的操作 (默认: scan)"
    )
    parser.add_argument("--category", type=str, help="要写入的类目路径")
    args = parser.parse_args()

    cdp = CDPClient(port=args.port)

    # Test connection
    print(f"连接 Chrome 调试端口 {args.port}...")
    try:
        tabs = cdp.list_tabs()
        print(f"  发现 {len(tabs)} 个标签页")
    except ConnectionError as e:
        print(f"\n❌ {e}")
        sys.exit(1)

    # Find the 店小秘 edit tab
    tab = cdp.find_dxm_edit_tab()
    if not tab:
        print("\n❌ 没有找到店小秘页面。请确认:")
        print("  1. Chrome 已以调试模式启动")
        print("  2. 已打开一个店小秘编辑页")
        sys.exit(1)

    print(f"  编辑页: {tab.get('title', 'unknown')[:60]}")

    # Execute the requested action
    if args.action == "scan":
        action_scan(cdp, tab)
    elif args.action == "scan-category":
        action_scan_category(cdp, tab)
    elif args.action == "write-category":
        if not args.category:
            print("❌ --action write-category 需要 --category 参数")
            sys.exit(1)
        action_write_category(cdp, tab, args.category)
    elif args.action == "full":
        action_full(cdp, tab, args.category)


if __name__ == "__main__":
    main()
