import asyncio
import sys
import subprocess
from pathlib import Path
from playwright.async_api import async_playwright, Page, BrowserContext


# 独立的 Chrome 配置目录（专给 Kalodata 用，与你日常 Chrome 互不干扰）
KALO_PROFILE_DIR = Path(__file__).resolve().parent / "data" / "kalo_chrome_profile"


class KalodataScraper:
    def __init__(self, headless: bool = False):
        self._pw = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._headless = headless

    async def _ensure_browser(self):
        """启动一个独立的 Chrome 窗口（独立配置目录），登录态持久保存。

        用系统真实的 chrome.exe，但 user-data-dir 是独立目录，因此可以和
        你日常用的 Chrome 同时运行、互不干扰。登录信息保存在该独立目录里，
        下次直接复用，无需再登录。
        """
        if self._context is not None:
            return

        from config import KALODATA_PROXY, CHROME_PATH

        KALO_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()

        launch_kwargs = dict(
            user_data_dir=str(KALO_PROFILE_DIR),
            headless=self._headless,
            viewport={"width": 1400, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        # 优先用系统真实 Chrome；找不到则回退到 Playwright 自带 chromium
        if CHROME_PATH and Path(CHROME_PATH).exists():
            launch_kwargs["executable_path"] = CHROME_PATH
        if KALODATA_PROXY:
            launch_kwargs["proxy"] = {"server": KALODATA_PROXY}

        self._context = await self._pw.chromium.launch_persistent_context(**launch_kwargs)
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

    async def close(self):
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None
        if self._pw:
            await self._pw.stop()
            self._pw = None

    async def _goto(self, url: str, retries: int = 3):
        """带重试的导航，容忍代理偶发的 ERR_CONNECTION_CLOSED。"""
        last_err = None
        for attempt in range(retries):
            try:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=40000)
                return
            except Exception as e:
                last_err = e
                await asyncio.sleep(3 + attempt * 2)
        if last_err:
            raise last_err

    async def ensure_logged_in(self, wait_seconds: int = 0) -> bool:
        """打开Kalodata并检查是否已登录。未登录时返回False，调用方可提示用户手动登录。"""
        await self._ensure_browser()
        page = self._page

        await self._goto("https://www.kalodata.com/product")
        await asyncio.sleep(3)

        # 检查是否有登录按钮可见 → 未登录
        login_btn = page.locator("text=登录").first
        try:
            if await login_btn.is_visible(timeout=2000):
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)
                    return await self._check_logged_in()
                return False
        except Exception:
            pass
        return True

    async def _check_logged_in(self) -> bool:
        page = self._page
        # 账号被踢也视为未登录
        try:
            if await self._is_session_invalid():
                return False
        except Exception:
            pass
        login_btn = page.locator("text=登录").first
        try:
            return not await login_btn.is_visible(timeout=2000)
        except Exception:
            return True

    async def select_country(self, country_code: str) -> bool:
        """在右上角切换国家/地区。country_code 如 'MY'、'ID'。

        Kalodata 右上角是 #region-dropdown，点击后弹出 .ant-popover，
        里面每个国家是 div.region-option，含 span 文本（如"马来西亚"）。
        """
        page = self._page

        # 国家代码 → Kalodata 实际显示的中文名（已通过 DOM 探测确认）
        country_names = {
            "MY": "马来西亚",
            "ID": "印度尼西亚",
            "TH": "泰国",
            "VN": "越南",
            "PH": "菲律宾",
            "US": "美国",
            "UK": "英国",
            "SG": "新加坡",
            "JP": "日本",
        }
        target = country_names.get(country_code.upper())
        if not target:
            return False

        opener = page.locator("#region-dropdown")
        try:
            await opener.wait_for(state="visible", timeout=10000)
        except Exception:
            return False

        # 若当前已是目标国家，跳过
        try:
            current = (await opener.inner_text()).strip()
            if target in current:
                return True
        except Exception:
            pass

        # 展开下拉。普通 click/hover 会因覆盖层超时，用合成鼠标事件触发最可靠
        await page.evaluate("""() => {
            const el = document.getElementById('region-dropdown');
            if (el) {
                ['mousedown', 'mouseup', 'click'].forEach(t =>
                    el.dispatchEvent(new MouseEvent(t, {bubbles: true, cancelable: true, view: window}))
                );
            }
        }""")
        await asyncio.sleep(1.5)

        # 点击目标国家选项（div.region-option 含国家名）
        clicked = await page.evaluate("""(target) => {
            const opts = [...document.querySelectorAll('div.region-option')]
                .filter(e => e.offsetParent !== null);
            const hit = opts.find(e => e.textContent.trim() === target)
                     || opts.find(e => e.textContent.includes(target));
            if (hit) {
                ['mousedown', 'mouseup', 'click'].forEach(t =>
                    hit.dispatchEvent(new MouseEvent(t, {bubbles: true, cancelable: true, view: window}))
                );
                return true;
            }
            return false;
        }""", target)

        if not clicked:
            return False

        # 切换国家后数据重新加载
        await asyncio.sleep(3)
        # 校验是否切换成功
        try:
            current = (await opener.inner_text()).strip()
            return target in current
        except Exception:
            return True

    async def search_product(self, product_name: str, country: str = "") -> bool:
        """搜索商品。先切换国家，再搜索。返回是否成功"""
        await self._ensure_browser()
        page = self._page

        if "kalodata.com/product" not in page.url:
            await self._goto("https://www.kalodata.com/product")
            await asyncio.sleep(3)

        # 先切换到目标国家
        if country:
            try:
                await self.select_country(country)
            except Exception:
                pass  # 切换失败不阻断搜索

        # 定位搜索输入框（placeholder 含"输入商品"）
        search_input = page.locator('input[placeholder*="输入商品"]').first
        try:
            await search_input.wait_for(state="visible", timeout=8000)
        except Exception:
            search_input = page.locator('input.ant-input[type="text"]').first
            try:
                await search_input.wait_for(state="visible", timeout=5000)
            except Exception:
                return False

        # 通过 JS 聚焦并清空（普通 click 会因覆盖层超时）
        await page.evaluate("""() => {
            const inp = document.querySelector('input[placeholder*="输入商品"]')
                     || document.querySelector('input.ant-input[type="text"]');
            if (inp) { inp.focus(); inp.value = ''; }
        }""")
        await asyncio.sleep(0.3)

        # 用键盘输入（已聚焦），再回车
        await page.keyboard.type(product_name, delay=40)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        await asyncio.sleep(3)

        # 检测账号被踢/掉登录状态
        if await self._is_session_invalid():
            raise RuntimeError(
                "Kalodata 登录已失效（账号可能在其他设备登录，单设备限制）。"
                "请点「打开 Kalodata 登录窗口」重新登录后再试。"
            )

        # 等待真实数据行加载（排除测量行/占位空行）
        for _ in range(8):
            n = await self._real_row_count()
            if n > 0:
                await asyncio.sleep(1)
                return True
            await asyncio.sleep(1.5)
        return False

    async def _is_session_invalid(self) -> bool:
        page = self._page
        for marker in ["已经在新的设备上登录", "请再次登录"]:
            try:
                if await page.locator(f"text={marker}").count():
                    return True
            except Exception:
                pass
        return False

    async def _real_row_count(self) -> int:
        """真实数据行数：AntD 数据行是 tr.ant-table-row（排除测量行/占位行）。"""
        try:
            return await self._page.evaluate("""() => {
                return document.querySelectorAll('table tbody tr.ant-table-row').length;
            }""")
        except Exception:
            return 0

    async def get_script_from_top_videos(self, product_name: str, count: int = 3, country: str = "") -> list[str]:
        """获取成交金额最高视频的口播稿"""
        ok = await self.search_product(product_name, country)
        if not ok:
            return []

        page = self._page
        scripts: list[str] = []

        # 取第一行真实数据行（成交金额最高的商品）
        rows = page.locator("table tbody tr.ant-table-row")
        row_count = await rows.count()
        if row_count == 0:
            return []

        first_row = rows.first
        # "成交金额最高视频"列（第10列, index 9）里的视频缩略图（CSS背景图，非img）
        thumb_handles = await self._get_video_thumbs(first_row)
        if not thumb_handles:
            return []

        # 遍历所有缩略图，跳过过短/无意义的口播稿，凑够 count 份
        for thumb in thumb_handles:
            if len(scripts) >= count:
                break
            try:
                script = await self._extract_script(thumb)
                # 过滤过短的无意义口播稿（如纯"感谢观看"）
                if script and len(script) >= 30:
                    scripts.append(script)
            except Exception:
                continue

        # 若有效口播稿不足，放宽长度限制再补
        if not scripts:
            for thumb in thumb_handles:
                try:
                    script = await self._extract_script(thumb)
                    if script:
                        scripts.append(script)
                        if len(scripts) >= count:
                            break
                except Exception:
                    continue

        return scripts

    async def _get_video_thumbs(self, row) -> list:
        """获取一行中"成交金额最高视频"列的视频缩略图元素句柄。

        缩略图是用 CSS background-image 渲染的 div（背景 URL 含 tiktok.video），
        不是 <img> 标签。
        """
        try:
            handle = await row.evaluate_handle("""(tr) => {
                const tds = tr.querySelectorAll('td');
                // 优先第9列；找不到则全行扫描含 tiktok.video 背景的元素
                const scan = (root) => [...root.querySelectorAll('*')].filter(e => {
                    const bg = getComputedStyle(e).backgroundImage;
                    return bg && bg.includes('tiktok.video');
                });
                let thumbs = tds[9] ? scan(tds[9]) : [];
                if (!thumbs.length) thumbs = scan(tr);
                return thumbs;
            }""")
            props = await handle.get_properties()
            return [v.as_element() for v in props.values() if v.as_element()]
        except Exception:
            return []

    async def _extract_script(self, thumb) -> str | None:
        """悬浮缩略图 → 悬浮"更多" → 点击"口播稿" → 读取弹窗正文。

        关键点（已通过真实DOM验证）：
        - "更多"是 hover 触发的 ant-dropdown 二级菜单
        - 用合成鼠标事件点击菜单项，避免真实鼠标移开导致菜单关闭
        - 弹窗是 .ant-modal，正文在 .ant-modal-body，正文异步加载需等待
        """
        page = self._page

        # 悬浮缩略图，弹出操作浮层
        await thumb.scroll_into_view_if_needed()
        await thumb.hover()
        await asyncio.sleep(1.2)

        # 悬浮"更多"展开 ant-dropdown 菜单
        try:
            await page.locator("text=更多").first.hover(timeout=4000)
        except Exception:
            return None
        await asyncio.sleep(1.2)

        # 用合成事件点击"口播稿"菜单项（避免鼠标移开关闭菜单）
        clicked = await page.evaluate("""() => {
            const items = [...document.querySelectorAll('.ant-dropdown-menu-item')]
                .filter(e => e.offsetParent !== null && /口播稿/.test(e.textContent || ''));
            if (!items.length) return false;
            const el = items[0];
            ['mousedown', 'mouseup', 'click'].forEach(t =>
                el.dispatchEvent(new MouseEvent(t, {bubbles: true, cancelable: true, view: window}))
            );
            return true;
        }""")
        if not clicked:
            return None

        # 等待弹窗正文加载（正文在 .ant-modal-body .script，异步加载）
        text = ""
        for _ in range(8):
            await asyncio.sleep(1)
            text = await page.evaluate("""() => {
                const m = [...document.querySelectorAll('.ant-modal')]
                    .filter(e => e.offsetParent !== null).pop();
                if (!m) return '';
                // 口播稿正文在 .script 节点；兜底用 .ant-modal-body
                const scriptEl = m.querySelector('.script')
                              || m.querySelector('.ant-modal-body');
                return scriptEl ? (scriptEl.innerText || scriptEl.textContent || '').trim() : '';
            }""")
            if text and len(text) > 10:
                break

        # 关闭弹窗
        await page.evaluate("""() => {
            const btn = document.querySelector('.ant-modal-close');
            if (btn) btn.click();
        }""")
        await asyncio.sleep(0.5)

        text = (text or "").strip()
        return text if len(text) >= 5 else None


