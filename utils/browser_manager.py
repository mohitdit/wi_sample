import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from playwright.async_api import async_playwright

async def get_browser():
    playwright = await async_playwright().start()

    context = await playwright.chromium.launch_persistent_context(
        user_data_dir="ny_chrome_profile",
        headless=False,
        viewport=None,
        args=[
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars"
        ]
    )

    page = context.pages[0] if context.pages else await context.new_page()
    return playwright, context, page



    