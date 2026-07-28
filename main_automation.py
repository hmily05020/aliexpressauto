import asyncio
import base64
import json
import mimetypes
import re
import time
import hashlib
import urllib.request
import urllib.error
import urllib.parse
import argparse
import traceback
import sys
import uuid
import subprocess
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Iterable

from playwright.async_api import async_playwright, Page, Browser

from config import CONFIG, ProductData, logger

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / ".write_test.tmp"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False

USER_DATA_DIR = Path.home() / "Documents" / "ShopAutomationGUI"
BASE_DIR = USER_DATA_DIR if getattr(sys, "frozen", False) else APP_DIR
BASE_DIR.mkdir(parents=True, exist_ok=True)
ERROR_LOG_FILE = BASE_DIR / "last_error_traceback.log"


def is_skip(field_name: str) -> bool:
    """根据运行时配置判断是否跳过某项修改。"""
    return bool(CONFIG.get(f"skip_{field_name}", False))


def write_error_trace(stage: str, exc: Exception):
    """
    把异常完整堆栈写入文件，便于定位真实退出点。
    """
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trace = traceback.format_exc()
        content = (
            f"\n{'='*80}\n"
            f"[{now}] stage={stage}\n"
            f"exception={repr(exc)}\n"
            f"{trace}\n"
        )
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(content)
        logger.error(f"异常堆栈已写入: {ERROR_LOG_FILE}")
    except Exception:
        pass


