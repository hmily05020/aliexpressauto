import asyncio
from playwright.async_api import async_playwright
import json
import urllib.request
import urllib.error

async def inspect_page():
    # 先检查调试端口是否可达
    print("🔍 检查调试端口...")
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=5) as response:
            data = json.loads(response.read().decode())
            print(f"✅ 调试端口可达，发现 {len(data)} 个页面")
            for i, page in enumerate(data):
                print(f"   [{i}] {page.get('title', '无标题')} - {page.get('url', '')}")
    except Exception as e:
        print(f"❌ 无法连接调试端口: {e}")
        return

    try:
        async with async_playwright() as p:
            # 尝试连接，使用127.0.0.1而不是localhost
            print("\n🔗 正在连接到Chrome...")
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")

            print(f"✅ 已连接到Chrome")

            # 获取所有页面
            contexts = browser.contexts
            print(f"Context数量: {len(contexts)}")

            pages = []
            for context in contexts:
                pages.extend(context.pages)

            print(f"页面数量: {len(pages)}")

            if not pages:
                print("❌ 无法找到打开的页面")
                await browser.close()
                return

            page = pages[0]
            print(f"\n当前页面URL: {page.url}")
            print(f"页面标题: {await page.title()}")

            # 等待一下让页面完全加载
            await asyncio.sleep(1)

            # 获取页面HTML
            html = await page.content()
            print(f"页面大小: {len(html)} 字符")

            # 保存HTML供分析
            with open("d:/facai/page_structure.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("✅ 页面HTML已保存到 page_structure.html")

            # 查找关键元素
            print("\n" + "="*60)
            print("查找页面中的关键元素:")
            print("="*60)

            # 查找编辑按钮
            try:
                edit_btn = await page.locator('button, a, div[role="button"]').first.evaluate("el => el.textContent")
                print(f"第一个按钮/链接文本: {edit_btn}")
            except:
                pass

            # 获取所有输入框
            inputs = await page.locator('input, textarea, select, [role="combobox"]').count()
            print(f"输入框/下拉框数量: {inputs}")

            await browser.close()
            print("\n✅ 检查完成")

    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(inspect_page())
