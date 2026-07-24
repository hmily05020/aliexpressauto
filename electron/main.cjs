const { app, BrowserWindow, Menu, ipcMain, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const isDev = !app.isPackaged;
const DEFAULT_CHROME_PORT = 9222;
const CHROME_PORT_CANDIDATES = [9222, 9223, 9224, 9225, 9333];
const SCANNER_VERSION = "0.1.15-repair-handlers";
let currentChromePort = DEFAULT_CHROME_PORT;

function appendAutomationLog(eventName, payload) {
  try {
    const logDir = path.join(app.getPath("userData"), "logs");
    fs.mkdirSync(logDir, { recursive: true });
    fs.appendFileSync(
      path.join(logDir, "automation.log"),
      `${new Date().toISOString()} ${eventName} ${JSON.stringify(payload)}\n`,
      "utf8"
    );
  } catch {
    // Logging must never block automation.
  }
}

function isDxmEditUrl(url = "") {
  return /dianxiaomi\.com/i.test(url) && /\/web\/smt\/.*edit|\/web\/smt\/edit|smtProduct.*edit/i.test(url);
}

async function fetchJson(url, timeoutMs = 3500) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

async function getChromeTabs(port = DEFAULT_CHROME_PORT) {
  return fetchJson(`http://127.0.0.1:${port}/json/list`);
}

async function getChromeConnection(port = DEFAULT_CHROME_PORT) {
  try {
    const version = await fetchJson(`http://127.0.0.1:${port}/json/version`);
    const tabs = await getChromeTabs(port);
    const editTab = await pickBestDxmEditTab(tabs);
    return {
      port,
      status: "connected",
      browser: version.Browser,
      activeUrl: editTab?.url ?? tabs.find((tab) => tab.type === "page")?.url ?? ""
    };
  } catch (error) {
    return {
      port,
      status: "disconnected",
      error: error instanceof Error ? error.message : String(error)
    };
  }
}

async function getAnyChromeConnection() {
  for (const port of [currentChromePort, ...CHROME_PORT_CANDIDATES]) {
    const connection = await getChromeConnection(port);
    if (connection.status === "connected") {
      currentChromePort = port;
      return connection;
    }
  }

  return getChromeConnection(currentChromePort);
}

async function waitForChromeConnection(port, attempts = 8) {
  for (let index = 0; index < attempts; index += 1) {
    const connection = await getChromeConnection(port);
    if (connection.status === "connected") {
      currentChromePort = port;
      return connection;
    }
    await new Promise((resolve) => setTimeout(resolve, 700));
  }

  return getChromeConnection(port);
}

async function getConnectedChromeTabs() {
  const connection = await getAnyChromeConnection();
  if (connection.status !== "connected") {
    throw new Error(
      `Chrome 调试端口未连接。请点击“启动专用调试 Chrome”，或确认 Windows 安全中心没有拦截本地调试进程。最后错误：${connection.error || "未知原因"}`
    );
  }

  return {
    port: connection.port,
    tabs: await getChromeTabs(connection.port)
  };
}

async function waitForDxmEditTab(port, timeoutMs = 20000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const tabs = await getChromeTabs(port);
    const editTab = await pickBestDxmEditTab(tabs);
    if (editTab) {
      return editTab;
    }
    await new Promise((resolve) => setTimeout(resolve, 600));
  }

  return null;
}

async function waitForDxmEditContent(tab, timeoutMs = 30000) {
  const startedAt = Date.now();
  let lastState = null;

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const state = await evaluateInTab(
        tab,
        `(() => {
          const norm = (value) => (value || "").replace(/\\s+/g, " ").trim();
          const cardTitles = Array.from(document.querySelectorAll(".form-card h4.form-card-title"))
            .map((el) => norm(el.innerText || el.textContent))
            .filter(Boolean);
          const productCard = Array.from(document.querySelectorAll(".form-card"))
            .find((card) => norm(card.querySelector("h4.form-card-title")?.innerText || "").includes("\\u4ea7\\u54c1\\u4fe1\\u606f"));
          if (productCard) {
            productCard.scrollIntoView({ block: "center", inline: "nearest" });
          }
          const productText = norm(productCard?.innerText || "");
          const productImageCount = productCard?.querySelectorAll("img").length || 0;
          const productInputCount = productCard?.querySelectorAll("input").length || 0;
          const productReady = productImageCount > 0 && productInputCount > 0 && ["A-", "C-", "D-", "\\u81ea\\u5b9a\\u4e49\\u540d\\u79f0", "\\u96f6\\u552e\\u4ef7"].some((word) => productText.includes(word));
          return {
            ready: cardTitles.length >= 5 && productReady,
            cardCount: cardTitles.length,
            productImageCount,
            productInputCount,
            title: document.title,
            url: location.href,
            cardTitles: cardTitles.slice(0, 12)
          };
        })()`
      );
      lastState = state;
      if (state?.ready) {
        return state;
      }
    } catch {
      // The edit page may still be replacing its app shell; retry until timeout.
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }

  throw new Error(
    `编辑页内容未加载完成，未检测到产品信息区。当前模块数：${lastState?.cardCount ?? 0}，产品图片数：${lastState?.productImageCount ?? 0}，输入框数：${lastState?.productInputCount ?? 0}`
  );
}

async function scoreDxmEditTab(tab) {
  try {
    const state = await evaluateInTab(
      tab,
      `(() => {
        const norm = (value) => (value || "").replace(/\\s+/g, " ").trim();
        const cards = Array.from(document.querySelectorAll(".form-card"));
        const productCard = cards.find((card) => norm(card.querySelector("h4.form-card-title")?.innerText || "").includes("\\u4ea7\\u54c1\\u4fe1\\u606f"));
        const productText = norm(productCard?.innerText || "");
        return {
          cardCount: document.querySelectorAll(".form-card h4.form-card-title").length,
          productImages: productCard?.querySelectorAll("img").length || 0,
          productInputs: productCard?.querySelectorAll("input").length || 0,
          hasSkuText: ["A-", "C-", "D-", "\\u81ea\\u5b9a\\u4e49\\u540d\\u79f0", "\\u96f6\\u552e\\u4ef7"].some((word) => productText.includes(word)),
          url: location.href
        };
      })()`
    );
    return {
      tab,
      state,
      score: (state?.cardCount || 0) * 10 + (state?.productImages || 0) * 3 + (state?.productInputs || 0) + (state?.hasSkuText ? 1000 : 0)
    };
  } catch {
    return { tab, state: null, score: -1 };
  }
}

async function pickBestDxmEditTab(tabs) {
  const editTabs = tabs.filter((tab) => tab.type === "page" && isDxmEditUrl(tab.url));
  if (!editTabs.length) return null;
  const scored = [];
  for (const tab of editTabs) {
    scored.push(await scoreDxmEditTab(tab));
  }
  scored.sort((a, b) => b.score - a.score);
  return scored[0]?.tab || editTabs[0];
}

function getChromeExecutablePath() {
  const candidates = [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    path.join(process.env.LOCALAPPDATA || "", "Google\\Chrome\\Application\\chrome.exe")
  ];

  return candidates.find((candidate) => candidate && fs.existsSync(candidate));
}

async function launchDebugChrome() {
  const chromePath = getChromeExecutablePath();

  if (!chromePath) {
    throw new Error("没有找到 Chrome，请确认已安装 Google Chrome。");
  }

  const existing = await getAnyChromeConnection();
  if (existing.status === "connected") {
    return existing;
  }

  const userDataDir = path.join(app.getPath("userData"), "debug-chrome-profile");
  fs.mkdirSync(userDataDir, { recursive: true });

  let lastConnection = existing;
  for (const port of CHROME_PORT_CANDIDATES) {
    const args = [
      `--remote-debugging-port=${port}`,
      "--remote-debugging-address=127.0.0.1",
      `--user-data-dir=${userDataDir}`,
      "--no-first-run",
      "--no-default-browser-check",
      "https://www.dianxiaomi.com/web/smt/smtProductList/draft"
    ];

    const child = spawn(chromePath, args, {
      detached: true,
      stdio: "ignore"
    });
    child.unref();

    lastConnection = await waitForChromeConnection(port);
    if (lastConnection.status === "connected") {
      return lastConnection;
    }
  }

  return {
    ...lastConnection,
    error: `${lastConnection.error || "Chrome 未开放调试端口"}。已尝试端口：${CHROME_PORT_CANDIDATES.join(", ")}`
  };
}

async function evaluateInTab(tab, expression) {
  if (typeof WebSocket === "undefined") {
    throw new Error("当前 Electron 运行时没有 WebSocket，无法连接 Chrome DevTools。");
  }

  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();

  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  });

  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });

  const send = (method, params = {}) =>
    new Promise((resolve) => {
      const messageId = ++id;
      pending.set(messageId, resolve);
      ws.send(JSON.stringify({ id: messageId, method, params }));
    });

  await send("Runtime.enable");
  const result = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true
  });

  ws.close();

  if (result.result?.exceptionDetails) {
    const details = result.result.exceptionDetails;
    const description = details.exception?.description || details.text || "页面脚本执行失败";
    throw new Error(`${description} at ${details.lineNumber ?? "?"}:${details.columnNumber ?? "?"}`);
  }

  return result.result?.result?.value;
}

async function dispatchMouseClick(tab, point) {
  if (!point || typeof point.x !== "number" || typeof point.y !== "number") {
    return;
  }

  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  let id = 0;
  const pending = new Map();

  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  });

  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", reject, { once: true });
  });

  const send = (method, params = {}) =>
    new Promise((resolve) => {
      const messageId = ++id;
      pending.set(messageId, resolve);
      ws.send(JSON.stringify({ id: messageId, method, params }));
    });

  await send("Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x: point.x,
    y: point.y,
    button: "none"
  });
  await send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: point.x,
    y: point.y,
    button: "left",
    clickCount: 1
  });
  await send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: point.x,
    y: point.y,
    button: "left",
    clickCount: 1
  });

  ws.close();
}