def _run_in_proactor_thread(coro_factory):
    """在独立线程里用 ProactorEventLoop 运行协程。

    Windows 上 Streamlit/Tornado 会把 asyncio 策略设为 SelectorEventLoop，
    它不支持子进程，导致 Playwright 启动浏览器时抛出空消息的 NotImplementedError。
    这里在独立线程里强制使用 ProactorEventLoop 绕开该限制。
    """
    import threading

    result = {}

    def _worker():
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result["value"] = loop.run_until_complete(coro_factory())
        except BaseException as e:  # noqa: BLE001
            result["error"] = e
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    t = threading.Thread(target=_worker)
    t.start()
    t.join()

    if "error" in result:
        raise result["error"]
    return result.get("value")


def search_and_get_scripts(product_name: str, count: int = 3, country: str = "", headless: bool = False) -> list[str]:
    """同步接口"""
    async def _run():
        scraper = KalodataScraper(headless=headless)
        try:
            logged_in = await scraper.ensure_logged_in()
            if not logged_in:
                # 浏览器留给用户手动登录，等60秒
                await asyncio.sleep(60)
                logged_in = await scraper._check_logged_in()
                if not logged_in:
                    raise RuntimeError("Kalodata未登录，请在弹出的浏览器中登录后重试")
            return await scraper.get_script_from_top_videos(product_name, count, country)
        finally:
            await scraper.close()

    return _run_in_proactor_thread(_run)


def open_kalodata_for_login(timeout_seconds: int = 300):
    """打开独立 Chrome 窗口登录 Kalodata，登录态保存到独立配置目录，下次复用。"""
    async def _run():
        scraper = KalodataScraper(headless=False)
        try:
            await scraper._ensure_browser()
            await scraper._goto("https://www.kalodata.com/product")
            await asyncio.sleep(3)
            if await scraper._check_logged_in():
                print("已登录")
                return True
            print(f"请在弹出的 Chrome 窗口中登录，{timeout_seconds}秒内完成...")
            for _ in range(timeout_seconds):
                if await scraper._check_logged_in():
                    print("登录成功，已保存")
                    return True
                await asyncio.sleep(1)
            return False
        finally:
            await scraper.close()

    return _run_in_proactor_thread(_run)
