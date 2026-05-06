"""Shared Playwright helper: one browser, many contexts, stealth JS.

Usage:
    from crawlers.playwright_pool import browser_session
    with browser_session(headless=True) as sess:
        page = sess.new_page()
        page.goto("...", wait_until="domcontentloaded")
        html = page.content()
"""
from contextlib import contextmanager
from config import UA


STEALTH = r"""
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined,
});

Object.defineProperty(navigator, 'plugins', {
    get: () => {
        return [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
        ];
    },
});

Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});

Object.defineProperty(navigator, 'platform', {
    get: () => 'MacIntel',
});

window.chrome = window.chrome || { runtime: {} };

const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
if (originalQuery) {
    window.navigator.permissions.query = (parameters) => (
        parameters && parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
}

try {
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) { return 'Intel Inc.'; }
        if (parameter === 37446) { return 'Intel Iris OpenGL Engine'; }
        return getParameter.call(this, parameter);
    };
} catch (e) {}
"""


class _Session:
    def __init__(self, pw, browser, context):
        self._pw = pw
        self._browser = browser
        self._context = context
        self._closed = False

    def new_page(self):
        page = self._context.new_page()
        try:
            page.set_default_timeout(30000)
        except Exception:
            pass
        return page

    def new_context(self, **kwargs):
        ctx = self._browser.new_context(**kwargs)
        ctx.add_init_script(STEALTH)
        return ctx

    def close(self):
        if self._closed:
            return
        self._closed = True
        for closer in (
            lambda: self._context.close(),
            lambda: self._browser.close(),
            lambda: self._pw.stop(),
        ):
            try:
                closer()
            except Exception as e:
                print(f"[playwright_pool] close err: {e}")


@contextmanager
def browser_session(headless: bool = True, locale: str = "en-US", user_agent: str | None = None):
    from playwright.sync_api import sync_playwright

    ua = user_agent or UA
    pw = sync_playwright().start()
    browser = None
    context = None
    try:
        browser = pw.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=ua,
            locale=locale,
            viewport={"width": 1366, "height": 900},
        )
        context.add_init_script(STEALTH)
        sess = _Session(pw, browser, context)
        try:
            yield sess
        finally:
            sess.close()
    except Exception:
        try:
            if context is not None:
                context.close()
        except Exception:
            pass
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass
        raise