function registerAutomationIpc() {
  ipcMain.handle("chrome:getStatus", async () => getAnyChromeConnection());
  ipcMain.handle("chrome:launchDebug", async () => launchDebugChrome());

  ipcMain.handle("chrome:scanProductList", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const listTab =
      tabs.find((tab) => tab.type === "page" && /smtProductList|collect|draft|productList/i.test(tab.url)) ||
      tabs.find((tab) => tab.type === "page" && /dianxiaomi\.com\/web\/smt/i.test(tab.url) && !/\/edit/.test(tab.url));

    if (!listTab) {
      throw new Error("没有找到店小秘商品列表页。请打开采集箱/待发布/草稿列表页后再扫描。");
    }

      const expression = `(() => {
      const SCANNER_VERSION = "${SCANNER_VERSION}";
      const norm = (value) => (value || "").replace(/\\s+/g, " ").trim();
      const abs = (url) => {
        try { return new URL(url, location.href).href; } catch { return url || ""; }
      };
      const visible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const uniq = (items) => Array.from(new Set(items.filter(Boolean)));
      const visibleButtons = uniq(Array.from(document.querySelectorAll("button,a"))
        .filter(visible)
        .map((el) => norm(el.innerText || el.textContent))
        .filter((text) => text.length > 0 && text.length < 40));

      const rowCandidates = Array.from(document.querySelectorAll(".vxe-body--row,.ant-table-row,.el-table__row,tr"))
        .filter(visible)
        .filter((row) => {
          const text = norm(row.innerText || row.textContent);
          return text.length > 20 && ["\\u7f16\\u8f91", "Edit"].some((word) => text.includes(word)) && ["1688", "AliExpress", "\\u901f\\u5356\\u901a", "\\u79fb\\u5165\\u5f85\\u53d1\\u5e03", "\\u53d1\\u5e03"].some((word) => text.includes(word));
        });

      const seen = new Set();
      const tasks = [];
      for (const row of rowCandidates) {
        const text = norm(row.innerText || row.textContent);
        const img = Array.from(row.querySelectorAll("img")).find((item) => {
          const src = item.currentSrc || item.src || item.getAttribute("data-src") || "";
          return src && !src.startsWith("data:") && !src.includes("favicon") && !src.includes("addImg-");
        });
        const imageUrl = abs(img?.currentSrc || img?.src || img?.getAttribute("data-src") || "");
        const links = Array.from(row.querySelectorAll("a,button")).map((el) => norm(el.innerText || el.textContent)).filter(Boolean);
        const editText = links.find((item) => ["\\u7f16\\u8f91", "Edit"].some((word) => item.includes(word))) || "";
        const idMatch = text.match(/\\b\\d{8,}\\b/);
        const titleCandidates = Array.from(row.querySelectorAll("a,span,div,p"))
          .map((el) => norm(el.getAttribute("title") || el.innerText || el.textContent))
          .filter((value) => value.length >= 8 && value.length <= 180)
          .filter((value) => !["\\u7f16\\u8f91", "\\u5220\\u9664", "\\u590d\\u5236", "\\u53d1\\u5e03", "\\u540c\\u6b65", "\\u68c0\\u6d4b", "\\u8be6\\u60c5", "\\u64cd\\u4f5c"].some((word) => value.includes(word)));
        const title = titleCandidates.sort((a, b) => b.length - a.length)[0] || text.slice(0, 120);
        const statusMatch = text.match(/(待发布|草稿|采集箱|未发布|发布失败|已发布|审核中|下架|在线|编辑中)/);
        const id = idMatch ? idMatch[0] : String(tasks.length + 1) + "-" + title.slice(0, 20);
        const key = id + "-" + title;
        if (seen.has(key)) continue;
        seen.add(key);
        tasks.push({
          id,
          title,
          imageUrl,
          status: statusMatch ? statusMatch[1] : "",
          source: text.includes("1688") ? "1688" : (text.includes("\\u901f\\u5356\\u901a") || /AliExpress/i.test(text)) ? "AliExpress" : "",
          editText,
          rowIndex: tasks.length
        });
        if (tasks.length >= 50) break;
      }

      return {
        url: location.href,
        title: document.title,
        tasks,
        visibleButtons,
        totalRows: rowCandidates.length
      };
    })()`;

    return evaluateInTab(listTab, expression);
  });

  ipcMain.handle("chrome:openTaskEditor", async (_event, rowIndex) => {
    const { tabs, port } = await getConnectedChromeTabs();
    const listTab =
      tabs.find((tab) => tab.type === "page" && /smtProductList|collect|draft|productList/i.test(tab.url)) ||
      tabs.find((tab) => tab.type === "page" && /dianxiaomi\.com\/web\/smt/i.test(tab.url) && !/\/edit/.test(tab.url));

    if (!listTab) {
      throw new Error("没有找到店小秘商品列表页，无法打开编辑。");
    }

    const expression = `(() => {
      const norm = (value) => (value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const rowCandidates = Array.from(document.querySelectorAll(".vxe-body--row,.ant-table-row,.el-table__row,tr"))
        .filter(visible)
        .filter((row) => {
          const text = norm(row.innerText || row.textContent);
          return text.length > 20 && ["\\u7f16\\u8f91", "Edit"].some((word) => text.includes(word)) && ["1688", "AliExpress", "\\u901f\\u5356\\u901a", "\\u79fb\\u5165\\u5f85\\u53d1\\u5e03", "\\u53d1\\u5e03"].some((word) => text.includes(word));
        });
      const row = rowCandidates[${Number(rowIndex) || 0}];
      if (!row) return { ok: false, reason: "未找到对应商品行" };
      const actions = Array.from(row.querySelectorAll("a,button,[role=button],span.link")).filter(visible);
      const editAction = actions.find((el) => ["\\u7f16\\u8f91", "Edit"].some((word) => norm(el.innerText || el.textContent).includes(word))) || actions.find((el) => /edit/i.test(el.href || el.getAttribute("class") || ""));
      if (!editAction) {
        return { ok: false, reason: "该行未找到编辑按钮" };
      }
      editAction.scrollIntoView({ block: "center", inline: "center" });
      const rect = editAction.getBoundingClientRect();
      return {
        ok: true,
        text: norm(editAction.innerText || editAction.textContent || "编辑"),
        clickPoint: {
          x: Math.round(rect.left + rect.width / 2),
          y: Math.round(rect.top + rect.height / 2)
        }
      };
    })()`;

    const result = await evaluateInTab(listTab, expression);
    if (!result?.ok) {
      throw new Error(result?.reason || "打开编辑页失败");
    }
    await dispatchMouseClick(listTab, result.clickPoint);
    const editTab = await waitForDxmEditTab(port);
    if (editTab) {
      await waitForDxmEditContent(editTab);
    }
    return {
      ...result,
      url: editTab?.url || "",
      editPageReady: Boolean(editTab)
    };
  });

  ipcMain.handle("chrome:scanEditPage", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);

    if (!editTab) {
      throw new Error("没有找到店小秘编辑页。请用远程调试模式打开 Chrome，并进入店小秘商品编辑页。");
    }
    await waitForDxmEditContent(editTab);

    const expression = `(() => {
      const norm = (value) => (value || "").replace(/\\s+/g, " ").trim();
      const uniq = (items) => Array.from(new Set(items.filter(Boolean)));
      const visible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const abs = (url) => {
        try { return new URL(url, location.href).href; } catch { return url || ""; }
      };
      const moduleOrder = [
        "\\u57fa\\u672c\\u4fe1\\u606f",
        "\\u5e97\\u5c0f\\u79d8\\u4fe1\\u606f",
        "\\u5c5e\\u6027\\u4fe1\\u606f",
        "\\u4ea7\\u54c1\\u4fe1\\u606f",
        "\\u533a\\u57df\\u8c03\\u4ef7\\u4fe1\\u606f",
        "\\u63cf\\u8ff0\\u4fe1\\u606f",
        "\\u5305\\u88c5\\u4fe1\\u606f",
        "\\u6a21\\u677f\\u4fe1\\u606f",
        "\\u5176\\u4ed6\\u4fe1\\u606f"
      ];
      const normalizeModuleName = (text) => {
        const value = norm(text).replace(/\\uff08.*?\\uff09|\\(.*?\\)/g, "");
        if (value.includes("\\u57fa\\u672c\\u4fe1\\u606f")) return "\\u57fa\\u672c\\u4fe1\\u606f";
        if (value.includes("\\u5e97\\u5c0f\\u79d8\\u4fe1\\u606f")) return "\\u5e97\\u5c0f\\u79d8\\u4fe1\\u606f";
        if (value.includes("\\u5c5e\\u6027\\u4fe1\\u606f")) return "\\u5c5e\\u6027\\u4fe1\\u606f";
        if (value.includes("\\u4ea7\\u54c1\\u4fe1\\u606f")) return "\\u4ea7\\u54c1\\u4fe1\\u606f";
        if (value.includes("\\u533a\\u57df\\u8c03\\u4ef7\\u4fe1\\u606f")) return "\\u533a\\u57df\\u8c03\\u4ef7\\u4fe1\\u606f";
        if (value.includes("\\u63cf\\u8ff0\\u4fe1\\u606f")) return "\\u63cf\\u8ff0\\u4fe1\\u606f";
        if (value.includes("\\u5305\\u88c5\\u4fe1\\u606f")) return "\\u5305\\u88c5\\u4fe1\\u606f";
        if (value.includes("\\u6a21\\u677f\\u4fe1\\u606f") || value.includes("\\u6a21\\u7248\\u4fe1\\u606f")) return "\\u6a21\\u677f\\u4fe1\\u606f";
        if (value.includes("\\u5176\\u4ed6\\u4fe1\\u606f")) return "\\u5176\\u4ed6\\u4fe1\\u606f";
        return "";
      };
      const cards = Array.from(document.querySelectorAll(".form-card"))
        .filter(visible)
        .map((card) => {
          const title = normalizeModuleName(card.querySelector("h4.form-card-title")?.innerText || card.innerText || "");
          return { title, card };
        })
        .filter((item) => item.title);
      const cardMap = new Map(cards.map((item) => [item.title, item.card]));
      const cardOf = (name) => cardMap.get(name) || null;
      const cardByTitle = (name) => {
        const exact = Array.from(document.querySelectorAll("h4.form-card-title"))
          .find((title) => normalizeModuleName(title.innerText || title.textContent) === name)
          ?.closest(".form-card");
        if (exact) return exact;
        return Array.from(document.querySelectorAll(".form-card"))
          .find((card) => normalizeModuleName(card.querySelector("h4.form-card-title")?.innerText || card.innerText || "") === name) || null;
      };
      const moduleOf = (el) => normalizeModuleName(el.closest(".form-card")?.querySelector("h4.form-card-title")?.innerText || "");
      const buttonTexts = uniq(Array.from(document.querySelectorAll("button,a,.link,[role=button]"))
        .filter(visible)
        .map((el) => norm(el.innerText || el.textContent))
        .filter((text) => text.length > 0 && text.length < 40));

      const basicCard = cardByTitle("\\u57fa\\u672c\\u4fe1\\u606f") || cardOf("\\u57fa\\u672c\\u4fe1\\u606f");
      const dxmCard = cardByTitle("\\u5e97\\u5c0f\\u79d8\\u4fe1\\u606f") || cardOf("\\u5e97\\u5c0f\\u79d8\\u4fe1\\u606f");
      const productCard =
        cardByTitle("\\u4ea7\\u54c1\\u4fe1\\u606f") ||
        cardOf("\\u4ea7\\u54c1\\u4fe1\\u606f") ||
        Array.from(document.querySelectorAll(".form-card")).find((card) => {
          const text = norm(card.innerText || card.textContent);
          return text.includes("\\u4ea7\\u54c1\\u56fe\\u7247") || text.includes("\\u96f6\\u552e\\u4ef7") || text.includes("\\u81ea\\u5b9a\\u4e49\\u540d\\u79f0");
        }) ||
        null;
      const describeCard = cardByTitle("\\u63cf\\u8ff0\\u4fe1\\u606f") || cardOf("\\u63cf\\u8ff0\\u4fe1\\u606f");
      const basicText = norm(basicCard?.innerText || "");
      const titleInput = Array.from(basicCard?.querySelectorAll("input") || [])
        .filter((input) => input.type !== "hidden" && input.type !== "search")
        .find((input) => norm(input.value).length > 12);
      const originalTitle = norm(titleInput?.value || "");
      const categoryValue = norm(basicCard?.querySelector(".ant-select-selection-item")?.innerText || "");
      const categoryPathMatch = basicText.match(/(?:\\u5bb6\\u5c45\\u7528\\u54c1|\\u6c7d\\u8f66\\u53ca\\u96f6\\u914d\\u4ef6|\\u624b\\u673a\\u901a\\u8baf\\u914d\\u4ef6|\\u7f8e\\u5bb9\\u5065\\u5eb7|\\u7535\\u8111\\u548c\\u529e\\u516c)[\\s\\S]{0,240}/);
      const categoryPath = norm(categoryPathMatch ? categoryPathMatch[0] : categoryValue);
      const sourceUrl = norm(dxmCard?.querySelector("input[name='sourceUrl']")?.value || dxmCard?.querySelector("input")?.value || "");

      const imageInfo = (img) => {
        const src = abs(img.currentSrc || img.src || img.getAttribute("data-src") || "");
        const rect = img.getBoundingClientRect();
        return {
          src,
          naturalW: img.naturalWidth || 0,
          naturalH: img.naturalHeight || 0,
          w: Math.round(rect.width),
          h: Math.round(rect.height)
        };
      };
      const isRealProductImage = (info) => info.src && !info.src.includes("addImg-") && !info.src.startsWith("data:");
      const productImages = uniq(Array.from(productCard?.querySelectorAll("img") || [])
        .map(imageInfo)
        .filter(isRealProductImage)
        .map((info) => JSON.stringify(info)))
        .map((item) => JSON.parse(item));
      const selectedCountMatch = norm(productCard?.innerText || "").match(/\\u5df2\\u7ecf\\u9009\\u7528\\u4e86\\s*(\\d+)\\s*\\u5f20/);
      const selectedMainCount = selectedCountMatch ? Number(selectedCountMatch[1]) : 6;
      const mainImages = productImages
        .filter((info) => info.w >= 90 && info.h >= 90 && info.naturalW >= 700 && info.naturalH >= 700)
        .slice(0, selectedMainCount)
        .map((info) => info.src);
      const mainImageFallback = productImages
        .filter((info) => info.naturalW >= 700 && info.naturalH >= 700)
        .slice(0, selectedMainCount)
        .map((info) => info.src);

      const describeImages = Array.from(describeCard?.querySelectorAll("img") || [])
        .filter(visible)
        .map(imageInfo)
        .filter(isRealProductImage)
        .map((info) => info.src);
      const frameImages = Array.from(document.querySelectorAll("iframe"))
        .flatMap((frame) => {
          try {
            return Array.from(frame.contentDocument?.querySelectorAll("img") || []).map(imageInfo).filter(isRealProductImage).map((info) => info.src);
          } catch {
            return [];
          }
        });
      const productDetailFallback = productImages.slice(mainImages.length).map((info) => info.src);
      const detailImages = uniq([...describeImages, ...frameImages, ...productDetailFallback]).slice(0, 20);

      const productText = norm(productCard?.innerText || "");
      const skuFromPairs = Array.from(productText.matchAll(/[\\(\\uff08]([^\\)\\uff09\\n]{1,40})[\\)\\uff09]/g)).map((match) => norm(match[1]));
      const skuFromInputs = Array.from(productCard?.querySelectorAll("input[type='text']") || [])
        .map((input) => norm(input.value))
        .filter((value) => value && value.length <= 40 && !/^\\d+(\\.\\d+)?$/.test(value) && !/^https?:/.test(value));
      const skuFallbackInputs = Array.from(document.querySelectorAll("input[type='text']"))
        .map((input) => norm(input.value))
        .filter((value) => value && value.length <= 40 && !/^\\d+(\\.\\d+)?$/.test(value) && !/^https?:/.test(value));
      const skuNames = uniq([...skuFromPairs, ...skuFromInputs, ...skuFallbackInputs])
        .filter((value) => /[A-Za-z0-9]-|\\u6309\\u952e|\\u9ed1|\\u767d|\\u8272/.test(value))
        .filter((value) => !/^\\d+\\s*:\\s*\\d+/.test(value) && !/\\u767d\\u5e95\\u56fe|\\u573a\\u666f\\u56fe/.test(value))
        .filter((value) => !value.includes(",") && value !== "\\u989c\\u8272\\u5206\\u7c7b")
        .slice(0, 30);
      const finalMainImages = mainImages.length ? mainImages : mainImageFallback;
      const priceFromInputs = Array.from(productCard?.querySelectorAll("input[type='text'],input[type='number']") || [])
        .map((input) => Number(norm(input.value)))
        .filter((value) => Number.isFinite(value) && value > 0 && value < 100000);
      const priceFromText = Array.from(productText.matchAll(/[\\(\\uff08][^\\)\\uff09]{1,40}[\\)\\uff09]\\s*(\\d+(?:\\.\\d+)?)/g)).map((match) => Number(match[1]));
      const priceCny = priceFromInputs[0] || priceFromText.find((value) => value > 0) || 0;
      if (moduleOrder.filter((name) => cardMap.has(name)).length >= 5 && (!productImages.length || !skuNames.length)) {
        throw new Error("\\u4ea7\\u54c1\\u4fe1\\u606f\\u672a\\u5b8c\\u6574\\u52a0\\u8f7d: images=" + productImages.length + ", sku=" + skuNames.length + ", inputs=" + (productCard?.querySelectorAll("input").length || 0));
      }

      const dropdowns = Array.from(document.querySelectorAll(".ant-select"))
        .filter(visible)
        .map((el) => ({
          module: moduleOf(el),
          label: norm(el.closest(".ant-form-item,tr,.form-card-header")?.innerText || "").slice(0, 120),
          currentValue: norm(el.querySelector(".ant-select-selection-item,.ant-select-selection-placeholder")?.innerText || el.innerText || "")
        }))
        .filter((item) => item.currentValue)
        .slice(0, 120);

      const redTextErrors = uniq(Array.from(document.querySelectorAll(".ant-form-item-explain-error,.error,.text-red,.f-red,[class*=error]"))
        .filter(visible)
        .map((el) => norm(el.innerText || el.textContent))
        .filter((text) => text && text.length < 180 && !/^\\*$/.test(text))
        .filter((text) => !moduleOrder.includes(normalizeModuleName(text)))
        .filter((text) => !/^\\d+$/.test(text)))
        .map((message) => ({ severity: "P1", field: "page", message }));

      const productId = new URLSearchParams(location.search).get("id") || "";

      return {
        product: {
          productId,
          sourceUrl,
          originalTitle,
          optimizedTitle: "",
          categoryPath,
          mainImages: finalMainImages,
          detailImages,
          skuNames,
          priceCny,
          validationErrors: redTextErrors
        },
        modules: moduleOrder.filter((name) => cardMap.has(name)),
        visibleButtons: buttonTexts,
        dropdowns,
        redTextErrors,
        scanDebug: {
          scannerVersion: "${SCANNER_VERSION}",
          url: location.href,
          productCardFound: Boolean(productCard),
          productImageCandidates: productImages.length,
          mainImageCandidates: finalMainImages.length,
          productInputCount: productCard?.querySelectorAll("input").length || 0,
          skuCandidates: skuNames.length
        }
      };
    })()`;

    try {
      const scanResult = await evaluateInTab(editTab, expression);
      appendAutomationLog("scanEditPage.success", {
        scannerVersion: scanResult?.scanDebug?.scannerVersion,
        url: scanResult?.scanDebug?.url,
        modules: scanResult?.modules?.length || 0,
        mainImages: scanResult?.product?.mainImages?.length || 0,
        detailImages: scanResult?.product?.detailImages?.length || 0,
        skuNames: scanResult?.product?.skuNames || [],
        priceCny: scanResult?.product?.priceCny || 0,
        scanDebug: scanResult?.scanDebug
      });
      return scanResult;
    } catch (error) {
      appendAutomationLog("scanEditPage.failed", {
        message: error instanceof Error ? error.message : String(error),
        url: editTab.url
      });
      throw error;
    }
  });

  ipcMain.handle("chrome:writeBasicInfo", async (_event, payload) => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);

    if (!editTab) {
      throw new Error("没有找到店小秘编辑页，无法写入基本信息。");
    }
    await waitForDxmEditContent(editTab);

    const payloadBase64 = Buffer.from(JSON.stringify(payload || {}), "utf8").toString("base64");
    const expression = `(() => {
      const payload = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob("${payloadBase64}"), (char) => char.charCodeAt(0))));
      const norm = (value) => (value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const normalizeModuleName = (text) => {
        const value = norm(text).replace(/\\uff08.*?\\uff09|\\(.*?\\)/g, "");
        if (value.includes("\\u57fa\\u672c\\u4fe1\\u606f")) return "\\u57fa\\u672c\\u4fe1\\u606f";
        if (value.includes("\\u4ea7\\u54c1\\u4fe1\\u606f")) return "\\u4ea7\\u54c1\\u4fe1\\u606f";
        return "";
      };
      const cardByTitle = (name) => {
        const exact = Array.from(document.querySelectorAll("h4.form-card-title"))
          .find((title) => normalizeModuleName(title.innerText || title.textContent) === name)
          ?.closest(".form-card");
        if (exact) return exact;
        return Array.from(document.querySelectorAll(".form-card"))
          .find((card) => normalizeModuleName(card.querySelector("h4.form-card-title")?.innerText || card.innerText || "") === name) || null;
      };
      const setInputValue = (input, value) => {
        input.scrollIntoView({ block: "center", inline: "nearest" });
        input.focus();
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        if (setter) {
          setter.call(input, value);
        } else {
          input.value = value;
        }
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        input.blur();
      };
      const warnings = [];
      const skipped = [];
      const basicCard = cardByTitle("\\u57fa\\u672c\\u4fe1\\u606f");
      const productCard = cardByTitle("\\u4ea7\\u54c1\\u4fe1\\u606f");

      let titleWritten = false;
      if (payload.optimizedTitle && basicCard) {
        const titleInputs = Array.from(basicCard.querySelectorAll("input"))
          .filter((input) => visible(input) && input.type !== "hidden" && input.type !== "search" && input.type !== "checkbox" && input.type !== "radio");
        const titleInput =
          titleInputs.find((input) => norm(input.value).length > 12) ||
          titleInputs.sort((a, b) => norm(b.value).length - norm(a.value).length)[0];
        if (titleInput) {
          setInputValue(titleInput, payload.optimizedTitle);
          titleWritten = true;
        } else {
          warnings.push("基本信息模块未找到标题输入框");
        }
      } else if (!basicCard) {
        warnings.push("未找到基本信息模块");
      }

      const skuPayload = Array.isArray(payload.skuNames) ? payload.skuNames : [];
      let skuWritten = 0;
      if (skuPayload.length && productCard) {
        const skuInputs = Array.from(productCard.querySelectorAll("input[type='text'],input:not([type])"))
          .filter((input) => visible(input))
          .filter((input) => {
            const value = norm(input.value);
            if (!value) return false;
            if (/^https?:/i.test(value)) return false;
            if (/^\\d+(\\.\\d+)?$/.test(value)) return false;
            if (/^\\d+\\s*[:：]\\s*\\d+/.test(value)) return false;
            if (value.length > 40) return false;
            return /[A-Za-z0-9]-|\\u6309\\u952e|\\u9ed1|\\u767d|\\u8272|Black|White|Gray|Green|Yellow|Red|Blue|Pink/i.test(value);
          });
        const used = new Set();
        const same = (left, right) => norm(left).toLowerCase() === norm(right).toLowerCase();

        for (let index = 0; index < skuPayload.length; index += 1) {
          const item = skuPayload[index];
          let inputIndex = skuInputs.findIndex((input, candidateIndex) => !used.has(candidateIndex) && same(input.value, item.original));
          if (inputIndex < 0) {
            inputIndex = skuInputs.findIndex((input, candidateIndex) => !used.has(candidateIndex) && norm(input.value).includes(norm(item.original)));
          }
          if (inputIndex < 0 && skuInputs.length === skuPayload.length) {
            inputIndex = index;
          }
          const input = skuInputs[inputIndex];
          if (input) {
            setInputValue(input, item.suggested);
            used.add(inputIndex);
            skuWritten += 1;
          }
        }

        if (skuWritten < skuPayload.length) {
          warnings.push("部分 SKU 自定义名称输入框未匹配到，已跳过未匹配项");
        }
      } else if (skuPayload.length && !productCard) {
        warnings.push("未找到产品信息模块，无法写入 SKU");
      }

      if (payload.categoryPath) {
        skipped.push("类目暂未自动写入：类目下拉存在级联选择，下一步单独做自动选择和回读校验");
      }

      return {
        ok: titleWritten || skuWritten > 0,
        titleWritten,
        skuWritten,
        skuTotal: skuPayload.length,
        skipped,
        warnings,
        url: location.href
      };
    })()`;

    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("writeBasicInfo.result", result);
    return result;
  });

  
  // === writeCategory (overwrites original) ===
  ipcMain.handle("chrome:writeCategory", async (_event, payload) => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页，无法写入类目。");
    await waitForDxmEditContent(editTab);

    const payloadBase64 = Buffer.from(JSON.stringify(payload || {}), "utf8").toString("base64");
    const expression = `(() => new Promise(async (resolve) => {
      const norm = (v) => (v || "").replace(/\\s+/g, " ").trim();
      const sleep = (ms) => new Promise((d) => setTimeout(d, ms));
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
        ["mouseover","mousedown","mouseup","click"].forEach(t => el.dispatchEvent(new MouseEvent(t, init)));
      };

      const warnings = [];
      const selectedPath = [];
      const catPath = norm(payload.categoryPath || "");
      const parts = catPath.split(/[>\u203a\/\\\\]+/).filter(Boolean).map(norm);
      const leaf = parts[parts.length - 1] || "";

      if (!parts.length) {
        resolve({ ok: false, attemptedPath: [], selectedPath, currentValue: "", warnings: ["路径为空"], url: location.href });
        return;
      }

      // Find 基本信息 card
      const cards = Array.from(document.querySelectorAll(".form-card")).filter(visible);
      const basicCard = cards.find(c => {
        const t = norm(c.querySelector("h4")?.innerText || c.innerText || "");
        return t.includes("基本信息");
      });
      if (!basicCard) {
        resolve({ ok: false, attemptedPath: parts, selectedPath, currentValue: "", warnings: ["未找到基本信息模块"], url: location.href });
        return;
      }

      // Find 产品分类 form item
      const formItems = Array.from(basicCard.querySelectorAll(".ant-form-item,.el-form-item,.form-item,.form-group,.form-row,tr,li")).filter(visible);
      const catItem = formItems.find(item => {
        const t = norm(item.innerText || item.textContent || "");
        return /产品分类|产品类目|商品分类|商品类目/.test(t) && item.querySelector(".ant-select");
      });
      if (!catItem) {
        resolve({ ok: false, attemptedPath: parts, selectedPath, currentValue: "", warnings: ["未找到产品分类控件"], url: location.href });
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
        resolve({ ok: false, attemptedPath: parts, selectedPath, currentValue: "", warnings: ["下拉框未打开"], url: location.href });
        return;
      }

      // Scroll virtual list to find leaf category
      let foundOption = null;
      const holder = dropdown.querySelector(".rc-virtual-list-holder");
      if (holder) {
        holder.scrollTop = 0; await sleep(100);
        let lastTop = -1;
        for (let s = 0; s < 40; s++) {
          if (holder.scrollTop === lastTop) break;
          lastTop = holder.scrollTop;
          const opts = Array.from(dropdown.querySelectorAll(".ant-select-item-option,[role=option]")).filter(visible);
          foundOption = opts.find(o => {
            const t = norm(o.innerText || o.textContent);
            const cmp = norm(t).replace(/[()\uff08\uff09]/g, " ").toLowerCase();
            const cmpL = norm(leaf).replace(/[()\uff08\uff09]/g, " ").toLowerCase();
            return t === leaf || cmp.indexOf(cmpL) >= 0 || cmpL.indexOf(cmp) >= 0 || t.indexOf(leaf.substring(0,4)) >= 0;
          });
          if (foundOption) break;
          holder.scrollTop = Math.min(holder.scrollHeight, holder.scrollTop + Math.max(60, Math.floor(holder.clientHeight * 0.8)));
          await sleep(80);
        }
      } else {
        const opts = Array.from(dropdown.querySelectorAll(".ant-select-item-option,[role=option]")).filter(visible);
        foundOption = opts.find(o => {
          const t = norm(o.innerText || o.textContent);
          const cmp = norm(t).replace(/[()\uff08\uff09]/g, " ").toLowerCase();
          const cmpL = norm(leaf).replace(/[()\uff08\uff09]/g, " ").toLowerCase();
          return t === leaf || cmp.indexOf(cmpL) >= 0 || cmpL.indexOf(cmp) >= 0;
        });
      }

      if (foundOption) {
        clickEl(foundOption);
        selectedPath.push(leaf);
        await sleep(500);
      } else {
        const vOpts = Array.from(dropdown.querySelectorAll(".ant-select-item-option,[role=option]")).filter(visible).map(o => norm(o.innerText || o.textContent)).filter(Boolean).slice(0,25);
        warnings.push("未找到类目[" + leaf + "]，可见：" + vOpts.join(" | "));
      }

      const currentValue = norm(catItem.querySelector(".ant-select-selection-item")?.innerText || "");
      resolve({ ok: selectedPath.length > 0, attemptedPath: parts, selectedPath, currentValue, warnings, url: location.href });
    }))()`;

    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("writeCategory.result", result);

    // Auto-scan attribute template after category write
    let attributeTemplateOptions = [];
    if (result?.ok) {
      try {
        const attrExpr = `(() => new Promise(async (resolve) => {
          const norm = (v) => (v || "").replace(/\\s+/g, " ").trim();
          const sleep = (ms) => new Promise((d) => setTimeout(d, ms));
          const visible = (el) => {
            if (!el || !el.getBoundingClientRect) return false;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0;
          };
          const clickEl = (el) => {
            if (!el) return;
            el.scrollIntoView({ block: "center" });
            const r = el.getBoundingClientRect();
            const init = { bubbles: true, cancelable: true, view: window, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
            ["mouseover","mousedown","mouseup","click"].forEach(t => el.dispatchEvent(new MouseEvent(t, init)));
          };
          const uniq = (a) => [...new Set(a.filter(Boolean))];
          const closeDD = async () => { document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",code:"Escape",bubbles:true})); await sleep(150); };
          const moduleOf = (el) => { const t = norm(el.closest(".form-card")?.querySelector("h4")?.innerText || "").replace(/[\uff08\uff09].*|[()].*/g,""); if(t.includes("属性信息"))return"属性信息"; return""; };

          await sleep(1500);
          const controls = Array.from(document.querySelectorAll(".ant-select")).filter(visible).slice(0,30);
          const options = [];
          for (const ctrl of controls) {
            const mod = moduleOf(ctrl);
            const lbl = norm(ctrl.closest(".ant-form-item")?.querySelector("label")?.innerText || "");
            const isAT = mod.includes("属性信息") && /引用模板|属性模板/.test(lbl);
            if (!isAT) continue;
            try {
              clickEl(ctrl.querySelector(".ant-select-selector") || ctrl);
              await sleep(500);
              const allOpts = uniq(Array.from(document.querySelectorAll(".ant-select-item-option,[role=option]")).filter(visible).map(o=>norm(o.innerText||o.textContent)).filter(t=>t&&t.length<=120));
              options.push(...allOpts);
              await closeDD();
            } catch(e) { await closeDD(); }
          }
          resolve({ fieldKey: "attributeTemplate", options: uniq(options).slice(0,80) });
        }))()`;
        const attrResult = await evaluateInTab(editTab, attrExpr);
        attributeTemplateOptions = attrResult?.options || [];
      } catch (attrError) {}
    }
    return { ...result, attributeTemplateOptions };
  });

  // Generic dropdown writer
  ipcMain.handle("chrome:writeDropdownOption", async (_event, fieldKey, value) => {
    if (!fieldKey || !value) throw new Error("fieldKey and value are required");
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const payloadBase64 = Buffer.from(JSON.stringify({ fieldKey, value }), "utf8").toString("base64");
    const expression = `(() => new Promise(async (resolve) => {
      const p = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob("${payloadBase64}"), (c) => c.charCodeAt(0))));
      const n = (v) => (v||"").replace(/\\s+/g," ").trim();
      const slp = (ms) => new Promise(d=>setTimeout(d,ms));
      const vis = (el) => {
        if(!el||!el.getBoundingClientRect)return false;
        const r=el.getBoundingClientRect();
        const s=getComputedStyle(el);
        return s.display!=="none"&&s.visibility!=="hidden"&&r.width>0&&r.height>0;
      };
      const clk = (el) => {
        if(!el)return;el.scrollIntoView({block:"center"});
        const r=el.getBoundingClientRect();
        ["mouseover","mousedown","mouseup","click"].forEach(t=>el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2})));
      };
      const normMod = (t) => {
        const v=n(t).replace(/[\\uff08\\uff09].*|[()].*/g,"");
        if(v.includes("\\u57fa\\u672c\\u4fe1\\u606f"))return"basic";
        if(v.includes("\\u5c5e\\u6027\\u4fe1\\u606f"))return"attr";
        if(v.includes("\\u6a21\\u677f\\u4fe1\\u606f")||v.includes("\\u6a21\\u7248\\u4fe1\\u606f"))return"tmpl";
        if(v.includes("\\u5176\\u4ed6\\u4fe1\\u606f"))return"other";
        return"";
      };
      const moduleOf = (el) => normMod(el.closest(".form-card")?.querySelector("h4")?.innerText||"");
      const labelOf = (el) => {
        const c = el.closest(".ant-form-item,.el-form-item,.form-item,.form-group,tr,li") || el.parentElement;
        return n(c?.querySelector("label,.ant-form-item-label,.el-form-item__label")?.innerText||"");
      };
      const classify = (ctrl,lbl,mod) => {
        const ll=n(lbl).toLowerCase(),ml=mod.toLowerCase();
        if(/店铺名称|店铺名|shop.?name/.test(ll))return"skip";
        if((ml==="basic"||!ml)&&(/产品类目|产品分类|商品类目|商品分类|所属类目|类目路径|选择类目/.test(ll)))return"category";
        if(ml==="attr"&&/引用模板|请选择引用模板|属性模板/.test(ll))return"attributeTemplate";
        if(ml==="tmpl"){if(/运费模板|物流模板/.test(ll))return"freightTemplate";if(/服务模板/.test(ll))return"serviceTemplate";}
        if(ml==="other"){if(/欧盟责任人|欧代|欧盟负责人/.test(ll))return"euResponsible";if(/品牌制造商|制造商信息/.test(ll))return"brandManufacturer";}
        if(/运费模板/.test(ll))return"freightTemplate";
        if(/服务模板/.test(ll))return"serviceTemplate";
        if(/欧盟责任人/.test(ll))return"euResponsible";
        if(/品牌制造商/.test(ll))return"brandManufacturer";
        return"unknown";
      };
      const controls=Array.from(document.querySelectorAll(".ant-select,.ant-cascader-picker,.el-select,.el-cascader")).filter(vis).slice(0,60);
      let targetCtrl=null;
      for(const ctrl of controls){
        const lbl=labelOf(ctrl),mod=moduleOf(ctrl);
        if(classify(ctrl,lbl,mod)===p.fieldKey){targetCtrl=ctrl;break}
      }
      if(!targetCtrl&&p.fieldKey==="attributeTemplate"){
        const attrCard=Array.from(document.querySelectorAll(".form-card")).filter(vis).find(c=>n(c.querySelector("h4")?.innerText||"").includes("属性信息"));
        if(attrCard){targetCtrl=attrCard.querySelector(".in-selector .ant-select,.d-selector .ant-select")||Array.from(attrCard.querySelectorAll(".ant-select")).filter(vis).find(s=>!s.closest(".ant-form-item"))}
      }
      if(!targetCtrl){resolve({ok:false,fieldKey:p.fieldKey,written:false,reason:"未找到控件"});return}
      if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();
      document.body.click();await slp(300);
      const trigger=targetCtrl.querySelector(".ant-select-selector")||targetCtrl;
      clk(trigger);await slp(800);
      const dropdown=document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
      if(!dropdown){resolve({ok:false,fieldKey:p.fieldKey,written:false,reason:"下拉框未打开"});return}
      const allOptions=Array.from(document.querySelectorAll(".ant-select-item-option"));
      const found=allOptions.find(o=>{const t=n(o.innerText||o.textContent);return t===p.value||t.indexOf(p.value)>=0||p.value.indexOf(t)>=0});
      if(found){const content=found.querySelector(".ant-select-item-option-content")||found;clk(content);resolve({ok:true,fieldKey:p.fieldKey,written:true,selectedValue:n(found.innerText||found.textContent)})}
      else{const texts=allOptions.map(o=>n(o.innerText||o.textContent)).filter(Boolean).filter((v,i,a)=>a.indexOf(v)===i);resolve({ok:false,fieldKey:p.fieldKey,written:false,reason:"未找到: "+p.value+" (共"+texts.length+"个)",visibleOptions:texts.slice(0,20)})}
    }))()`;
    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("writeDropdownOption.result", result);
    return result;
  });

  ipcMain.handle("chrome:scanDropdownOptions", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页，无法扫描下拉框选项。");
    await waitForDxmEditContent(editTab);

    const expression = `(() => new Promise(async (resolve) => {
      const norm = (value) => (value || "").replace(/\\s+/g, " ").trim();
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
        ["mouseover", "mousedown", "mouseup", "click"].forEach((type) => el.dispatchEvent(new MouseEvent(type, init)));
      };
      const closeDropdown = async () => {
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
        document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
        document.body.click();
        await sleep(180);
      };
      const normalizeModuleName = (text) => {
        const value = norm(text).replace(/\\uff08.*?\\uff09|\\(.*?\\)/g, "");
        if (value.includes("\\u57fa\\u672c\\u4fe1\\u606f")) return "\\u57fa\\u672c\\u4fe1\\u606f";
        if (value.includes("\\u5e97\\u5c0f\\u79d8\\u4fe1\\u606f")) return "\\u5e97\\u5c0f\\u79d8\\u4fe1\\u606f";
        if (value.includes("\\u5c5e\\u6027\\u4fe1\\u606f")) return "\\u5c5e\\u6027\\u4fe1\\u606f";
        if (value.includes("\\u4ea7\\u54c1\\u4fe1\\u606f")) return "\\u4ea7\\u54c1\\u4fe1\\u606f";
        if (value.includes("\\u533a\\u57df\\u8c03\\u4ef7\\u4fe1\\u606f")) return "\\u533a\\u57df\\u8c03\\u4ef7\\u4fe1\\u606f";
        if (value.includes("\\u63cf\\u8ff0\\u4fe1\\u606f")) return "\\u63cf\\u8ff0\\u4fe1\\u606f";
        if (value.includes("\\u5305\\u88c5\\u4fe1\\u606f")) return "\\u5305\\u88c5\\u4fe1\\u606f";
        if (value.includes("\\u6a21\\u677f\\u4fe1\\u606f") || value.includes("\\u6a21\\u7248\\u4fe1\\u606f")) return "\\u6a21\\u677f\\u4fe1\\u606f";
        if (value.includes("\\u5176\\u4ed6\\u4fe1\\u606f")) return "\\u5176\\u4ed6\\u4fe1\\u606f";
        return "";
      };
      const moduleOf = (el) => normalizeModuleName(el.closest(".form-card")?.querySelector("h4.form-card-title,h4")?.innerText || "");
      const labelOf = (el) => {
        const container = el.closest(".ant-form-item,.el-form-item,.form-item,.form-group,tr,li,.form-row") || el.parentElement;
        const label = norm(container?.querySelector("label,.ant-form-item-label,.el-form-item__label,.label")?.innerText || "");
        if (label) return label.replace(/[：:*\\s]+$/g, "");
        const text = norm(container?.innerText || container?.textContent || "");
        const current = norm(el.querySelector(".ant-select-selection-item,.ant-select-selection-placeholder,.el-input__inner,input")?.innerText || el.querySelector("input")?.value || "");
        return text.replace(current, "").slice(0, 80).replace(/[：:*\\s]+$/g, "") || "\\u672a\\u8bc6\\u522b\\u5b57\\u6bb5";
      };
      const classifyField = (control, label, module, currentValue) => {
        const container = control.closest(".ant-form-item,.el-form-item,.form-item,.form-group,tr,li,.form-row") || control.parentElement;
        const ownText = norm(String(module) + " " + String(label) + " " + String(currentValue)).toLowerCase();
        const containerText = norm(container?.innerText || container?.textContent || "").toLowerCase();
        const ariaText = norm(control.getAttribute("aria-label") || control.getAttribute("title") || control.querySelector("input")?.getAttribute("placeholder") || "").toLowerCase();
        const text = ownText + " " + ariaText + " " + containerText.slice(0, 220);
        if (/店铺名称|店铺名|店铺分类|shop.?name/.test(text)) return "skip";
        if (/产品分类|产品类目|商品分类|商品类目|所属类目|类目路径|选择类目|\\bcategory\\b/.test(text)) return "category";
        if (/引用模板|请选择引用模板|属性模板/.test(text) || (/属性信息/.test(module) && /引用模板|管理模板/.test(containerText))) return "attributeTemplate";
        if (/运费模板|物流模板/.test(text)) return "freightTemplate";
        if (/服务模板/.test(text)) return "serviceTemplate";
        if (/欧盟责任人|欧代|欧盟负责人/.test(text)) return "euResponsible";
        if (/品牌制造商|制造商信息/.test(text)) return "brandManufacturer";
        return "unknown";
      };
      const isUsefulOption = (fieldKey, option) => {
        const value = norm(option);
        if (!value || value === "从页面选项填入") return false;
        if (/^-+\\s*请选择/.test(value) || value === "暂无数据" || value === "管理模板") return false;
        if (/^cn\\d+[a-z0-9]*$/i.test(value)) return false;
        if (fieldKey === "category") return /[\\u4e00-\\u9fff]/.test(value) || /\\(.+\\)/.test(value);
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
        .filter((text) => text && text.length <= 120);
      const collectAllOptions = async () => {
        const collected = [];
        const addVisible = () => collected.push(...collectVisibleOptions());
        addVisible();
        const containers = Array.from(document.querySelectorAll(".rc-virtual-list-holder,.ant-select-dropdown-menu,.ant-cascader-menu,.el-select-dropdown__wrap,.el-cascader-menu__wrap"))
          .filter(visible)
          .filter((el) => el.scrollHeight > el.clientHeight + 4);
        for (const container of containers) {
          container.scrollTop = 0;
          await sleep(80);
          addVisible();
          let lastTop = -1;
          for (let index = 0; index < 40; index += 1) {
            if (container.scrollTop === lastTop) break;
            lastTop = container.scrollTop;
            container.scrollTop = Math.min(container.scrollHeight, container.scrollTop + Math.max(80, Math.floor(container.clientHeight * 0.8)));
            await sleep(100);
            addVisible();
            if (container.scrollTop + container.clientHeight >= container.scrollHeight - 2) break;
          }
        }
        return uniq(collected).slice(0, 240);
      };

      const controls = uniq(Array.from(document.querySelectorAll(".ant-select,.ant-cascader-picker,.el-select,.el-cascader")).filter(visible));
      const groups = [];
      const warnings = [];
      const skipped = [];
      await closeDropdown();
      for (const control of controls.slice(0, 70)) {
        try {
          const label = labelOf(control);
          const module = moduleOf(control);
          const currentValue = currentValueOf(control);
          const fieldKey = classifyField(control, label, module, currentValue);
          if (fieldKey === "skip" || fieldKey === "unknown") {
            skipped.push({ label, module, fieldKey });
            continue;
          }
          clickEl(control.querySelector(".ant-select-selector,.el-input,input") || control);
          await sleep(650);
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
        _debug: { totalControls: controls.length, scanned: groups.length, skipped: skipped.slice(0, 20) }
      });
    }))()`;

    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("scanDropdownOptions.result", {
      url: result?.url,
      groups: result?.groups?.map((group) => ({
        fieldKey: group.fieldKey,
        module: group.module,
        label: group.label,
        currentValue: group.currentValue,
        optionCount: group.options?.length || 0
      })),
      warnings: result?.warnings
    });
    return result;
  });

  ipcMain.handle("chrome:diagnoseCategory", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    return evaluateInTab(editTab, `(() => {
      const norm = (value) => (value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const cards = Array.from(document.querySelectorAll(".form-card")).filter(visible);
      const basicCard = cards.find((card) => norm(card.querySelector("h4")?.innerText || "").includes("基本信息"));
      if (!basicCard) return { ok: false, reason: "未找到基本信息模块" };
      const controls = Array.from(basicCard.querySelectorAll(".ant-select,.ant-cascader-picker,.el-select,.el-cascader"))
        .filter(visible)
        .map((control, index) => {
          const item = control.closest(".ant-form-item,.el-form-item,.form-item,.form-group,tr,li,.form-row") || control.parentElement;
          return {
            index,
            label: norm(item?.querySelector("label,.ant-form-item-label,.el-form-item__label")?.innerText || ""),
            text: norm(item?.innerText || item?.textContent || "").slice(0, 220),
            currentValue: norm(control.querySelector(".ant-select-selection-item,.ant-select-selection-placeholder")?.innerText || control.querySelector("input")?.value || "")
          };
        });
      return { ok: true, controlCount: controls.length, controls, cardText: norm(basicCard.innerText || "").slice(0, 1200) };
    })()`);
  });

  ipcMain.handle("chrome:diagnoseAttrTemplate", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    return evaluateInTab(editTab, `(() => new Promise(async (resolve) => {
      const norm = (value) => (value || "").replace(/\\s+/g, " ").trim();
      const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
      const visible = (el) => {
        if (!el || !el.getBoundingClientRect) return false;
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const clickEl = (el) => {
        if (!el) return;
        el.scrollIntoView({ block: "center" });
        const rect = el.getBoundingClientRect();
        const init = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        ["mouseover", "mousedown", "mouseup", "click"].forEach((type) => el.dispatchEvent(new MouseEvent(type, init)));
      };
      const cards = Array.from(document.querySelectorAll(".form-card")).filter(visible);
      const attrCard = cards.find((card) => norm(card.querySelector("h4")?.innerText || "").includes("属性信息"));
      if (!attrCard) { resolve({ ok: false, reason: "未找到属性信息模块" }); return; }
      const allSelects = Array.from(attrCard.querySelectorAll(".ant-select")).filter(visible);
      const selects = allSelects.map((select, index) => {
        const parent = select.closest(".in-selector,.d-selector,.form-card-header,.ant-form-item") || select.parentElement;
        return {
          index,
          inFormItem: Boolean(select.closest(".ant-form-item")),
          parentClass: String(parent?.className || "").slice(0, 120),
          currentValue: norm(select.querySelector(".ant-select-selection-item")?.innerText || ""),
          placeholder: norm(select.querySelector(".ant-select-selection-placeholder")?.innerText || "")
        };
      });
      const templateSelect = attrCard.querySelector(".in-selector .ant-select,.d-selector .ant-select")
        || allSelects.find((select) => !select.closest(".ant-form-item"))
        || allSelects.find((select) => /引用模板|属性模板/.test(norm((select.closest(".ant-form-item") || select.parentElement)?.innerText || "")));
      let dropdown = null;
      if (templateSelect) {
        document.body.click();
        await sleep(250);
        clickEl(templateSelect.querySelector(".ant-select-selector") || templateSelect);
        await sleep(900);
        const dd = document.querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)");
        if (dd) {
          dropdown = {
            optionCount: dd.querySelectorAll(".ant-select-item-option").length,
            options: Array.from(dd.querySelectorAll(".ant-select-item-option"))
              .filter(visible)
              .map((option) => norm(option.innerText || option.textContent))
              .filter(Boolean)
              .slice(0, 60)
          };
        }
      }
      resolve({ ok: true, selectCount: allSelects.length, selects, templateSelectFound: Boolean(templateSelect), dropdown, cardText: norm(attrCard.innerText || "").slice(0, 1200) });
    }))()`);
  });

  ipcMain.handle("chrome:processImage", async (_event, params) => {
    const p = params || {};
    if (!p.imagePath || !fs.existsSync(p.imagePath)) throw new Error("图片文件不存在: " + (p.imagePath || ""));
    if (!p.apiUrl) throw new Error("请先填写 AI 图片 API 端点");
    if (!p.apiKey) throw new Error("请先填写 AI API Key");

    const prompt = p.prompt || "Remove the original background and place the real product on a clean light gray studio background. Keep the product unchanged.";
    const size = p.size || "1024x1024";
    const imageBuffer = fs.readFileSync(p.imagePath);
    const fileName = path.basename(p.imagePath);
    const ext = path.extname(fileName).toLowerCase();
    const mimeType = ext === ".png" ? "image/png" : ext === ".webp" ? "image/webp" : "image/jpeg";
    const form = new FormData();
    form.append("image", new Blob([imageBuffer], { type: mimeType }), fileName);
    form.append("prompt", prompt);
    form.append("size", size);

    if (p.model) form.append("model", p.model);

    const response = await fetch(p.apiUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${p.apiKey}`
      },
      body: form
    });

    const outDir = path.join(app.getPath("userData"), "processed");
    fs.mkdirSync(outDir, { recursive: true });
    const outPath = path.join(outDir, `processed_${Date.now()}.png`);

    const contentType = response.headers.get("content-type") || "";
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(`AI 图片接口失败 HTTP ${response.status}: ${text.slice(0, 300)}`);
    }

    if (contentType.includes("image/")) {
      const resultBuffer = Buffer.from(await response.arrayBuffer());
      fs.writeFileSync(outPath, resultBuffer);
      return { ok: true, resultPath: outPath };
    }

    const json = await response.json();
    const first = Array.isArray(json.data) ? json.data[0] : json;
    const b64 = first?.b64_json || first?.image_base64 || first?.base64 || json.b64_json || json.image_base64;
    const imageUrl = first?.url || first?.image_url || json.url || json.image_url;

    if (b64) {
      fs.writeFileSync(outPath, Buffer.from(String(b64).replace(/^data:image\/\w+;base64,/, ""), "base64"));
      return { ok: true, resultPath: outPath, revisedPrompt: first?.revised_prompt || json.revised_prompt || "" };
    }

    if (imageUrl) {
      const imageResponse = await fetch(imageUrl);
      if (!imageResponse.ok) throw new Error("AI 图片结果下载失败 HTTP " + imageResponse.status);
      fs.writeFileSync(outPath, Buffer.from(await imageResponse.arrayBuffer()));
      return { ok: true, resultPath: outPath, revisedPrompt: first?.revised_prompt || json.revised_prompt || "" };
    }

    throw new Error("AI 图片接口返回中未找到 b64_json/url/image 数据");
  });

  ipcMain.handle("chrome:downloadImages", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const urlsExpr = `(() => {
      const vis = (el) => { if (!el || !el.getBoundingClientRect) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
      const cards = Array.from(document.querySelectorAll(".form-card")).filter(vis);
      const prodCard = cards.find(c => { const t = (c.querySelector("h4")?.innerText || "").replace(/\\s+/g, " ").trim(); return t.includes("产品信息"); });
      if (!prodCard) return JSON.stringify({ error: "产品信息模块未找到" });
      const imgs = Array.from(prodCard.querySelectorAll("img")).filter(vis);
      const urls = imgs.map(img => img.src).filter(u => u && u.startsWith("http") && !u.includes("addImg-"));
      return JSON.stringify({ count: urls.length, urls: [...new Set(urls)] });
    })()`;
    const urlsResult = await evaluateInTab(editTab, urlsExpr);
    const { urls, error } = JSON.parse(urlsResult || "{}");
    if (error) throw new Error(error);
    if (!urls || !urls.length) throw new Error("未找到产品图片");
    const downloadDir = path.join(app.getPath("userData"), "downloads");
    fs.mkdirSync(downloadDir, { recursive: true });
    const downloaded = [];
    for (let i = 0; i < urls.length; i++) {
      const url = urls[i], ext = url.match(/\\\\.(jpg|jpeg|png|webp|gif)/i)?.[0] || ".jpg";
      const fp = path.join(downloadDir, `image_${i}${ext}`);
      try {
        const buf = await fetch(url).then(r => { if (!r.ok) throw new Error("HTTP "+r.status); return r.arrayBuffer(); });
        fs.writeFileSync(fp, Buffer.from(buf));
        downloaded.push({ index: i, url, file: fp, size: buf.byteLength });
      } catch (e) { downloaded.push({ index: i, url, error: e.message }); }
    }
    return { ok: true, dir: downloadDir, images: downloaded };
  });

  ipcMain.handle("chrome:uploadImage", async (_event, filePath) => {
    if (!filePath || !fs.existsSync(filePath)) throw new Error("文件不存在: "+filePath);
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const fileBuffer = fs.readFileSync(filePath);
    const base64 = fileBuffer.toString("base64");
    const fileName = path.basename(filePath);
    const mimeType = fileName.endsWith(".png") ? "image/png" : "image/jpeg";
    const expression = `(() => {
      const b64="${base64}",fn="${fileName}",mt="${mimeType}";
      const inp=document.getElementById("localFileUploadInp");
      if(!inp)return"no inp";
      const binaryStr=atob(b64);
      const bytes=new Uint8Array(binaryStr.length);
      for(let i=0;i<binaryStr.length;i++)bytes[i]=binaryStr.charCodeAt(i);
      const blob=new Blob([bytes],{type:mt});
      const file=new File([blob],fn,{type:mt});
      const dt=new DataTransfer();dt.items.add(file);
      inp.files=dt.files;
      inp.dispatchEvent(new Event("input",{bubbles:true}));
      inp.dispatchEvent(new Event("change",{bubbles:true}));
      return "ok";
    })()`;
    const result = await evaluateInTab(editTab, expression);
    return { ok: true, file: filePath, result };
  });

  ipcMain.handle("chrome:setOriginalBox", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const expression = `(() => {
      const n=(v)=>(v||"").replace(/\\s+/g," ").trim();
      const vis=(el)=>{if(!el||!el.getBoundingClientRect)return false;const r=el.getBoundingClientRect();return r.width>0&&r.height>0};
      const cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
      const prodCard=cards.find(c=>n(c.querySelector("h4")?.innerText||"").includes("产品信息"));
      if(!prodCard)return JSON.stringify({ok:false});
      const selects=Array.from(prodCard.querySelectorAll("select"));
      let count=0;
      for(const sel of selects){
        const opts=Array.from(sel.options).map(o=>o.text);
        if(opts.includes("是")&&opts.includes("否")){const setter=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,"value")?.set;if(setter)setter.call(sel,"1");else sel.value="1";sel.dispatchEvent(new Event("input",{bubbles:true}));sel.dispatchEvent(new Event("change",{bubbles:true}));count++}
      }
      return JSON.stringify({ok:count>0,setCount:count});
    })()`;
    const result = await evaluateInTab(editTab, expression);
    return JSON.parse(result||"{}");
  });

  ipcMain.handle("chrome:generateMarketingImages", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const expression = `(() => new Promise(async (resolve) => {
      const n=(v)=>(v||"").replace(/\\s+/g," ").trim();
      const slp=ms=>new Promise(d=>setTimeout(d,ms));
      const vis=(el)=>{if(!el||!el.getBoundingClientRect)return false;const r=el.getBoundingClientRect();return r.width>0&&r.height>0};
      const clk=(el)=>{el.scrollIntoView({block:"center"});const r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(t=>el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2})))};
      const cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
      const prodCard=cards.find(c=>n(c.querySelector("h4")?.innerText||"").includes("产品信息"));
      if(!prodCard){resolve({ok:false,reason:"未找到"});return}
      const btns=Array.from(prodCard.querySelectorAll("button")).filter(vis);
      const genBtn=btns.find(b=>n(b.innerText||b.textContent)==="一键生成");
      if(!genBtn){resolve({ok:false,reason:"未找到一键生成按钮"});return}
      clk(genBtn);await slp(3000);
      resolve({ok:true,message:"已点击一键生成"});
    }))()`;
    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("generateMarketingImages", result);
    return result;
  });

  ipcMain.handle("chrome:fillSkuBatch", async (_event, params) => {
    const p = params || {};
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const expression = `(() => new Promise(async (resolve) => {
      const p=${JSON.stringify({...p})};
      const n=(v)=>(v||"").replace(/\\s+/g," ").trim();
      const slp=ms=>new Promise(d=>setTimeout(d,ms));
      const vis=(el)=>{if(!el||!el.getBoundingClientRect)return false;const r=el.getBoundingClientRect();return r.width>0&&r.height>0};
      const setVal=(input,value)=>{if(!input)return;input.focus();const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")?.set;if(setter)setter.call(input,String(value));else input.value=String(value);input.dispatchEvent(new Event("input",{bubbles:true}));input.dispatchEvent(new Event("change",{bubbles:true}));input.dispatchEvent(new Event("blur",{bubbles:true}))};
      const clk=(el)=>{el.scrollIntoView({block:"center"});const r=el.getBoundingClientRect();["mouseover","mousedown","mouseup","click"].forEach(t=>el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2})))};
      const cards=Array.from(document.querySelectorAll(".form-card")).filter(vis);
      const prodCard=cards.find(c=>n(c.querySelector("h4")?.innerText||"").includes("产品信息"));
      if(!prodCard){resolve({ok:false,reason:"未找到"});return}
      const allInputs=Array.from(prodCard.querySelectorAll("input[type=text],input:not([type])")).filter(vis);
      const skuPrices=allInputs.filter(inp=>!isNaN(parseFloat(inp.value))&&parseFloat(inp.value)>0&&parseFloat(inp.value)<1000);
      const origPrice=skuPrices.length>0?parseFloat(skuPrices[0].value):0;
      let filled={};
      const retailInp=allInputs.find(inp=>inp.placeholder==="零售价");
      if(retailInp&&p.priceMultiplier&&origPrice>0){const v=Math.round(origPrice*p.priceMultiplier*100)/100;setVal(retailInp,v);filled.retailPrice=v}
      const dvInp=allInputs.find(inp=>inp.placeholder==="货值");
      if(dvInp&&p.declaredValueMultiplier&&origPrice>0){const v=Math.round(origPrice*p.declaredValueMultiplier*100)/100;setVal(dvInp,v);filled.declaredValue=v}
      const stInp=allInputs.find(inp=>inp.placeholder==="库存");if(stInp&&p.stock){setVal(stInp,p.stock);filled.stock=p.stock}
      const wtInp=allInputs.find(inp=>inp.placeholder==="重量");if(wtInp&&p.weight){setVal(wtInp,p.weight);filled.weight=p.weight}
      const lInp=allInputs.find(inp=>inp.placeholder==="长");if(lInp&&p.length){setVal(lInp,p.length);filled.length=p.length}
      const wInp=allInputs.find(inp=>inp.placeholder==="宽");if(wInp&&p.width){setVal(wInp,p.width);filled.width=p.width}
      const hInp=allInputs.find(inp=>inp.placeholder==="高");if(hInp&&p.height){setVal(hInp,p.height);filled.height=p.height}
      await slp(500);
      const btns=Array.from(prodCard.querySelectorAll("button")).filter(vis);
      const batchBtn=btns.find(b=>n(b.innerText||b.textContent)==="批量填充");
      if(batchBtn){clk(batchBtn);filled.batchClicked=true;await slp(1000)}else{filled.batchClicked=false}
      resolve({ok:true,filled,originalPrice:origPrice});
    }))()`;
    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("fillSkuBatch", result);
    return result;
  });

  ipcMain.handle("chrome:setLogisticsAttribute", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);

    const expression = "(() => new Promise(async (resolve) => {" +
      "try{" +
      "var n=function(v){return(v||'').replace(/\\s+/g,' ').trim()};" +
      "var slp=function(ms){return new Promise(function(d){setTimeout(d,ms)})};" +
      "var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};" +
      "var clk=function(el){el.scrollIntoView({block:'center'});var r=el.getBoundingClientRect();['mouseover','mousedown','mouseup','click'].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};" +
      "var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);" +
      "var prodCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('产品信息')>=0});" +
      "if(!prodCard){resolve({ok:false,reason:'no card'});return}" +
      "var spans=Array.from(prodCard.querySelectorAll('span.link'));" +
      "var logSpan=spans.find(function(s){return n(s.innerText||s.textContent)==='批量'&&vis(s)});" +
      "if(!logSpan){resolve({ok:false,reason:'no span',count:spans.length});return}" +
      "document.body.click();await slp(300);clk(logSpan);await slp(1200);" +
      "var modal=document.querySelector('.batch-edit-modal');" +
      "if(!modal){resolve({ok:false,reason:'no modal'});return}" +
      "modal.style.display='';modal.style.removeProperty('display');await slp(500);" +
      "var wrappers=Array.from(modal.querySelectorAll('.ant-checkbox-wrapper'));" +
      "var cargo=wrappers.find(function(w){return n(w.innerText||w.textContent)==='普货'});" +
      "if(!cargo){resolve({ok:false,reason:'no cargo',wrappers:wrappers.length});return}" +
      "var cb=cargo.querySelector('input[type=checkbox]')||cargo.querySelector('.ant-checkbox-input');" +
      "clk(cb||cargo);await slp(400);" +
      "var btns=Array.from(modal.querySelectorAll('button')).filter(vis);" +
      "var ok=btns.find(function(b){return n(b.innerText||b.textContent)==='确定'});" +
      "if(ok){clk(ok);await slp(500)}" +
      "resolve({ok:true,modalFound:!!modal,cargoFound:!!cargo,okClicked:!!ok});" +
      "}catch(e){resolve({ok:false,error:e.message||String(e)})}" +
      "}))()";

    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("setLogisticsAttribute", JSON.stringify(result));
    return result;
  });


  ipcMain.handle("chrome:writeRegionalPricing", async (_event, value) => {
    if (!value) throw new Error("value is required");
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const target = JSON.stringify(value);
    const expression = "(() => new Promise(async (resolve) => {" +
      "var target=" + target + ";" +
      "var n=function(v){return(v||'').replace(/\\s+/g,' ').trim()};" +
      "var slp=function(ms){return new Promise(function(d){setTimeout(d,ms)})};" +
      "var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};" +
      "var clk=function(el){el.scrollIntoView({block:'center'});var r=el.getBoundingClientRect();['mouseover','mousedown','mouseup','click'].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};" +
      "var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);" +
      "var rpCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('区域调价')>=0});" +
      "if(!rpCard){resolve({ok:false,reason:'no card'});return}" +
      "var dSel=rpCard.querySelector('.d-selector .ant-select,.in-selector .ant-select');" +
      "if(!dSel)dSel=Array.from(rpCard.querySelectorAll('.ant-select')).filter(vis).find(function(s){return !s.closest('.ant-form-item')});" +
      "if(!dSel){resolve({ok:false,reason:'no selector'});return}" +
      "if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();document.body.click();await slp(300);" +
      "var trigger=dSel.querySelector('.ant-select-selector')||dSel;clk(trigger);await slp(800);" +
      "var allOpts=Array.from(document.querySelectorAll('.ant-select-item-option'));" +
      "var found=allOpts.find(function(o){var t=n(o.innerText||o.textContent);return t===target||t.indexOf(target)>=0});" +
      "if(found){var content=found.querySelector('.ant-select-item-option-content')||found;clk(content);resolve({ok:true})}" +
      "else{resolve({ok:false,allTexts:allOpts.map(function(o){return n(o.innerText||o.textContent)}).filter(Boolean).filter(function(v,i,a){return a.indexOf(v)===i}).slice(0,20)})}" +
      "}))()";
    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("writeRegionalPricing", JSON.stringify(result));
    return result;
  });


  
  
  ipcMain.handle("chrome:generateWirelessDesc", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const expression = "(() => new Promise(async (resolve) => {" +
      "var n=function(v){return(v||'').replace(/\\s+/g,' ').trim()};" +
      "var slp=function(ms){return new Promise(function(d){setTimeout(d,ms)})};" +
      "var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};" +
      "var clk=function(el){el.scrollIntoView({block:'center'});var r=el.getBoundingClientRect();['mouseover','mousedown','mouseup','click'].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};" +
      "var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);" +
      "var descCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('描述信息')>=0});" +
      "if(!descCard){resolve({ok:false,reason:'no card'});return}" +
      "var labels=Array.from(descCard.querySelectorAll('.ant-radio-wrapper'));" +
      "var oldEditor=labels.find(function(l){return n(l.innerText||l.textContent)==='使用老版编辑器'});" +
      "var wasChecked=false;" +
      "if(oldEditor){var radio=oldEditor.querySelector('.ant-radio');wasChecked=radio&&radio.className.indexOf('ant-radio-checked')>=0;" +
      "if(!wasChecked){var radioInp=oldEditor.querySelector('input[type=radio]');clk(radioInp||oldEditor);await slp(1500);" +
      "var modal=null;var modals=document.querySelectorAll('.ant-modal');" +
      "for(var mi=0;mi<modals.length;mi++){var m=modals[mi];var ds=(m.getAttribute('style')||'').indexOf('display: none')>=0;if(!ds&&m.offsetParent){modal=m;break}}" +
      "if(modal){await slp(300);var okBtn=Array.from(modal.querySelectorAll('button')).filter(vis).find(function(b){var t=n(b.innerText||b.textContent);return t.indexOf('确')>=0&&t.length<=3});" +
      "if(okBtn){clk(okBtn);await slp(2000);}}else{await slp(2000);}}}" +
      "var genBtn=null;" +
      "for(var ri=0;ri<15;ri++){" +
      "var spans=Array.from(descCard.querySelectorAll('span.link'));" +
      "genBtn=spans.find(function(s){return n(s.innerText||s.textContent)==='一键生成'&&vis(s)});" +
      "if(genBtn)break;await slp(500)}" +
      "if(!genBtn){resolve({ok:false,reason:'no gen btn after retries',wasChecked:wasChecked});return}" +
      "clk(genBtn);await slp(2000);" +
      "resolve({ok:true,wasChecked:wasChecked,genClicked:true});" +
      "}))()";
    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("generateWirelessDesc", JSON.stringify(result));
    return result;
  });







  // Fill packaging weight and dimensions from presets
  ipcMain.handle("chrome:fillPackaging", async (_event, params) => {
    const p = params || {};
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const payload = JSON.stringify(p);
    const expression = "(() => new Promise(async (resolve) => {" +
      "var p=" + payload + ";" +
      "var n=function(v){return(v||'').replace(/\\s+/g,' ').trim()};" +
      "var slp=function(ms){return new Promise(function(d){setTimeout(d,ms)})};" +
      "var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};" +
      "var setVal=function(input,value){if(!input||value==null)return;input.focus();var setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')?.set;if(setter)setter.call(input,String(value));else input.value=String(value);input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));input.dispatchEvent(new Event('blur',{bubbles:true}))};" +
      "var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);" +
      "var pkgCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('包装信息')>=0});" +
      "if(!pkgCard){resolve({ok:false,reason:'no card'});return}" +
      "var inputs=Array.from(pkgCard.querySelectorAll('input[type=text],input:not([type])')).filter(vis);" +
      "var filled={};" +
      "// Weight: first text input with class w100" +
      "if(p.weight){var wtInp=inputs[0];if(!wtInp||wtInp.type==='search')wtInp=inputs.find(function(i){return i.type==='text'&&!i.className.includes('search')});if(wtInp){setVal(wtInp,p.weight);filled.weight=p.weight}}" +
      "// Dimensions: find inputs after 尺寸 label" +
      "var dimInputs=inputs.filter(function(i){return i.type==='text'&&!i.className.includes('search')&&!i.className.includes('w100')});" +
      "if(p.length&&dimInputs[1]){setVal(dimInputs[1],p.length);filled.length=p.length}" +
      "if(p.width&&dimInputs[2]){setVal(dimInputs[2],p.width);filled.width=p.width}" +
      "if(p.height&&dimInputs[3]){setVal(dimInputs[3],p.height);filled.height=p.height}" +
      "resolve({ok:true,filled:filled});" +
      "}))()";
    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("fillPackaging", JSON.stringify(result));
    return result;
  });



  // Scan customs cascading select structure
  ipcMain.handle("chrome:scanCustomsLevels", async () => {
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const expression = "(() => new Promise(async (resolve) => {" +
      "var n=function(v){return(v||'').replace(/\\s+/g,' ').trim()};" +
      "var slp=function(ms){return new Promise(function(d){setTimeout(d,ms)})};" +
      "var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};" +
      "var clk=function(el){el.scrollIntoView({block:'center'});var r=el.getBoundingClientRect();['mouseover','mousedown','mouseup','click'].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};" +
      "var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);" +
      "var tmplCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('模板信息')>=0});" +
      "if(!tmplCard){resolve({ok:false,reason:'no card'});return}" +
      "// Check if cascaders already exist" +
      "var cascaders=Array.from(document.querySelectorAll('.ant-cascader,.ant-cascader-picker')).filter(vis);" +
      "if(!cascaders.length){" +
      "  var btns=Array.from(tmplCard.querySelectorAll('button')).filter(vis);" +
      "  var addBtn=btns.find(function(b){return n(b.innerText||b.textContent)==='添加海关监管'});" +
      "  if(!addBtn){resolve({ok:false,reason:'no add btn'});return}" +
      "  // Try multiple click methods" +
      "  var span=addBtn.querySelector('span');if(span)clk(span);" +
      "  clk(addBtn);" +
      "  addBtn.focus();addBtn.click();" +
      "  await slp(3000);" +
      "  cascaders=Array.from(document.querySelectorAll('.ant-cascader,.ant-cascader-picker')).filter(vis);" +
      "}" +
      "if(!cascaders.length){resolve({ok:false,reason:'no cascaders after click',btnClicked:true});return}" +
      "// For each cascader, open and scan levels" +
      "var allCustoms=[];" +
      "for(var ci=0;ci<cascaders.length;ci++){" +
      "  var cs=cascaders[ci];" +
      "  if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();document.body.click();await slp(200);" +
      "  var inp=cs.querySelector('input');clk(inp||cs);await slp(1000);" +
      "  var menus=Array.from(document.querySelectorAll('.ant-cascader-menu')).filter(vis);" +
      "  var levels=[];" +
      "  for(var li=0;li<menus.length;li++){" +
      "    var m=menus[li];" +
      "    m.scrollTop=0;await slp(100);var lastTop=-1;var allItems=[];" +
      "    for(var s=0;s<30;s++){" +
      "      if(m.scrollTop===lastTop)break;lastTop=m.scrollTop;" +
      "      Array.from(m.querySelectorAll('.ant-cascader-menu-item')).filter(vis).forEach(function(it){var t=n(it.innerText||it.textContent);if(allItems.indexOf(t)<0)allItems.push(t)});" +
      "      m.scrollTop=Math.min(m.scrollHeight,m.scrollTop+Math.max(60,Math.floor(m.clientHeight*0.8)));await slp(60);" +
      "    }" +
      "    if(allItems.length>0)levels.push({level:li,itemCount:allItems.length,items:allItems});" +
      "  }" +
      "  allCustoms.push({index:ci,menuCount:menus.length,levels:levels});" +
      "  document.body.click();await slp(200);" +
      "}" +
      "resolve({ok:true,cascaderCount:cascaders.length,customs:allCustoms});" +
      "}))()";
    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("scanCustomsLevels", JSON.stringify(result));
    return result;
  });

  // Write customs cascading values by navigating levels
  ipcMain.handle("chrome:writeCustoms", async (_event, pathArray) => {
    if (!pathArray || !pathArray.length) throw new Error("path is required");
    const { tabs } = await getConnectedChromeTabs();
    const editTab = await pickBestDxmEditTab(tabs);
    if (!editTab) throw new Error("没有找到店小秘编辑页");
    await waitForDxmEditContent(editTab);
    const pathJson = JSON.stringify(pathArray);
    const expression = "(() => new Promise(async (resolve) => {" +
      "var path=" + pathJson + ";" +
      "var n=function(v){return(v||'').replace(/\\s+/g,' ').trim()};" +
      "var slp=function(ms){return new Promise(function(d){setTimeout(d,ms)})};" +
      "var vis=function(el){if(!el||!el.getBoundingClientRect)return false;var r=el.getBoundingClientRect();return r.width>0&&r.height>0};" +
      "var clk=function(el){el.scrollIntoView({block:'center'});var r=el.getBoundingClientRect();['mouseover','mousedown','mouseup','click'].forEach(function(t){el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,clientX:r.left+r.width/2,clientY:r.top+r.height/2}))})};" +
      "var cards=Array.from(document.querySelectorAll('.form-card')).filter(vis);" +
      "var tmplCard=cards.find(function(c){return n(c.querySelector('h4')?c.querySelector('h4').innerText:'').indexOf('模板信息')>=0});" +
      "if(!tmplCard){resolve({ok:false,reason:'no card'});return}" +
      "var cascaders=Array.from(tmplCard.querySelectorAll('.ant-cascader,.ant-cascader-picker')).filter(vis);" +
      "if(!cascaders.length){resolve({ok:false,reason:'no cascaders'});return}" +
      "var results=[];" +
      "for(var ci=0;ci<cascaders.length;ci++){" +
      "  var cs=cascaders[ci];" +
      "  if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();document.body.click();await slp(200);" +
      "  var inp=cs.querySelector('input');clk(inp||cs);await slp(800);" +
      "  var selected=[];" +
      "  for(var li=0;li<path.length;li++){" +
      "    var target=path[li];" +
      "    var menus=Array.from(document.querySelectorAll('.ant-cascader-menu')).filter(vis);" +
      "    var menu=menus[li];if(!menu)break;" +
      "    menu.scrollTop=0;await slp(100);var lastTop=-1;var found=null;" +
      "    for(var s=0;s<30;s++){" +
      "      if(menu.scrollTop===lastTop)break;lastTop=menu.scrollTop;" +
      "      var items=Array.from(menu.querySelectorAll('.ant-cascader-menu-item')).filter(vis);" +
      "      found=items.find(function(it){var t=n(it.innerText||it.textContent);return t===target||t.indexOf(target)>=0||target.indexOf(t)>=0});" +
      "      if(found)break;" +
      "      menu.scrollTop=Math.min(menu.scrollHeight,menu.scrollTop+Math.max(60,Math.floor(menu.clientHeight*0.8)));await slp(60);" +
      "    }" +
      "    if(!found)break;clk(found);selected.push(n(found.innerText||found.textContent));await slp(700);" +
      "  }" +
      "  results.push({index:ci,selected:selected});" +
      "}" +
      "resolve({ok:results.length>0,results:results});" +
      "}))()";
    const result = await evaluateInTab(editTab, expression);
    appendAutomationLog("writeCustoms", JSON.stringify(result));
    return result;
  });



}

function createMainWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1100,
    minHeight: 760,
    title: "店小秘自动编辑助手",
    backgroundColor: "#edf1f5",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false
    }
  });

  win.once("ready-to-show", () => {
    win.show();
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  if (isDev) {
    win.loadURL("http://127.0.0.1:5173");
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    win.loadFile(path.join(__dirname, "../dist/index.html"));
  }

  return win;
}

function createMenu() {
  const template = [
    {
      label: "文件",
      submenu: [{ role: "quit", label: "退出" }]
    },
    {
      label: "视图",
      submenu: [
        { role: "reload", label: "刷新" },
        { role: "toggleDevTools", label: "开发者工具" },
        { type: "separator" },
        { role: "resetZoom", label: "重置缩放" },
        { role: "zoomIn", label: "放大" },
        { role: "zoomOut", label: "缩小" }
      ]
    }
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

app.whenReady().then(() => {
  registerAutomationIpc();
  createMenu();
  createMainWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