class ShopAutomationRunner:
    """
    店小秘商品编辑自动化主脚本

    使用方式：
    1. 手动启动 Chrome，并开启远程调试端口:
       chrome.exe --remote-debugging-port=9222
    2. 手动登录店小秘并打开商品编辑页
    3. 运行本脚本
    4. 如果控件文本与实际页面不一致，调整下方候选文本
    """

    DEBUG_URL = "http://127.0.0.1:9222"
    DEBUG_URLS = ("http://127.0.0.1:9222", "http://localhost:9222", "http://[::1]:9222")
    OUTPUT_DIR = BASE_DIR / "output"

    SELECTOR_TEXTS = {
        "category_button": ["选择分类", "选择类目", "编辑分类", "类目"],
        "template_button": ["引用模板", "选择模板", "模板"],
        "generate_marketing_image": ["一键生成", "生成营销图", "营销图一键生成"],
        "translate_button": ["一键翻译", "翻译"],
        "publish_button": ["立即发布", "发布商品", "提交发布", "发布"],
        "currency_template": ["币种模板", "运费模板", "售价运费"],
        "service_template": ["服务模板", "物流服务模板", "服务"],
        "tax_included": ["税费", "含税", "报价方式"],
        "european_responsible": ["欧洲责任人", "欧代", "责任人"],
        "brand_manufacturer": ["品牌/制造商", "品牌制造商", "制造商"],
        "translation_type": ["翻译方式", "翻译类型"],
        "language_pair": ["语言对", "翻译语言", "语言"],
    }

    INPUT_TEXTS = {
        "stock": ["库存", "可售库存"],
        "weight": ["重量", "包裹重量"],
        "size": ["尺寸", "包裹尺寸", "长宽高"],
        "customs_item": ["报关名", "海关品名", "申报名"],
        "customs_material": ["材质", "报关材质", "商品材质"],
        "original_box": ["原箱", "是否原箱"],
    }

    def __init__(self, product_data: Optional[dict] = None):
        self.product = ProductData(product_data or {"original_price": 0})
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.ai_text_cache: dict = {}
        self.current_ai_product_context: dict = {}
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async def run(self):
        try:
            src = Path(__file__).resolve()
            logger.info(
                f"运行源码诊断: pid={os.getpid()}, file={src}, mtime={datetime.fromtimestamp(src.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}, quiet_stdout={os.environ.get('SHOP_AUTOMATION_QUIET_STDOUT', '')}"
            )
        except Exception:
            pass
        logger.info("开始执行店小秘自动化脚本")
        try:
            await self.connect()

            # 批量模式：从采集箱逐个点击“编辑”
            await self.run_batch_from_draft_list(max_items=int(CONFIG.get("max_items", 100)))

            logger.success("批量自动化流程执行完成")
        except Exception as exc:
            logger.error(f"自动化流程执行失败: {exc}")
            write_error_trace("runner.run", exc)
            raise
        finally:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()

    async def connect(self):
        self.playwright = await async_playwright().start()
        logger.info(f"连接 Chrome 调试端口: {', '.join(self.DEBUG_URLS)}")

        # 等待调试端口可用，避免刚启动浏览器时 ECONNREFUSED
        ready_url = None
        last_probe_err = None
        for _ in range(30):  # 最多约30秒
            for debug_url in self.DEBUG_URLS:
                try:
                    with urllib.request.urlopen(f"{debug_url}/json/version", timeout=1.5):
                        ready_url = debug_url
                        break
                except Exception as exc:
                    last_probe_err = exc
            if ready_url:
                break
            await asyncio.sleep(1)

        if not ready_url:
            raise RuntimeError(f"Chrome 调试端口 9222 未就绪，请确认浏览器已启动并开启远程调试: {last_probe_err}")

        last_err = None
        for _ in range(8):
            for debug_url in [ready_url, *self.DEBUG_URLS]:
                try:
                    self.browser = await self.playwright.chromium.connect_over_cdp(debug_url)
                    self.DEBUG_URL = debug_url
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
            if self.browser:
                break
            await asyncio.sleep(1)

        if last_err:
            raise RuntimeError(f"连接 Chrome 失败: {last_err}")

        pages = []
        for context in self.browser.contexts:
            pages.extend(context.pages)

        if not pages:
            raise RuntimeError("未找到任何已打开页面，请先手动打开店小秘页面")

        self.page = self.pick_target_page(pages)
        logger.success(f"已连接目标页面: {self.page.url}")

    def pick_target_page(self, pages: Iterable[Page]) -> Page:
        priority_keywords = [
            "smtproductlist/draft",
            "product",
            "edit",
            "publish",
            "listing",
            "shop",
            "店小秘",
            "商品",
            "编辑",
            "刊登",
        ]

        scored_pages = []
        for page in pages:
            url = (page.url or "").lower()
            score = sum(1 for kw in priority_keywords if kw.lower() in url)
            scored_pages.append((score, page))

        scored_pages.sort(key=lambda item: item[0], reverse=True)
        return scored_pages[0][1]

    async def apply_draft_search_filter(self) -> bool:
        keyword = str(CONFIG.get("draft_search_keyword", "") or "").strip()
        if not keyword:
            return True

        search_type = str(CONFIG.get("draft_search_type", "标题") or "标题").strip()
        logger.info(f"采集箱筛选：搜索类型={search_type}，搜索词={keyword}")

        try:
            await self.page.wait_for_load_state("domcontentloaded")
        except Exception:
            pass

        result = await self.page.evaluate(
            """async ({ keyword, searchType }) => {
                const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
                const visible = (el) => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                };
                const textOf = (el) => ((el && (el.innerText || el.textContent)) || "").replace(/\\s+/g, "").trim();
                const clickNode = (el) => {
                    const target = el.closest("button,a,label,span,div") || el;
                    target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                    target.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                    target.click();
                };

                if (searchType) {
                    const typeCandidates = Array.from(document.querySelectorAll("button,a,span,label,div"))
                        .filter(visible)
                        .filter(el => textOf(el) === searchType);
                    if (typeCandidates.length > 0) {
                        clickNode(typeCandidates[0]);
                        await sleep(120);
                    }
                }

                const inputs = Array.from(document.querySelectorAll("input"))
                    .filter(visible)
                    .filter(input => !input.disabled && !input.readOnly && (input.type || "text").toLowerCase() !== "checkbox");

                const scored = inputs.map((input, idx) => {
                    const rect = input.getBoundingClientRect();
                    let context = "";
                    let cur = input;
                    for (let i = 0; cur && i < 5; i++) {
                        context += " " + textOf(cur);
                        cur = cur.parentElement;
                    }
                    let score = 0;
                    if (context.includes("搜索内容")) score += 1000;
                    if (context.includes("搜索类型")) score += 120;
                    if ((input.placeholder || "").includes("搜索")) score += 200;
                    if (rect.width >= 200) score += 80;
                    if (rect.top < 320) score += 40;
                    if (String(input.value || "").trim() === keyword) score += 20;
                    if (rect.width < 80) score -= 200;
                    return { input, idx, score, rectTop: rect.top, width: rect.width, context };
                }).sort((a, b) => b.score - a.score);

                const picked = scored[0];
                if (!picked || picked.score < 50) {
                    return { ok: false, reason: "search_input_not_found", inputCount: inputs.length, bestScore: picked?.score || 0 };
                }

                const input = picked.input;
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
                if (setter) setter.call(input, keyword);
                else input.value = keyword;
                input.dispatchEvent(new Event("input", { bubbles: true }));
                input.dispatchEvent(new Event("change", { bubbles: true }));
                input.dispatchEvent(new Event("blur", { bubbles: true }));

                await sleep(80);

                const searchButtons = Array.from(document.querySelectorAll("button,a,span"))
                    .filter(visible)
                    .map(el => ({ el, text: textOf(el), rect: el.getBoundingClientRect() }))
                    .filter(item => item.text === "搜索" || item.text.includes("搜索"))
                    .filter(item => item.rect.top < 340);

                if (searchButtons.length === 0) {
                    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
                    input.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true }));
                    return { ok: true, action: "enter", inputScore: picked.score };
                }

                searchButtons.sort((a, b) => {
                    const da = Math.abs(a.rect.top - input.getBoundingClientRect().top) + Math.abs(a.rect.left - input.getBoundingClientRect().right);
                    const db = Math.abs(b.rect.top - input.getBoundingClientRect().top) + Math.abs(b.rect.left - input.getBoundingClientRect().right);
                    return da - db;
                });
                clickNode(searchButtons[0].el);
                return { ok: true, action: "click", buttonText: searchButtons[0].text, inputScore: picked.score };
            }""",
            {"keyword": keyword, "searchType": search_type},
        )

        if not result or not result.get("ok"):
            logger.warning(f"采集箱筛选失败，继续按当前列表处理: {result}")
            return False

        try:
            await self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            await self.page.wait_for_timeout(1200)

        for wait_idx in range(1, 16):
            matched = await self.page.evaluate(
                """(keyword) => {
                    const norm = (value) => String(value || "").replace(/\\s+/g, "").trim();
                    const target = norm(keyword);
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== "none"
                            && style.visibility !== "hidden"
                            && rect.width > 0
                            && rect.height > 0;
                    };
                    const rows = Array.from(document.querySelectorAll("tr, .ant-table-row, .table-row, .list-row"))
                        .filter(visible)
                        .map(row => ({ text: norm(row.innerText || row.textContent), top: row.getBoundingClientRect().top }))
                        .filter(item => item.top > 300);
                    const matchedRows = rows.filter(item => item.text.includes(target));
                    return {
                        ok: matchedRows.length > 0,
                        rows: rows.length,
                        matched: matchedRows.length,
                        firstMatchedText: matchedRows[0]?.text?.slice(0, 120) || ""
                    };
                }""",
                keyword,
            )
            if matched and matched.get("ok"):
                logger.info(f"采集箱搜索结果已刷新: {matched}")
                break
            logger.info(f"等待采集箱搜索结果刷新 {wait_idx}/15: {matched}")
            await self.page.wait_for_timeout(700)

        logger.success(f"采集箱筛选完成: {keyword}")
        return True

    async def click_first_draft_edit_link(self) -> bool:
        keyword = str(CONFIG.get("draft_search_keyword", "") or "").strip()
        for attempt in range(1, 8):
            try:
                result = await self.page.evaluate(
                    """(keyword) => {
                        const targetKeyword = String(keyword || "").replace(/\\s+/g, "").trim();
                        const visible = (el) => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style.display !== "none"
                                && style.visibility !== "hidden"
                                && rect.width > 0
                                && rect.height > 0;
                        };
                        const textOf = (el) => ((el.innerText || el.textContent || "").replace(/\\s+/g, "").trim());
                        const rowOf = (el) => {
                            let cur = el;
                            for (let i = 0; cur && i < 8; i++) {
                                if (cur.matches?.("tr, .ant-table-row, .table-row, .list-row")) return cur;
                                cur = cur.parentElement;
                            }
                            return el.closest("tr") || el.parentElement;
                        };
                        const candidates = Array.from(document.querySelectorAll("a"))
                            .filter(visible)
                            .map(el => {
                                const row = rowOf(el);
                                return {
                                    el,
                                    row,
                                    text: textOf(el),
                                    rowText: textOf(row),
                                    rect: el.getBoundingClientRect()
                                };
                            })
                            .filter(item => item.text === "编辑" || item.text.includes("编辑"))
                            .filter(item => item.rect.top > 300);

                        const filtered = targetKeyword
                            ? candidates.filter(item => item.rowText.includes(targetKeyword))
                            : candidates;

                        filtered.sort((a, b) => a.rect.top - b.rect.top || a.rect.left - b.rect.left);
                        const picked = filtered[0];
                        if (!picked) {
                            return {
                                ok: false,
                                count: candidates.length,
                                matched: filtered.length,
                                keyword: targetKeyword,
                                firstRowText: candidates[0]?.rowText?.slice(0, 120) || ""
                            };
                        }

                        picked.el.scrollIntoView({ block: "center", inline: "center" });
                        picked.el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                        picked.el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                        picked.el.click();
                        return {
                            ok: true,
                            count: candidates.length,
                            matched: filtered.length,
                            keyword: targetKeyword,
                            text: picked.text,
                            rowText: picked.rowText.slice(0, 120),
                            top: picked.rect.top
                        };
                    }""",
                    keyword,
                )
                if result and result.get("ok"):
                    logger.success(f"点击采集箱第一条编辑成功: {result}")
                    return True
                logger.info(f"采集箱暂未找到可点击编辑链接，等待重试 {attempt}/7: {result}")
            except Exception as exc:
                logger.warning(f"点击采集箱编辑链接失败，等待重试 {attempt}/7: {exc}")
            await self.page.wait_for_timeout(700)

        return False

    async def handle_draft_edit_category_prompt(self) -> bool:
        if not self.page:
            return False
        try:
            result = await self.page.evaluate(
                """() => {
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== "none"
                            && style.visibility !== "hidden"
                            && rect.width > 0
                            && rect.height > 0;
                    };
                    const textOf = (el) => ((el.innerText || el.textContent || "").replace(/\\s+/g, "").trim());
                    const modal = Array.from(document.querySelectorAll(".ant-modal, .modal, .el-dialog, [role='dialog'], body > div"))
                        .filter(visible)
                        .find(el => {
                            const text = textOf(el);
                            return text.includes("编辑分类") && text.includes("编辑产品");
                        });
                    if (!modal) return { ok: false, reason: "no_prompt" };

                    const buttons = Array.from(modal.querySelectorAll("button, a, span"))
                        .filter(visible)
                        .map(el => ({ el, text: textOf(el) }));
                    const skip = buttons.find(item => item.text.includes("跳过") && item.text.includes("编辑产品"))
                        || buttons.find(item => item.text.includes("跳过"))
                        || buttons.find(item => item.text.includes("编辑产品"));
                    if (!skip) return { ok: false, reason: "skip_button_not_found", modalText: textOf(modal).slice(0, 200) };

                    const target = skip.el.closest("button,a") || skip.el;
                    target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                    target.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                    target.click();
                    return { ok: true, text: skip.text };
                }"""
            )
            if result and result.get("ok"):
                logger.success(f"已处理采集箱编辑分类提示弹窗: {result}")
                await self.page.wait_for_timeout(1500)
                return True
            return False
        except Exception as exc:
            logger.warning(f"处理采集箱编辑分类提示弹窗失败: {exc}")
            return False

    async def run_batch_from_draft_list(self, max_items: int = 100):
        draft_url = "https://www.dianxiaomi.com/web/smt/smtProductList/draft?pageType=0"

        if not self.page:
            raise RuntimeError("页面未初始化")

        for p in [p for ctx in self.browser.contexts for p in ctx.pages]:
            if "smtproductlist/draft" in (p.url or "").lower():
                draft_url = p.url
                self.page = p
                break

        # 切到采集箱页面
        if "smtproductlist/draft" not in (self.page.url or "").lower():
            await self.page.goto(draft_url, wait_until="domcontentloaded")

        await self.page.wait_for_load_state("networkidle")
        logger.info(f"已进入采集箱页面: {self.page.url}")
        max_items = max(1, int(max_items or 1))
        logger.info(f"批量模式：本次最多处理 {max_items} 个商品；成功后继续下一条，失败保留当前编辑页")

        for i in range(max_items):
            try:
                await self.page.bring_to_front()
                await self.page.wait_for_timeout(500)
                await self.apply_draft_search_filter()

                pages_before = {p for ctx in self.browser.contexts for p in ctx.pages}
                clicked = await self.click_first_draft_edit_link()
                if not clicked:
                    logger.info("当前页面未找到可编辑商品，批量结束")
                    break
                await self.page.wait_for_timeout(1200)
                await self.handle_draft_edit_category_prompt()

                pages_after = [p for ctx in self.browser.contexts for p in ctx.pages]
                edit_page = None
                for p in pages_after:
                    if p not in pages_before and ("edit" in (p.url or "").lower() or "smt/edit" in (p.url or "").lower()):
                        edit_page = p
                        break

                # 若未新开标签，可能是当前页跳转
                if not edit_page:
                    for p in pages_after:
                        if "smt/edit" in (p.url or "").lower():
                            edit_page = p
                            break

                if not edit_page:
                    logger.warning(f"第 {i+1} 个商品未进入编辑页，跳过")
                    continue

                self.page = edit_page
                logger.info(f"开始处理第 {i+1} 个商品: {self.page.url}")

                await self.ensure_page_ready()
                await self.capture_state("00_initial")

                if not is_skip("category"):
                    await self.step_select_category()
                if not is_skip("template"):
                    await self.step_select_template()
                await self.prepare_ai_text_context(apply_to_page=False)
                await self.step_ai_main_image_processing()
                await self.step_marketing_and_delete_video()
                await self.step_fill_basic_info()
                logger.info("准备进入描述信息步骤")
                await self.step_description_info()
                await self.step_packaging_info()

                await self.step_translate()
                logger.info("翻译/AI文本处理完成，进入模板配置与海关监管步骤")
                await self.step_select_templates_and_options()

                published_ok = await self.step_publish()
                try:
                    await self.capture_state("99_finished")
                except Exception as e:
                    logger.warning(f"完成截图失败（页面可能已自动关闭）: {e}")

                if not published_ok:
                    logger.error(f"第 {i+1} 个商品未确认发布成功，暂停批量流程并保留当前编辑页")
                    break

                logger.success(f"第 {i+1} 个商品处理完成，准备回到采集箱继续下一条")

                # 关闭编辑页，回到采集箱
                try:
                    if not self.page.is_closed() and "smtproductlist/draft" not in (self.page.url or "").lower():
                        await self.page.close()
                except Exception as e:
                    logger.warning(f"关闭编辑页失败或页面已关闭，继续回到采集箱: {e}")

                # 找回采集箱页
                draft_page = None
                for p in [p for ctx in self.browser.contexts for p in ctx.pages]:
                    if "smtproductlist/draft" in (p.url or "").lower():
                        draft_page = p
                        break

                if not draft_page:
                    # 没找到就新开
                    any_page = [p for ctx in self.browser.contexts for p in ctx.pages][0]
                    await any_page.goto(draft_url, wait_until="domcontentloaded")
                    draft_page = any_page

                self.page = draft_page
                await self.page.wait_for_load_state("networkidle")
                await self.page.reload(wait_until="domcontentloaded")
                await self.page.wait_for_load_state("networkidle")

            except Exception as item_exc:
                logger.error(f"第 {i+1} 个商品处理失败: {item_exc}")
                write_error_trace(f"run_batch_from_draft_list.item_{i+1}", item_exc)
                logger.warning("批量暂停：处理失败后保留当前编辑页，方便人工查看页面结果")
                break

                draft_page = None
                for p in [p for ctx in self.browser.contexts for p in ctx.pages]:
                    if "smtproductlist/draft" in (p.url or "").lower():
                        draft_page = p
                        break
                if draft_page:
                    self.page = draft_page
                continue

    def is_mirror_signal_mode(self) -> bool:
        category = str(CONFIG.get("category", "")).strip()
        customs_item = str(CONFIG.get("customs_item", "")).strip()
        customs_material = str(CONFIG.get("customs_material", "")).strip()

        # 兼容不同写法，避免类目名没完全包含“后视镜转向灯”时仍走错分支
        mirror_keywords = ["后视镜转向灯", "后视镜", "转向灯", "后视镜灯", "mirror", "signal"]
        mirror_customs_values = ["视觉信号装置", "Visual signal device", "载人的机动车辆", "Manned motor vehicle"]

        return (
            any(k.lower() in category.lower() for k in mirror_keywords)
            or any(v.lower() in customs_item.lower() for v in mirror_customs_values if customs_item)
            or any(v.lower() in customs_material.lower() for v in mirror_customs_values if customs_material)
        )

    async def ensure_page_ready(self):
        if not self.page:
            raise RuntimeError("页面未初始化")
        await self.page.wait_for_load_state("domcontentloaded")
        await asyncio.sleep(CONFIG.get("delay_between_actions", 0.5))
        logger.info(f"页面标题: {await self.page.title()}")
        logger.info(f"页面地址: {self.page.url}")

    async def capture_state(self, name: str):
        if not self.page:
            return
        png_path = self.OUTPUT_DIR / f"{name}.png"
        html_path = self.OUTPUT_DIR / f"{name}.html"
        try:
            await self.page.screenshot(path=str(png_path), full_page=True, timeout=12000)
            logger.info(f"已保存现场截图: {png_path}")
        except Exception as exc:
            logger.warning(f"保存现场截图失败，已跳过不中断流程: {exc}")

        try:
            html = await self.page.content()
            html_path.write_text(html, encoding="utf-8")
            logger.info(f"已保存页面HTML: {html_path}")
        except Exception as exc:
            logger.warning(f"保存页面HTML失败，已跳过不中断流程: {exc}")

    @staticmethod
    def config_enabled(name: str) -> bool:
        value = str(CONFIG.get(name, "")).strip().lower()
        return value in {"1", "true", "yes", "y", "on", "是", "启用", "开启"}

    @staticmethod
    def compact_title(text: str, max_len: int = 128) -> str:
        s = re.sub(r"\s+", " ", (text or "").strip())
        if len(s) <= max_len:
            return s
        words = s.split(" ")
        while len(words) > 1 and len(" ".join(words)) > max_len:
            words.pop()
        s = " ".join(words).strip()
        return s[:max_len].rstrip()

    @staticmethod
    def sanitize_sku_name(text: str, max_len: int = 20) -> str:
        s = re.sub(r"[^A-Za-z0-9 ().-]+", " ", text or "")
        s = re.sub(r"\s+", " ", s).strip()
        if len(s) <= max_len:
            return s
        words = s.split(" ")
        while len(words) > 1 and len(" ".join(words)) > max_len:
            words.pop()
        s = " ".join(words).strip()
        return (s or re.sub(r"[^A-Za-z0-9().-]+", "", text or ""))[:max_len].strip()

    def post_json_sync(self, url: str, api_key: str, payload: dict, timeout: int = 90) -> dict:
        url = self.normalize_chat_api_url(url)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body[:500]}") from exc

    @staticmethod
    def extract_json_object(text: str) -> dict:
        s = (text or "").strip()
        s = re.sub(r"^```(?:json)?", "", s, flags=re.I).strip()
        s = re.sub(r"```$", "", s).strip()
        try:
            return json.loads(s)
        except Exception:
            pass
        match = re.search(r"\{[\s\S]*\}", s)
        if not match:
            raise ValueError("AI response does not contain a JSON object")
        return json.loads(match.group(0))

    @staticmethod
    def normalize_chat_api_url(url: str) -> str:
        value = (url or "").strip().rstrip("/")
        if not value:
            return value
        lowered = value.lower()
        if lowered.endswith("/chat/completions") or lowered.endswith("/messages"):
            return value
        return value + "/chat/completions"

    async def collect_product_snapshot(self) -> dict:
        if not self.page:
            return {}
        return await self.page.evaluate(
            """() => {
                const norm = (v) => (v || "").replace(/\s+/g, " ").trim();
                const visible = (el) => {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return st.display !== "none" && st.visibility !== "hidden" && r.width > 0 && r.height > 0;
                };
                const cardByTitle = (name) => {
                    const titles = Array.from(document.querySelectorAll("h4.form-card-title,h4,.form-card-title"));
                    const title = titles.find((el) => norm(el.innerText || el.textContent).includes(name));
                    return title ? title.closest(".form-card") : null;
                };
                const basicCard = cardByTitle("基本信息") || document;
                const productCard = cardByTitle("产品信息") || Array.from(document.querySelectorAll(".form-card"))
                    .find((card) => {
                        const t = norm(card.innerText || card.textContent);
                        return t.includes("产品图片") || t.includes("零售价") || t.includes("自定义名称");
                    }) || document;
                const titleInputs = Array.from(basicCard.querySelectorAll("input"))
                    .filter((input) => visible(input) && input.type !== "hidden" && input.type !== "search");
                const titleInput = titleInputs.find((input) => norm(input.value).length > 12)
                    || titleInputs.sort((a, b) => norm(b.value).length - norm(a.value).length)[0];
                const imageInfo = (img) => {
                    const rect = img.getBoundingClientRect();
                    return {
                        src: img.currentSrc || img.src || img.getAttribute("data-src") || "",
                        w: Math.round(rect.width),
                        h: Math.round(rect.height),
                        naturalW: img.naturalWidth || 0,
                        naturalH: img.naturalHeight || 0
                    };
                };
                const productImages = Array.from(productCard.querySelectorAll("img"))
                    .filter(visible)
                    .map(imageInfo)
                    .filter((info) => info.src && /^https?:/i.test(info.src) && !info.src.includes("addImg-"));
                const selectedCountMatch = norm(productCard.innerText || "").match(/已经选用了\s*(\d+)\s*张/);
                const selectedMainCount = selectedCountMatch ? Number(selectedCountMatch[1]) : 6;
                const mainImages = productImages
                    .filter((info) => (info.w >= 80 && info.h >= 80) || (info.naturalW >= 500 && info.naturalH >= 500))
                    .slice(0, selectedMainCount)
                    .map((info) => info.src);
                const skuTable = Array.from(document.querySelectorAll("table, .ant-table, .ant-table-container"))
                    .find((el) => {
                        const text = norm(el.innerText || el.textContent);
                        return text.includes("自定义名称") || text.includes("批量编辑");
                    });
                const skuScope = skuTable || productCard || document;
                let skuInputNodes = Array.from(skuScope.querySelectorAll(
                    "tbody tr input[type='text'], tbody tr input:not([type]), input.hide-error[maxlength='20'], input[maxlength='20']"
                )).filter((input) => visible(input));
                if (!skuInputNodes.length) {
                    skuInputNodes = Array.from(document.querySelectorAll(
                        "table tbody input[type='text'], table tbody input:not([type]), .ant-table input[type='text'], .ant-table input:not([type]), input.hide-error[maxlength='20'], input[maxlength='20']"
                    )).filter((input) => visible(input));
                }
                const skuInputs = skuInputNodes
                    .filter((input) => visible(input))
                    .map((input) => norm(input.value))
                    .filter((value) => value && value.length <= 80)
                    .filter((value) => !/^https?:/i.test(value) && !/^\d+(\.\d+)?$/.test(value))
                    .filter((value) => !value.includes(",") && !/白底图|场景图|颜色分类/.test(value));
                const skuNames = Array.from(new Set(skuInputs)).slice(0, 30);
                return {
                    originalTitle: norm(titleInput ? titleInput.value : ""),
                    skuNames,
                    mainImages: Array.from(new Set(mainImages)).slice(0, 10),
                    url: location.href
                };
            }"""
        )

    async def call_ai_text_optimizer(self, snapshot: dict) -> Optional[dict]:
        api_url = str(CONFIG.get("ai_text_api_url", "")).strip()
        api_key = str(CONFIG.get("ai_text_api_key", "")).strip()
        model = str(CONFIG.get("ai_text_model", "")).strip() or "deepseek-v4-flash"
        if model in {"deepseek-chat", "deepseek-reasoner"}:
            logger.warning(f"检测到即将弃用的DeepSeek模型 {model}，自动切换为 deepseek-v4-flash")
            model = "deepseek-v4-flash"
        if not api_url or not api_key:
            logger.warning("AI标题/SKU已开启，但文本API地址或API Key为空，跳过AI文本优化")
            return None

        system_prompt = str(CONFIG.get("ai_text_prompt", "")).strip() or (
            "Translate and optimize AliExpress listing text into compliant English. Return strict JSON."
        )
        user_payload = {
            "title": snapshot.get("originalTitle", ""),
            "sku_names": snapshot.get("skuNames", []),
            "category": str(CONFIG.get("category", "")),
            "rules": [
                (
                    "Return JSON only with this schema: "
                    "{\"title\":\"...\",\"sku_names\":[{\"original\":\"...\",\"suggested\":\"...\"}],"
                    "\"vehicle_fitment\":{\"brands\":[],\"models\":[],\"years\":[],\"body_or_trim\":[],\"notes\":\"\"},"
                    "\"product_attributes\":{\"product_type\":\"\",\"position\":\"\",\"material\":\"\",\"color\":\"\",\"oem\":\"\",\"keywords\":[]},"
                    "\"image_context\":\"\"}"
                ),
                "Title must be English and <= 128 characters.",
                "SKU suggested names must be <= 20 chars and only English letters, digits, spaces, parentheses, dots and hyphens.",
                "Extract vehicle brands, models, years and trims only when clearly present in the source title/SKU/category. Do not guess missing fitment.",
                "Keep brand/model words when they describe compatibility or search intent, but do not claim official/original/genuine unless present.",
                "image_context must be one short English sentence for image prompt context. It must not ask to add text, logos, badges, brand marks or watermarks.",
                "No trademark logo, no watermark, no exaggerated claims."
            ]
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }
        logger.info("正在调用AI文本接口优化标题/SKU...")
        data = await asyncio.to_thread(self.post_json_sync, api_url, api_key, payload)
        content = ""
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            content = json.dumps(data, ensure_ascii=False)
        result = self.extract_json_object(content)
        title = self.compact_title(str(result.get("title", "")), 128)
        sku_items = result.get("sku_names", [])
        if isinstance(sku_items, dict):
            sku_items = [{"original": k, "suggested": v} for k, v in sku_items.items()]
        cleaned_skus = []
        for item in sku_items if isinstance(sku_items, list) else []:
            if isinstance(item, str):
                cleaned_skus.append({"original": item, "suggested": self.sanitize_sku_name(item)})
            elif isinstance(item, dict):
                original = str(item.get("original", "")).strip()
                suggested = self.sanitize_sku_name(str(item.get("suggested", "") or item.get("name", "")))
                if original and suggested:
                    cleaned_skus.append({"original": original, "suggested": suggested})
        context = self.normalize_ai_product_context(result)
        return {"title": title, "sku_names": cleaned_skus, **context}

    @staticmethod
    def _clean_text_list(value, max_items: int = 12, max_len: int = 60) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            parts = re.split(r"[,;/，；、|]+", value)
        elif isinstance(value, (list, tuple, set)):
            parts = list(value)
        else:
            return []
        cleaned = []
        seen = set()
        for item in parts:
            text = re.sub(r"\s+", " ", str(item or "")).strip()
            if not text:
                continue
            text = text[:max_len]
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
            if len(cleaned) >= max_items:
                break
        return cleaned

    def normalize_ai_product_context(self, result: dict) -> dict:
        fitment = result.get("vehicle_fitment") if isinstance(result.get("vehicle_fitment"), dict) else {}
        attrs = result.get("product_attributes") if isinstance(result.get("product_attributes"), dict) else {}

        normalized_fitment = {
            "brands": self._clean_text_list(fitment.get("brands")),
            "models": self._clean_text_list(fitment.get("models")),
            "years": self._clean_text_list(fitment.get("years")),
            "body_or_trim": self._clean_text_list(fitment.get("body_or_trim")),
            "notes": re.sub(r"\s+", " ", str(fitment.get("notes", "") or "")).strip()[:180],
        }
        normalized_attrs = {
            "product_type": re.sub(r"\s+", " ", str(attrs.get("product_type", "") or "")).strip()[:80],
            "position": re.sub(r"\s+", " ", str(attrs.get("position", "") or "")).strip()[:60],
            "material": re.sub(r"\s+", " ", str(attrs.get("material", "") or "")).strip()[:60],
            "color": re.sub(r"\s+", " ", str(attrs.get("color", "") or "")).strip()[:60],
            "oem": re.sub(r"\s+", " ", str(attrs.get("oem", "") or "")).strip()[:80],
            "keywords": self._clean_text_list(attrs.get("keywords"), max_items=10, max_len=40),
        }
        image_context = re.sub(r"\s+", " ", str(result.get("image_context", "") or "")).strip()[:240]
        blocked = ["logo", "watermark", "brand mark", "badge", "text"]
        if any(re.search(rf"\b(add|include|show|display)\s+.*\b{re.escape(word)}\b", image_context, re.I) for word in blocked):
            image_context = ""

        return {
            "vehicle_fitment": normalized_fitment,
            "product_attributes": normalized_attrs,
            "image_context": image_context,
        }

    def save_ai_text_context(self, snapshot: dict, result: dict) -> Optional[Path]:
        try:
            out_dir = self.OUTPUT_DIR / "ai_text_context"
            out_dir.mkdir(parents=True, exist_ok=True)
            digest_src = f"{snapshot.get('url', '')}|{snapshot.get('originalTitle', '')}"
            digest = hashlib.md5(digest_src.encode("utf-8", errors="ignore")).hexdigest()[:10]
            path = out_dir / f"context_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{digest}.json"
            payload = {
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "page_url": snapshot.get("url", ""),
                "source": {
                    "title": snapshot.get("originalTitle", ""),
                    "sku_names": snapshot.get("skuNames", []),
                    "category": str(CONFIG.get("category", "")),
                },
                "ai_result": result,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return path
        except Exception as exc:
            logger.warning(f"保存AI产品上下文失败: {exc}")
            return None

    async def prepare_ai_text_context(self, apply_to_page: bool = False) -> Optional[dict]:
        if not self.config_enabled("enable_ai_text"):
            return None
        try:
            snapshot = await self.collect_product_snapshot()
            if not snapshot.get("originalTitle") and not snapshot.get("skuNames"):
                logger.warning("未读取到标题/SKU，跳过AI文本优化")
                return None

            cache_key = f"{snapshot.get('url', '')}|{snapshot.get('originalTitle', '')}|{','.join(snapshot.get('skuNames', [])[:20])}"
            cached = self.ai_text_cache.get(cache_key)
            if cached:
                cached_sku_count = len(cached.get("sku_names", []) or [])
                current_sku_count = len(snapshot.get("skuNames", []) or [])
                if current_sku_count > 0 and cached_sku_count == 0:
                    logger.warning(
                        f"AI文本缓存缺少SKU结果，当前已采集到SKU={current_sku_count}，重新调用AI文本接口"
                    )
                    cached = None
                else:
                    result = cached
                    logger.info("复用当前商品AI文本上下文缓存")
            if not cached:
                logger.info(
                    f"AI文本输入: title_len={len(snapshot.get('originalTitle', ''))}, "
                    f"sku_count={len(snapshot.get('skuNames', []))}, "
                    f"sku_preview={snapshot.get('skuNames', [])[:5]}"
                )
                result = await self.call_ai_text_optimizer(snapshot)
                if not result:
                    return None
                self.ai_text_cache = {cache_key: result}
                saved_path = self.save_ai_text_context(snapshot, result)
                if saved_path:
                    logger.success(f"AI产品上下文已保存: {saved_path}")

            self.current_ai_product_context = {
                "vehicle_fitment": result.get("vehicle_fitment", {}),
                "product_attributes": result.get("product_attributes", {}),
                "image_context": result.get("image_context", ""),
                "title": result.get("title", ""),
            }

            if apply_to_page:
                applied = await self.apply_ai_text_result(result)
                logger.success(
                    f"AI标题/SKU写回完成: title={applied.get('titleWritten')}, "
                    f"sku={applied.get('skuWritten')}/{applied.get('skuTotal')}, "
                    f"sku_inputs={applied.get('skuInputCount')}"
                )
            return result
        except Exception as exc:
            logger.warning(f"AI标题/SKU优化失败，继续使用页面现有内容: {exc}")
            write_error_trace("prepare_ai_text_context", exc)
            return None

    async def apply_ai_text_result(self, result: dict) -> dict:
        if not self.page:
            return {"ok": False}
        return await self.page.evaluate(
            """(payload) => {
                const norm = (v) => (v || "").replace(/\s+/g, " ").trim();
                const visible = (el) => {
                    if (!el || !el.getBoundingClientRect) return false;
                    const r = el.getBoundingClientRect();
                    const st = getComputedStyle(el);
                    return st.display !== "none" && st.visibility !== "hidden" && r.width > 0 && r.height > 0;
                };
                const setInput = (input, value) => {
                    input.scrollIntoView({ block: "center", inline: "nearest" });
                    input.focus();
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
                    if (setter) setter.call(input, value); else input.value = value;
                    input.dispatchEvent(new Event("input", { bubbles: true }));
                    input.dispatchEvent(new Event("change", { bubbles: true }));
                    input.blur();
                };
                const cardByTitle = (name) => {
                    const titles = Array.from(document.querySelectorAll("h4.form-card-title,h4,.form-card-title"));
                    const title = titles.find((el) => norm(el.innerText || el.textContent).includes(name));
                    return title ? title.closest(".form-card") : null;
                };
                const basicCard = cardByTitle("基本信息") || document;
                const productCard = cardByTitle("产品信息") || document;
                let titleWritten = false;
                if (payload.title) {
                    const inputs = Array.from(basicCard.querySelectorAll("input"))
                        .filter((input) => visible(input) && input.type !== "hidden" && input.type !== "search");
                    const target = inputs.find((input) => norm(input.value).length > 12)
                        || inputs.sort((a, b) => norm(b.value).length - norm(a.value).length)[0];
                    if (target) {
                        setInput(target, payload.title);
                        titleWritten = true;
                    }
                }
                const skuPayload = Array.isArray(payload.sku_names) ? payload.sku_names : [];
                const skuTable = Array.from(document.querySelectorAll("table, .ant-table, .ant-table-container"))
                    .find((el) => {
                        const text = norm(el.innerText || el.textContent);
                        return text.includes("自定义名称") || text.includes("批量编辑");
                    });
                const skuScope = skuTable || productCard || document;
                let skuInputs = Array.from(skuScope.querySelectorAll("tbody tr input[type='text'], tbody tr input:not([type])"))
                    .filter((input) => visible(input));
                if (!skuInputs.length) {
                    skuInputs = Array.from(skuScope.querySelectorAll("input[type='text'],input:not([type])"))
                        .filter((input) => visible(input));
                }
                skuInputs = skuInputs.filter((input) => {
                    const value = norm(input.value);
                    const rect = input.getBoundingClientRect();
                    if (!value || /^https?:/i.test(value) || /^\d+(\.\d+)?$/.test(value)) return false;
                    if (value.includes(",")) return false;
                    if (rect.width < 60) return false;
                    return true;
                });
                const used = new Set();
                let skuWritten = 0;
                for (let i = 0; i < skuPayload.length; i += 1) {
                    const item = skuPayload[i] || {};
                    const original = norm(item.original);
                    const suggested = norm(item.suggested);
                    if (!suggested) continue;
                    let idx = skuInputs.findIndex((input, n) => !used.has(n) && norm(input.value).toLowerCase() === original.toLowerCase());
                    if (idx < 0 && original) {
                        idx = skuInputs.findIndex((input, n) => !used.has(n) && norm(input.value).includes(original));
                    }
                    if (idx < 0 && i < skuInputs.length) idx = i;
                    const input = skuInputs[idx];
                    if (input) {
                        setInput(input, suggested);
                        used.add(idx);
                        skuWritten += 1;
                    }
                }
                return {
                    ok: titleWritten || skuWritten > 0,
                    titleWritten,
                    skuWritten,
                    skuTotal: skuPayload.length,
                    skuInputCount: skuInputs.length,
                    skuValuesBefore: skuInputs.slice(0, 8).map((input) => norm(input.value))
                };
            }""",
            result
        )

    async def step_ai_text_optimization(self):
        if not self.config_enabled("enable_ai_text"):
            return
        await self.prepare_ai_text_context(apply_to_page=True)

    def download_image_sync(self, url: str, out_path: Path, timeout: int = 90) -> Path:
        if out_path.exists() and out_path.stat().st_size > 1024:
            return out_path

        out_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = out_path.with_suffix(out_path.suffix + ".part")
        try:
            if part_path.exists():
                part_path.unlink()
            curl_cmd = [
                "curl.exe",
                "-L",
                "--fail",
                "--silent",
                "--show-error",
                "--connect-timeout",
                "10",
                "--max-time",
                str(max(15, int(timeout))),
                "-A",
                "Mozilla/5.0",
                "-o",
                str(part_path),
                url,
            ]
            result = subprocess.run(
                curl_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=max(20, int(timeout) + 5),
            )
            if result.returncode == 0 and part_path.exists() and part_path.stat().st_size > 1024:
                if out_path.exists():
                    out_path.unlink()
                part_path.replace(out_path)
                return out_path
            if part_path.exists():
                part_path.unlink()
        except Exception:
            try:
                if part_path.exists():
                    part_path.unlink()
            except Exception:
                pass

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Connection": "close",
        }
        req = urllib.request.Request(url, headers=headers)
        resp = None
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
            content_length = 0
            try:
                content_length = int(resp.headers.get("Content-Length") or "0")
            except Exception:
                content_length = 0
            total = 0
            max_bytes = 25 * 1024 * 1024
            with open(out_path, "wb") as f:
                while True:
                    if content_length and total >= content_length:
                        break
                    chunk = resp.read(1024 * 128)
                    if not chunk:
                        break
                    f.write(chunk)
                    total += len(chunk)
                    if content_length and total >= content_length:
                        break
                    if total > max_bytes:
                        raise RuntimeError(f"image too large: {total} bytes")
            if total <= 0:
                raise RuntimeError("downloaded image is empty")
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass
        return out_path

    def build_ai_image_prompt(self, base_prompt: str) -> str:
        prompt = (base_prompt or "").strip()
        if str(CONFIG.get("ai_image_use_product_context", "否")).strip() != "是":
            return prompt
        context = self.current_ai_product_context if isinstance(self.current_ai_product_context, dict) else {}
        if not context:
            return prompt

        fitment = context.get("vehicle_fitment") if isinstance(context.get("vehicle_fitment"), dict) else {}
        attrs = context.get("product_attributes") if isinstance(context.get("product_attributes"), dict) else {}
        parts = []
        product_type = str(attrs.get("product_type", "") or "").strip()
        position = str(attrs.get("position", "") or "").strip()
        material = str(attrs.get("material", "") or "").strip()
        color = str(attrs.get("color", "") or "").strip()
        if product_type:
            parts.append(f"product type: {product_type}")
        if position:
            parts.append(f"position: {position}")
        if material:
            parts.append(f"material: {material}")
        if color:
            parts.append(f"color: {color}")

        brands = ", ".join(self._clean_text_list(fitment.get("brands"), max_items=6))
        models = ", ".join(self._clean_text_list(fitment.get("models"), max_items=8))
        years = ", ".join(self._clean_text_list(fitment.get("years"), max_items=8))
        trims = ", ".join(self._clean_text_list(fitment.get("body_or_trim"), max_items=6))
        vehicle_bits = []
        if brands:
            vehicle_bits.append(brands)
        if models:
            vehicle_bits.append(models)
        if years:
            vehicle_bits.append(years)
        if trims:
            vehicle_bits.append(trims)
        if vehicle_bits:
            parts.append("compatible vehicle context: " + " ".join(vehicle_bits))

        image_context = str(context.get("image_context", "") or "").strip()
        if image_context:
            parts.append(image_context)
        if not parts:
            return prompt

        suffix = (
            " Product context for preserving accurate shape and fitment: "
            + "; ".join(parts)
            + ". Use this context only to preserve product shape, angle and proportions. "
            "Do not add text, logos, badges, brand marks, model names or watermarks."
        )
        final_prompt = (prompt.rstrip() + suffix).strip()
        return final_prompt[:1800]

    def post_image_sync(self, image_path: Path) -> Path:
        api_url = str(CONFIG.get("ai_image_api_url", "")).strip()
        api_key = str(CONFIG.get("ai_image_api_key", "")).strip()
        if not api_url or not api_key:
            raise RuntimeError("AI image API url/key is empty")
        prompt = self.build_ai_image_prompt(str(CONFIG.get("ai_image_prompt", "")).strip())
        size = str(CONFIG.get("ai_image_size", "")).strip() or "1024x1024"
        model = str(CONFIG.get("ai_image_model", "")).strip() or "gpt-image-2"
        if self.is_volcengine_seedream(api_url, model):
            return self.post_volcengine_seedream_image_sync(str(image_path), api_url, api_key, model, prompt, size)
        if model == "gpt-image-2" or "/v1/images/generations" in api_url:
            return self.post_geeknow_gpt_image_sync(image_path, api_url, api_key, model, prompt, size)

        boundary = "----ShopAutomationBoundary" + uuid.uuid4().hex
        mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"

        def field(name: str, value: str) -> bytes:
            return (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")

        body = bytearray()
        for key, value in [("prompt", prompt), ("size", size)]:
            if value:
                body.extend(field(key, value))
        if model:
            body.extend(field("model", model))
        body.extend(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode("utf-8")
        )
        body.extend(image_path.read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))

        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Authorization": f"Bearer {api_key}"}
        req = urllib.request.Request(api_url, data=bytes(body), headers=headers, method="POST")
        out_dir = self.OUTPUT_DIR / "ai_images"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"processed_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}.png"
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                content_type = resp.headers.get("Content-Type", "")
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Image API HTTP {exc.code}: {body_text[:500]}") from exc

        if content_type.startswith("image/"):
            out_path.write_bytes(raw)
            return out_path

        data = json.loads(raw.decode("utf-8", errors="replace"))
        first = data.get("data", [data])[0] if isinstance(data.get("data"), list) else data
        b64 = first.get("b64_json") or first.get("image_base64") or first.get("base64") or data.get("b64_json")
        image_url = first.get("url") or first.get("image_url") or data.get("url") or data.get("image_url")
        if b64:
            out_path.write_bytes(base64.b64decode(re.sub(r"^data:image/\w+;base64,", "", b64)))
            return out_path
        if image_url:
            return self.download_image_sync(image_url, out_path)
        raise RuntimeError("Image API response has no image data")

    def post_geeknow_gpt_image_sync(
        self,
        image_path: Path,
        api_url: str,
        api_key: str,
        model: str,
        prompt: str,
        size: str,
    ) -> Path:
        out_dir = self.OUTPUT_DIR / "ai_images"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"processed_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}.png"

        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": model,
            "prompt": prompt,
            "image": [image_b64],
            "n": 1,
            "size": size,
            "response_format": "url",
            "watermark": False,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        req = urllib.request.Request(api_url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GeekNow image API HTTP {exc.code}: {body_text[:500]}") from exc

        result = json.loads(raw.decode("utf-8", errors="replace"))
        first = result.get("data", [result])[0] if isinstance(result.get("data"), list) else result
        b64 = first.get("b64_json") or first.get("image_base64") or first.get("base64") or result.get("b64_json")
        image_url = first.get("url") or first.get("image_url") or result.get("url") or result.get("image_url")

        if image_url:
            return self.download_image_sync(image_url, out_path)
        if b64:
            out_path.write_bytes(base64.b64decode(re.sub(r"^data:image/\w+;base64,", "", b64)))
            return out_path
        raise RuntimeError("GeekNow image API response has no url/b64_json image data")

    @staticmethod
    def is_volcengine_seedream(api_url: str, model: str) -> bool:
        value = f"{api_url or ''} {model or ''}".lower()
        return "volces.com" in value or "volcengine" in value or "seedream" in value or "doubao-seedream" in value

    @staticmethod
    def normalize_volcengine_seedream_model(model: str) -> str:
        raw = (model or "").strip()
        if not raw:
            return "doubao-seedream-5-0-260128"
        normalized = raw.lower()
        normalized = normalized.replace("doubao-", "doubao-")
        normalized = re.sub(r"[\s_]+", "-", normalized)
        normalized = normalized.replace(".", "-")
        normalized = re.sub(r"-+", "-", normalized).strip("-")

        aliases = {
            "doubao-seedream-5-0-pro-260628": "doubao-seedream-5-0-pro-260628",
            "seedream-5-0-pro-260628": "doubao-seedream-5-0-pro-260628",
            "doubao-seedream-5-0-pro": "doubao-seedream-5-0-pro-260628",
            "seedream-5-0-pro": "doubao-seedream-5-0-pro-260628",
            "doubao-seedream-5-0-lite": "doubao-seedream-5-0-260128",
            "seedream-5-0-lite": "doubao-seedream-5-0-260128",
            "doubao-seedream-5-0-260128": "doubao-seedream-5-0-260128",
            "seedream-5-0-260128": "doubao-seedream-5-0-260128",
        }
        if normalized in aliases:
            mapped = aliases[normalized]
            if mapped != raw:
                logger.info(f"火山Seedream模型名已规范化: {raw} -> {mapped}")
            return mapped
        return raw

    @staticmethod
    def volcengine_image_url(api_url: str) -> str:
        value = (api_url or "").strip().rstrip("/")
        if not value:
            return "https://ark.cn-beijing.volces.com/api/v3/images/generations"
        if value.endswith("/api/v3/images/generations"):
            return value
        if value.endswith("/images/generations"):
            return value
        return value + "/api/v3/images/generations"

    @staticmethod
    def normalize_volcengine_seedream_size(size: str) -> tuple[str, Optional[int]]:
        """
        火山 Seedream 5.0 lite 控制台示例使用 2K 这类生成规格。
        用户填 1K/1024x1024 时，接口仍按 2K 生成，下载后本地压成 1024x1024。
        """
        raw = (size or "").strip()
        normalized = raw.lower().replace(" ", "")
        if normalized in {"1k", "1024", "1024x1024", "1024*1024"}:
            return "2K", 1024
        return raw or "2K", None

    def resize_image_to_square_sync(self, image_path: Path, side: int = 1024) -> Path:
        try:
            from PIL import Image
        except Exception as exc:
            logger.warning(f"未安装Pillow，无法压缩为{side}x{side}，保留原图上传: {exc}")
            return image_path

        side = int(side or 1024)
        out_path = image_path.with_name(f"{image_path.stem}_{side}x{side}.png")
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            canvas = Image.new("RGB", (side, side), (242, 242, 242))
            scale = min(side / img.width, side / img.height)
            new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
            resized = img.resize(new_size, Image.Resampling.LANCZOS)
            left = (side - new_size[0]) // 2
            top = (side - new_size[1]) // 2
            canvas.paste(resized, (left, top))
            canvas.save(out_path, format="PNG", optimize=True)
        logger.success(f"AI主图已压缩为{side}x{side}正方形: {out_path}")
        return out_path

    def post_volcengine_seedream_image_sync(
        self,
        image_path_or_url: str,
        api_url: str,
        api_key: str,
        model: str,
        prompt: str,
        size: str,
    ) -> Path:
        if not api_key:
            raise RuntimeError("Volcengine Seedream API key is empty")

        submit_url = self.volcengine_image_url(api_url)
        model = self.normalize_volcengine_seedream_model(model)
        request_size, final_square_side = self.normalize_volcengine_seedream_size(size)
        prompt = prompt or (
            "保持商品主体完全不变，去除原背景和水印，将产品放在统一的浅灰色电商棚拍背景中。"
            "不要添加文字、logo、品牌标识、边框或装饰元素。画面干净真实，产品居中，1:1正方形构图，适合速卖通主图。"
        )
        if "1:1" not in prompt and "正方形" not in prompt:
            prompt = prompt.rstrip("。") + "。请输出1:1正方形构图。"

        image_value = str(image_path_or_url or "").strip()
        image_hint = "empty"
        if image_value.lower().startswith(("http://", "https://")):
            image_hint = urllib.parse.urlparse(image_value).netloc or "url"
        else:
            maybe_path = Path(image_value)
            if maybe_path.exists():
                mime = mimetypes.guess_type(str(maybe_path))[0] or "image/jpeg"
                b64 = base64.b64encode(maybe_path.read_bytes()).decode("ascii")
                image_value = f"data:{mime};base64,{b64}"
                image_hint = f"local-base64:{maybe_path.name}:{len(b64)} chars"
            else:
                image_hint = "raw-value"

        payload = {
            "model": model,
            "prompt": prompt,
            "image": [image_value] if image_value else [],
            "response_format": "url",
            "size": request_size,
            "watermark": False,
        }

        timeout = int(CONFIG.get("ai_image_timeout_sec", 1800) or 1800)
        timeout = max(60, min(timeout, 900))
        logger.info(
            f"火山Seedream生图提交: {submit_url}, model={model}, size={request_size}, "
            f"final_square={final_square_side or '原尺寸'}, "
            f"image={image_hint}, prompt_len={len(prompt)}"
        )
        result = self.request_json_sync(submit_url, api_key, payload=payload, method="POST", timeout=timeout)
        logger.info("火山Seedream生图请求已返回")

        out_dir = self.OUTPUT_DIR / "ai_images"
        out_dir.mkdir(parents=True, exist_ok=True)
        proof_path = out_dir / f"volcengine_seedream_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}.json"
        image_path = self.write_image_response_to_file(result)
        if final_square_side:
            image_path = self.resize_image_to_square_sync(image_path, final_square_side)

        data = result.get("data") if isinstance(result.get("data"), list) else []
        first = data[0] if data and isinstance(data[0], dict) else {}
        image_url = first.get("url") or first.get("image_url") or result.get("url") or result.get("image_url")
        proof_payload = {
            "provider": "volcengine_seedream",
            "submit_url": submit_url,
            "model": model,
            "request_size": request_size,
            "final_square_side": final_square_side,
            "input_image": image_hint,
            "output_url": image_url,
            "local_image_path": str(image_path),
            "raw_response": result,
        }
        proof_path.write_text(json.dumps(proof_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.success(f"火山Seedream生图结果已保存: local={image_path}, proof={proof_path}")
        if image_url:
            logger.info(f"火山Seedream输出URL: {image_url}")
        return image_path

    @staticmethod
    def geeknow_async_url(api_url: str) -> str:
        value = (api_url or "").strip().rstrip("/")
        if value.endswith("/async"):
            return value
        if value.endswith("/v1/images/generations"):
            return value + "/async"
        return value + "/v1/images/generations/async"

    def request_json_sync(
        self,
        url: str,
        api_key: str,
        payload: Optional[dict] = None,
        method: str = "GET",
        timeout: int = 45,
    ) -> dict:
        method = (method or "GET").upper()
        timeout = max(10, int(timeout or 45))
        tmp_path = None
        marker = "\n__HTTP_STATUS__:"
        cmd = [
            "curl.exe",
            "-L",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "10",
            "--max-time",
            str(timeout),
            "-X",
            method,
            "-H",
            "Accept: application/json",
            "-H",
            f"Authorization: Bearer {api_key}",
        ]
        if payload is not None:
            tmp_path = self.OUTPUT_DIR / "ai_images" / f"request_{uuid.uuid4().hex}.json"
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            cmd.extend(["-H", "Content-Type: application/json", "--data-binary", "@" + str(tmp_path)])
        cmd.extend(["-w", marker + "%{http_code}", url])
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout + 5,
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            body = stdout
            status = ""
            if marker in stdout:
                body, status = stdout.rsplit(marker, 1)
                status = status.strip()
            body = body.strip()
            if result.returncode != 0:
                raise RuntimeError(f"curl请求失败: method={method}, code={result.returncode}, http={status or 'unknown'}, error={(stderr or body)[:500]}")
            if status and status.isdigit() and int(status) >= 400:
                raise RuntimeError(f"HTTP {status}: {body[:500]}")
            if not body:
                raise RuntimeError(f"接口返回为空: method={method}, http={status or 'unknown'}")
            try:
                return json.loads(body)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"接口返回不是JSON: method={method}, http={status or 'unknown'}, body={body[:500]}") from exc
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def write_image_response_to_file(self, response: dict) -> Path:
        out_dir = self.OUTPUT_DIR / "ai_images"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"processed_{int(datetime.now().timestamp())}_{uuid.uuid4().hex[:8]}.png"

        data = response.get("data") if isinstance(response, dict) else None
        first = data[0] if isinstance(data, list) and data else response
        if not isinstance(first, dict):
            first = {}
        b64 = (
            first.get("b64_json")
            or first.get("image_base64")
            or first.get("base64")
            or response.get("b64_json")
            or response.get("image_base64")
        )
        image_url = first.get("url") or first.get("image_url") or response.get("url") or response.get("image_url")
        if image_url:
            return self.download_image_sync(image_url, out_path, timeout=90)
        if b64:
            out_path.write_bytes(base64.b64decode(re.sub(r"^data:image/\w+;base64,", "", str(b64))))
            return out_path
        raise RuntimeError("image response has no url/b64_json")

    def post_geeknow_gpt_image_async_from_url_sync(
        self,
        image_path_or_url: str,
        api_url: str,
        api_key: str,
        model: str,
        prompt: str,
        size: str,
    ) -> Path:
        logger.info("GeekNow异步生图函数进入")
        logger.info(f"GeekNow异步生图配置: api_url={api_url}, model={model or 'gpt-image-2'}, size={size or '1024x1024'}")
        submit_url = self.geeknow_async_url(api_url)
        logger.info(f"GeekNow异步生图提交地址已生成: {submit_url}")
        image_value = image_path_or_url
        is_url_image = str(image_path_or_url).lower().startswith(("http://", "https://"))
        if not is_url_image:
            try:
                maybe_path = Path(image_path_or_url)
                if maybe_path.exists():
                    image_value = base64.b64encode(maybe_path.read_bytes()).decode("ascii")
            except Exception:
                image_value = image_path_or_url
        image_hint = "url"
        if is_url_image:
            image_hint = urllib.parse.urlparse(str(image_path_or_url)).netloc or "url"
        elif image_value != image_path_or_url:
            image_hint = f"base64:{len(str(image_value))} chars"
        else:
            image_hint = "raw-local-value"
        payload = {
            "model": model or "gpt-image-2",
            "prompt": prompt,
            "image": [image_value],
            "n": 1,
            "size": size or "1024x1024",
            "response_format": "url",
            "watermark": False,
        }
        logger.info(f"GeekNow异步生图提交: {submit_url}, image={image_hint}, prompt_len={len(prompt or '')}")
        submitted = self.request_json_sync(submit_url, api_key, payload=payload, method="POST", timeout=45)
        logger.info("GeekNow异步生图提交请求已返回")
        submitted_data = submitted.get("data") if isinstance(submitted.get("data"), dict) else {}
        task_id = (
            submitted.get("id")
            or submitted.get("task_id")
            or submitted.get("taskId")
            or submitted_data.get("id")
            or submitted_data.get("task_id")
            or submitted_data.get("taskId")
        )
        if not task_id:
            try:
                return self.write_image_response_to_file(submitted)
            except Exception:
                raise RuntimeError(f"GeekNow async response has no task id: {json.dumps(submitted, ensure_ascii=False)[:500]}")

        logger.success(f"GeekNow异步生图任务已创建: {task_id}")
        query_url = submit_url.rstrip("/") + "/" + urllib.parse.quote(str(task_id), safe="")
        max_wait = int(CONFIG.get("ai_image_timeout_sec", 1800) or 1800)
        poll_interval = int(CONFIG.get("ai_image_poll_interval_sec", 15) or 15)
        started = time.monotonic()

        while True:
            elapsed = int(time.monotonic() - started)
            if elapsed > max_wait:
                raise TimeoutError(f"GeekNow异步生图超时: task_id={task_id}, waited={elapsed}s")
            logger.info(f"GeekNow异步生图轮询: task_id={task_id}, elapsed={elapsed}s")
            time.sleep(poll_interval)
            result = self.request_json_sync(query_url, api_key, method="GET", timeout=45)
            result_data = result.get("data") if isinstance(result.get("data"), dict) else {}
            status = str(result.get("status") or result.get("state") or result.get("task_status") or result_data.get("status") or "").lower()
            if status in {"failed", "fail", "error", "cancelled", "canceled"}:
                raise RuntimeError(f"GeekNow异步生图失败: {json.dumps(result, ensure_ascii=False)[:500]}")
            try:
                image_path = self.write_image_response_to_file(result)
                usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
                data = result.get("data") if isinstance(result.get("data"), list) else []
                first = data[0] if data and isinstance(data[0], dict) else {}
                image_url = first.get("url") or first.get("image_url") or result.get("url") or result.get("image_url")
                proof_path = self.OUTPUT_DIR / "ai_images" / f"{task_id}_result.json"
                proof_payload = {
                    "task_id": str(task_id),
                    "query_url": query_url,
                    "image_url": image_url,
                    "local_image_path": str(image_path),
                    "usage": usage,
                    "raw_response": result,
                }
                proof_path.write_text(json.dumps(proof_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.success(
                    f"GeekNow异步生图结果已保存: task_id={task_id}, local={image_path}, "
                    f"input={usage.get('input_tokens')}, output={usage.get('output_tokens')}, proof={proof_path}"
                )
                if image_url:
                    logger.info(f"GeekNow异步生图输出URL: {image_url}")
                return image_path
            except Exception:
                if status in {"success", "succeeded", "completed", "done"}:
                    raise
                continue

    async def upload_image_file(self, file_path: Path) -> bool:
        if not self.page:
            return False
        try:
            before = await self.get_main_image_gallery_snapshot()
            before_count = int(before.get("count") or 0)
            before_checked = int(before.get("checkedCount") or 0)
            before_srcs = {str(item.get("src") or "") for item in before.get("items", [])}
            first_before = (before.get("items") or [{}])[0].get("src") if before.get("items") else ""

            uploaded = await self.upload_main_image_via_local_menu(file_path, before_count)
            if not uploaded.get("ok"):
                logger.warning(f"AI主图本地上传失败: {uploaded}")
                return False

            after_upload = await self.get_main_image_gallery_snapshot()
            uploaded_item = self.find_uploaded_main_image(after_upload, before_srcs, before_count)
            if not uploaded_item:
                logger.warning(f"AI主图已上传但未在主图池识别到新增图片: before={before_count}, after={after_upload.get('count')}")
                return False

            logger.success(
                f"AI主图已上传到主图池: index={uploaded_item.get('idx')}, "
                f"checked={uploaded_item.get('checked')}, src={str(uploaded_item.get('src') or '')[:120]}"
            )

            if int(uploaded_item.get("idx") or 0) != 0:
                moved = await self.drag_main_image_to_first(int(uploaded_item.get("idx") or 0))
                if not moved:
                    after_drag = await self.get_main_image_gallery_snapshot()
                    logger.warning(f"AI主图上传成功但排序到第一张失败: uploaded={uploaded_item}, after={after_drag.get('items', [])[:3]}")
                    return False

            desired_checked = min(before_checked or 5, 5)
            await self.trim_checked_main_images(
                desired_checked=desired_checked,
                keep_src=str(uploaded_item.get("src") or ""),
                prefer_uncheck_src=str(first_before or ""),
            )

            final_sig = await self.get_first_main_image_signature()
            ok = "wxalbum" in str(final_sig.get("src") or "") or str(final_sig.get("src") or "") == str(uploaded_item.get("src") or "")
            if ok:
                logger.success(
                    f"AI主图已完成替换并排序为第一张: checked={final_sig.get('checkedCount')}, "
                    f"src={str(final_sig.get('src') or '')[:120]}"
                )
                return True
            logger.warning(f"AI主图最终校验失败: first={final_sig}, uploaded={uploaded_item}")
            return False
        except Exception as exc:
            logger.warning(f"AI主图上传替换流程失败: {exc}")
            return False

    async def upload_main_image_via_local_menu(self, file_path: Path, before_count: int) -> dict:
        if not self.page:
            return {"ok": False, "reason": "no_page"}
        await self.page.locator(".img-module.productMainImgModule").scroll_into_view_if_needed(timeout=8000)
        await asyncio.sleep(0.3)
        button = self.page.locator(".img-module.productMainImgModule .header button").first
        if await button.count() <= 0:
            return {"ok": False, "reason": "no_choose_image_button"}
        await button.click(timeout=5000, force=True)
        await asyncio.sleep(0.4)

        menu_item = self.page.locator(
            ".ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item[data-menu-id='local'], "
            ".ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item:has-text('本地图片')"
        ).last
        if await menu_item.count() <= 0:
            return {"ok": False, "reason": "no_local_image_menu"}

        async with self.page.expect_file_chooser(timeout=8000) as chooser_info:
            await menu_item.click(timeout=5000, force=True)
        chooser = await chooser_info.value
        await chooser.set_files(str(file_path))

        await self.page.wait_for_function(
            """(beforeCount) => {
                const mod = document.querySelector('.img-module.productMainImgModule');
                const items = mod ? mod.querySelectorAll('.single-image') : [];
                return items.length > beforeCount;
            }""",
            arg=before_count,
            timeout=30000,
        )
        await asyncio.sleep(1.0)
        snapshot = await self.get_main_image_gallery_snapshot()
        return {"ok": True, "count": snapshot.get("count"), "checkedCount": snapshot.get("checkedCount")}

    @staticmethod
    def find_uploaded_main_image(snapshot: dict, before_srcs: set[str], before_count: int) -> dict | None:
        items = snapshot.get("items", []) or []
        new_items = [item for item in items if str(item.get("src") or "") and str(item.get("src") or "") not in before_srcs]
        wx_items = [item for item in new_items if "wxalbum" in str(item.get("src") or "") or "dianxiaomi" in str(item.get("src") or "")]
        if wx_items:
            return wx_items[-1]
        if new_items:
            return new_items[-1]
        if len(items) > before_count:
            return items[-1]
        return None

    async def drag_main_image_to_first(self, source_idx: int) -> bool:
        if not self.page:
            return False
        for attempt in range(1, 4):
            await self.position_main_image_gallery_for_drag()
            snapshot = await self.get_main_image_gallery_snapshot()
            items = snapshot.get("items", []) or []
            if not items or source_idx >= len(items):
                return False
            source = items[source_idx]
            if int(source.get("idx") or 0) == 0:
                return True
            first = items[0]
            src = str(source.get("src") or "")
            sr = source.get("rect") or {}
            fr = first.get("rect") or {}
            # Sortable ignores <img> and <a>; start from the size label area inside the tile.
            start_x = float(sr.get("x") or 0) + min(50, max(10, float(sr.get("w") or 120) * 0.4))
            start_y = float(sr.get("y") or 0) + min(130, max(40, float(sr.get("h") or 167) * 0.77))
            target_x = float(fr.get("x") or 0) + 8
            target_y = float(fr.get("y") or 0) + min(90, max(40, float(fr.get("h") or 167) * 0.5))
            await self.page.mouse.move(start_x, start_y)
            await self.page.mouse.down()
            await asyncio.sleep(0.25)
            await self.page.mouse.move(start_x - 40, start_y - 40, steps=8)
            await self.page.mouse.move((start_x + target_x) / 2, (start_y + target_y) / 2, steps=15)
            await self.page.mouse.move(target_x, target_y, steps=25)
            await asyncio.sleep(0.4)
            await self.page.mouse.up()
            await asyncio.sleep(1.2)
            after = await self.get_main_image_gallery_snapshot()
            first_after = (after.get("items") or [{}])[0]
            if str(first_after.get("src") or "") == src:
                logger.success(f"AI主图已拖拽排序到第一张: attempt={attempt}")
                return True
            source_idx = next((int(item.get("idx") or 0) for item in after.get("items", []) if str(item.get("src") or "") == src), source_idx)
        return False

    async def position_main_image_gallery_for_drag(self) -> None:
        if not self.page:
            return
        try:
            await self.page.evaluate(
                """() => {
                    const first = document.querySelector('.img-module.productMainImgModule .single-image');
                    if (!first) return;
                    const r = first.getBoundingClientRect();
                    window.scrollBy({ top: r.y - 250, left: 0, behavior: 'auto' });
                }"""
            )
            await asyncio.sleep(0.4)
        except Exception as exc:
            logger.warning(f"主图拖拽前调整页面位置失败: {exc}")

    async def trim_checked_main_images(self, desired_checked: int, keep_src: str, prefer_uncheck_src: str = "") -> bool:
        if not self.page:
            return False
        for _ in range(4):
            snapshot = await self.get_main_image_gallery_snapshot()
            checked = [item for item in snapshot.get("items", []) if item.get("checked")]
            if len(checked) <= desired_checked:
                return True
            target = None
            if prefer_uncheck_src:
                target = next((item for item in checked if str(item.get("src") or "") == prefer_uncheck_src and str(item.get("src") or "") != keep_src), None)
            if not target:
                target = next((item for item in checked if str(item.get("src") or "") != keep_src), None)
            if not target:
                return False
            cr = target.get("checkboxRect") or target.get("rect") or {}
            await self.page.mouse.click(float(cr.get("x") or 0) + 8, float(cr.get("y") or 0) + 8)
            await asyncio.sleep(0.8)
        return False

    @staticmethod
    def main_image_replaced(before_sig: dict, after_sig: dict) -> bool:
        before_src = str((before_sig or {}).get("src") or "")
        after_src = str((after_sig or {}).get("src") or "")
        if after_src and before_src and after_src != before_src:
            return True
        if after_src and not before_src:
            return True
        return False

    async def get_first_main_image_signature(self) -> dict:
        if not self.page:
            return {}
        try:
            snapshot = await self.get_main_image_gallery_snapshot()
            first = (snapshot.get("items") or [{}])[0]
            return {
                "src": first.get("src") or "",
                "width": first.get("width"),
                "height": first.get("height"),
                "top": round((first.get("rect") or {}).get("y", 0)),
                "left": round((first.get("rect") or {}).get("x", 0)),
                "count": snapshot.get("count"),
                "checkedCount": snapshot.get("checkedCount"),
            }
        except Exception as exc:
            logger.warning(f"读取第一张主图信息失败: {exc}")
            return {}

    async def get_main_image_gallery_snapshot(self) -> dict:
        if not self.page:
            return {}
        return await self.page.evaluate(
            """() => {
                const mod = document.querySelector('.img-module.productMainImgModule');
                if (!mod) return { ok: false, reason: 'no_product_main_module', count: 0, checkedCount: 0, items: [] };
                const items = Array.from(mod.querySelectorAll('.single-image')).map((el, idx) => {
                    const img = el.querySelector('img');
                    const r = el.getBoundingClientRect();
                    const cb = el.querySelector('.ant-checkbox, .ant-checkbox-input, .image-checkbox');
                    const cr = cb && cb.getBoundingClientRect ? cb.getBoundingClientRect() : null;
                    const sizeText = (el.innerText || '').match(/\\d+\\s*X\\s*\\d+/i);
                    const width = sizeText ? Number((sizeText[0].split(/x/i)[0] || '').trim()) : null;
                    const height = sizeText ? Number((sizeText[0].split(/x/i)[1] || '').trim()) : null;
                    return {
                        idx,
                        checked: el.classList.contains('checked') || !!el.querySelector('.ant-checkbox-checked'),
                        src: img ? (img.currentSrc || img.src || '') : '',
                        text: el.innerText || '',
                        width,
                        height,
                        rect: { x: r.x, y: r.y, w: r.width, h: r.height },
                        checkboxRect: cr ? { x: cr.x, y: cr.y, w: cr.width, h: cr.height } : null
                    };
                });
                return {
                    ok: true,
                    count: items.length,
                    checkedCount: items.filter((item) => item.checked).length,
                    items
                };
            }"""
        )

    async def delete_first_main_image_for_replace(self) -> bool:
        logger.info("当前主图替换流程不再删除原图，改为上传新图、排序到第一位并取消旧首图勾选")
        return True

    async def step_ai_main_image_processing(self):
        if not self.config_enabled("enable_ai_image"):
            return
        try:
            snapshot = await self.collect_product_snapshot()
            urls = snapshot.get("mainImages", []) or []
            if not urls:
                logger.warning("未读取到主图URL，跳过AI主图处理")
                return
            count = int(CONFIG.get("ai_image_count", 1) or 1)
            count = max(1, min(count, len(urls), 6))
            out_dir = self.OUTPUT_DIR / "ai_images"
            out_dir.mkdir(parents=True, exist_ok=True)
            uploaded = 0
            for idx, url in enumerate(urls[:count]):
                api_url = str(CONFIG.get("ai_image_api_url", "")).strip()
                model = str(CONFIG.get("ai_image_model", "")).strip() or "gpt-image-2"
                prompt = self.build_ai_image_prompt(str(CONFIG.get("ai_image_prompt", "")).strip())
                size = str(CONFIG.get("ai_image_size", "")).strip() or "1024x1024"
                api_key = str(CONFIG.get("ai_image_api_key", "")).strip()
                if self.is_volcengine_seedream(api_url, model):
                    logger.info(f"正在提交第 {idx + 1} 张主图到火山Seedream生图(URL): {url}")
                    processed_path = await asyncio.to_thread(
                        self.post_volcengine_seedream_image_sync,
                        url,
                        api_url,
                        api_key,
                        model,
                        prompt,
                        size,
                    )
                elif model == "gpt-image-2" or "geeknow" in api_url.lower():
                    logger.info(f"正在提交第 {idx + 1} 张主图到GeekNow异步生图(URL): {url}")
                    processed_path = await asyncio.to_thread(
                        self.post_geeknow_gpt_image_async_from_url_sync,
                        url,
                        api_url,
                        api_key,
                        model,
                        prompt,
                        size,
                    )
                else:
                    suffix = Path(url.split("?")[0]).suffix.lower()
                    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                        suffix = ".jpg"
                    src_path = out_dir / f"source_{idx}{suffix}"
                    logger.info(f"正在下载第 {idx + 1} 张主图用于AI处理: {url}")
                    await asyncio.to_thread(self.download_image_sync, url, src_path)
                    logger.info(f"正在调用AI图片接口处理主图: {src_path}")
                    processed_path = await asyncio.to_thread(self.post_image_sync, src_path)
                if await self.upload_image_file(processed_path):
                    uploaded += 1
            logger.success(f"AI主图处理完成，成功上传 {uploaded}/{count} 张")
            await self.capture_state("03_ai_main_image")
        except Exception as exc:
            logger.warning(f"AI主图处理失败，继续执行旧流程: {exc}")
            write_error_trace("step_ai_main_image_processing", exc)

    async def smart_click_by_text(self, texts: list[str], description: str, exact: bool = False) -> bool:
        if not self.page:
            return False

        for text in texts:
            candidates = [
                self.page.get_by_role("button", name=text, exact=exact),
                self.page.get_by_role("link", name=text, exact=exact),
                self.page.get_by_text(text, exact=exact),
                self.page.locator(f'text="{text}"'),
            ]

            for locator in candidates:
                try:
                    count = await locator.count()
                    if count > 0:
                        target = locator.first
                        await target.scroll_into_view_if_needed()
                        await target.click(timeout=2000)
                        logger.success(f"点击成功: {description} - {text}")
                        await asyncio.sleep(CONFIG.get("delay_between_actions", 0.5))
                        return True
                except Exception:
                    continue

        logger.warning(f"未找到可点击元素: {description}")
        return False

    async def smart_fill_by_label(self, labels: list[str], value: str, description: str) -> bool:
        if not self.page:
            return False

        for label in labels:
            candidates = [
                self.page.get_by_label(label, exact=False),
                self.page.get_by_placeholder(label, exact=False),
                self.page.locator(f'input[placeholder*="{label}"], textarea[placeholder*="{label}"]'),
                self.page.locator(f'input[aria-label*="{label}"], textarea[aria-label*="{label}"]'),
            ]

            for locator in candidates:
                try:
                    count = await locator.count()
                    if count > 0:
                        target = locator.first
                        await target.scroll_into_view_if_needed()
                        await target.click()
                        await target.fill(str(value))
                        logger.success(f"填写成功: {description} = {value}")
                        await asyncio.sleep(CONFIG.get("delay_between_actions", 0.5))
                        return True
                except Exception:
                    continue

        logger.warning(f"未找到输入框: {description}")
        return False

    async def smart_select_dropdown(self, field_keywords: list[str], option_text: str, description: str) -> bool:
        if not self.page:
            return False

        opened = await self.smart_click_by_text(field_keywords, f"{description}-打开下拉")
        if not opened:
            for keyword in field_keywords:
                try:
                    combobox = self.page.locator('[role="combobox"]').filter(has_text=keyword)
                    count = await combobox.count()
                    if count > 0:
                        await combobox.first.click(timeout=2000)
                        opened = True
                        break
                except Exception:
                    continue

        if not opened:
            logger.warning(f"无法打开下拉框: {description}")
            return False

        await asyncio.sleep(0.5)

        option_locators = [
            self.page.get_by_role("option", name=option_text, exact=False),
            self.page.get_by_text(option_text, exact=False),
            self.page.locator(".ant-select-item-option-content").filter(has_text=option_text),
            self.page.locator('[role="option"]').filter(has_text=option_text),
        ]

        for locator in option_locators:
            try:
                count = await locator.count()
                if count > 0:
                    await locator.first.click(timeout=2000)
                    logger.success(f"下拉选择成功: {description} = {option_text}")
                    await asyncio.sleep(CONFIG.get("delay_between_actions", 0.5))
                    return True
            except Exception:
                continue

        logger.warning(f"未找到下拉选项: {description} = {option_text}")
        return False

    async def click_if_exists(self, texts: list[str], description: str):
        ok = await self.smart_click_by_text(texts, description)
        if not ok:
            logger.warning(f"跳过步骤: {description}")

    async def step_select_category(self):
        logger.info(f"步骤1: 处理类目 -> {CONFIG['category']}")

        opened = False

        # 优先点击“产品分类”这一行内的 ant-select-selector（你截图里红框位置）
        category_selectors = [
            self.page.locator("label:has-text('产品分类')").locator("xpath=../following-sibling::*").locator(".ant-select-selector").first,
            self.page.locator(".ant-form-item").filter(has_text="产品分类").locator(".ant-select-selector").first,
            self.page.locator("text=产品分类").locator("xpath=ancestor::*[contains(@class,'ant-form-item')]").locator(".ant-select-selector").first,
        ]

        for loc in category_selectors:
            try:
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed()
                    await loc.click(timeout=3000)
                    opened = True
                    logger.success("点击成功: 类目下拉框")
                    break
            except Exception:
                continue

        # 兜底：再尝试原先“选择分类”按钮
        if not opened:
            opened = await self.smart_click_by_text(self.SELECTOR_TEXTS["category_button"], "类目按钮")

        await asyncio.sleep(0.6)

        # 直接在下拉选项中选目标类目（支持滚动到底部查找）
        selected = False

        async def try_pick_category_once() -> bool:
            try:
                clicked_text = await self.page.evaluate(
                    """(targetText) => {
                        const normalize = (s) => (s || "")
                            .replace(/（/g, "(")
                            .replace(/）/g, ")")
                            .replace(/\\s+/g, "")
                            .trim()
                            .toLowerCase();
                        const target = normalize(targetText);
                        const roots = Array.from(document.querySelectorAll(".ant-select-dropdown"))
                            .filter((el) => {
                                const st = window.getComputedStyle(el);
                                const rect = el.getBoundingClientRect();
                                return st.display !== "none"
                                    && st.visibility !== "hidden"
                                    && rect.width > 0
                                    && rect.height > 0;
                            });
                        if (!roots.length || !target) return "";
                        const root = roots[roots.length - 1];
                        const items = Array.from(root.querySelectorAll(
                            ".ant-select-item-option:not(.ant-select-item-option-disabled), [role='option']"
                        ));
                        const candidates = items.map((el) => {
                            const text = (el.getAttribute("title") || el.innerText || "").trim();
                            return { el, text, norm: normalize(text) };
                        }).filter((item) => item.text);
                        const found = candidates.find((item) => item.norm === target)
                            || candidates.find((item) => item.norm.includes(target));
                        if (!found) return "";
                        found.el.scrollIntoView({ block: "center", inline: "nearest" });
                        found.el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                        found.el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                        found.el.click();
                        return found.text;
                    }""",
                    CONFIG["category"]
                )
                if clicked_text:
                    logger.success(f"点击成功: 选择类目 {clicked_text}")
                    return True
            except Exception:
                pass
            return False

        selected = await try_pick_category_once()

        # 下拉列表滚动查找（你反馈目标在最后）
        if not selected:
            dropdown_scroll_boxes = [
                self.page.locator(".ant-select-dropdown .rc-virtual-list-holder").first,
                self.page.locator(".ant-select-dropdown .ant-select-item-option-content").first.locator("xpath=ancestor::*[contains(@class,'rc-virtual-list-holder')]"),
                self.page.locator(".ant-select-dropdown").first,
            ]
            for box in dropdown_scroll_boxes:
                try:
                    if await box.count() == 0:
                        continue
                    for _ in range(12):
                        await box.evaluate("(el) => { el.scrollTop = el.scrollTop + 420; }")
                        await asyncio.sleep(0.2)
                        if await try_pick_category_once():
                            selected = True
                            break
                    if selected:
                        break
                except Exception:
                    continue

        # 兜底：下拉搜索后再选
        if not selected:
            search_candidates = [
                self.page.locator(".ant-select-dropdown input[role='combobox']").first,
                self.page.locator(".ant-select-dropdown input[type='search']").first,
                self.page.locator(".ant-select-dropdown input").first,
            ]
            for search in search_candidates:
                try:
                    if await search.count() > 0:
                        await search.click(timeout=2000)
                        await search.fill(CONFIG["category"])
                        await asyncio.sleep(0.6)
                        if await try_pick_category_once():
                            selected = True
                            logger.success(f"点击成功: 搜索后选择类目 {CONFIG['category']}")
                            break
                except Exception:
                    continue

        if not selected:
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass

            choose_buttons = [
                self.page.locator(".ant-form-item").filter(has_text="产品分类").locator("button:has-text('选择分类')").first,
                self.page.locator("button:has-text('选择分类')").first,
                self.page.get_by_role("button", name="选择分类").first,
            ]

            opened_category_panel = False
            for btn in choose_buttons:
                try:
                    if await btn.count() == 0:
                        continue
                    await btn.scroll_into_view_if_needed()
                    await btn.click(timeout=3000, force=True)
                    opened_category_panel = True
                    logger.success("点击成功: 产品分类-选择分类")
                    break
                except Exception:
                    continue

            if opened_category_panel:
                await asyncio.sleep(0.8)
                panel = self.page.locator(".ant-modal-content, .ant-drawer-content").filter(has_text="分类").last

                search_inputs = [
                    panel.locator("input[placeholder*='搜索']").first,
                    panel.locator("input[placeholder*='请输入']").first,
                    panel.locator("input").first,
                    self.page.locator(".ant-modal-content input[placeholder*='搜索'], .ant-drawer-content input[placeholder*='搜索']").first,
                    self.page.locator(".ant-modal-content input, .ant-drawer-content input").first,
                ]

                for search in search_inputs:
                    try:
                        if await search.count() == 0:
                            continue
                        await search.click(timeout=2000, force=True)
                        await search.fill(CONFIG["category"])
                        await search.press("Enter")
                        await asyncio.sleep(0.8)
                        break
                    except Exception:
                        continue

                try:
                    clicked_text = await self.page.evaluate(
                        """(targetText) => {
                            const normalize = (s) => (s || "")
                                .replace(/（/g, "(")
                                .replace(/）/g, ")")
                                .replace(/\\s+/g, "")
                                .trim()
                                .toLowerCase();
                            const target = normalize(targetText);
                            const roots = Array.from(document.querySelectorAll(".ant-modal-content, .ant-drawer-content"))
                                .filter((el) => {
                                    const st = window.getComputedStyle(el);
                                    const rect = el.getBoundingClientRect();
                                    return st.display !== "none"
                                        && st.visibility !== "hidden"
                                        && rect.width > 0
                                        && rect.height > 0
                                        && (el.innerText || "").includes("分类");
                                });
                            const root = roots.length ? roots[roots.length - 1] : document.body;
                            const items = Array.from(root.querySelectorAll(
                                "li, .ant-tree-node-content-wrapper, .ant-select-item-option, .ant-table-row, [role='treeitem'], [role='option']"
                            ));
                            const candidates = items.map((el) => {
                                const text = (el.innerText || el.getAttribute("title") || "").trim();
                                return { el, text, norm: normalize(text) };
                            }).filter((item) => item.text);
                            const found = candidates.find((item) => item.norm === target)
                                || candidates.find((item) => item.norm.includes(target));
                            if (!found) return "";
                            found.el.scrollIntoView({ block: "center", inline: "nearest" });
                            found.el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                            found.el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                            found.el.click();
                            return found.text;
                        }""",
                        CONFIG["category"]
                    )
                    if clicked_text:
                        selected = True
                        logger.success(f"点击成功: 选择分类面板选择类目 {clicked_text}")
                except Exception:
                    pass

                if selected:
                    confirm_buttons = [
                        panel.locator("button:has-text('确定')").first,
                        panel.locator("button:has-text('确 定')").first,
                        self.page.locator(".ant-modal-content button:has-text('确定'), .ant-drawer-content button:has-text('确定')").last,
                    ]
                    for btn in confirm_buttons:
                        try:
                            if await btn.count() == 0:
                                continue
                            await btn.click(timeout=3000, force=True)
                            logger.success("点击成功: 产品分类-确定")
                            await asyncio.sleep(0.8)
                            break
                        except Exception:
                            continue

        if not selected:
            logger.warning(f"未找到可点击元素: 选择类目 {CONFIG['category']}")
            raise RuntimeError(f"产品分类未选中，停止后续流程: {CONFIG['category']}")

        await self.capture_state("01_category")

    async def step_select_template(self):
        logger.info(f"步骤2: 选择模板 -> {CONFIG['template']}")

        opened = False

        # 先精准点“---请选择引用模板---”这一块（避免点错到别的下拉）
        template_selectors = [
            self.page.locator("text=请选择引用模板").locator("xpath=ancestor::*[contains(@class,'ant-select-selector')]").first,
            self.page.locator(".ant-select-selector").filter(has_text="请选择引用模板").first,
            self.page.locator("input#rc_select_2").locator("xpath=ancestor::*[contains(@class,'ant-select-selector')]").first,
        ]

        for sel in template_selectors:
            try:
                if await sel.count() > 0:
                    await sel.scroll_into_view_if_needed()
                    await sel.click(timeout=3000)
                    opened = True
                    logger.success("点击成功: 打开引用模板下拉框")
                    break
            except Exception:
                continue

        # 兜底才走老逻辑
        if not opened:
            opened = await self.smart_click_by_text(self.SELECTOR_TEXTS["template_button"], "模板按钮")

        if opened:
            await asyncio.sleep(0.6)

            # 先输入关键词“假发”
            search_inputs = [
                self.page.locator(".ant-select-dropdown input[placeholder*='请输入模板名称']").first,
                self.page.locator(".ant-select-dropdown input[role='combobox']").first,
                self.page.locator(".ant-select-dropdown input").first,
            ]
            for inp in search_inputs:
                try:
                    if await inp.count() > 0:
                        await inp.click(timeout=2000)
                        await inp.fill(CONFIG["template"])
                        await asyncio.sleep(0.6)
                        logger.info(f"已输入模板关键词: {CONFIG['template']}")
                        break
                except Exception:
                    continue

            async def try_pick_template_once() -> bool:
                # 按你给的 DOM 结构优先匹配：
                # div.ant-select-item-option[title='假发'] 或其子节点 div.in-check-options
                locators = [
                    self.page.locator(f".ant-select-item-option[title='{CONFIG['template']}']").first,
                    self.page.locator(".ant-select-item-option-content").filter(has_text=CONFIG["template"]).first,
                    self.page.locator(".ant-select-item-option").filter(has_text=CONFIG["template"]).first,
                    self.page.locator(".in-check-options").filter(has_text=CONFIG["template"]).first,
                    self.page.get_by_text(CONFIG["template"], exact=False).first,
                ]
                for loc in locators:
                    try:
                        if await loc.count() > 0:
                            await loc.scroll_into_view_if_needed()
                            await loc.click(timeout=3000)
                            logger.success(f"点击成功: 选择模板 {CONFIG['template']}")
                            return True
                    except Exception:
                        continue
                return False

            picked = await try_pick_template_once()

            # 选项在下方时滚动列表继续找
            if not picked:
                dropdown_scroll_boxes = [
                    self.page.locator(".ant-select-dropdown .rc-virtual-list-holder").first,
                    self.page.locator(".ant-select-dropdown").first,
                ]
                for box in dropdown_scroll_boxes:
                    try:
                        if await box.count() == 0:
                            continue
                        for _ in range(12):
                            await box.evaluate("(el) => { el.scrollTop = el.scrollTop + 420; }")
                            await asyncio.sleep(0.2)
                            if await try_pick_template_once():
                                picked = True
                                break
                        if picked:
                            break
                    except Exception:
                        continue

            if not picked:
                logger.warning(f"未找到可点击元素: 选择模板 {CONFIG['template']}")

        await self.capture_state("02_template")

    async def step_fill_basic_info(self):
        logger.info("步骤4: 填写产品信息（自动识别有/无SKU）")

        async def fill_first(placeholder: str, value: str, desc: str):
            loc = self.page.locator(f"input[placeholder='{placeholder}']").first
            if await loc.count() > 0:
                try:
                    # 不再强制 scroll，避免“元素不可见”长时间卡住
                    await loc.click(timeout=1200, force=True)
                    await loc.fill(value, timeout=1200)
                    logger.success(f"填写成功: {desc} = {value}")
                    await asyncio.sleep(0.2)
                    return True
                except Exception as e:
                    logger.warning(f"{desc} 输入框存在但不可操作: {e}")
                    return False
            return False

        async def set_controlled_input(locator, value: str):
            target = locator.first
            try:
                # 避免 scroll_into_view_if_needed 在不可见元素上卡死
                await target.click(timeout=1200, force=True)
            except Exception:
                pass

            await target.evaluate(
                """(el, val) => {
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(el, val);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new Event('blur', { bubbles: true }));
                }""",
                value,
            )

        size_text = str(CONFIG.get("size", "26*16*6"))
        size_parts = [p.strip() for p in size_text.replace("×", "*").split("*")]
        while len(size_parts) < 3:
            size_parts.append("0")

        async def fill_no_sku_fields():
            logger.info("进入无SKU填写流程")

            base_retail_input = self.page.locator("input[placeholder='零售价'], input[placeholder='请输入零售价格']").first
            base_value_input = self.page.locator("input[placeholder='货值'], input[placeholder='请输入货值']").first
            base_stock_input = self.page.locator("input[placeholder='库存'], input[placeholder='库存数量']").first
            base_weight_input = self.page.locator(
                "input[placeholder='重量'], input[placeholder='重量(kg)'], input[placeholder='请输入重量'], input[placeholder='请输入重量(kg)']"
            ).first
            base_len_input = self.page.locator("input[placeholder='长']").first
            base_wid_input = self.page.locator("input[placeholder='宽']").first
            base_hei_input = self.page.locator("input[placeholder='高']").first

            retail_field_count = await self.page.locator("input[placeholder='零售价'], input[placeholder='请输入零售价格']").count()
            value_field_count = await self.page.locator("input[placeholder='货值'], input[placeholder='请输入货值']").count()
            stock_field_count = await self.page.locator("input[placeholder='库存'], input[placeholder='库存数量']").count()
            weight_field_count = await self.page.locator(
                "input[placeholder='重量'], input[placeholder='重量(kg)'], input[placeholder='请输入重量'], input[placeholder='请输入重量(kg)']"
            ).count()
            logger.info(
                f"无SKU字段计数: retail={retail_field_count}, value={value_field_count}, "
                f"stock={stock_field_count}, weight={weight_field_count}"
            )

            try:
                raw_price = ""
                if await base_retail_input.count() > 0:
                    raw_price = (await base_retail_input.input_value()).strip()
                    if not raw_price:
                        raw_price = (await base_retail_input.evaluate("(el) => el.value || el.getAttribute('value') || ''")).strip()
                raw_price = raw_price.replace(",", "").replace("￥", "").strip()
                original_price = float(raw_price or 0)
            except Exception:
                original_price = 0.0

            retail_mul = float(CONFIG.get("retail_multiplier", 7.0))
            value_mul = float(CONFIG.get("value_multiplier", 2.0))
            new_retail = round(original_price * retail_mul, 2)
            new_value = round(original_price * value_mul, 2)

            if not is_skip("retail_multiplier") and await base_retail_input.count() > 0:
                await set_controlled_input(base_retail_input, str(new_retail))
                logger.success(f"填写成功: 零售价 = {new_retail}")

            if not is_skip("value_multiplier") and await base_value_input.count() > 0:
                await set_controlled_input(base_value_input, str(new_value))
                logger.success(f"填写成功: 货值 = {new_value}")

            if not is_skip("stock") and await base_stock_input.count() > 0:
                await set_controlled_input(base_stock_input, str(CONFIG.get("stock", 50000)))
                logger.success(f"填写成功: 库存 = {CONFIG.get('stock', 50000)}")

            if not is_skip("weight") and await base_weight_input.count() > 0:
                await set_controlled_input(base_weight_input, str(CONFIG.get("weight", 0.14)))
                logger.success(f"填写成功: 重量 = {CONFIG.get('weight', 0.14)}")

            if not is_skip("size"):
                if await base_len_input.count() > 0:
                    await set_controlled_input(base_len_input, size_parts[0])
                if await base_wid_input.count() > 0:
                    await set_controlled_input(base_wid_input, size_parts[1])
                if await base_hei_input.count() > 0:
                    await set_controlled_input(base_hei_input, size_parts[2])
                logger.success(f"填写成功: 包装尺寸 = {size_parts[0]}*{size_parts[1]}*{size_parts[2]}")

            if not is_skip("original_box"):
                # 精准定位“是否原箱”对应下拉，避免误点到店铺等其它“请选择”
                original_box_targets = [
                    # 你提供的 DOM（rc_select_5）
                    self.page.locator("input#rc_select_5").locator("xpath=ancestor::div[contains(@class,'ant-select')]").first,
                    # 按“是否原箱”标签反向定位
                    self.page.locator("text=是否原箱").locator("xpath=ancestor::*[contains(@class,'ant-form-item')]").locator(".ant-select-selector").first,
                    self.page.locator("label:has-text('是否原箱')").locator("xpath=../following-sibling::*").locator(".ant-select-selector").first,
                ]

                selected_box = False
                for target in original_box_targets:
                    try:
                        if await target.count() == 0:
                            continue
                        await target.click(timeout=2000, force=True)

                        # 优先选择“是”
                        opt = self.page.locator(".ant-select-dropdown .ant-select-item-option-content").filter(has_text="是").first
                        if await opt.count() > 0:
                            await opt.click(timeout=2000)
                            selected_box = True
                            logger.success("填写成功: 是否原箱 = 是")
                            break
                    except Exception:
                        continue

                if not selected_box:
                    logger.warning("无SKU模式下是否原箱设置失败：未命中目标下拉或选项“是”")

        async def set_logistics_property_common_goods_anywhere() -> bool:
            async def select_common_goods_in_modal() -> bool:
                await asyncio.sleep(0.5)
                result = await self.page.evaluate(
                    """() => {
                        const visible = (el) => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style.display !== "none"
                                && style.visibility !== "hidden"
                                && rect.width > 0
                                && rect.height > 0;
                        };
                        const norm = (value) => String(value || "").replace(/\\s+/g, "").trim();
                        const textOf = (el) => norm(el.innerText || el.textContent || "");
                        const roots = Array.from(document.querySelectorAll(".ant-modal-content, .modal-content, .el-dialog, [role='dialog']"))
                            .filter(visible)
                            .filter(el => textOf(el).includes("物流属性") || textOf(el).includes("普货"));
                        const root = roots.length ? roots[roots.length - 1] : document.body;
                        const options = Array.from(root.querySelectorAll("label, .ant-radio-wrapper, span, div"))
                            .filter(visible)
                            .filter(el => textOf(el) === "普货" || textOf(el).includes("普货"));
                        const option = options.find(el => el.closest("label, .ant-radio-wrapper")) || options[0];
                        if (!option) {
                            return { ok: false, reason: "common_goods_not_found", modalText: textOf(root).slice(0, 300) };
                        }
                        const radioLabel = option.closest("label, .ant-radio-wrapper") || option;
                        radioLabel.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                        radioLabel.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                        radioLabel.click();
                        return { ok: true, selectedText: textOf(radioLabel).slice(0, 80) };
                    }"""
                )
                if not result or not result.get("ok"):
                    logger.warning(f"物流属性弹窗中未找到“普货”选项: {result}")
                    return False

                logger.success("选择成功: 物流属性 = 普货")
                await asyncio.sleep(0.3)

                confirmed = await self.page.evaluate(
                    """() => {
                        const visible = (el) => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style.display !== "none"
                                && style.visibility !== "hidden"
                                && rect.width > 0
                                && rect.height > 0;
                        };
                        const norm = (value) => String(value || "").replace(/\\s+/g, "").trim();
                        const textOf = (el) => norm(el.innerText || el.textContent || "");
                        const roots = Array.from(document.querySelectorAll(".ant-modal-content, .modal-content, .el-dialog, [role='dialog']"))
                            .filter(visible)
                            .filter(el => textOf(el).includes("物流属性") || textOf(el).includes("普货"));
                        const root = roots.length ? roots[roots.length - 1] : document.body;
                        const buttons = Array.from(root.querySelectorAll("button, a, span"))
                            .filter(visible)
                            .map(el => ({ el, text: textOf(el) }));
                        const target = buttons.find(item => item.text === "确定" || item.text === "确定")
                            || buttons.find(item => item.text.includes("确定"));
                        if (!target) return { ok: false, reason: "confirm_not_found" };
                        const btn = target.el.closest("button,a") || target.el;
                        btn.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                        btn.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                        btn.click();
                        return { ok: true, text: target.text };
                    }"""
                )
                if confirmed and confirmed.get("ok"):
                    logger.success("点击成功: 物流属性-确定")
                    await asyncio.sleep(0.8)
                    return True
                logger.warning(f"未找到物流属性弹窗的确定按钮: {confirmed}")
                return False

            # 1) 有SKU表格优先点击“物流属性”列下的“批量”
            batch_clicked = False
            batch_targets = [
                self.page.locator(".ant-table-thead th").filter(has_text="物流属性").locator("a:has-text('批量'), span:has-text('批量')").first,
                self.page.locator("th").filter(has_text="物流属性").locator("a:has-text('批量'), span:has-text('批量')").first,
                self.page.locator("xpath=//*[contains(normalize-space(.), '物流属性')]/ancestor::th[1]//*[contains(normalize-space(.), '批量')]").first,
                self.page.locator("xpath=//*[contains(normalize-space(.), '物流属性')]/ancestor::*[contains(@class, 'ant-table-cell')][1]//*[contains(normalize-space(.), '批量')]").first,
            ]
            for target in batch_targets:
                try:
                    if await target.count() == 0:
                        continue
                    await target.scroll_into_view_if_needed()
                    await target.click(timeout=2500, force=True)
                    batch_clicked = True
                    logger.success("点击成功: 物流属性-批量")
                    break
                except Exception:
                    continue

            if batch_clicked:
                return await select_common_goods_in_modal()

            # 2) 单SKU/普通商品：优先使用页面稳定 class 定位“物流属性”编辑图标
            single_edit_targets = [
                self.page.locator(".single-logistics-attr-edit").first,
                self.page.locator("i.icon_edit2.single-logistics-attr-edit").first,
                self.page.locator(".single-logistics-attr-row .icon_edit2").first,
            ]
            for target in single_edit_targets:
                try:
                    if await target.count() == 0:
                        continue
                    await target.scroll_into_view_if_needed(timeout=3000)
                    await asyncio.sleep(0.2)
                    await target.click(timeout=3000, force=True)
                    logger.success("点击成功: 物流属性-单SKU编辑")
                    return await select_common_goods_in_modal()
                except Exception as exc:
                    logger.warning(f"按单SKU物流属性class点击失败，尝试兜底: {exc}")

            # 3) 兜底：无SKU/普通商品：点击“物流属性”旁边的编辑图标
            edit_clicked = await self.page.evaluate(
                """() => {
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== "none"
                            && style.visibility !== "hidden"
                            && rect.width > 0
                            && rect.height > 0;
                    };
                    const norm = (value) => String(value || "").replace(/\\s+/g, "").trim();
                    const textOf = (el) => norm(el.innerText || el.textContent || "");
                    const labels = Array.from(document.querySelectorAll("label, span, div"))
                        .filter(visible)
                        .filter(el => textOf(el).includes("物流属性") && el.getBoundingClientRect().top > 250);
                    for (const label of labels) {
                        const lr = label.getBoundingClientRect();
                        const scopes = [];
                        let cur = label;
                        for (let i = 0; cur && i < 6; i++) {
                            scopes.push(cur);
                            cur = cur.parentElement;
                        }
                        for (const scope of scopes) {
                            const nodes = Array.from(scope.querySelectorAll("svg, i, a, button, span"))
                                .filter(visible)
                                .map(el => ({ el, text: textOf(el), cls: String(el.className || ""), rect: el.getBoundingClientRect() }))
                                .filter(item => item.rect.left >= lr.left && item.rect.top >= lr.top - 20 && item.rect.top <= lr.top + 80);
                            const target = nodes.find(item => /edit|编辑|pen|icon/i.test(item.text + " " + item.cls))
                                || nodes.find(item => item.rect.left > lr.right && item.rect.width <= 60 && item.rect.height <= 60);
                            if (target) {
                                const el = target.el.closest("button,a") || target.el;
                                el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                                el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                                el.click();
                                return { ok: true, label: textOf(label), cls: target.cls, text: target.text };
                            }
                        }
                    }
                    return { ok: false, reason: "edit_icon_not_found", labels: labels.map(el => textOf(el)).slice(0, 5) };
                }"""
            )
            if not edit_clicked or not edit_clicked.get("ok"):
                logger.warning(f"未找到物流属性编辑入口: {edit_clicked}")
                return False

            logger.success(f"点击成功: 物流属性-编辑 {edit_clicked}")
            return await select_common_goods_in_modal()

        # 判定是否有SKU表格（加强日志，避免误判）
        batch_fill_count = await self.page.locator("button:has-text('批量填充'), span:has-text('批量填充')").count()
        sku_table_row_count = await self.page.locator(".ant-table-tbody tr, .ant-table-body tr, table tbody tr").count()
        sku_retail_count = await self.page.locator("input[placeholder='零售价'], input[placeholder='请输入零售价格']").count()

        logger.info(
            f"SKU判定: batch_fill_count={batch_fill_count}, "
            f"sku_table_row_count={sku_table_row_count}, sku_retail_count={sku_retail_count}"
        )

        # 关键：只有明确存在“批量填充”或多行SKU零售价输入时才判定为有SKU
        has_sku_mode = (batch_fill_count > 0) or (sku_retail_count > 1)

        if has_sku_mode:
            logger.info("识别为【有SKU】模式，执行原批量逻辑")

            stock_ok = True
            if not is_skip("stock"):
                stock_ok = await fill_first("库存", str(CONFIG.get("stock", 50000)), "批量库存")
            if not is_skip("weight"):
                await fill_first("重量", str(CONFIG.get("weight", 0.14)), "批量重量")
            if not is_skip("size"):
                await fill_first("长", size_parts[0], "批量长")
                await fill_first("宽", size_parts[1], "批量宽")
                await fill_first("高", size_parts[2], "批量高")

            # 关键兜底：判定为有SKU但“批量库存”字段不可操作，直接切无SKU流程
            if not stock_ok:
                logger.warning("有SKU模式下批量库存不可操作，切换到无SKU填写流程")
                await fill_no_sku_fields()
                await set_logistics_property_common_goods_anywhere()
                await asyncio.sleep(1.0)
                await self.capture_state("05_sku_batch")
                return

            batch_btns = [
                self.page.get_by_role("button", name="批量填充"),
                self.page.locator("span:has-text('批量填充')"),
                self.page.get_by_text("批量填充", exact=False),
            ]
            clicked_batch = False
            for btn in batch_btns:
                try:
                    if await btn.count() > 0:
                        await btn.first.scroll_into_view_if_needed()
                        await btn.first.click(timeout=3000)
                        clicked_batch = True
                        logger.success("点击成功: 批量填充")
                        break
                except Exception:
                    continue

            if not clicked_batch:
                logger.warning("未找到可点击元素: 批量填充")

            sku_retail_inputs = self.page.locator('input[placeholder="零售价"], input[placeholder="请输入零售价格"]')
            sku_value_inputs = self.page.locator('input[placeholder="货值"], input[placeholder="请输入货值"]')

            retail_count = await sku_retail_inputs.count()
            value_count = await sku_value_inputs.count()
            row_count = min(retail_count, value_count)

            logger.info(f"有SKU字段计数: retail_count={retail_count}, value_count={value_count}, row_count={row_count}")

            # 关键兜底：误判有SKU但没有可处理行时，直接走无SKU流程
            if row_count == 0:
                logger.warning("检测为有SKU但未找到有效SKU行，切换到无SKU填写流程")
                await fill_no_sku_fields()
                await set_logistics_property_common_goods_anywhere()
                await asyncio.sleep(1.0)
                await self.capture_state("05_sku_batch")
                return

            updated_price_rows = 0
            for i in range(row_count):
                try:
                    retail_input = sku_retail_inputs.nth(i)
                    value_input = sku_value_inputs.nth(i)

                    raw_price = (await retail_input.input_value()).strip()
                    if not raw_price:
                        raw_price = (await retail_input.evaluate("(el) => el.value || el.getAttribute('value') || ''")).strip()

                    raw_price = raw_price.replace(",", "").replace("￥", "").strip()
                    original_price = float(raw_price or 0)

                    retail_mul = float(CONFIG.get("retail_multiplier", 7.0))
                    value_mul = float(CONFIG.get("value_multiplier", 2.0))
                    new_retail = round(original_price * retail_mul, 2)
                    new_value = round(original_price * value_mul, 2)

                    if not is_skip("retail_multiplier"):
                        await set_controlled_input(retail_input, str(new_retail))
                    if not is_skip("value_multiplier"):
                        await set_controlled_input(value_input, str(new_value))

                    updated_price_rows += 1
                except Exception:
                    continue

            if updated_price_rows:
                logger.success(f"已按采集价格计算并更新零售价/货值，共 {updated_price_rows} 行")
            else:
                logger.warning("未能更新任何SKU的零售价/货值")

            async def set_sku_logistics_property_common_goods() -> bool:
                """
                SKU表格：点击“物流属性”列标题下的“批量”，选择“普货”，再确定。
                """
                batch_targets = [
                    self.page.locator(".ant-table-thead th").filter(has_text="物流属性").locator("a:has-text('批量'), span:has-text('批量')").first,
                    self.page.locator("th").filter(has_text="物流属性").locator("a:has-text('批量'), span:has-text('批量')").first,
                    self.page.locator("xpath=//*[contains(normalize-space(.), '物流属性')]/ancestor::th[1]//*[contains(normalize-space(.), '批量')]").first,
                    self.page.locator("xpath=//*[contains(normalize-space(.), '物流属性')]/ancestor::*[contains(@class, 'ant-table-cell')][1]//*[contains(normalize-space(.), '批量')]").first,
                ]

                clicked_batch = False
                for target in batch_targets:
                    try:
                        if await target.count() == 0:
                            continue
                        await target.scroll_into_view_if_needed()
                        await target.click(timeout=3000, force=True)
                        clicked_batch = True
                        logger.success("点击成功: 物流属性-批量")
                        break
                    except Exception:
                        continue

                if not clicked_batch:
                    logger.warning("未找到物流属性列下的“批量”按钮")
                    return False

                await asyncio.sleep(0.6)

                modal = self.page.locator(".ant-modal-content").filter(has_text="物流属性").last
                try:
                    if await modal.count() == 0 or not await modal.is_visible():
                        modal = self.page.locator(".ant-modal-content").filter(has_text="普货").last
                except Exception:
                    modal = self.page.locator(".ant-modal-content").filter(has_text="普货").last

                common_goods_targets = [
                    modal.locator("label:has-text('普货')").first,
                    modal.locator(".ant-radio-wrapper:has-text('普货')").first,
                    modal.get_by_text("普货", exact=True),
                    self.page.locator("label:has-text('普货')").first,
                    self.page.get_by_text("普货", exact=True),
                ]

                selected_common_goods = False
                for target in common_goods_targets:
                    try:
                        if await target.count() == 0:
                            continue
                        await target.scroll_into_view_if_needed()
                        await target.click(timeout=3000, force=True)
                        selected_common_goods = True
                        logger.success("选择成功: 物流属性 = 普货")
                        break
                    except Exception:
                        continue

                if not selected_common_goods:
                    logger.warning("物流属性弹窗中未找到“普货”选项")
                    return False

                await asyncio.sleep(0.3)

                confirm_targets = [
                    modal.locator("button:has-text('确定')").first,
                    modal.locator("button:has-text('确 定')").first,
                    self.page.locator(".ant-modal-content").filter(has_text="普货").last.locator("button:has-text('确定')").first,
                    self.page.locator(".ant-modal-content").filter(has_text="普货").last.locator("button:has-text('确 定')").first,
                ]

                for target in confirm_targets:
                    try:
                        if await target.count() == 0:
                            continue
                        await target.click(timeout=3000, force=True)
                        logger.success("点击成功: 物流属性-确定")
                        await asyncio.sleep(0.6)
                        return True
                    except Exception:
                        continue

                logger.warning("未找到物流属性弹窗的确定按钮")
                return False

            sku_original_box_selectors = [
                self.page.locator(".ant-table-tbody select"),
                self.page.locator(".ant-table-body select"),
                self.page.locator("table tbody select"),
            ]

            sku_selects = None
            for sel in sku_original_box_selectors:
                try:
                    if await sel.count() > 0:
                        sku_selects = sel
                        break
                except Exception:
                    continue

            if sku_selects:
                updated = 0
                total = await sku_selects.count()
                for i in range(total):
                    try:
                        item = sku_selects.nth(i)
                        await item.scroll_into_view_if_needed()
                        await item.select_option("1")
                        updated += 1
                    except Exception:
                        continue

                if updated:
                    logger.success(f"已将 {updated} 个SKU的是否原箱设置为是")
                else:
                    logger.warning("未能设置任何SKU的是否原箱")
            else:
                logger.warning("未找到SKU行内的是否原箱下拉框")

            await set_logistics_property_common_goods_anywhere()

        else:
            logger.info("识别为【无SKU】模式，执行单商品字段填写")
            await fill_no_sku_fields()
            await set_logistics_property_common_goods_anywhere()

        await asyncio.sleep(1.0)
        await self.capture_state("05_sku_batch")

    async def step_select_templates_and_options(self):
        logger.info("步骤6: 选择模板和配置项")

        async def wait_page_stable(stage: str):
            """
            等待页面稳定，避免海关品名切换后仍在加载就进入下一步。
            """
            try:
                # 常见 loading / spin 兜底等待
                await self.page.wait_for_load_state("networkidle", timeout=6000)
            except Exception:
                pass

            spinner_selectors = [
                ".ant-spin-spinning",
                ".ant-spin-dot-spin",
                ".loading",
            ]
            for sel in spinner_selectors:
                try:
                    await self.page.locator(sel).first.wait_for(state="hidden", timeout=3000)
                except Exception:
                    pass

            await asyncio.sleep(0.6)
            logger.info(f"页面稳定检查完成: {stage}")

        async def open_and_pick_option(input_selector: str, option_texts: list[str], description: str) -> bool:
            target = self.page.locator(input_selector)
            opened = False
            expected_texts = [str(v).strip() for v in option_texts if str(v).strip()]

            click_targets = [
                target.locator("xpath=ancestor::div[contains(@class,'ant-select-selector')]").first,
                target.locator("xpath=ancestor::div[contains(@class,'ant-select')]").first,
                target.first,
            ]

            for click_target in click_targets:
                try:
                    if await click_target.count() > 0:
                        await click_target.scroll_into_view_if_needed()
                        await click_target.click(timeout=3000, force=True)
                        opened = True
                        break
                except Exception:
                    continue

            if not opened:
                logger.warning(f"未能打开下拉框: {description}")
                return False

            await asyncio.sleep(0.6)

            for opt_text in option_texts:
                try:
                    clicked_text = await self.page.evaluate(
                        """(targetText) => {
                            const normalize = (s) => (s || "")
                                .replace(/（/g, "(")
                                .replace(/）/g, ")")
                                .replace(/\\s+/g, "")
                                .trim()
                                .toLowerCase();
                            const target = normalize(targetText);
                            const roots = Array.from(document.querySelectorAll(".ant-select-dropdown"))
                                .filter((el) => {
                                    const st = window.getComputedStyle(el);
                                    const rect = el.getBoundingClientRect();
                                    return st.display !== "none"
                                        && st.visibility !== "hidden"
                                        && rect.width > 0
                                        && rect.height > 0;
                                });
                            if (!roots.length || !target) return "";
                            const root = roots[roots.length - 1];
                            const items = Array.from(root.querySelectorAll(
                                ".ant-select-item-option:not(.ant-select-item-option-disabled), [role='option'], .in-check-options"
                            ));
                            const candidates = items.map((el) => {
                                const text = (el.getAttribute("title") || el.innerText || "").trim();
                                return { el, text, norm: normalize(text) };
                            }).filter((item) => item.text);
                            const found = candidates.find((item) => item.norm === target)
                                || candidates.find((item) => item.norm.includes(target));
                            if (!found) return "";
                            found.el.scrollIntoView({ block: "center", inline: "nearest" });
                            found.el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                            found.el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                            found.el.click();
                            return found.text;
                        }""",
                        opt_text
                    )
                    if clicked_text:
                        logger.success(f"选择成功: {description} = {clicked_text}")
                        await wait_page_stable(f"{description}={clicked_text}")

                        current_text = ""
                        for _ in range(10):
                            try:
                                current_text = await target.locator(
                                    "xpath=ancestor::div[contains(@class,'ant-select')]"
                                ).first.evaluate(
                                    """(el) => (
                                        el.querySelector(".ant-select-selection-item")?.getAttribute("title")
                                        || el.querySelector(".ant-select-selection-item")?.innerText
                                        || el.innerText
                                        || ""
                                    ).trim()"""
                                )
                            except Exception:
                                current_text = ""

                            if any(v in current_text or current_text in v for v in expected_texts):
                                logger.success(f"已确认选中: {description} = {current_text}")
                                return True
                            await asyncio.sleep(0.3)

                        logger.warning(f"{description}点击后未确认选中，当前值: {current_text or '空'}")
                        return False
                except Exception:
                    continue

            logger.warning(f"未找到下拉选项: {description}")
            return False

        if not is_skip("currency_template"):
            freight_ok = await open_and_pick_option(
                "#form_item_freightTemplateId",
                [str(CONFIG.get("currency_template", "不包邮2")), "不包邮2"],
                "运费模板"
            )
            if not freight_ok:
                raise RuntimeError(f"运费模板未选中，停止后续流程: {CONFIG.get('currency_template', '')}")

        if not is_skip("service_template"):
            await open_and_pick_option(
                "#form_item_promiseTemplateId",
                [str(CONFIG.get("service_template", "预设好的")), "Service Template for New Sellers", "预设的", "预设"],
                "服务模板"
            )

        customs_mode = str(CONFIG.get("customs_process_mode", "按预设下拉选择") or "按预设下拉选择").strip()
        all_customs_fields_skipped = all(
            is_skip(key)
            for key in [
                "customs_level1",
                "customs_level2",
                "customs_level3",
                "customs_level4",
                "customs_item",
                "customs_material",
            ]
        )
        customs_click_only = customs_mode == "仅点击添加/更新"
        customs_skip_flow = customs_mode == "跳过海关监管" or (
            customs_mode == "按预设下拉选择" and all_customs_fields_skipped
        )
        customs_auto_fill_targets: list[str] = []

        async def click_customs_add_or_update_button() -> bool:
            clicked = await self.smart_click_by_text(
                ["更新海关监管", "添加海关监管", "添加全球海关监管属性"],
                "海关监管-添加/更新",
                exact=False,
            )
            if clicked:
                await asyncio.sleep(0.8)
            return clicked

        async def confirm_or_close_customs_modal_if_visible(reason: str) -> bool:
            try:
                result = await self.page.evaluate(
                    """() => {
                        const visible = (el) => {
                            if (!el || !el.getBoundingClientRect) return false;
                            const st = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return st.display !== "none" && st.visibility !== "hidden" && r.width > 0 && r.height > 0;
                        };
                        const clickNode = (node) => {
                            const rect = node.getBoundingClientRect();
                            const init = {
                                bubbles: true,
                                cancelable: true,
                                view: window,
                                clientX: rect.left + rect.width / 2,
                                clientY: rect.top + rect.height / 2,
                            };
                            ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach((type) => {
                                node.dispatchEvent(new MouseEvent(type, init));
                            });
                        };
                        const modals = Array.from(document.querySelectorAll(".ant-modal-content, .ant-drawer-content"))
                            .filter((el) => visible(el) && (el.innerText || "").includes("海关监管"));
                        const modal = modals[modals.length - 1];
                        if (!modal) return { ok: false, action: "", text: "" };
                        const buttons = Array.from(modal.querySelectorAll("button, .ant-modal-close, .ant-drawer-close"))
                            .filter(visible)
                            .map((node) => ({ node, text: (node.innerText || node.textContent || "").replace(/\\s+/g, "").trim() }));
                        const confirm = buttons.find((item) => item.text.includes("确定"));
                        if (confirm) {
                            clickNode(confirm.node);
                            return { ok: true, action: "confirm", text: confirm.text };
                        }
                        const cancel = buttons.find((item) => item.text.includes("取消"));
                        if (cancel) {
                            clickNode(cancel.node);
                            return { ok: true, action: "cancel", text: cancel.text };
                        }
                        const close = buttons.find((item) => item.node.className && String(item.node.className).includes("close"));
                        if (close) {
                            clickNode(close.node);
                            return { ok: true, action: "close", text: close.text };
                        }
                        return { ok: false, action: "", text: modal.innerText.slice(0, 120) };
                    }"""
                )
                if result and result.get("ok"):
                    if result.get("action") == "confirm":
                        logger.success(f"{reason}: 已确认海关监管弹窗")
                        await asyncio.sleep(0.8)
                    else:
                        logger.warning(f"{reason}: 已关闭海关监管弹窗，不执行下拉选择")
                        await asyncio.sleep(0.4)
                    return True
                if result and result.get("text"):
                    logger.warning(f"{reason}: 找到海关监管弹窗但未找到确定/关闭按钮: {result.get('text')}")
            except Exception as exc:
                logger.warning(f"{reason}: 处理海关监管弹窗失败: {exc}")
            return False

        async def customs_select_snapshot() -> list[dict]:
            try:
                result = await self.page.evaluate(
                    """() => {
                        const visible = (el) => {
                            if (!el || !el.getBoundingClientRect) return false;
                            const st = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return st.display !== "none" && st.visibility !== "hidden" && r.width > 0 && r.height > 0;
                        };
                        const modals = Array.from(document.querySelectorAll(".ant-modal-content, .ant-drawer-content"))
                            .filter((el) => visible(el) && (el.innerText || "").includes("海关监管"));
                        const modal = modals[modals.length - 1];
                        if (!modal) return { count: 0, snapshot: [] };
                        const snapshot = [];
                        const selects = [];
                        for (const select of Array.from(modal.querySelectorAll(".ant-select")).filter(visible)) {
                            const row = select.closest(".ant-form-item") || select.closest(".ant-row") || select.parentElement;
                            const label = (
                                row?.querySelector(".ant-form-item-label")?.innerText
                                || row?.querySelector("label")?.innerText
                                || row?.innerText
                                || ""
                            ).replace(/\\s+/g, " ").trim();
                            const text = (
                                select.querySelector(".ant-select-selection-item")?.getAttribute("title")
                                || select.querySelector(".ant-select-selection-item")?.innerText
                                || select.querySelector(".ant-select-selection-placeholder")?.innerText
                                || select.innerText
                                || ""
                            ).replace(/\\s+/g, " ").trim();
                            const disabled = select.classList.contains("ant-select-disabled") || !!select.querySelector("input[disabled]");
                            const unresolved = !disabled && (!text || text.includes("请选择") || text.includes("Please select"));
                            snapshot.push(`${label || "字段"}=${text || "空"}`);
                            selects.push({ label, text, disabled, unresolved });
                        }
                        const count = selects.filter((item) => item.unresolved).length;
                        return { count, snapshot, selects };
                    }"""
                )
                if result:
                    logger.info(f"海关监管待选择下拉检测: count={result.get('count')}, snapshot={result.get('snapshot')}")
                    return result.get("selects") or []
            except Exception as exc:
                logger.warning(f"海关监管待选择下拉检测失败: {exc}")
            return []

        def build_auto_customs_targets(selects: list[dict]) -> list[str]:
            configured_levels = [
                str(CONFIG.get("customs_level1", "")).strip(),
                str(CONFIG.get("customs_level2", "")).strip(),
                str(CONFIG.get("customs_level3", "")).strip(),
                str(CONFIG.get("customs_level4", "")).strip(),
            ]
            customs_item = str(CONFIG.get("customs_item", "")).strip()
            customs_material = str(CONFIG.get("customs_material", "")).strip()

            def first_value(candidates: list[str]) -> str:
                for value in candidates:
                    value = (value or "").strip()
                    if value and "请选择" not in value:
                        return value
                return "其他(Other)"

            targets: list[str] = []
            for idx, item in enumerate(selects):
                current = str(item.get("text", "") or "").strip()
                label = str(item.get("label", "") or "").lower()
                if current and "请选择" not in current and "please select" not in current.lower():
                    targets.append(current)
                    continue
                if "material" in label or "材质" in label:
                    targets.append(first_value([customs_material, configured_levels[1], configured_levels[0], "其他(Other)"]))
                elif "vehicle part" in label or "车辆零件" in label or "车身零件" in label or "part type" in label:
                    targets.append(first_value([customs_item, configured_levels[0], configured_levels[1], "其他(Other)"]))
                else:
                    target_by_index = configured_levels[idx] if idx < len(configured_levels) else ""
                    targets.append(first_value([target_by_index, customs_item, customs_material, "其他(Other)"]))
            return targets

        async def unresolved_customs_select_count() -> int:
            try:
                selects = await customs_select_snapshot()
                return sum(1 for item in selects if item.get("unresolved"))
            except Exception:
                return 0
            return 0

        if customs_skip_flow:
            logger.info(f"海关监管流程已跳过: mode={customs_mode}, all_fields_skipped={all_customs_fields_skipped}")
        elif customs_click_only:
            logger.info("海关监管处理方式=仅点击添加/更新：先点击按钮，再检测翻译后是否生成海关下拉字段")
            clicked_customs = await click_customs_add_or_update_button()
            if clicked_customs:
                logger.success("海关监管仅点击模式：已点击添加/更新按钮")
                await asyncio.sleep(1.0)
                modal_selects = await customs_select_snapshot()
                modal_select_count = sum(1 for item in modal_selects if item.get("unresolved"))
                if modal_select_count > 0:
                    customs_auto_fill_targets = build_auto_customs_targets(modal_selects)
                    logger.warning(
                        f"海关监管仅点击模式点击后出现 {modal_select_count} 个待选择下拉字段，"
                        f"自动切换为按弹窗字段选择: {customs_auto_fill_targets}"
                    )
                    customs_click_only = False
                    customs_mode = "按预设下拉选择(自动)"
                else:
                    await confirm_or_close_customs_modal_if_visible("海关监管仅点击模式")
            else:
                logger.warning("海关监管仅点击模式：未找到或未点到添加/更新按钮，继续后续流程")
        else:
            await click_customs_add_or_update_button()

        async def get_customs_modal():
            """
            显式等待弹窗出现，并精确定位“海关监管”弹窗，避免误取其他 modal。
            """
            try:
                await self.page.wait_for_selector(".ant-modal-content:visible", timeout=5000)
            except Exception:
                return None

            modal = self.page.locator(".ant-modal-content").filter(has_text="海关监管").last
            try:
                if await modal.is_visible():
                    return modal
            except Exception:
                pass

            return None

        async def get_row_selector_by_label(modal, field_terms: list[str]):
            """
            按截图中的真实结构定位：
            - 左侧 label: 品名(Product name): / 材质(Material):
            - 右侧同一行 control 区域的 .ant-select-selector
            """
            # 店小秘海关弹窗是 Ant Form 结构。优先只遍历 .ant-form-item，
            # 避免外层 ant-row/m-top 容器包含整段弹窗文本时误命中第一个下拉框。
            try:
                rows = modal.locator(".ant-form-item")
                row_count = await rows.count()
                for i in range(row_count):
                    row = rows.nth(i)
                    try:
                        row_text = (await row.inner_text()).strip()
                    except Exception:
                        continue
                    if not any(term in row_text for term in field_terms):
                        continue

                    control_candidates = [
                        row.locator(".ant-form-item-control .ant-select-selector"),
                        row.locator(".ant-form-item-control .ant-select"),
                        row.locator(".ant-form-item-control input[role='combobox']"),
                        row.locator(".ant-form-item-control input.ant-select-selection-search-input"),
                    ]
                    for cand in control_candidates:
                        try:
                            if await cand.count() > 0:
                                return cand.first
                        except Exception:
                            continue
            except Exception:
                pass

            # 1) 先按“左侧 attr-label/label -> 同一行右侧 control”直接定位
            for term in field_terms:
                direct_candidates = [
                    modal.locator(
                        f"xpath=.//span[contains(@class,'attr-label') and contains(normalize-space(.), '{term}')]"
                        f"/ancestor::div[contains(@class,'ant-form-item-row')][1]"
                        f"/div[contains(@class,'ant-col') and contains(@class,'ant-form-item-control')]"
                        f"//div[contains(@class,'ant-select-selector')]"
                    ),
                    modal.locator(
                        f"xpath=.//span[contains(@class,'attr-label') and contains(normalize-space(.), '{term}')]"
                        f"/ancestor::div[contains(@class,'ant-form-item-row')][1]"
                        f"/div[contains(@class,'ant-col') and contains(@class,'ant-form-item-control')]"
                        f"//div[contains(@class,'ant-select-in-form-item')]"
                    ),
                    modal.locator(
                        f"xpath=.//label[contains(@title, '{term}')]"
                        f"/ancestor::div[contains(@class,'ant-form-item-row')][1]"
                        f"/div[contains(@class,'ant-col') and contains(@class,'ant-form-item-control')]"
                        f"//div[contains(@class,'ant-select-selector')]"
                    ),
                ]

                for cand in direct_candidates:
                    try:
                        if await cand.count() > 0:
                            return cand.first
                    except Exception:
                        continue

            # 2) 兜底：遍历表单行，按 label 文本匹配，再取该行 control 区域
            rows = modal.locator(".ant-form-item")
            row_count = await rows.count()

            for i in range(row_count):
                row = rows.nth(i)
                try:
                    label_text = ""
                    label_candidates = [
                        row.locator(".ant-form-item-label .attr-label"),
                        row.locator(".ant-form-item-label label"),
                        row.locator(".ant-form-item-label"),
                    ]

                    for lab in label_candidates:
                        try:
                            if await lab.count() > 0:
                                label_text = (await lab.first.inner_text()).strip()
                                if label_text:
                                    break
                        except Exception:
                            continue

                    if not label_text:
                        label_text = (await row.inner_text()).strip()
                except Exception:
                    continue

                if any(term in label_text for term in field_terms):
                    control_candidates = [
                        row.locator(".ant-form-item-control .ant-select-selector"),
                        row.locator(".ant-form-item-control .ant-select-in-form-item"),
                        row.locator(".ant-form-item-control input[role='combobox']"),
                        row.locator(".ant-form-item-control input.ant-select-selection-search-input"),
                    ]
                    for cand in control_candidates:
                        try:
                            if await cand.count() > 0:
                                return cand.first
                        except Exception:
                            continue

            return None

        async def pick_customs_select(field_terms: list[str], option_texts: list[str], description: str) -> bool:
            """
            海关监管弹窗：
            通过“品名/材质”文案反向定位表单行，再定位同一行右侧下拉框。
            """
            # 在函数内部做显式等待，不依赖外部一次性获取结果
            modal = await get_customs_modal()
            if not modal:
                logger.warning(f"未找到海关监管弹窗: {description}")
                return False

            # 先等文案渲染，避免异步弹窗还未就绪
            label_ready = False
            for _ in range(10):
                selector = await get_row_selector_by_label(modal, field_terms)
                if selector:
                    label_ready = True
                    break
                await asyncio.sleep(0.3)

            if not label_ready:
                logger.warning(f"未找到海关监管下拉框: {description}")
                return False

            selector = await get_row_selector_by_label(modal, field_terms)
            if not selector:
                logger.warning(f"未找到海关监管下拉框: {description}")
                return False

            try:
                await selector.scroll_into_view_if_needed()
                await selector.click(timeout=3000, force=True)
                await asyncio.sleep(0.6)
            except Exception:
                try:
                    container = selector.locator("xpath=ancestor::div[contains(@class,'ant-select-selector')]").first
                    await container.scroll_into_view_if_needed()
                    await container.click(timeout=3000, force=True)
                    await asyncio.sleep(0.6)
                except Exception:
                    logger.warning(f"未能打开海关监管下拉框: {description}")
                    return False

            for _ in range(12):
                for opt_text in option_texts:
                    option_locators = [
                        self.page.locator(f".ant-select-dropdown .ant-select-item-option[title='{opt_text}']"),
                        self.page.locator(f".ant-select-dropdown div[title='{opt_text}']"),
                        self.page.locator(f".ant-select-dropdown [role='option']:has-text('{opt_text}')"),
                        self.page.locator(".ant-select-dropdown .ant-select-item-option-content").filter(has_text=opt_text),
                        self.page.locator(".ant-select-dropdown .in-check-options").filter(has_text=opt_text),
                        self.page.get_by_text(opt_text, exact=False),
                    ]

                    for option in option_locators:
                        try:
                            if await option.count() > 0:
                                await option.first.scroll_into_view_if_needed()
                                await option.first.click(timeout=3000)
                                logger.success(f"选择成功: {description} = {opt_text}")
                                await asyncio.sleep(0.8)
                                return True
                        except Exception:
                            continue

                await asyncio.sleep(0.3)

            logger.warning(f"未找到海关监管选项: {description}")
            return False

        # 通用海关监管多级方案：
        # - 优先用 customs_level1~4
        # - 兼容旧字段 customs_item/customs_material
        if customs_auto_fill_targets:
            customs_levels = customs_auto_fill_targets
            logger.info("海关监管使用弹窗字段自动目标，不受跳过勾选限制")
        elif customs_skip_flow or customs_click_only:
            customs_levels = []
        else:
            customs_levels = [
                "" if is_skip("customs_level1") else str(CONFIG.get("customs_level1", "")).strip(),
                "" if is_skip("customs_level2") else str(CONFIG.get("customs_level2", "")).strip(),
                "" if is_skip("customs_level3") else str(CONFIG.get("customs_level3", "")).strip(),
                "" if is_skip("customs_level4") else str(CONFIG.get("customs_level4", "")).strip(),
            ]

            if not customs_levels[0] and not is_skip("customs_item"):
                customs_levels[0] = str(CONFIG.get("customs_item", "")).strip()
            if not customs_levels[1] and not is_skip("customs_material"):
                customs_levels[1] = str(CONFIG.get("customs_material", "")).strip()

            customs_levels = [v for v in customs_levels if v]
        logger.info(f"海关监管目标层级: {customs_levels}")

        async def click_dropdown_option_by_normalized_text(option_text: str, description: str, selector=None) -> bool:
            """
            选择当前字段自己的 Ant Select 选项，兼容中英文括号、AI推荐、前缀匹配。
            如果传入 selector，会绑定该字段 input 的 aria-controls，避免误扫其他残留下拉框。
            """
            try:
                if selector is not None:
                    clicked_text = await selector.evaluate(
                        """async (el, targetText) => {
                        const normalize = (s) => (s || "")
                            .replace(/\\uFF08/g, "(")
                            .replace(/\\uFF09/g, ")")
                            .replace(/\\s+/g, "")
                            .replace(/\\(ai推荐\\)/gi, "")
                            .replace(/ai推荐/gi, "")
                            .trim()
                            .toLowerCase();
                        const englishKey = (s) => {
                            const m = String(s || "")
                                .replace(/\\uFF08/g, "(")
                                .replace(/\\uFF09/g, ")")
                                .match(/\\(([A-Za-z][A-Za-z0-9\\s\\-\\/]+)\\)/);
                            return m ? normalize(m[1]) : "";
                        };
                        const isOtherText = (s) => {
                            const n = normalize(s).replace(/\\(other\\)/gi, "");
                            const key = englishKey(s);
                            return n === "其他" || n === "other" || key === "other";
                        };
                        const visible = (node) => {
                            if (!node || !node.getBoundingClientRect) return false;
                            const st = window.getComputedStyle(node);
                            const rect = node.getBoundingClientRect();
                            return st.display !== "none"
                                && st.visibility !== "hidden"
                                && rect.width > 0
                                && rect.height > 0;
                        };
                        const clickNode = (node) => {
                            const rect = node.getBoundingClientRect();
                            const init = {
                                bubbles: true,
                                cancelable: true,
                                view: window,
                                clientX: rect.left + rect.width / 2,
                                clientY: rect.top + rect.height / 2,
                            };
                            ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach((type) => {
                                node.dispatchEvent(new MouseEvent(type, init));
                            });
                        };
                        const target = normalize(targetText);
                        const targetKey = englishKey(targetText) || target;
                        const selectRoot = el.closest(".ant-select") || el;
                        const selectorNode = selectRoot.querySelector(".ant-select-selector") || el;
                        const input = selectRoot.querySelector("input[role='combobox'], input.ant-select-selection-search-input");
                        const controls = input?.getAttribute("aria-controls") || input?.getAttribute("aria-owns") || "";

                        selectorNode.scrollIntoView({ block: "center", inline: "nearest" });
                        clickNode(selectorNode);

                        const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                        const findDropdown = () => {
                            const roots = Array.from(document.querySelectorAll(".ant-select-dropdown")).filter(visible);
                            if (!roots.length) return null;
                            if (controls) {
                                const bound = roots.find((root) => {
                                    try {
                                        return !!root.querySelector(`#${CSS.escape(controls)}`);
                                    } catch (_) {
                                        return false;
                                    }
                                });
                                if (bound) return bound;
                            }
                            return roots[roots.length - 1];
                        };
                        let root = null;
                        for (let i = 0; i < 30; i += 1) {
                            root = findDropdown();
                            if (root) break;
                            await wait(100);
                        }
                        if (!root || !target) return "";

                        const findMatch = () => {
                            if (!root || !target) return null;
                            const items = Array.from(root.querySelectorAll(
                                ".ant-select-item-option:not(.ant-select-item-option-disabled), [role='option'], .ant-select-item-option-content, .in-check-options, div[title]"
                            ));
                            const candidates = items.map((el) => {
                                const text = (el.getAttribute("title") || el.innerText || "").trim();
                                const norm = normalize(text);
                                const key = englishKey(text) || norm;
                                let score = 0;
                                if (norm === target) score = 100;
                                else if (isOtherText(text) && isOtherText(targetText)) score = 95;
                                else if (targetKey && key === targetKey) score = 90;
                                else if (target && (norm.startsWith(target) || target.startsWith(norm))) score = 80;
                                else if (target && (norm.includes(target) || target.includes(norm))) score = 70;
                                else if (targetKey && (key.startsWith(targetKey) || targetKey.startsWith(key))) score = 60;
                                return { el, text, norm, key, score };
                            }).filter((item) => item.text);
                            return candidates.filter((item) => item.score > 0)
                                .sort((a, b) => b.score - a.score)[0] || null;
                        };

                        const holder = root.querySelector(".rc-virtual-list-holder")
                            || root.querySelector(".ant-select-dropdown")
                            || root;

                        let found = null;
                        for (let i = 0; i < 18; i += 1) {
                            found = findMatch();
                            if (found) break;
                            if (holder) holder.scrollTop = holder.scrollTop + 280;
                            await wait(80);
                        }

                        if (!found && holder) {
                            holder.scrollTop = 0;
                            for (let i = 0; i < 18; i += 1) {
                                found = findMatch();
                                if (found) break;
                                holder.scrollTop = holder.scrollTop + 280;
                                await wait(80);
                            }
                        }

                        if (!found) {
                            const visibleOptions = Array.from(root.querySelectorAll(".ant-select-item-option, [role='option'], .in-check-options"))
                                .map((el) => (el.getAttribute("title") || el.innerText || "").trim())
                                .filter(Boolean)
                                .slice(0, 12)
                                .join(" | ");
                            return "__NOT_FOUND__" + visibleOptions;
                        }

                        const optionNode = found.el.closest(".ant-select-item-option")
                            || found.el.closest(".ant-select-item")
                            || found.el;
                        optionNode.scrollIntoView({ block: "center", inline: "nearest" });
                        clickNode(optionNode);
                        return found.text;
                    }""",
                        option_text
                    )
                else:
                    clicked_text = await self.page.evaluate(
                        """(targetText) => {
                            const normalize = (s) => (s || "")
                                .replace(/\\uFF08/g, "(")
                                .replace(/\\uFF09/g, ")")
                                .replace(/\\s+/g, "")
                                .replace(/\\(ai推荐\\)/gi, "")
                                .replace(/ai推荐/gi, "")
                                .trim()
                                .toLowerCase();
                            const target = normalize(targetText);
                            const isOtherText = (s) => {
                                const n = normalize(s).replace(/\\(other\\)/gi, "");
                                return n === "其他" || n === "other";
                            };
                            const roots = Array.from(document.querySelectorAll(".ant-select-dropdown"))
                                .filter((el) => {
                                    const st = window.getComputedStyle(el);
                                    const rect = el.getBoundingClientRect();
                                    return st.display !== "none"
                                        && st.visibility !== "hidden"
                                        && rect.width > 0
                                        && rect.height > 0;
                                });
                            const root = roots.length ? roots[roots.length - 1] : null;
                            if (!root || !target) return "";
                            const items = Array.from(root.querySelectorAll(
                                ".ant-select-item-option:not(.ant-select-item-option-disabled), [role='option'], .ant-select-item-option-content, .in-check-options, div[title]"
                            ));
                            const found = items.map((el) => {
                                const text = (el.getAttribute("title") || el.innerText || "").trim();
                                const norm = normalize(text);
                                return { el, text, norm };
                            }).filter((item) => item.text).find((item) => (
                                item.norm === target
                                || (isOtherText(item.text) && isOtherText(targetText))
                                || item.norm.startsWith(target)
                                || target.startsWith(item.norm)
                                || item.norm.includes(target)
                            ));
                            if (!found) {
                                const visibleOptions = Array.from(root.querySelectorAll(".ant-select-item-option, [role='option'], .in-check-options"))
                                    .map((el) => (el.getAttribute("title") || el.innerText || "").trim())
                                    .filter(Boolean)
                                    .slice(0, 12)
                                    .join(" | ");
                                return "__NOT_FOUND__" + visibleOptions;
                            }
                            const optionNode = found.el.closest(".ant-select-item-option")
                                || found.el.closest(".ant-select-item")
                                || found.el;
                            optionNode.scrollIntoView({ block: "center", inline: "nearest" });
                            optionNode.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                            optionNode.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                            optionNode.click();
                            return found.text;
                        }""",
                        option_text
                    )
                if clicked_text and clicked_text.startswith("__NOT_FOUND__"):
                    logger.warning(f"{description} 当前下拉可见选项: {clicked_text.replace('__NOT_FOUND__', '')}")
                    return False
                if clicked_text:
                    logger.success(f"选择成功: {description} = {clicked_text}")
                    return True
            except Exception:
                pass
            return False

        async def click_dropdown_option_by_mouse(option_text: str, description: str, selector) -> bool:
            """
            店小秘海关弹窗里的级联 Select 对 JS 派发 click 不稳定。
            这里只用 JS 做“找坐标”，最终用 Playwright mouse.click 触发真实鼠标点击。
            """
            try:
                await selector.scroll_into_view_if_needed()
                await selector.click(timeout=3000, force=True)
                await asyncio.sleep(0.4)

                match_info = await selector.evaluate(
                    """async (el, targetText) => {
                        const normalize = (s) => (s || "")
                            .replace(/\\uFF08/g, "(")
                            .replace(/\\uFF09/g, ")")
                            .replace(/\\s+/g, "")
                            .replace(/\\(ai推荐\\)/gi, "")
                            .replace(/ai推荐/gi, "")
                            .trim()
                            .toLowerCase();
                        const englishKey = (s) => {
                            const m = String(s || "")
                                .replace(/\\uFF08/g, "(")
                                .replace(/\\uFF09/g, ")")
                                .match(/\\(([A-Za-z][A-Za-z0-9\\s\\-\\/]+)\\)/);
                            return m ? normalize(m[1]) : "";
                        };
                        const isOtherText = (s) => {
                            const n = normalize(s).replace(/\\(other\\)/gi, "");
                            const key = englishKey(s);
                            return n === "其他" || n === "other" || key === "other";
                        };
                        const visible = (node) => {
                            if (!node || !node.getBoundingClientRect) return false;
                            const st = window.getComputedStyle(node);
                            const rect = node.getBoundingClientRect();
                            return st.display !== "none"
                                && st.visibility !== "hidden"
                                && rect.width > 0
                                && rect.height > 0;
                        };
                        const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                        const selectRoot = el.closest(".ant-select") || el;
                        const input = selectRoot.querySelector("input[role='combobox'], input.ant-select-selection-search-input");
                        const controls = input?.getAttribute("aria-controls") || input?.getAttribute("aria-owns") || "";

                        const findDropdown = () => {
                            const roots = Array.from(document.querySelectorAll(".ant-select-dropdown")).filter(visible);
                            if (!roots.length) return null;
                            if (controls) {
                                const bound = roots.find((root) => {
                                    try {
                                        return !!root.querySelector(`#${CSS.escape(controls)}`);
                                    } catch (_) {
                                        return false;
                                    }
                                });
                                if (bound) return bound;
                            }
                            return roots[roots.length - 1];
                        };

                        let root = null;
                        for (let i = 0; i < 30; i += 1) {
                            root = findDropdown();
                            if (root) break;
                            await wait(100);
                        }
                        if (!root) return { ok: false, reason: "no_dropdown", options: "" };

                        const target = normalize(targetText);
                        const targetKey = englishKey(targetText) || target;
                        const holder = root.querySelector(".rc-virtual-list-holder") || root;

                        const collect = () => Array.from(root.querySelectorAll(
                            ".ant-select-item-option:not(.ant-select-item-option-disabled), [role='option'], .ant-select-item-option-content, .in-check-options, div[title]"
                        )).filter(visible).map((node) => {
                            const text = (node.getAttribute("title") || node.innerText || "").trim();
                            const norm = normalize(text);
                            const key = englishKey(text) || norm;
                            let score = 0;
                            if (norm === target) score = 100;
                            else if (isOtherText(text) && isOtherText(targetText)) score = 95;
                            else if (targetKey && key === targetKey) score = 90;
                            else if (target && (norm.startsWith(target) || target.startsWith(norm))) score = 80;
                            else if (target && (norm.includes(target) || target.includes(norm))) score = 70;
                            else if (targetKey && (key.startsWith(targetKey) || targetKey.startsWith(key))) score = 60;
                            return { node, text, score };
                        }).filter((item) => item.text);

                        let found = null;
                        for (let i = 0; i < 20; i += 1) {
                            found = collect().filter((item) => item.score > 0).sort((a, b) => b.score - a.score)[0] || null;
                            if (found) break;
                            holder.scrollTop += 260;
                            await wait(80);
                        }
                        if (!found) {
                            holder.scrollTop = 0;
                            await wait(80);
                            for (let i = 0; i < 20; i += 1) {
                                found = collect().filter((item) => item.score > 0).sort((a, b) => b.score - a.score)[0] || null;
                                if (found) break;
                                holder.scrollTop += 260;
                                await wait(80);
                            }
                        }

                        if (!found) {
                            return {
                                ok: false,
                                reason: "not_found",
                                options: collect().map((item) => item.text).slice(0, 12).join(" | ")
                            };
                        }

                        const optionNode = found.node.closest(".ant-select-item-option")
                            || found.node.closest(".ant-select-item")
                            || found.node;
                        optionNode.scrollIntoView({ block: "center", inline: "nearest" });
                        const rect = optionNode.getBoundingClientRect();
                        return {
                            ok: true,
                            text: found.text,
                            score: found.score,
                            x: rect.left + rect.width / 2,
                            y: rect.top + rect.height / 2
                        };
                    }""",
                    option_text
                )

                if not match_info or not match_info.get("ok"):
                    logger.warning(
                        f"{description} 真实点击前未找到匹配选项: "
                        f"reason={match_info.get('reason') if match_info else 'empty'}, "
                        f"options={match_info.get('options') if match_info else ''}"
                    )
                    return False

                await self.page.mouse.click(float(match_info["x"]), float(match_info["y"]))
                await asyncio.sleep(0.8)
                logger.success(f"选择成功: {description} = {match_info.get('text')}")
                return True
            except Exception as exc:
                logger.warning(f"{description} 真实鼠标点击失败: {exc}")
                return False

        def normalize_customs_text(text: str) -> str:
            return (
                (text or "")
                .replace("（", "(")
                .replace("）", ")")
                .replace("\u00a0", " ")
                .replace(" ", "")
                .replace("(AI推荐)", "")
                .replace("(ai推荐)", "")
                .replace("AI推荐", "")
                .replace("ai推荐", "")
                .strip()
                .lower()
            )

        def customs_text_matches(current_text: str, option_text: str) -> bool:
            current_norm = normalize_customs_text(current_text)
            target_norm = normalize_customs_text(option_text)
            if not current_norm or not target_norm or "请选择" in (current_text or ""):
                return False
            current_other = current_norm.replace("(other)", "") in {"其他", "other"}
            target_other = target_norm.replace("(other)", "") in {"其他", "other"}
            if current_other and target_other:
                return True
            return (
                current_norm == target_norm
                or current_norm.startswith(target_norm)
                or target_norm.startswith(current_norm)
            )

        async def get_select_current_text(selector) -> str:
            try:
                return await selector.evaluate(
                    """(el) => {
                        const root = el.closest(".ant-select") || el;
                        return (
                            root.querySelector(".ant-select-selection-item")?.getAttribute("title")
                            || root.querySelector(".ant-select-selection-item")?.innerText
                            || root.innerText
                            || ""
                        ).trim();
                    }"""
                )
            except Exception:
                return ""

        async def wait_customs_level_committed(level_index: int, selector, option_text: str) -> bool:
            """
            等待当前级别真的显示为目标值，避免选项点击后页面还没写入就进入下一级。
            """
            target_norm = normalize_customs_text(option_text)
            last_text = ""
            for _ in range(30):
                last_text = await get_select_current_text(selector)
                current_norm = normalize_customs_text(last_text)
                if customs_text_matches(last_text, option_text):
                    logger.success(f"已确认海关监管第{level_index+1}级选中: {last_text}")
                    return True

                await asyncio.sleep(0.25)

            logger.warning(
                f"海关监管第{level_index+1}级点击后未确认选中，目标={option_text}，目标归一={target_norm}，"
                f"当前={last_text or '空'}，当前归一={normalize_customs_text(last_text)}"
            )
            return False

        async def wait_customs_after_level(level_index: int, next_level_index: int | None = None) -> bool:
            """
            等待级联刷新完成。这里只做软等待，不把“下一级未及时出现”当作失败。
            """
            try:
                modal = await get_customs_modal()
                if modal:
                    title = modal.locator(".ant-modal-title, text=海关监管").first
                    if await title.count() > 0:
                        await title.click(timeout=800, force=True)
            except Exception:
                pass

            try:
                await self.page.wait_for_load_state("networkidle", timeout=2500)
            except Exception:
                pass

            # 店小秘这里有时没有标准 networkidle，只能轮询 DOM 中的 loading/spin。
            await self.page.evaluate(
                """() => new Promise((resolve) => {
                    const isLoading = () => Array.from(document.querySelectorAll(
                        ".ant-spin-spinning, .ant-select-loading-icon, .ant-select-item-empty"
                    )).some((el) => {
                        const st = window.getComputedStyle(el);
                        const text = (el.innerText || "").trim();
                        return st.display !== "none"
                            && st.visibility !== "hidden"
                            && (text.includes("加载") || text.includes("Loading") || el.classList.contains("ant-spin-spinning") || el.classList.contains("ant-select-loading-icon"));
                    });
                    let tries = 0;
                    const tick = () => {
                        tries += 1;
                        if (!isLoading() || tries >= 30) return resolve(true);
                        setTimeout(tick, 200);
                    };
                    tick();
                })"""
            )

            if next_level_index is None:
                return True

            level_label_terms = [
                ["车身零件类型", "Body Part Type", "车辆零件类型", "Vehicle Part Type"],
                ["材质", "Material"],
                ["适用车辆类型", "Applicable Vehicle Type", "适用对象", "Applicable Object"],
                ["轮胎载重指数", "Tire load index"],
            ]

            modal = await get_customs_modal()
            if not modal or next_level_index >= len(level_label_terms):
                await asyncio.sleep(0.8)
                return True

            for _ in range(30):
                next_selector = await get_row_selector_by_label(modal, level_label_terms[next_level_index])
                if next_selector:
                    try:
                        disabled = await next_selector.evaluate(
                            """(el) => {
                                const root = el.closest(".ant-select") || el;
                                return root.classList.contains("ant-select-disabled")
                                    || !!root.querySelector("input[disabled]");
                            }"""
                        )
                        if not disabled:
                            logger.info(f"海关监管第{next_level_index+1}级已可操作")
                            return True
                    except Exception:
                        return True
                await asyncio.sleep(0.3)

            logger.warning(f"海关监管第{next_level_index+1}级等待超时：子级字段尚未生成")
            return False

        async def pick_customs_level_by_index(level_index: int, option_text: str, allow_fallback: bool = False) -> bool:
            """
            按“当前弹窗里的第 N 个下拉框”去选，不依赖字段名字固定不变。
            每选一层，都等待下一层异步加载出来。
            """
            if not option_text:
                return False

            logger.info(f"海关监管第{level_index+1}级开始选择，目标={option_text}")
            modal = await get_customs_modal()
            if not modal:
                logger.warning(f"未找到海关监管弹窗: 第{level_index+1}级")
                return False

            try:
                level_label_terms = [
                    ["车身零件类型", "Body Part Type", "车辆零件类型", "Vehicle Part Type"],
                    ["材质", "Material"],
                    ["适用车辆类型", "Applicable Vehicle Type", "适用对象", "Applicable Object"],
                    ["轮胎载重指数", "Tire load index"],
                ]

                selector = None
                total = 0
                all_selects = modal.locator(".ant-select-selector")
                visible_select_indexes = []
                total = await all_selects.count()
                for select_idx in range(total):
                    try:
                        cand = all_selects.nth(select_idx)
                        if await cand.is_visible():
                            visible_select_indexes.append(select_idx)
                    except Exception:
                        continue

                if len(visible_select_indexes) > level_index:
                    selector = all_selects.nth(visible_select_indexes[level_index])
                    logger.info(f"海关监管第{level_index+1}级按弹窗第 {level_index+1} 个可见下拉定位")

                if not selector and level_index < len(level_label_terms):
                    for _ in range(20):
                        selector = await get_row_selector_by_label(modal, level_label_terms[level_index])
                        if selector:
                            logger.warning(f"海关监管第{level_index+1}级未按序号命中，改按字段名定位: {'/'.join(level_label_terms[level_index])}")
                            break
                        await asyncio.sleep(0.3)

                try:
                    labels_snapshot = await modal.evaluate(
                        """(root) => Array.from(root.querySelectorAll(".ant-form-item-row, .ant-row"))
                            .map((row) => (row.innerText || "").replace(/\\s+/g, " ").trim())
                            .filter((text) => text && /Body Part Type|Material|Applicable Vehicle Type|车身零件类型|材质|适用车辆类型/.test(text))
                            .slice(0, 8)"""
                    )
                    logger.info(f"海关监管弹窗字段快照: {' || '.join(labels_snapshot)}")
                except Exception:
                    pass

                if not selector:
                    logger.info(f"海关监管当前只有 {total} 个下拉框，下标 {level_index} 不存在，停止后续级联选择")
                    return False

                await selector.scroll_into_view_if_needed()
                before_text = await get_select_current_text(selector)
                logger.info(f"海关监管第{level_index+1}级打开前当前值: {before_text or '空'}")
                if customs_text_matches(before_text, option_text):
                    next_idx = level_index + 1 if level_index + 1 < len(customs_levels) else None
                    if next_idx is None:
                        logger.success(f"海关监管第{level_index+1}级已是目标值，跳过重复选择: {before_text}")
                        return True

                    if await wait_customs_after_level(level_index, next_idx):
                        logger.success(f"海关监管第{level_index+1}级已是目标值，且第{next_idx+1}级已生成: {before_text}")
                        return True

                    logger.warning(
                        f"海关监管第{level_index+1}级虽已是目标值，但第{next_idx+1}级未生成，"
                        f"将重新选择当前级触发级联加载: {before_text}"
                    )
                    await selector.click(timeout=3000, force=True)
                    await asyncio.sleep(0.8)
                    if await click_dropdown_option_by_mouse(option_text, f"海关监管第{level_index+1}级重新触发", selector):
                        await asyncio.sleep(1.0)
                        if await wait_customs_after_level(level_index, next_idx):
                            logger.success(f"海关监管第{level_index+1}级重新触发后，第{next_idx+1}级已生成")
                            return True
                    logger.warning(f"海关监管第{level_index+1}级重新触发后，第{next_idx+1}级仍未生成")
                    return True

                await selector.scroll_into_view_if_needed()
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.warning(f"无法打开海关监管第{level_index+1}级下拉框: {e}")
                return False

            if await click_dropdown_option_by_mouse(option_text, f"海关监管第{level_index+1}级", selector):
                if not await wait_customs_level_committed(level_index, selector, option_text):
                    return False
                next_idx = level_index + 1 if level_index + 1 < len(customs_levels) else None
                await wait_customs_after_level(level_index, next_idx)
                return True

            for _ in range(12):
                option_locators = [
                    self.page.locator(f".ant-select-dropdown .ant-select-item-option[title='{option_text}']"),
                    self.page.locator(f".ant-select-dropdown div[title='{option_text}']"),
                    self.page.locator(".ant-select-dropdown .ant-select-item-option-content").filter(has_text=option_text),
                ]
                for option in option_locators:
                    try:
                        if await option.count() > 0:
                            await option.first.click(timeout=3000)
                            logger.success(f"选择成功: 海关监管第{level_index+1}级 = {option_text}")
                            if not await wait_customs_level_committed(level_index, selector, option_text):
                                return False
                            next_idx = level_index + 1 if level_index + 1 < len(customs_levels) else None
                            await wait_customs_after_level(level_index, next_idx)
                            return True
                    except Exception:
                        continue
                await asyncio.sleep(0.3)

            current_text = await get_select_current_text(selector)
            logger.warning(f"海关监管第{level_index+1}级未找到目标选项: {option_text}，当前字段值={current_text or '空'}")
            if allow_fallback or level_index >= 2:
                if current_text and "请选择" not in current_text:
                    logger.warning(
                        f"海关监管第{level_index+1}级目标与页面候选不匹配，保留当前值继续: "
                        f"target={option_text}, current={current_text}"
                    )
                    next_idx = level_index + 1 if level_index + 1 < len(customs_levels) else None
                    await wait_customs_after_level(level_index, next_idx)
                    return True

                for fallback_text in ["其他(Other)（AI推荐）", "其他(Other)(AI推荐)", "其他(Other)", "其他", "Other"]:
                    fallback_clicked = await click_dropdown_option_by_mouse(
                        fallback_text,
                        f"海关监管第{level_index+1}级兜底",
                        selector,
                    )
                    if not fallback_clicked:
                        fallback_clicked = await click_dropdown_option_by_normalized_text(
                            fallback_text,
                            f"海关监管第{level_index+1}级兜底",
                            selector,
                        )
                    if fallback_clicked:
                        if not await wait_customs_level_committed(level_index, selector, fallback_text):
                            logger.warning(
                                f"海关监管第{level_index+1}级兜底点击后未写入，继续尝试下一个兜底: "
                                f"fallback={fallback_text}"
                            )
                            continue
                        logger.warning(
                            f"海关监管第{level_index+1}级未找到预设值，已使用兜底选项继续: "
                            f"target={option_text}, fallback={fallback_text}"
                        )
                        await wait_customs_after_level(level_index, None)
                        return True
            return False

        async def fill_dynamic_customs_modal_fields(max_rounds: int = 8) -> bool:
            """
            海关监管字段会在选择上一项后动态生成下一项。
            每次只处理当前第一个待选下拉框，选完后重新扫描弹窗。
            """
            for round_idx in range(max_rounds):
                selects = await customs_select_snapshot()
                if not selects:
                    logger.info("海关监管动态填充：未检测到弹窗下拉字段")
                    return True

                unresolved = [
                    (idx, item)
                    for idx, item in enumerate(selects)
                    if item.get("unresolved")
                ]
                if not unresolved:
                    logger.success("海关监管动态填充：所有下拉字段已选择完成")
                    return True

                targets = build_auto_customs_targets(selects)
                select_idx, select_info = unresolved[0]
                target = targets[select_idx] if select_idx < len(targets) else "其他(Other)"
                label = str(select_info.get("label", "") or f"第{select_idx + 1}个字段").strip()
                logger.info(
                    f"海关监管动态填充第{round_idx + 1}轮："
                    f"处理第{select_idx + 1}个待选字段 {label}，目标={target}"
                )

                ok = await pick_customs_level_by_index(select_idx, target, allow_fallback=True)
                if not ok:
                    logger.warning(
                        f"海关监管动态填充失败：第{select_idx + 1}个字段未选中，"
                        f"label={label}, target={target}"
                    )
                    return False

                await wait_customs_after_level(select_idx, None)
                await asyncio.sleep(0.8)

            remaining = await unresolved_customs_select_count()
            if remaining > 0:
                logger.warning(f"海关监管动态填充达到最大轮次后仍有 {remaining} 个待选字段")
                return False
            logger.success("海关监管动态填充：最大轮次后复查已无待选字段")
            return True

        if customs_auto_fill_targets:
            ok = await fill_dynamic_customs_modal_fields()
            if not ok:
                raise RuntimeError("海关监管动态字段未全部确认选中，停止后续流程")
        else:
            for idx, option_text in enumerate(customs_levels):
                ok = await pick_customs_level_by_index(idx, option_text)
                if not ok:
                    raise RuntimeError(f"海关监管第{idx+1}级未确认选中，停止后续流程: {option_text}")

            remaining_customs_selects = await unresolved_customs_select_count()
            if remaining_customs_selects > 0:
                logger.warning(
                    f"海关监管预设层级选择后仍有 {remaining_customs_selects} 个待选下拉字段，"
                    "切换为动态填充兜底"
                )
                ok = await fill_dynamic_customs_modal_fields()
                if not ok:
                    raise RuntimeError("海关监管兜底动态字段未全部确认选中，停止后续流程")

        # 点击确定（若存在）。跳过/仅点击模式不再尝试确认，避免误点其它弹窗或页面按钮。
        if customs_skip_flow or customs_click_only:
            logger.info(f"海关监管弹窗确认步骤不执行: mode={customs_mode}")
            await confirm_or_close_customs_modal_if_visible(f"海关监管弹窗兜底处理 mode={customs_mode}")
        else:
            confirm_btn = self.page.locator(".ant-modal button:has-text('确定'), .ant-drawer button:has-text('确定'), button:has-text('确定')")
            if await confirm_btn.count() > 0:
                try:
                    await wait_page_stable("海关监管-确定前")
                    await asyncio.sleep(0.8)
                    await confirm_btn.first.click(timeout=3000, force=True)
                    logger.success("点击成功: 海关监管-确定")
                    await wait_page_stable("海关监管-确定后")
                except Exception as e:
                    logger.warning(f"海关监管-确定点击失败: {e}")
            else:
                logger.warning("未找到海关监管-确定按钮，跳过确认步骤")

        # ===== 其他信息补充 =====
        # 1) 报价是否含关税 -> 含关税报价（精确点击 value=2）
        if not is_skip("tax_included"):
            tax_selected = False
            tax_target = str(CONFIG.get("tax_included", "含关税报价")).strip()
            tax_value = "1" if "不含" in tax_target else "2"

            tax_radio = self.page.locator(f"input.ant-radio-input[value='{tax_value}']").first
            if await tax_radio.count() > 0:
                try:
                    await tax_radio.check(force=True)
                    tax_selected = True
                    logger.success(f"选择成功: 报价是否含关税 = {tax_target}(value={tax_value})")
                except Exception as e:
                    logger.warning(f"tax_radio.check 失败，改用文本点击兜底: {e}")

            if not tax_selected:
                # 兜底：按配置文本点击
                tax_selected = await self.smart_click_by_text([tax_target], f"报价是否含关税-{tax_target}")
            if not tax_selected:
                logger.warning(f"未能精确选择“{tax_target}”")
            await asyncio.sleep(0.5)

        async def select_by_field_input(input_id: str, option_texts: list[str], description: str) -> bool:
            inp = self.page.locator(f"input#{input_id}")
            if await inp.count() == 0:
                logger.warning(f"未找到输入框: {description} ({input_id})")
                return False

            click_targets = [
                inp.locator("xpath=ancestor::div[contains(@class,'ant-select-selector')]").first,
                inp.locator("xpath=ancestor::div[contains(@class,'ant-select')]").first,
                inp.first,
            ]

            opened = False
            for target in click_targets:
                try:
                    if await target.count() > 0:
                        await target.scroll_into_view_if_needed()
                        await target.click(timeout=3000, force=True)
                        opened = True
                        break
                except Exception:
                    continue

            if not opened:
                logger.warning(f"未能打开下拉框: {description}")
                return False

            await asyncio.sleep(0.5)

            for _ in range(10):
                for text in option_texts:
                    option_locators = [
                        self.page.locator(f".ant-select-dropdown .ant-select-item-option[title='{text}']"),
                        self.page.locator(f".ant-select-dropdown div[title='{text}']"),
                        self.page.locator(".ant-select-dropdown .ant-select-item-option-content").filter(has_text=text),
                        self.page.get_by_text(text, exact=False),
                    ]
                    for opt in option_locators:
                        try:
                            if await opt.count() > 0:
                                await opt.first.scroll_into_view_if_needed()
                                await opt.first.click(timeout=3000)
                                logger.success(f"选择成功: {description} = {text}")
                                await asyncio.sleep(0.6)
                                return True
                        except Exception:
                            continue
                await asyncio.sleep(0.2)

            logger.warning(f"未找到下拉选项: {description}")
            return False

        # 2) 欧盟责任人 -> GOLDENCLICK SL
        if not is_skip("european_responsible"):
            await select_by_field_input(
                "form_item_msrEuId",
                [str(CONFIG.get("european_responsible", "预设好的")), "GOLDENCLICK SL", "GOLDENCLIC SL"],
                "欧盟责任人"
            )

        if not is_skip("brand_manufacturer"):
            await select_by_field_input(
                "form_item_manufactureId",
                [str(CONFIG.get("brand_manufacturer", "预设好的")), "Guangzhou Qingsu International Trade Co., Ltd", "预设好的", "制造商信息"],
                "品牌制造商"
            )

        await self.capture_state("04_templates_and_options")

    async def step_description_info(self):
        raw_desc_mode = str(CONFIG.get("description_image_mode", "保留前N张") or "保留前N张").strip()
        desc_image_count = max(0, int(CONFIG.get("description_image_count", 5) or 0))
        if "不" in raw_desc_mode or "跳" in raw_desc_mode or raw_desc_mode.lower() in {"none", "skip", "off"}:
            desc_image_mode = "none"
        elif "删" in raw_desc_mode or raw_desc_mode.lower().startswith("delete"):
            desc_image_mode = "delete"
        else:
            desc_image_mode = "keep"
        trim_config = {"mode": desc_image_mode, "count": desc_image_count}

        if desc_image_mode == "none":
            logger.info("步骤5: 处理描述信息（详情图不删减 + 无线端老版编辑器一键生成）")
        elif desc_image_mode == "delete":
            logger.info(f"步骤5: 处理描述信息（PC/无线端删除末尾{desc_image_count}张详情图 + 无线端老版编辑器一键生成）")
        else:
            logger.info(f"步骤5: 处理描述信息（PC/无线端保留前{desc_image_count}张详情图 + 无线端老版编辑器一键生成）")

        # ===== 5.1 PC端描述：按配置删减详情图 =====
        # 你提供的 DOM 含有 cke-id / data-cke-saved-src，优先按 CKEditor 风格定位
        trimmed = False
        pc_left_in_editor = None

        # 方案A：先尝试 iframe 编辑器
        try:
            frame_done = False
            for frame in self.page.frames:
                if frame == self.page.main_frame:
                    continue
                try:
                    result = await frame.evaluate(
                        """(trimConfig) => {
                            const body = document.body;
                            if (!body) return { ok: false };
                            const mode = String(trimConfig?.mode || "keep").toLowerCase();
                            const count = Math.max(0, Number(trimConfig?.count || 5) || 0);
                            const pickRemoveList = (items) => {
                                if (mode === "none" || count <= 0) return [];
                                if (mode === "delete") return items.slice(Math.max(0, items.length - count));
                                return items.slice(count);
                            };

                            const imgs = Array.from(body.querySelectorAll("img[cke-id], img[data-cke-saved-src], img[src]"));
                            if (imgs.length === 0) return { ok: false };

                            const target = imgs.filter(img => (img.getAttribute("src") || "").startsWith("http"));
                            const work = target.length > 0 ? target : imgs;

                            const removeList = pickRemoveList(work);
                            removeList.forEach(img => {
                                // 只删除图片节点本身，避免误删整块容器
                                img.remove();
                            });

                            const left = Array.from(body.querySelectorAll("img[cke-id], img[data-cke-saved-src], img[src^='http']")).length;
                            body.dispatchEvent(new Event("input", { bubbles: true }));
                            body.dispatchEvent(new Event("change", { bubbles: true }));
                            return { ok: true, total: work.length, removed: removeList.length, left };
                        }""",
                        trim_config,
                    )
                    if result and result.get("ok"):
                        pc_left_in_editor = result.get("left")
                        logger.success(f"PC端描述处理成功：共{result.get('total', 0)}张，删除{result.get('removed', 0)}张，剩余{pc_left_in_editor}张")
                        trimmed = True
                        frame_done = True
                        break
                except Exception:
                    continue
            if frame_done:
                pass
        except Exception:
            pass

        # 方案B：主文档中按你给的特征图片处理（img[cke-id] / img[data-cke-saved-src]）
        if not trimmed:
            try:
                result = await self.page.evaluate(
                    """(trimConfig) => {
                        const mode = String(trimConfig?.mode || "keep").toLowerCase();
                        const count = Math.max(0, Number(trimConfig?.count || 5) || 0);
                        const pickRemoveList = (items) => {
                            if (mode === "none" || count <= 0) return [];
                            if (mode === "delete") return items.slice(Math.max(0, items.length - count));
                            return items.slice(count);
                        };
                        const roots = [
                            document.querySelector("[contenteditable='true']"),
                            document.querySelector(".cke_wysiwyg_div"),
                            document.querySelector(".cke_editable"),
                            document.body
                        ].filter(Boolean);

                        for (const root of roots) {
                            let imgs = Array.from(root.querySelectorAll("img[cke-id], img[data-cke-saved-src]"));
                            if (imgs.length === 0) {
                                imgs = Array.from(root.querySelectorAll("img[src*='alicdn.com'], img[src^='http']"));
                            }
                            if (imgs.length === 0) continue;

                            const removeList = pickRemoveList(imgs);
                            removeList.forEach(img => {
                                // 只删图片，避免删掉父容器导致前面的图片也丢失
                                img.remove();
                            });

                            const left = Array.from(root.querySelectorAll("img[cke-id], img[data-cke-saved-src], img[src*='alicdn.com'], img[src^='http']")).length;
                            root.dispatchEvent(new Event("input", { bubbles: true }));
                            root.dispatchEvent(new Event("change", { bubbles: true }));
                            return { ok: true, total: imgs.length, removed: removeList.length, left };
                        }

                        return { ok: false, reason: "no_pc_desc_images" };
                    }""",
                    trim_config,
                )
                if result and result.get("ok"):
                    pc_left_in_editor = result.get("left")
                    logger.success(f"PC端描述处理成功：共{result.get('total', 0)}张，删除{result.get('removed', 0)}张，剩余{pc_left_in_editor}张")
                    trimmed = True
            except Exception:
                pass

        if not trimmed:
            logger.warning("PC端描述未定位到图片容器（未执行详情图删减）")

        # 强校验：保留模式下如果仍超过目标数量，跳过无线端一键生成，避免错误操作
        pc_left = 0
        if isinstance(pc_left_in_editor, int):
            pc_left = pc_left_in_editor
        else:
            try:
                pc_left = await self.page.evaluate(
                    """() => {
                        // 只统计富文本编辑区内图片，避免把页面其他图片算进去
                        const roots = [
                            document.querySelector(".cke_wysiwyg_div"),
                            document.querySelector(".cke_editable"),
                            document.querySelector("[contenteditable='true']")
                        ].filter(Boolean);

                        for (const root of roots) {
                            const imgs = Array.from(root.querySelectorAll("img[cke-id], img[data-cke-saved-src], img[src*='alicdn.com'], img[src^='http']"));
                            if (imgs.length > 0) return imgs.length;
                        }
                        return 0;
                    }"""
                )
            except Exception:
                pc_left = 0

        logger.info(f"PC端描述当前图片数量: {pc_left}")
        await self.capture_state("06_pc_desc")

        if desc_image_mode == "keep" and desc_image_count > 0 and pc_left > desc_image_count:
            logger.warning(f"PC端描述图片仍超过目标数量（目标{desc_image_count}，当前{pc_left}），跳过无线端一键生成，避免错误操作")
            return

        # ===== 5.2 无线端描述：使用老版编辑器 -> 确定 -> 一键生成 =====
        old_editor_clicked = await self.smart_click_by_text(["使用老版编辑器"], "无线端-使用老版编辑器")
        if not old_editor_clicked:
            old_editor_clicked = await self.smart_click_by_text(["老版编辑器"], "无线端-老版编辑器选项")

        await asyncio.sleep(0.6)

        # 弹窗确认
        await self.smart_click_by_text(["确 定", "确定"], "无线端-确认弹窗")
        await asyncio.sleep(0.6)

        # 关键修复：基于“无线端描述不支持GIF格式图片”所在区块，精确点击旁边的一键生成
        generated = False
        try:
            mobile_hint = self.page.locator("div.cont:has-text('无线端描述不支持GIF格式图片')").first
            if await mobile_hint.count() > 0:
                parent = mobile_hint.locator("xpath=..")
                target_btn = parent.locator("span.link.ml-20:has-text('一键生成')").first
                if await target_btn.count() > 0:
                    await target_btn.scroll_into_view_if_needed()
                    await target_btn.click(timeout=3000)
                    logger.success("点击成功: 无线端-一键生成（精准定位）")
                    generated = True
        except Exception:
            generated = False

        if not generated:
            # 兜底：在“无线端描述”区域附近找，避免误点营销图一键生成
            try:
                region = self.page.locator("text=无线端描述").first.locator("xpath=ancestor::div[1]/following-sibling::div[1]")
                near_btn = region.locator("span.link.ml-20:has-text('一键生成'), span:has-text('一键生成')").first
                if await near_btn.count() > 0:
                    await near_btn.scroll_into_view_if_needed()
                    await near_btn.click(timeout=3000)
                    logger.success("点击成功: 无线端-一键生成（区域定位）")
                    generated = True
            except Exception:
                generated = False

        if not generated:
            logger.warning("未找到可点击元素: 无线端-一键生成")

        # 无线端图片也按配置删减（按你提供的 cke-id / data-cke-saved-src 特征）
        await asyncio.sleep(0.8)
        mobile_trimmed = False

        # 先尝试在主文档中：严格限定到“无线端描述不支持GIF格式图片”所在容器，避免误删其他区域
        try:
            result = await self.page.evaluate(
                """(trimConfig) => {
                    const mode = String(trimConfig?.mode || "keep").toLowerCase();
                    const count = Math.max(0, Number(trimConfig?.count || 5) || 0);
                    const pickRemoveList = (items) => {
                        if (mode === "none" || count <= 0) return [];
                        if (mode === "delete") return items.slice(Math.max(0, items.length - count));
                        return items.slice(count);
                    };
                    const hint = Array.from(document.querySelectorAll("div.cont"))
                        .find(el => (el.textContent || "").includes("无线端描述不支持GIF格式图片"));
                    if (!hint) return { ok: false, reason: "no_mobile_hint" };

                    // 从 hint 往上找候选容器（最多向上6层），只在该局部容器里删图
                    const scopes = [];
                    let cur = hint.parentElement;
                    for (let i = 0; cur && i < 6; i++) {
                        scopes.push(cur);
                        cur = cur.parentElement;
                    }

                    let targetScope = null;
                    for (const s of scopes) {
                        const imgs = Array.from(s.querySelectorAll("img[cke-id], img[data-cke-saved-src]"));
                        const hasRichText = !!s.querySelector(".rich-text-component");
                        if (imgs.length > 0 && hasRichText) {
                            targetScope = s;
                            break;
                        }
                    }

                    if (!targetScope) return { ok: false, reason: "no_precise_scope" };

                    const imgs = Array.from(targetScope.querySelectorAll("img[cke-id], img[data-cke-saved-src]"));
                    if (imgs.length === 0) return { ok: false, reason: "no_mobile_imgs" };

                    const removeList = pickRemoveList(imgs);
                    removeList.forEach(img => img.remove());

                    const left = Array.from(targetScope.querySelectorAll("img[cke-id], img[data-cke-saved-src]")).length;
                    targetScope.dispatchEvent(new Event("input", { bubbles: true }));
                    targetScope.dispatchEvent(new Event("change", { bubbles: true }));
                    return { ok: true, total: imgs.length, removed: removeList.length, left };
                }""",
                trim_config,
            )
            if result and result.get("ok"):
                logger.success(f"无线端描述图片处理成功：共{result.get('total', 0)}张，删除{result.get('removed', 0)}张，剩余{result.get('left', 0)}张")
                mobile_trimmed = True
            else:
                logger.warning(f"无线端主文档精准裁剪未命中: {result}")
        except Exception:
            pass

        # 兜底：遍历 iframe（某些页面无线端编辑器在 frame 里）
        if not mobile_trimmed:
            for frame in self.page.frames:
                if frame == self.page.main_frame:
                    continue
                try:
                    result = await frame.evaluate(
                        """(trimConfig) => {
                            const body = document.body;
                            if (!body) return { ok: false };
                            const mode = String(trimConfig?.mode || "keep").toLowerCase();
                            const count = Math.max(0, Number(trimConfig?.count || 5) || 0);
                            const pickRemoveList = (items) => {
                                if (mode === "none" || count <= 0) return [];
                                if (mode === "delete") return items.slice(Math.max(0, items.length - count));
                                return items.slice(count);
                            };

                            const imgs = Array.from(body.querySelectorAll("img[cke-id], img[data-cke-saved-src], img[src*='alicdn.com']"));
                            if (imgs.length === 0) return { ok: false };

                            const removeList = pickRemoveList(imgs);
                            removeList.forEach(img => img.remove());

                            const left = Array.from(body.querySelectorAll("img[cke-id], img[data-cke-saved-src], img[src*='alicdn.com']")).length;
                            body.dispatchEvent(new Event("input", { bubbles: true }));
                            body.dispatchEvent(new Event("change", { bubbles: true }));
                            return { ok: true, total: imgs.length, removed: removeList.length, left };
                        }""",
                        trim_config,
                    )
                    if result and result.get("ok"):
                        logger.success(f"无线端描述图片处理成功：共{result.get('total', 0)}张，删除{result.get('removed', 0)}张，剩余{result.get('left', 0)}张")
                        mobile_trimmed = True
                        break
                except Exception:
                    continue

        if not mobile_trimmed:
            logger.warning("无线端描述未定位到图片容器（未执行详情图删减）")

        await asyncio.sleep(1.2)
        await self.capture_state("07_mobile_desc")

    async def step_packaging_info(self):
        """
        直接填写包装信息（精准定位 #packageInfo）：
        - 包装后重量：0.14
        - 包装后尺寸：26 * 16 * 6
        """
        logger.info("步骤5.5: 处理包装信息（直接填重量和尺寸）")

        if not self.page:
            return

        package_card = self.page.locator("#packageInfo").first
        if await package_card.count() == 0:
            logger.warning("未找到 #packageInfo，跳过包装信息填写")
            return

        async def set_controlled_input(locator, value: str, desc: str) -> bool:
            try:
                if await locator.count() == 0:
                    logger.warning(f"未找到输入框: {desc}")
                    return False

                target = locator.first
                await target.scroll_into_view_if_needed()
                await target.evaluate(
                    """(el, val) => {
                        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        setter.call(el, val);
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                        el.dispatchEvent(new Event('blur', { bubbles: true }));
                    }""",
                    value,
                )
                logger.success(f"填写成功: {desc} = {value}")
                return True
            except Exception:
                logger.warning(f"填写失败: {desc}")
                return False

        # 读取 GUI/运行时参数，避免固定默认值
        weight_value = str(CONFIG.get("weight", 0.14))
        size_text = str(CONFIG.get("size", "26*16*6"))
        dims = [p.strip() for p in size_text.replace("×", "*").split("*")]
        while len(dims) < 3:
            dims.append("0")
        dims = dims[:3]

        weight_ok = True
        if not is_skip("weight"):
            weight_ok = await set_controlled_input(
                package_card.locator("input#form_item_grossWeight"),
                weight_value,
                "包装后重量",
            )

        # 2) 尺寸（三个输入框）
        size_row = package_card.locator("label[for='form_item_packageSize']").locator(
            "xpath=ancestor::div[contains(@class,'ant-form-item')][1]"
        )
        size_inputs = size_row.locator("input.ant-input")

        # 兜底：若上面未命中，直接在 #packageInfo 内找前三个非重量输入
        if await size_inputs.count() < 3:
            size_inputs = package_card.locator("input.ant-input:not(#form_item_grossWeight)")
        size_ok_count = 0
        if not is_skip("size"):
            for idx in range(3):
                try:
                    ok = await set_controlled_input(
                        size_inputs.nth(idx),
                        dims[idx],
                        f"包装后尺寸[{idx+1}]",
                    )
                    if ok:
                        size_ok_count += 1
                except Exception:
                    continue

        if not weight_ok:
            logger.warning("包装后重量未成功填写")
        if size_ok_count < 3:
            logger.warning(f"包装后尺寸填写不完整，成功 {size_ok_count}/3")

        await asyncio.sleep(0.8)
        await self.capture_state("05_5_packaging_info")

    async def step_translate(self, apply_ai_text: bool = True):
        logger.info("步骤7: 一键翻译")

        async def title_has_chinese() -> bool:
            try:
                title_inputs = self.page.locator("input.ant-input.ant-input-sm")
                total = await title_inputs.count()
                for i in range(total):
                    val = (await title_inputs.nth(i).input_value()).strip()
                    if any("\u4e00" <= ch <= "\u9fff" for ch in val):
                        return True
                return False
            except Exception:
                return True

        async def click_visible_text_in_overlay(texts: list[str], description: str, require_all: bool = False) -> bool:
            try:
                result = await self.page.evaluate(
                    """({ texts, requireAll }) => {
                        const visible = (el) => {
                            if (!el || !el.getBoundingClientRect) return false;
                            const st = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return st.display !== "none"
                                && st.visibility !== "hidden"
                                && r.width > 0
                                && r.height > 0;
                        };
                        const norm = (s) => (s || "")
                            .replace(/\\s+/g, "")
                            .replace(/->/g, "→")
                            .replace(/-/g, "→")
                            .trim();
                        const roots = Array.from(document.querySelectorAll(
                            ".ant-popover, .ant-dropdown, .ant-tooltip, .translate-popover, .dropdown-menu, .dropdown-con, .popover, [class*='popover'], [class*='dropdown']"
                        )).filter(visible);
                        if (!roots.length) roots.push(document.body);
                        const normalizedTexts = texts.map(norm).filter(Boolean);
                        const candidates = [];
                        for (const root of roots) {
                            const nodes = Array.from(root.querySelectorAll("button,a,li,span,div,p"))
                                .filter(visible)
                                .map((el) => {
                                    const raw = (el.innerText || el.textContent || "").trim();
                                    return { el, raw, n: norm(raw) };
                                })
                                .filter((item) => item.raw);
                            for (const item of nodes) {
                                const matched = requireAll
                                    ? normalizedTexts.every((t) => item.n.includes(t))
                                    : normalizedTexts.some((t) => item.n === t || item.n.includes(t));
                                if (!matched) continue;
                                const r = item.el.getBoundingClientRect();
                                const score =
                                    (item.n === normalizedTexts[0] ? 100 : 0)
                                    + (r.width > 80 ? 10 : 0)
                                    + (r.height > 24 ? 10 : 0)
                                    - Math.abs(item.raw.length - texts.join("").length);
                                candidates.push({ el: item.el, text: item.raw, score });
                            }
                        }
                        candidates.sort((a, b) => b.score - a.score);
                        const found = candidates[0];
                        if (!found) return { ok: false, text: "" };
                        const target = found.el.closest("button,a,li") || found.el;
                        target.scrollIntoView({ block: "center", inline: "nearest" });
                        target.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, view: window }));
                        target.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, view: window }));
                        target.click();
                        return { ok: true, text: found.text };
                    }""",
                    {"texts": texts, "requireAll": require_all},
                )
                if result and result.get("ok"):
                    logger.success(f"点击成功: {description} = {result.get('text')}")
                    await asyncio.sleep(0.5)
                    return True
            except Exception as exc:
                logger.warning(f"{description}点击失败: {exc}")
            return False

        async def open_translate_panel() -> bool:
            open_targets = [
                self.page.locator("button:has-text('一键翻译')").first,
                self.page.locator("a:has-text('一键翻译')").first,
                self.page.get_by_text("一键翻译", exact=False).first,
            ]
            for target in open_targets:
                try:
                    if await target.count() > 0:
                        await target.scroll_into_view_if_needed()
                        await target.click(timeout=3000, force=True)
                        logger.success("点击成功: 一键翻译按钮")
                        await asyncio.sleep(0.7)
                        return True
                except Exception:
                    continue
            opened = await self.smart_click_by_text(["一键翻译"], "一键翻译按钮")
            if opened:
                await asyncio.sleep(0.7)
            return opened

        async def click_translate_language_option() -> bool:
            try:
                result = await self.page.evaluate(
                    """() => {
                        const visible = (el) => {
                            if (!el || !el.getBoundingClientRect) return false;
                            const st = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return st.display !== "none" && st.visibility !== "hidden" && r.width > 0 && r.height > 0;
                        };
                        const clickNode = (node) => {
                            const rect = node.getBoundingClientRect();
                            const init = {
                                bubbles: true,
                                cancelable: true,
                                view: window,
                                clientX: rect.left + rect.width / 2,
                                clientY: rect.top + rect.height / 2,
                            };
                            ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach((type) => {
                                node.dispatchEvent(new MouseEvent(type, init));
                            });
                        };
                        const norm = (s) => (s || "")
                            .replace(/\\s+/g, "")
                            .replace(/->/g, "→")
                            .replace(/-/g, "→")
                            .trim();
                        const roots = Array.from(document.querySelectorAll(
                            ".ant-popover, .ant-dropdown, .translate-popover, .dropdown-menu, .dropdown-con, .popover, [class*='popover'], [class*='dropdown']"
                        )).filter(visible);
                        if (!roots.length) roots.push(document.body);
                        const candidates = [];
                        for (const root of roots) {
                            const nodes = Array.from(root.querySelectorAll("button,a,li,div,span,p"))
                                .filter(visible);
                            for (const node of nodes) {
                                const raw = (node.innerText || node.textContent || "").trim();
                                const n = norm(raw);
                                if (!raw) continue;
                                const hasZhEn = n.includes("中文") && n.includes("英文");
                                const hasArrow = n.includes("→") || n.includes("至") || n.includes("到");
                                const isBigChoice = node.getBoundingClientRect().width > 80 && node.getBoundingClientRect().height > 24;
                                if (!hasZhEn) continue;
                                let score = 50;
                                if (hasArrow) score += 30;
                                if (isBigChoice) score += 15;
                                if (n === "中文→英文" || n === "中文英文") score += 25;
                                candidates.push({ node, raw, score });
                            }
                        }
                        candidates.sort((a, b) => b.score - a.score);
                        const found = candidates[0];
                        if (!found) return { ok: false, text: "" };
                        const target = found.node.closest("button,a,li") || found.node;
                        target.scrollIntoView({ block: "center", inline: "nearest" });
                        clickNode(target);
                        return { ok: true, text: found.raw };
                    }"""
                )
                if result and result.get("ok"):
                    logger.success(f"点击成功: 翻译语言-中文→英文 = {result.get('text')}")
                    await asyncio.sleep(1.2)
                    return True
            except Exception as exc:
                logger.warning(f"翻译语言-中文→英文点击失败: {exc}")
            return False

        # 新版店小秘是蓝色“一键翻译”按钮 + 弹出面板。
        opened = await open_translate_panel()
        if opened:
            picked = False

            for attempt in range(3):
                if attempt > 0:
                    await open_translate_panel()

                if attempt == 0:
                    await click_visible_text_in_overlay(["普通翻译"], "翻译方式-普通翻译")
                    await asyncio.sleep(0.5)

                if await click_translate_language_option():
                    logger.success("选择成功: 普通翻译 -> 中文 → 英文")
                    picked = True
                    break

                new_panel_item = await click_visible_text_in_overlay(["中文", "英文"], "翻译语言-中文→英文", require_all=True)
                if new_panel_item:
                    logger.success("选择成功: 普通翻译 -> 中文 → 英文")
                    picked = True
                    break

                # 旧版菜单兼容：普通翻译 -> 中文 → 英文
                group_normal = self.page.locator("li.group-label").filter(has_text="普通翻译")
                if await group_normal.count() > 0:
                    menu_item = group_normal.first.locator("xpath=following-sibling::li[1]").locator("span").filter(has_text="中文").first
                    if await menu_item.count() > 0:
                        await menu_item.scroll_into_view_if_needed()
                        await menu_item.click(timeout=3000)
                        logger.success("选择成功: 普通翻译 -> 中文 → 英文")
                        picked = True
                        break

                # 兜底：直接找菜单里的“中文 → 英文”
                fallback_item = self.page.locator("ul.dropdown-con li.menu-item span").filter(has_text="中文").first
                if await fallback_item.count() > 0:
                    await fallback_item.scroll_into_view_if_needed()
                    await fallback_item.click(timeout=3000)
                    logger.success("选择成功: 翻译语言 = 中文 → 英文")
                    picked = True
                    break

                await asyncio.sleep(0.5)

            if not picked:
                logger.warning("未找到翻译选项: 普通翻译 -> 中文 → 英文")

        await asyncio.sleep(1.2)
        await self.wait_translation_done(timeout_sec=35 if apply_ai_text else 12)
        if not apply_ai_text and await title_has_chinese():
            logger.warning("采集海关前店小秘翻译未落地，跳过本次海关选项采集，避免采集翻译前字段")
            return False
        if apply_ai_text:
            await self.step_ai_text_optimization()
        else:
            logger.info("店小秘一键翻译完成；当前流程跳过AI标题/SKU写回")
        await self.capture_state("05_translate")
        return True

    async def wait_translation_done(self, timeout_sec: int = 25):
        """
        等待标题翻译完成：
        - 轮询标题输入框中的中文字符数量
        - 连续两次检测都“无中文”才继续发布
        """
        if not self.page:
            return

        logger.info("翻译后等待：检查标题是否仍含中文...")
        stable_rounds = 0
        started = asyncio.get_event_loop().time()

        while True:
            has_chinese = False
            try:
                title_inputs = self.page.locator("input.ant-input.ant-input-sm")
                total = await title_inputs.count()

                for i in range(total):
                    val = (await title_inputs.nth(i).input_value()).strip()
                    if any("\u4e00" <= ch <= "\u9fff" for ch in val):
                        has_chinese = True
                        break
            except Exception:
                # 读取失败时继续等一轮
                has_chinese = True

            if not has_chinese:
                stable_rounds += 1
            else:
                stable_rounds = 0

            # 连续两轮无中文，认为翻译落地完成
            if stable_rounds >= 2:
                logger.success("翻译检查通过：标题已无中文，继续发布")
                return

            if asyncio.get_event_loop().time() - started > timeout_sec:
                logger.warning("翻译等待超时，继续后续发布（可能仍有少量中文）")
                return

            await asyncio.sleep(1.2)

    async def step_marketing_and_delete_video(self):
        video_action = str(CONFIG.get("product_video_action", "删除") or "删除").strip()
        keep_video = "保留" in video_action or video_action.lower() in {"keep", "skip", "none"}
        logger.info(f"步骤3: 营销图片一键生成 + 产品视频处理({video_action})")

        # 1) 营销图一键生成（按你给的 DOM：div.generate-market-img 内的 span: 一键生成）
        generate_locators = [
            self.page.locator("div.generate-market-img button:has-text('一键生成')").first,
            self.page.locator("div.generate-market-img span:has-text('一键生成')").first,
            self.page.locator("span:has-text('一键生成')").first,
        ]

        generated = False
        for loc in generate_locators:
            try:
                if await loc.count() > 0:
                    await loc.scroll_into_view_if_needed()
                    await loc.click(timeout=3000)
                    logger.success("点击成功: 营销图片一键生成")
                    generated = True
                    break
            except Exception:
                continue

        if not generated:
            logger.warning("未找到可点击元素: 营销图片一键生成")

        await asyncio.sleep(1.0)
        await self.capture_state("03_marketing_images")

        if keep_video:
            logger.info("产品视频处理设置为保留，跳过删除视频步骤")
            return

        # 2) 删除采集视频
        # 有些商品根本没有视频，这里不要因为页面上其它隐藏“删除”元素而卡住
        delete_video_locators = [
            self.page.locator("a.link:has-text('删除')"),
            self.page.locator("a:has-text('删除')"),
        ]

        deleted = False
        for loc in delete_video_locators:
            try:
                count = await loc.count()
                if count == 0:
                    continue

                for i in range(count):
                    item = loc.nth(i)
                    try:
                        if not await item.is_visible():
                            continue
                        await item.click(timeout=1200, force=True)
                        logger.success("点击成功: 删除视频")
                        deleted = True
                        break
                    except Exception:
                        continue

                if deleted:
                    break
            except Exception:
                continue

        if not deleted:
            logger.info("当前商品没有可删除的视频，跳过删除视频步骤")

        await asyncio.sleep(0.4)
        await self.capture_state("04_delete_video")

    async def click_publish_button_precise(self, description: str = "发布") -> bool:
        if not self.page:
            return False
        try:
            try:
                await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(0.4)
            except Exception:
                pass

            result = None
            try:
                green_publish = self.page.locator("button.btn-green, .ant-btn.btn-green").last
                if await green_publish.count() > 0:
                    await green_publish.scroll_into_view_if_needed(timeout=3000)
                    await asyncio.sleep(0.2)
                    box = await green_publish.bounding_box(timeout=3000)
                    btn_text = ""
                    try:
                        btn_text = (await green_publish.inner_text(timeout=1000)).strip()
                    except Exception:
                        btn_text = "发布"
                    if box:
                        result = {
                            "ok": True,
                            "text": btn_text or "发布",
                            "x": round(box["x"] + box["width"] / 2),
                            "y": round(box["y"] + box["height"] / 2),
                            "cls": "btn-green",
                            "bg": "",
                            "source": "css-btn-green",
                        }
            except Exception as css_exc:
                logger.warning(f"按绿色发布按钮定位失败，改用DOM兜底: {css_exc}")

            if not result:
                result = await self.page.evaluate(
                """() => {
                    const visible = (el) => {
                        if (!el || !el.getBoundingClientRect) return false;
                        const r = el.getBoundingClientRect();
                        const st = getComputedStyle(el);
                        return st.display !== 'none'
                            && st.visibility !== 'hidden'
                            && r.width > 0
                            && r.height > 0;
                    };
                    const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
                    const buttons = Array.from(document.querySelectorAll('button, a, .ant-btn'))
                        .filter(visible)
                        .map((el) => {
                            const r = el.getBoundingClientRect();
                            const st = getComputedStyle(el);
                            const text = norm(el.innerText || el.textContent || el.getAttribute('title') || '');
                            return { el, text, y: r.y, x: r.x, w: r.width, h: r.height, bg: st.backgroundColor, cls: String(el.className || '') };
                        })
                        .filter((item) =>
                            item.text === '发布'
                            || item.text === '立即发布'
                            || item.text.includes('提交发布')
                            || (item.text.includes('发布') && /btn-green/.test(item.cls))
                        );
                    if (!buttons.length) return { ok: false, reason: 'no_publish_button' };
                    const score = (item) => {
                        let s = 0;
                        if (item.text === '发布') s += 200;
                        if (item.text === '立即发布') s += 180;
                        if (/btn-green/i.test(item.cls)) s += 160;
                        if (/primary/i.test(item.cls)) s += 30;
                        if (/0, 153, 102/.test(item.bg)) s += 80;
                        if (item.text.includes('发布商品')) s -= 80;
                        s += Math.max(0, item.x);
                        s += Math.max(0, item.y) / 20;
                        return s;
                    };
                    buttons.sort((a, b) => score(b) - score(a));
                    const target = buttons[0];
                    target.el.scrollIntoView({ block: 'center', inline: 'nearest' });
                    const rect = target.el.getBoundingClientRect();
                    return {
                        ok: true,
                        text: target.text,
                        x: Math.round(rect.left + rect.width / 2),
                        y: Math.round(rect.top + rect.height / 2),
                        cls: target.cls,
                        bg: target.bg
                    };
                }"""
                )
            if result and result.get("ok"):
                await self.page.mouse.click(float(result.get("x", 0)), float(result.get("y", 0)))
                logger.success(f"点击成功: {description} - {result}")
                await asyncio.sleep(0.8)
                if str(result.get("text") or "").strip() == "发布":
                    clicked_menu = False
                    for _ in range(10):
                        menu_target = await self.page.evaluate(
                            """() => {
                                const visible = (el) => {
                                    if (!el || !el.getBoundingClientRect) return false;
                                    const r = el.getBoundingClientRect();
                                    const st = getComputedStyle(el);
                                    return st.display !== 'none'
                                        && st.visibility !== 'hidden'
                                        && r.width > 0
                                        && r.height > 0
                                        && r.bottom >= 0
                                        && r.top <= window.innerHeight
                                        && r.right >= 0
                                        && r.left <= window.innerWidth;
                                };
                                const items = Array.from(document.querySelectorAll(
                                    '.ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item, '
                                    + '.ant-dropdown:not(.ant-dropdown-hidden) [role="menuitem"], '
                                    + '.ant-dropdown-menu-item, [role="menuitem"]'
                                ))
                                    .filter(visible)
                                    .map((el) => {
                                        const r = el.getBoundingClientRect();
                                        const text = (
                                            el.getAttribute('title')
                                            || el.innerText
                                            || el.textContent
                                            || ''
                                        ).replace(/\\s+/g, ' ').trim();
                                        return {
                                            text,
                                            x: r.left + r.width / 2,
                                            y: r.top + r.height / 2,
                                            cls: String(el.className || '')
                                        };
                                    });
                                const found = items.find((item) => item.text === '立即发布')
                                    || items.find((item) => item.text.includes('立即发布'));
                                return found || null;
                            }"""
                        )
                        if menu_target:
                            await self.page.mouse.click(float(menu_target["x"]), float(menu_target["y"]))
                            logger.success(f"点击成功: 发布下拉菜单 - 立即发布 {menu_target}")
                            clicked_menu = True
                            break
                        await asyncio.sleep(0.25)

                    if not clicked_menu:
                        menu_locators = [
                            self.page.locator(".ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item[title='立即发布']").last,
                            self.page.locator(".ant-dropdown:not(.ant-dropdown-hidden) .ant-dropdown-menu-item").filter(has_text="立即发布").last,
                            self.page.locator(".ant-dropdown:not(.ant-dropdown-hidden) li").filter(has_text="立即发布").last,
                            self.page.get_by_text("立即发布", exact=True).last,
                        ]
                        for loc in menu_locators:
                            try:
                                if await loc.count() > 0 and await loc.is_visible():
                                    box = await loc.bounding_box()
                                    if box:
                                        await self.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                    else:
                                        await loc.click(timeout=3000, force=True)
                                    logger.success("点击成功: 发布下拉菜单 - 立即发布")
                                    clicked_menu = True
                                    break
                            except Exception:
                                continue

                    if not clicked_menu:
                        try:
                            visible_menus = await self.page.evaluate(
                                """() => Array.from(document.querySelectorAll('.ant-dropdown, .ant-dropdown-menu, [role="menu"]'))
                                    .map((el) => {
                                        const r = el.getBoundingClientRect();
                                        const st = getComputedStyle(el);
                                        return {
                                            visible: st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0,
                                            text: (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim(),
                                            cls: String(el.className || ''),
                                            x: Math.round(r.x),
                                            y: Math.round(r.y),
                                            w: Math.round(r.width),
                                            h: Math.round(r.height)
                                        };
                                    })
                                    .filter((item) => item.visible || item.text.includes('发布'))
                                    .slice(-8)"""
                            )
                            logger.warning(f"已打开发布下拉，但未找到“立即发布”菜单项，当前可见菜单: {visible_menus}")
                        except Exception:
                            logger.warning("已打开发布下拉，但未找到“立即发布”菜单项")
                        return False
                await asyncio.sleep(0.8)
                return True
            logger.warning(f"未找到精准发布按钮: {result}")
        except Exception as exc:
            logger.warning(f"精准点击发布按钮失败: {exc}")
        return False

    async def click_save_to_pending_button_precise(self, description: str = "保存并移入待发布") -> bool:
        if not self.page:
            return False
        try:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(0.4)

            target = self.page.locator("button:has-text('保存并移入待发布'), .ant-btn:has-text('保存并移入待发布')").last
            if await target.count() > 0:
                await target.scroll_into_view_if_needed(timeout=3000)
                box = await target.bounding_box(timeout=3000)
                if box:
                    await self.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                else:
                    await target.click(timeout=3000, force=True)
                logger.success(f"点击成功: {description}")
                await asyncio.sleep(0.8)
                return True

            result = await self.page.evaluate(
                """() => {
                    const visible = (el) => {
                        if (!el || !el.getBoundingClientRect) return false;
                        const r = el.getBoundingClientRect();
                        const st = getComputedStyle(el);
                        return st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const buttons = Array.from(document.querySelectorAll('button, a, .ant-btn'))
                        .filter(visible)
                        .map((el) => {
                            const r = el.getBoundingClientRect();
                            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                            return { el, text, x: r.left + r.width / 2, y: r.top + r.height / 2, cls: String(el.className || '') };
                        })
                        .filter((item) => item.text.includes('保存并移入待发布'));
                    buttons.sort((a, b) => b.x - a.x);
                    const target = buttons[0];
                    if (!target) return null;
                    return { text: target.text, x: target.x, y: target.y, cls: target.cls };
                }"""
            )
            if result:
                await self.page.mouse.click(float(result["x"]), float(result["y"]))
                logger.success(f"点击成功: {description} - {result}")
                await asyncio.sleep(0.8)
                return True
        except Exception as exc:
            logger.warning(f"点击保存并移入待发布失败: {exc}")
        return False

    async def confirm_publish_dialog_if_present(self) -> None:
        if not self.page:
            return
        confirm_selectors = [
            ".ant-modal button:has-text('确定')",
            ".ant-modal button:has-text('确 定')",
            ".ant-modal button:has-text('确认')",
            ".ant-modal button:has-text('发布')",
            ".ant-popconfirm button:has-text('确定')",
            ".ant-popconfirm button:has-text('确 定')",
        ]
        for selector in confirm_selectors:
            try:
                loc = self.page.locator(selector).last
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click(timeout=2000, force=True)
                    logger.success(f"已确认发布弹窗: {selector}")
                    await asyncio.sleep(1.0)
                    return
            except Exception:
                continue

    async def close_publish_success_dialog_if_present(self) -> bool:
        if not self.page or self.page.is_closed():
            return False
        try:
            modal = self.page.locator(".ant-modal-content").filter(has_text="产品已提交发布").last
            if await modal.count() == 0 or not await modal.is_visible():
                modal = self.page.locator(".ant-modal-content").filter(has_text="消息提示").last
            if await modal.count() == 0 or not await modal.is_visible():
                return False

            close_targets = [
                modal.locator("button:has-text('关闭')").first,
                modal.locator(".ant-modal-close").first,
                self.page.locator(".ant-modal-content:has-text('产品已提交发布') button:has-text('关闭')").last,
                self.page.locator(".ant-modal-content:has-text('消息提示') button:has-text('关闭')").last,
            ]
            for target in close_targets:
                try:
                    if await target.count() == 0:
                        continue
                    if not await target.is_visible():
                        continue
                    await target.click(timeout=2000, force=True)
                    logger.success("已关闭发布成功提示弹窗")
                    await asyncio.sleep(0.8)
                    return True
                except Exception:
                    continue
        except Exception as exc:
            logger.warning(f"关闭发布成功弹窗失败: {exc}")
        return False

    async def detect_publish_success(self) -> tuple[bool, str]:
        if not self.page or self.page.is_closed():
            return True, "编辑页已关闭"
        validation_errors = await self.collect_visible_validation_errors()
        if validation_errors:
            return False, "页面仍有校验错误: " + " | ".join(validation_errors[:5])
        try:
            current_url = self.page.url or ""
            if "smt/edit" not in current_url.lower() and "edit" not in current_url.lower():
                return True, f"页面已离开编辑页: {current_url}"
        except Exception:
            return True, "编辑页状态不可读，可能已关闭"

        try:
            result = await self.page.evaluate(
                """() => {
                    const visible = (el) => {
                        if (!el || !el.getBoundingClientRect) return false;
                        const r = el.getBoundingClientRect();
                        const st = getComputedStyle(el);
                        return st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const successRoots = Array.from(document.querySelectorAll(
                        '.ant-modal, .ant-message, .ant-notification, .ant-result, .dxm-message, [class*=message], [class*=notification]'
                    )).filter(visible);
                    const texts = successRoots
                        .map((el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim())
                        .filter(Boolean);
                    const successText = texts.find((text) =>
                        text.includes('产品已提交发布')
                        || text.includes('保存并移入待发布')
                        || text.includes('移入待发布')
                        || (
                            (text.includes('操作成功') || text.includes('发布成功') || text.includes('保存成功'))
                            && (text.includes('待发布') || text.includes('成功'))
                        )
                    );
                    return {
                        success: !!successText,
                        successText: successText || '',
                        texts: texts.slice(0, 12),
                        bodySuccess: (
                            (document.body.innerText || '').includes('操作成功，请到')
                            || (document.body.innerText || '').includes('发布成功')
                            || (document.body.innerText || '').includes('产品已提交发布')
                            || (document.body.innerText || '').includes('移入待发布')
                        )
                    };
                }"""
            )
            if result and (result.get("success") or result.get("bodySuccess")):
                return True, result.get("successText") or "页面检测到发布成功文案"
            visible_texts = result.get("texts") if isinstance(result, dict) else []
            if visible_texts:
                logger.info(f"发布后可见消息快照: {visible_texts}")
        except Exception as exc:
            logger.warning(f"检测发布成功状态失败: {exc}")
        return False, "未检测到成功提示"

    async def wait_publish_success(self, timeout_sec: int = 10) -> tuple[bool, str]:
        started = time.monotonic()
        reason = ""
        while time.monotonic() - started <= timeout_sec:
            await self.confirm_publish_dialog_if_present()
            ok, reason = await self.detect_publish_success()
            if ok:
                return ok, reason
            await asyncio.sleep(0.8)
        return False, reason or "等待发布成功超时"

    async def collect_visible_validation_errors(self) -> list[str]:
        if not self.page or self.page.is_closed():
            return []
        try:
            return await self.page.evaluate(
                """() => {
                    const visible = (el) => {
                        if (!el || !el.getBoundingClientRect) return false;
                        const r = el.getBoundingClientRect();
                        const st = getComputedStyle(el);
                        return st.display !== 'none' && st.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                    };
                    const selectors = ['.ant-form-item-explain-error', '.ant-form-item-has-error', '.f-red', '.color-red', '[class*=error]'];
                    const skip = [
                        'Chrome',
                        'Firefox',
                        '产品信息',
                        '非海外仓用户请勿勾选',
                        '2017年1月3日开始',
                        'NONE(无品牌)',
                        '商品所对应的品牌',
                        '「产品分类」「标题」「商品属性」「物流属性」'
                    ];
                    const out = [];
                    const seen = new Set();
                    for (const sel of selectors) {
                        for (const el of document.querySelectorAll(sel)) {
                            if (!visible(el)) continue;
                            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                            if (!text || text.length > 300 || skip.some((s) => text.includes(s))) continue;
                            if (/^\\d+$/.test(text)) continue;
                            if (!seen.has(text)) {
                                seen.add(text);
                                out.push(text);
                            }
                        }
                    }
                    return out.slice(0, 20);
                }"""
            )
        except Exception as exc:
            logger.warning(f"读取发布校验错误失败: {exc}")
            return []

    async def fix_title_and_sku_validation_errors(self, stage: str = "发布校验") -> bool:
        if not self.page or self.page.is_closed():
            return False
        try:
            result = await self.page.evaluate(
                """(stage) => {
                    const visible = (el) => {
                        if (!el || !el.getBoundingClientRect) return false;
                        const r = el.getBoundingClientRect();
                        const st = getComputedStyle(el);
                        return st.display !== "none" && st.visibility !== "hidden" && r.width > 0 && r.height > 0;
                    };
                    const setInput = (input, value) => {
                        input.scrollIntoView({ block: "center", inline: "nearest" });
                        input.focus();
                        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
                        if (setter) setter.call(input, value); else input.value = value;
                        input.dispatchEvent(new Event("input", { bubbles: true }));
                        input.dispatchEvent(new Event("change", { bubbles: true }));
                        input.blur();
                    };
                    const norm = (s) => (s || "").replace(/\\s+/g, " ").trim();
                    const compactSku = (value) => {
                        let s = norm(String(value || "").replace(/[^A-Za-z0-9 ().-]+/g, " "));
                        if (s.length <= 20) return s;
                        for (const ch of [" ", "-", ".", "(", ")"]) {
                            while (s.includes(ch) && s.length > 20) s = s.replace(ch, "");
                        }
                        if (s.length <= 20) return s;
                        let remove = s.length - 20;
                        const out = [];
                        for (const ch of s) {
                            if (/\\d/.test(ch) && remove > 0) {
                                remove -= 1;
                                continue;
                            }
                            out.push(ch);
                        }
                        s = out.join("");
                        return s.slice(0, 20).trim();
                    };
                    const cleanTitle = (value) => {
                        let s = norm(String(value || "").replace(/[^\\x00-\\x7F]+/g, " "));
                        if (s.length <= 128) return s;
                        const words = s.split(" ");
                        while (words.length > 1 && words.join(" ").length > 128) words.pop();
                        s = words.join(" ").trim();
                        return (s || norm(value).slice(0, 128)).slice(0, 128).trim();
                    };

                    const skuTables = Array.from(document.querySelectorAll("table, .ant-table, .ant-table-container"))
                        .filter((el) => norm(el.innerText || el.textContent).includes("自定义名称"));
                    const skuInputs = [];
                    for (const table of skuTables) {
                        for (const input of Array.from(table.querySelectorAll("tbody tr input[type='text'], tbody tr input:not([type]), input[maxlength='20']"))) {
                            if (!visible(input) || skuInputs.includes(input)) continue;
                            const value = norm(input.value);
                            const rect = input.getBoundingClientRect();
                            if (!value || rect.width < 60 || /^https?:/i.test(value) || /^\\d+(\\.\\d+)?$/.test(value)) continue;
                            if (!/[A-Za-z]/.test(value) && !/[\\u4e00-\\u9fff]/.test(value)) continue;
                            skuInputs.push(input);
                        }
                    }

                    let skuFixed = 0;
                    const skuBefore = [];
                    for (const input of skuInputs) {
                        const raw = norm(input.value);
                        const next = compactSku(raw);
                        if (next && next !== raw && (raw.length > 20 || /[^A-Za-z0-9 ().-]/.test(raw))) {
                            skuBefore.push(raw);
                            setInput(input, next);
                            skuFixed += 1;
                        }
                    }

                    const titleInputs = Array.from(document.querySelectorAll("input.ant-input.ant-input-sm, input.ant-input"))
                        .filter((input) => visible(input) && !skuInputs.includes(input))
                        .filter((input) => {
                            const value = norm(input.value);
                            if (!value || /^\\d+(\\.\\d+)?$/.test(value) || /^https?:/i.test(value)) return false;
                            return value.length > 128 || /[^\\x00-\\x7F]/.test(value);
                        });
                    let titleFixed = 0;
                    for (const input of titleInputs) {
                        const raw = norm(input.value);
                        const next = cleanTitle(raw);
                        if (next && next !== raw) {
                            setInput(input, next);
                            titleFixed += 1;
                        }
                    }

                    return { stage, skuFixed, titleFixed, skuBefore: skuBefore.slice(0, 5) };
                }""",
                stage,
            )
            sku_fixed = int(result.get("skuFixed", 0)) if isinstance(result, dict) else 0
            title_fixed = int(result.get("titleFixed", 0)) if isinstance(result, dict) else 0
            if sku_fixed or title_fixed:
                logger.success(
                    f"{stage}: 标题/SKU规则修正完成，SKU={sku_fixed}，标题={title_fixed}，"
                    f"sku_preview={(result.get('skuBefore') or [])[:3] if isinstance(result, dict) else []}"
                )
                await asyncio.sleep(0.8)
                return True
        except Exception as exc:
            logger.warning(f"{stage}: 标题/SKU规则修正失败: {exc}")
        return False

    async def step_publish(self) -> bool:
        publish_action = str(CONFIG.get("publish_action", "立即发布") or "立即发布").strip()
        await self.fix_title_and_sku_validation_errors("发布前")
        if "待发布" in publish_action or "移入" in publish_action:
            logger.info("步骤8: 保存并移入待发布")
            clicked = await self.click_save_to_pending_button_precise("保存并移入待发布")
            if not clicked:
                logger.error("保存并移入待发布按钮未点击成功，停止发布步骤")
                return False
            await asyncio.sleep(2)
            success, success_reason = await self.wait_publish_success(timeout_sec=10)
            if success:
                logger.success(f"确认保存并移入待发布成功: {success_reason}")
                await self.close_publish_success_dialog_if_present()
            else:
                errors = await self.collect_visible_validation_errors()
                if errors:
                    logger.warning(f"保存并移入待发布未确认成功，页面可见校验提示: {' | '.join(errors)}")
                else:
                    logger.warning(f"保存并移入待发布未确认成功: {success_reason}")
                fixed = await self.fix_title_and_sku_validation_errors("保存失败后")
                if fixed:
                    retry_clicked = await self.click_save_to_pending_button_precise("保存并移入待发布(修正后重试)")
                    if retry_clicked:
                        await asyncio.sleep(2)
                        success, success_reason = await self.wait_publish_success(timeout_sec=10)
                        if success:
                            logger.success(f"修正后确认保存并移入待发布成功: {success_reason}")
                            await self.close_publish_success_dialog_if_present()
                    else:
                        logger.error("修正后重试保存失败：未点到保存并移入待发布")
            try:
                await self.capture_state("07_publish")
            except Exception as e:
                logger.warning(f"保存后截图失败（页面可能已关闭）: {e}")
            return success

        logger.info("步骤8: 发布商品")
        publish_clicked = await self.click_publish_button_precise("发布商品")
        if not publish_clicked:
            logger.error("发布按钮/立即发布菜单未点击成功，停止发布步骤")
            return False
        await asyncio.sleep(2)

        success, success_reason = await self.wait_publish_success(timeout_sec=8)
        if success:
            logger.success(f"确认发布成功: {success_reason}")
            await self.close_publish_success_dialog_if_present()
            try:
                await self.capture_state("07_publish")
            except Exception as e:
                logger.warning(f"发布后截图失败（页面可能已关闭）: {e}")
            return True

        async def compress_with_rules(text: str, max_len: int) -> str:
            s = (text or "").strip()
            s = " ".join(s.split())
            if len(s) <= max_len:
                return s

            # 优先删空格和符号
            for ch in [" ", "-", ".", "(", ")"]:
                while ch in s and len(s) > max_len:
                    s = s.replace(ch, "", 1)
            if len(s) <= max_len:
                return s

            # 再从前往后删数字
            out = []
            removed = 0
            for c in s:
                if c.isdigit() and len(s) - removed > max_len:
                    removed += 1
                    continue
                out.append(c)
            s = "".join(out)
            if len(s) <= max_len:
                return s

            # 仍超长再截断
            return s[:max_len]

        fixed_any = False

        # 1) 修正自定义名称（20）
        custom_name_error = self.page.locator("div.ant-form-item-explain-error").filter(
            has_text="自定义名称必须为20个字符以内"
        )
        if await custom_name_error.count() > 0:
            logger.warning("检测到自定义名称超长错误，开始自动修正")
            custom_inputs = self.page.locator("input.hide-error.g-form-component[maxlength='20']")
            total = await custom_inputs.count()
            fixed = 0
            for i in range(total):
                inp = custom_inputs.nth(i)
                try:
                    raw = await inp.input_value()
                    new_val = await compress_with_rules(raw, 20)
                    if new_val != raw:
                        await inp.scroll_into_view_if_needed()
                        await inp.fill(new_val)
                        await inp.dispatch_event("input")
                        await inp.dispatch_event("change")
                        fixed += 1
                except Exception:
                    continue
            if fixed > 0:
                fixed_any = True
            logger.success(f"自定义名称修正完成，共处理 {fixed} 项")

        # 2) 修正标题（128）
        # 标题规则：保留空格，不拼接；超长时从后往前删单词
        def trim_title_by_words(text: str, max_len: int = 128) -> str:
            s = " ".join((text or "").strip().split())
            if len(s) <= max_len:
                return s

            words = s.split(" ")
            while len(words) > 0 and len(" ".join(words)) > max_len:
                words.pop()  # 从后面删除单词

            result = " ".join(words).strip()
            # 兜底：至少保留前 max_len 个字符（尽量不断词）
            if not result:
                result = s[:max_len].rstrip()
            return result

        title_inputs = self.page.locator("input.ant-input.ant-input-sm")
        title_total = await title_inputs.count()
        title_fixed = 0
        for i in range(title_total):
            inp = title_inputs.nth(i)
            try:
                raw = await inp.input_value()
                if not raw:
                    continue
                if len(raw.strip()) > 128:
                    new_val = trim_title_by_words(raw, 128)
                    await inp.scroll_into_view_if_needed()
                    await inp.fill(new_val)
                    await inp.dispatch_event("input")
                    await inp.dispatch_event("change")
                    title_fixed += 1
            except Exception:
                continue
        if title_fixed > 0:
            fixed_any = True
            logger.success(f"标题长度修正完成（按词裁剪），共处理 {title_fixed} 项")

        # 3) 修正“自定义属性值只能输入英文、数字或空格符号”问题
        def sanitize_ascii_attr_value(text: str) -> str:
            s = (text or "").strip()
            # 仅保留英文、数字、空格；括号等符号一律删掉
            cleaned = "".join(ch for ch in s if ch.isascii() and (ch.isalnum() or ch == " "))
            cleaned = " ".join(cleaned.split())
            return cleaned

        async def fix_invalid_custom_attr_values() -> int:
            fixed = 0

            # 先精准按报错文案反查最近输入框
            attr_error_locators = [
                self.page.locator("text=请输入英文、数字或空格符号！"),
                self.page.locator(".ant-form-item-explain-error").filter(has_text="请输入英文、数字或空格符号"),
            ]

            for err_loc in attr_error_locators:
                try:
                    err_count = await err_loc.count()
                    for i in range(err_count):
                        err = err_loc.nth(i)
                        if not await err.is_visible():
                            continue

                        # 报错通常紧跟在值输入框后面，优先取最近的前一个 input
                        near_inputs = [
                            err.locator("xpath=preceding::input[1]").first,
                            err.locator("xpath=ancestor::*[self::tr or contains(@class,'row')][1]//input").last,
                        ]

                        for target_input in near_inputs:
                            try:
                                if await target_input.count() == 0:
                                    continue
                                raw = await target_input.input_value()
                                new_val = sanitize_ascii_attr_value(raw)
                                if new_val != raw:
                                    await target_input.fill(new_val)
                                    await target_input.dispatch_event("input")
                                    await target_input.dispatch_event("change")
                                    fixed += 1
                                    break
                            except Exception:
                                continue
                except Exception:
                    continue

            # 如果页面还没来得及渲染红字报错，则兜底清洗所有“包含非法字符”的可见自定义属性值输入框
            if fixed == 0:
                try:
                    all_inputs = self.page.locator("input.ant-input")
                    total = await all_inputs.count()
                    for i in range(total):
                        inp = all_inputs.nth(i)
                        try:
                            if not await inp.is_visible():
                                continue
                            raw = await inp.input_value()
                            if not raw:
                                continue
                            new_val = sanitize_ascii_attr_value(raw)
                            # 只处理“原值包含非法字符且清洗后发生变化”的输入框
                            if new_val != raw and any(not (ch.isascii() and (ch.isalnum() or ch == " ")) for ch in raw):
                                await inp.fill(new_val)
                                await inp.dispatch_event("input")
                                await inp.dispatch_event("change")
                                fixed += 1
                        except Exception:
                            continue
                except Exception:
                    pass

            return fixed

        attr_fixed = await fix_invalid_custom_attr_values()
        if attr_fixed > 0:
            fixed_any = True
            logger.success(f"自定义属性非法字符修正完成，共处理 {attr_fixed} 项")

        # 有任何修正后再重发一次
        if fixed_any:
            publish_clicked = await self.click_publish_button_precise("发布商品(重试)")
            if not publish_clicked:
                logger.error("修正后重试发布失败：未点到立即发布")
                return False
            await asyncio.sleep(2)

        # 如果修正后发布仍未成功，且页面上出现非法字符报错，再修一次并重试一次
        success, success_reason = await self.wait_publish_success(timeout_sec=10)
        if not success:
            late_attr_fixed = await fix_invalid_custom_attr_values()
            if late_attr_fixed > 0:
                logger.success(f"发布后检测到非法字符并修正，共处理 {late_attr_fixed} 项，准备二次发布")
                publish_clicked = await self.click_publish_button_precise("发布商品(二次重试)")
                if not publish_clicked:
                    logger.error("二次重试发布失败：未点到立即发布")
                    return False
                await asyncio.sleep(2)
                success, success_reason = await self.wait_publish_success(timeout_sec=10)

        if success:
            logger.success(f"确认发布成功: {success_reason}")
            await self.close_publish_success_dialog_if_present()
        else:
            errors = await self.collect_visible_validation_errors()
            if errors:
                logger.warning(f"发布未确认成功，页面可见校验提示: {' | '.join(errors)}")
            else:
                logger.warning(f"发布未确认成功: {success_reason}")

        try:
            await self.capture_state("07_publish")
        except Exception as e:
            # 有些商品点击发布后会自动关闭当前编辑页，这里不再抛异常中断批量
            logger.warning(f"发布后截图失败（页面可能已关闭）: {e}")
        return success


def load_product_data() -> dict:
    path = BASE_DIR / "product_data.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            logger.info(f"已加载商品数据文件: {path}")
            return data
        except Exception as exc:
            logger.warning(f"读取商品数据失败，改用默认数据: {exc}")

    return {
        "original_price": 10.0,
        "title": "示例商品",
        "sku": "DEMO-SKU-001",
    }


async def fetch_dropdown_info(mode: str = "linked"):
    """
    从当前已登录/已打开的页面采集下拉框信息，供 GUI 选择。
    """
    mode = mode if mode in {"categories", "linked", "customs", "all"} else "linked"
    runner = ShopAutomationRunner(load_product_data())
    try:
        await runner.connect()
        await runner.ensure_page_ready()

        page = runner.page
        if not page:
            raise RuntimeError("页面未初始化")

        # 如果当前在采集箱列表页，先自动进入第一个“编辑”页再采集
        if "smtproductlist/draft" in (page.url or "").lower():
            logger.info("当前在采集箱页，先进入第一个编辑页采集下拉信息")
            edit_links = page.locator("a:has-text('编辑')")
            if await edit_links.count() == 0:
                raise RuntimeError("采集箱页面未找到“编辑”按钮，无法采集下拉信息")

            pages_before = {p for ctx in runner.browser.contexts for p in ctx.pages}
            await edit_links.first.click()
            await page.wait_for_timeout(1500)

            pages_after = [p for ctx in runner.browser.contexts for p in ctx.pages]
            edit_page = None
            for p in pages_after:
                if p not in pages_before and "smt/edit" in (p.url or "").lower():
                    edit_page = p
                    break
            if not edit_page:
                for p in pages_after:
                    if "smt/edit" in (p.url or "").lower():
                        edit_page = p
                        break

            if not edit_page:
                raise RuntimeError("未能进入编辑页，无法采集下拉信息")

            page = edit_page
            await page.bring_to_front()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(1200)
            logger.info(f"已切换到编辑页: {page.url}")

        # 产品属性模板、海关监管等字段会随类目联动变化。
        # 第二/三步采集时先按 GUI 当前预设类目切换页面类目，再读取该类目下的联动下拉项。
        configured_category = str(CONFIG.get("category") or "").strip()
        if mode in {"linked", "customs", "all"} and configured_category:
            try:
                runner.page = page
                logger.info(f"采集前先应用预设类目，以刷新联动下拉: {configured_category}")
                await runner.step_select_category()
                await page.wait_for_timeout(1500)
            except Exception as category_exc:
                logger.warning(f"采集前切换预设类目失败，继续按当前页面类目采集: {category_exc}")

        configured_template = str(CONFIG.get("template") or "").strip()
        if mode in {"customs", "all"} and configured_template:
            try:
                runner.page = page
                logger.info(f"采集海关前先应用产品属性模板，以刷新海关监管字段: {configured_template}")
                await runner.step_select_template()
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                await page.wait_for_timeout(1800)
            except Exception as template_exc:
                logger.warning(f"采集海关前选择属性模板失败，继续按当前页面状态采集: {template_exc}")

        if mode in {"customs", "all"}:
            try:
                runner.page = page
                logger.info("采集海关前先执行店小秘一键翻译，确保翻译后生成的海关字段已刷新")
                translated = await runner.step_translate(apply_ai_text=False)
                if not translated:
                    raise RuntimeError("店小秘一键翻译未落地，已停止本次海关选项采集")
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                await page.wait_for_timeout(1500)
            except Exception as translate_exc:
                logger.warning(f"采集海关前执行一键翻译失败，继续按当前页面状态采集: {translate_exc}")

        # 采集页面上的 ant-select 及其标签/当前值/placeholder
        data = await page.evaluate(
            """() => {
                const rows = [];
                const selects = Array.from(document.querySelectorAll(".ant-select"));
                selects.forEach((sel, idx) => {
                    let label = "";
                    const formItem = sel.closest(".ant-form-item");
                    if (formItem) {
                        const labelEl = formItem.querySelector(".ant-form-item-label");
                        if (labelEl) label = (labelEl.innerText || "").trim();
                    }

                    const current = sel.querySelector(".ant-select-selection-item")?.getAttribute("title")
                        || (sel.querySelector(".ant-select-selection-item")?.innerText || "").trim();
                    const placeholder = (sel.querySelector(".ant-select-selection-placeholder")?.innerText || "").trim();
                    const inputId = sel.querySelector("input[role='combobox']")?.id || "";

                    rows.push({
                        index: idx,
                        label,
                        current: current || "",
                        placeholder: placeholder || "",
                        inputId
                    });
                });
                return rows;
            }"""
        )

        async def collect_open_dropdown_options(field_name: str, limit: int = 200, max_rounds: int = 45):
            vals: list[str] = []
            seen: set[str] = set()

            try:
                await page.evaluate(
                    """() => {
                        const roots = Array.from(document.querySelectorAll(".ant-select-dropdown"))
                          .filter(el => {
                            const st = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return st.display !== "none" && st.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                          });
                        const root = roots[roots.length - 1];
                        const box = root && (root.querySelector(".rc-virtual-list-holder") || root.querySelector("[class*='virtual-list-holder']"));
                        if (box) {
                            box.scrollTop = 0;
                            box.dispatchEvent(new Event("scroll", { bubbles: true }));
                        }
                    }"""
                )
                await asyncio.sleep(0.2)
            except Exception:
                pass

            stagnant_rounds = 0
            last_key = ""
            for _ in range(max_rounds):
                result = await page.evaluate(
                    """(lim) => {
                        const visible = (el) => {
                            if (!el || !el.getBoundingClientRect) return false;
                            const r = el.getBoundingClientRect();
                            const st = window.getComputedStyle(el);
                            return st.display !== "none" && st.visibility !== "hidden" && r.width > 0 && r.height > 0;
                        };
                        const roots = Array.from(document.querySelectorAll(".ant-select-dropdown"))
                          .filter(visible);
                        if (roots.length === 0) return { options: [], done: true, reason: "no_dropdown" };
                        const root = roots[roots.length - 1];
                        const found = [];
                        const items = Array.from(root.querySelectorAll(
                            ".ant-select-item-option:not(.ant-select-item-option-disabled), [role='option'], .in-check-options"
                        ));
                        for (const it of items) {
                            const text = (it.getAttribute("title") || it.innerText || it.textContent || "").replace(/\\s+/g, " ").trim();
                            if (!text || text === "暂无数据" || text === "Not Found") continue;
                            if (/^\\d{6,}$/.test(text)) continue;
                            found.push(text);
                            if (found.length >= lim) break;
                        }

                        const box = root.querySelector(".rc-virtual-list-holder")
                            || root.querySelector("[class*='virtual-list-holder']")
                            || root;
                        const before = box.scrollTop || 0;
                        const client = box.clientHeight || 260;
                        const max = Math.max(0, (box.scrollHeight || 0) - client);
                        if (max > before + 2) {
                            box.scrollTop = Math.min(max, before + Math.max(180, Math.floor(client * 0.85)));
                            box.dispatchEvent(new Event("scroll", { bubbles: true }));
                            box.dispatchEvent(new WheelEvent("wheel", { bubbles: true, deltaY: 260 }));
                        }
                        const after = box.scrollTop || 0;
                        return {
                            options: found,
                            done: max <= 0 || after >= max - 2 || after === before,
                            scrollTop: after,
                            max,
                            visibleCount: found.length
                        };
                    }""",
                    limit
                )
                for value in result.get("options", []) if isinstance(result, dict) else []:
                    if isinstance(value, str):
                        value = value.strip()
                        if value and value not in seen:
                            seen.add(value)
                            vals.append(value)
                            if len(vals) >= limit:
                                break
                if len(vals) >= limit:
                    break

                key = f"{len(vals)}:{result.get('scrollTop')}:{result.get('max')}:{result.get('visibleCount')}" if isinstance(result, dict) else str(len(vals))
                if key == last_key:
                    stagnant_rounds += 1
                else:
                    stagnant_rounds = 0
                    last_key = key
                if isinstance(result, dict) and result.get("done") and stagnant_rounds >= 1:
                    break
                if stagnant_rounds >= 4:
                    break
                await asyncio.sleep(0.18)

            logger.info(f"滚动采集 {field_name} 下拉候选: {len(vals)} 条")
            return vals

        async def collect_dropdown_options(open_locator, field_name: str, limit: int = 200):
            options = []
            try:
                if await open_locator.count() == 0:
                    return options

                target = open_locator.first
                try:
                    await target.evaluate("(el) => el.scrollIntoView({ block: 'center', inline: 'nearest' })")
                    await asyncio.sleep(0.2)
                except Exception:
                    pass
                # 避免 scroll_into_view 在“不可见”时长时间超时，改为直接强制点击
                await target.click(timeout=3000, force=True)
                await asyncio.sleep(0.6)

                options = await collect_open_dropdown_options(field_name, limit=limit)

                # 关闭下拉，避免干扰后续
                try:
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
                await asyncio.sleep(0.2)

                logger.info(f"已采集 {field_name} 下拉候选: {len(options)} 条")
            except Exception as e:
                logger.warning(f"采集 {field_name} 下拉候选失败: {e}")
            return options

        category_options = []
        template_options = []
        freight_options = []
        service_options = []
        european_responsible_options = []
        brand_manufacturer_options = []

        if mode in {"categories", "all"}:
            category_options = await collect_dropdown_options(
                page.locator("label:has-text('产品分类')").locator("xpath=../following-sibling::*").locator(".ant-select-selector"),
                "产品分类",
                500
            )

        if mode in {"linked", "all"}:
            template_options = await collect_dropdown_options(
                page.locator("input#rc_select_2").locator("xpath=ancestor::div[contains(@class,'ant-select')][1]"),
                "产品属性模板",
                300
            )

            freight_options = await collect_dropdown_options(
                page.locator("input#form_item_freightTemplateId").locator("xpath=ancestor::div[contains(@class,'ant-select')][1]"),
                "运费模板",
                300
            )

            service_options = await collect_dropdown_options(
                page.locator("input#form_item_promiseTemplateId").locator("xpath=ancestor::div[contains(@class,'ant-select')][1]"),
                "服务模板",
                300
            )

            european_responsible_options = await collect_dropdown_options(
                page.locator("input#form_item_msrEuId").locator("xpath=ancestor::div[contains(@class,'ant-select')][1]"),
                "欧盟责任人",
                300
            )

            brand_manufacturer_options = await collect_dropdown_options(
                page.locator("input#form_item_manufactureId").locator("xpath=ancestor::div[contains(@class,'ant-select')][1]"),
                "品牌制造商",
                300
            )

        # 第三步：打开“添加海关监管”弹窗，按当前 GUI 预设逐级采集海关监管选项。
        customs_item_options = []
        customs_material_options = []
        customs_level_options = {f"customs_level{i}": [] for i in range(1, 5)}
        if mode in {"customs", "all"}:
            try:
                clicked = await page.evaluate(
                    """() => {
                        const visible = (el) => {
                            if (!el || !el.getBoundingClientRect) return false;
                            const st = window.getComputedStyle(el);
                            const r = el.getBoundingClientRect();
                            return st.display !== "none" && st.visibility !== "hidden" && r.width > 0 && r.height > 0;
                        };
                        const clickNode = (node) => {
                            const rect = node.getBoundingClientRect();
                            const init = {
                                bubbles: true,
                                cancelable: true,
                                view: window,
                                clientX: rect.left + rect.width / 2,
                                clientY: rect.top + rect.height / 2,
                            };
                            ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach((type) => {
                                node.dispatchEvent(new MouseEvent(type, init));
                            });
                        };
                        const candidates = Array.from(document.querySelectorAll("button, a, span, div"))
                            .filter((el) => visible(el) && (el.innerText || el.textContent || "").trim().includes("添加海关监管"));
                        const el = candidates.find((node) => node.closest("button, a")) || candidates[0];
                        if (!el) return "";
                        const target = el.closest("button, a") || el;
                        target.scrollIntoView({ block: "center", inline: "nearest" });
                        clickNode(target);
                        return (target.innerText || target.textContent || "").trim();
                    }"""
                )
                if clicked:
                    logger.success(f"点击成功: 添加海关监管 - {clicked}")
                else:
                    logger.warning("未找到“添加海关监管”按钮，跳过海关下拉采集")
                    raise RuntimeError("未找到添加海关监管按钮")

                await page.wait_for_timeout(1000)

                async def get_customs_root():
                    for _ in range(20):
                        root = page.locator(".ant-modal-content").filter(has_text="海关监管").last
                        try:
                            if await root.count() > 0 and await root.is_visible():
                                return root
                        except Exception:
                            pass
                        root = page.locator(".ant-drawer-content").filter(has_text="海关监管").last
                        try:
                            if await root.count() > 0 and await root.is_visible():
                                return root
                        except Exception:
                            pass
                        await page.wait_for_timeout(200)
                    return None

                customs_root = await get_customs_root()
                if not customs_root:
                    raise RuntimeError("海关监管弹窗未打开")

                async def get_visible_customs_selects():
                    return customs_root.locator(".ant-select")

                async def get_select_current_text(selector) -> str:
                    try:
                        return await selector.evaluate(
                            """(el) => {
                                const root = el.closest(".ant-select") || el;
                                return (
                                    root.querySelector(".ant-select-selection-item")?.getAttribute("title")
                                    || root.querySelector(".ant-select-selection-item")?.innerText
                                    || root.innerText
                                    || ""
                                ).replace(/\\s+/g, " ").trim();
                            }"""
                        )
                    except Exception:
                        return ""

                async def pick_option_from_select(selector, target_text: str, description: str) -> bool:
                    if not target_text:
                        return False
                    try:
                        picked = await selector.evaluate(
                            """async (el, targetText) => {
                                const normalize = (s) => (s || "")
                                    .replace(/\\uFF08/g, "(")
                                    .replace(/\\uFF09/g, ")")
                                    .replace(/\\s+/g, "")
                                    .replace(/\\(ai推荐\\)/gi, "")
                                    .replace(/ai推荐/gi, "")
                                    .trim()
                                    .toLowerCase();
                                const englishKey = (s) => {
                                    const m = String(s || "")
                                        .replace(/\\uFF08/g, "(")
                                        .replace(/\\uFF09/g, ")")
                                        .match(/\\(([A-Za-z][A-Za-z0-9\\s\\-\\/]+)\\)/);
                                    return m ? normalize(m[1]) : "";
                                };
                                const visible = (node) => {
                                    if (!node || !node.getBoundingClientRect) return false;
                                    const st = window.getComputedStyle(node);
                                    const r = node.getBoundingClientRect();
                                    return st.display !== "none" && st.visibility !== "hidden" && r.width > 0 && r.height > 0;
                                };
                                const clickNode = (node) => {
                                    const rect = node.getBoundingClientRect();
                                    const init = {
                                        bubbles: true,
                                        cancelable: true,
                                        view: window,
                                        clientX: rect.left + rect.width / 2,
                                        clientY: rect.top + rect.height / 2,
                                    };
                                    ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach((type) => {
                                        node.dispatchEvent(new MouseEvent(type, init));
                                    });
                                };
                                const target = normalize(targetText);
                                const targetKey = englishKey(targetText) || target;
                                const rootSelect = el.closest(".ant-select") || el;
                                const selectorNode = rootSelect.querySelector(".ant-select-selector") || el;
                                const input = rootSelect.querySelector("input[role='combobox'], input.ant-select-selection-search-input");
                                const controls = input?.getAttribute("aria-controls") || input?.getAttribute("aria-owns") || "";
                                selectorNode.scrollIntoView({ block: "center", inline: "nearest" });
                                clickNode(selectorNode);
                                const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                                const findRoot = () => {
                                    const roots = Array.from(document.querySelectorAll(".ant-select-dropdown")).filter(visible);
                                    if (!roots.length) return null;
                                    if (controls) {
                                        const bound = roots.find((root) => {
                                            try { return !!root.querySelector(`#${CSS.escape(controls)}`); } catch (_) { return false; }
                                        });
                                        if (bound) return bound;
                                    }
                                    return roots[roots.length - 1];
                                };
                                let dropdown = null;
                                for (let i = 0; i < 25; i += 1) {
                                    dropdown = findRoot();
                                    if (dropdown) break;
                                    await wait(100);
                                }
                                if (!dropdown || !target) return "";
                                const holder = dropdown.querySelector(".rc-virtual-list-holder")
                                    || dropdown.querySelector("[class*='virtual-list-holder']")
                                    || dropdown;
                                const findMatch = () => {
                                    const items = Array.from(dropdown.querySelectorAll(
                                        ".ant-select-item-option:not(.ant-select-item-option-disabled), [role='option'], .ant-select-item-option-content, .in-check-options, div[title]"
                                    ));
                                    const candidates = items.map((node) => {
                                        const text = (node.getAttribute("title") || node.innerText || node.textContent || "").replace(/\\s+/g, " ").trim();
                                        const norm = normalize(text);
                                        const key = englishKey(text) || norm;
                                        let score = 0;
                                        if (norm === target) score = 100;
                                        else if (targetKey && key === targetKey) score = 90;
                                        else if (target && (norm.startsWith(target) || target.startsWith(norm))) score = 80;
                                        else if (target && (norm.includes(target) || target.includes(norm))) score = 70;
                                        else if (targetKey && (key.startsWith(targetKey) || targetKey.startsWith(key))) score = 60;
                                        return { node, text, score };
                                    }).filter((item) => item.text);
                                    return candidates.filter((item) => item.score > 0).sort((a, b) => b.score - a.score)[0] || null;
                                };
                                let found = null;
                                for (let pass = 0; pass < 2 && !found; pass += 1) {
                                    if (holder) holder.scrollTop = 0;
                                    for (let i = 0; i < 28; i += 1) {
                                        found = findMatch();
                                        if (found) break;
                                        if (holder) {
                                            holder.scrollTop += 260;
                                            holder.dispatchEvent(new Event("scroll", { bubbles: true }));
                                        }
                                        await wait(80);
                                    }
                                }
                                if (!found) return "";
                                const optionNode = found.node.closest(".ant-select-item-option")
                                    || found.node.closest(".ant-select-item")
                                    || found.node;
                                optionNode.scrollIntoView({ block: "center", inline: "nearest" });
                                clickNode(optionNode);
                                return found.text;
                            }""",
                            target_text
                        )
                        if picked:
                            logger.success(f"选择成功: {description} = {picked}")
                            await page.wait_for_timeout(900)
                            return True
                    except Exception as exc:
                        logger.warning(f"{description} 选择失败: {exc}")
                    return False

                async def collect_customs_level(level_index: int) -> list[str]:
                    selects = await get_visible_customs_selects()
                    count = await selects.count()
                    if count <= level_index:
                        logger.info(f"海关监管第{level_index + 1}级下拉框尚未生成")
                        return []
                    selector = selects.nth(level_index)
                    try:
                        await selector.scroll_into_view_if_needed()
                        await selector.click(timeout=2500, force=True)
                        await page.wait_for_timeout(500)
                    except Exception as exc:
                        logger.warning(f"打开海关监管第{level_index + 1}级失败: {exc}")
                        return []
                    opts = await collect_open_dropdown_options(f"海关监管第{level_index + 1}级", limit=300)
                    try:
                        modal_title = customs_root.locator(".ant-modal-title, .ant-drawer-title").first
                        if await modal_title.count() > 0:
                            await modal_title.click(timeout=1000, force=True)
                        else:
                            await customs_root.click(position={"x": 20, "y": 20}, timeout=1000, force=True)
                    except Exception:
                        pass
                    await page.wait_for_timeout(250)
                    logger.info(f"已采集海关监管第{level_index + 1}级: {len(opts)} 条")
                    return opts

                configured_levels = [
                    str(CONFIG.get("customs_level1") or CONFIG.get("customs_item") or "").strip(),
                    str(CONFIG.get("customs_level2") or CONFIG.get("customs_material") or "").strip(),
                    str(CONFIG.get("customs_level3") or "").strip(),
                    str(CONFIG.get("customs_level4") or "").strip(),
                ]

                for idx in range(4):
                    opts = await collect_customs_level(idx)
                    customs_level_options[f"customs_level{idx + 1}"] = opts
                    if idx == 0:
                        customs_item_options = opts
                    elif idx == 1:
                        customs_material_options = opts

                    target = configured_levels[idx]
                    if not target:
                        logger.info(f"海关监管第{idx + 1}级未配置目标值，停止继续拉取子级")
                        break

                    selects = await get_visible_customs_selects()
                    if await selects.count() <= idx:
                        logger.warning(f"海关监管第{idx + 1}级采集后弹窗内下拉框不可用，停止继续拉取子级")
                        break
                    current = await get_select_current_text(selects.nth(idx))
                    normalized_current = current.replace("（", "(").replace("）", ")").replace(" ", "").replace("(AI推荐)", "")
                    normalized_target = target.replace("（", "(").replace("）", ")").replace(" ", "").replace("(AI推荐)", "")
                    if normalized_current and normalized_target and (
                        normalized_current == normalized_target
                        or normalized_current.startswith(normalized_target)
                        or normalized_target.startswith(normalized_current)
                    ):
                        logger.success(f"海关监管第{idx + 1}级已是目标值: {current}")
                    else:
                        await pick_option_from_select(selects.nth(idx), target, f"海关监管第{idx + 1}级")
                    try:
                        await page.wait_for_load_state("networkidle", timeout=2500)
                    except Exception:
                        pass
                    await page.wait_for_timeout(1000)

                modal_close_btn = page.locator(
                    ".ant-modal-content:has-text('海关监管') button:has-text('取消'), "
                    ".ant-modal-content:has-text('海关监管') .ant-modal-close, "
                    ".ant-drawer-content:has-text('海关监管') button:has-text('取消'), "
                    ".ant-drawer-content:has-text('海关监管') .ant-drawer-close"
                ).last
                if await modal_close_btn.count() > 0:
                    try:
                        await modal_close_btn.click(timeout=1500, force=True)
                    except Exception:
                        pass
            except Exception as customs_exc:
                logger.warning(f"采集海关信息下拉失败: {customs_exc}")

        out = {
            "mode": mode,
            "url": page.url,
            "count": len(data),
            "items": data,
            "special_options": {
                "category": category_options,
                "template": template_options,
                "currency_template": freight_options,
                "service_template": service_options,
                "european_responsible": european_responsible_options,
                "brand_manufacturer": brand_manufacturer_options,
                "customs_level1": customs_level_options["customs_level1"],
                "customs_level2": customs_level_options["customs_level2"],
                "customs_level3": customs_level_options["customs_level3"],
                "customs_level4": customs_level_options["customs_level4"],
                "customs_item": customs_item_options,
                "customs_material": customs_material_options
            }
        }
        out_path = BASE_DIR / "dropdown_options.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.success(f"下拉框信息已导出: {out_path}")
    finally:
        if runner.browser:
            await runner.browser.close()
        if runner.playwright:
            await runner.playwright.stop()


async def publish_current_edit_page_only():
    """
    只验证/执行当前编辑页的发布步骤，不从采集箱重新跑完整流程。
    """
    runner = ShopAutomationRunner(load_product_data())
    try:
        await runner.connect()

        edit_pages = []
        if runner.browser:
            for context in runner.browser.contexts:
                for page in context.pages:
                    if "smt/edit" in (page.url or "").lower():
                        edit_pages.append(page)

        if not edit_pages:
            raise RuntimeError("未找到已打开的店小秘编辑页，请先停留在商品编辑页再执行仅发布验证")

        runner.page = edit_pages[-1]
        await runner.page.bring_to_front()
        await runner.ensure_page_ready()
        logger.info(f"仅发布模式：当前编辑页 {runner.page.url}")

        success = await runner.step_publish()
        if success:
            logger.success("仅发布模式执行完成：已确认发布成功")
        else:
            logger.error("仅发布模式执行完成：未确认发布成功")
    finally:
        if runner.browser:
            await runner.browser.close()
        if runner.playwright:
            await runner.playwright.stop()


async def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fetch-dropdowns", action="store_true", help="采集当前页面下拉框信息")
    parser.add_argument("--fetch-mode", choices=["categories", "linked", "customs", "all"], default="linked")
    parser.add_argument("--publish-only", action="store_true", help="只执行当前编辑页发布步骤")
    # 关键修复：允许外层 exe 传入其它参数（如 --worker），避免 argparse 直接 code=2 退出
    args, _unknown = parser.parse_known_args()

    if args.fetch_dropdowns:
        await fetch_dropdown_info(args.fetch_mode)
        return

    if args.publish_only:
        await publish_current_edit_page_only()
        return

    runner = ShopAutomationRunner(load_product_data())
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
