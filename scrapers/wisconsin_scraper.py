import os
import json
from playwright.async_api import TimeoutError as PlaywrightTimeoutError


from scrapers.base_scraper import BaseScraper
from utils.captcha_solver import solve_puzzle_captcha
from utils.browser_manager import get_stealth_browser
from utils.logger import log

COOKIE_FILE = "wcca_cookies.json"


class WisconsinScraper(BaseScraper):

    async def get_geetest_params(self, page):
        """
        Extract dynamic gt and challenge parameters from the page.
        Adjust selectors if WCCA uses different names/ids.
        """
        log.info("🔎 Searching for Geetest gt/challenge parameters...")

        GT_SELECTOR = "input[name='gt']"
        CHALLENGE_SELECTOR = "input[name='challenge']"

        try:
            gt_el = await page.wait_for_selector(GT_SELECTOR, timeout=20000)
            ch_el = await page.wait_for_selector(CHALLENGE_SELECTOR, timeout=20000)

            gt = await gt_el.get_attribute("value")
            challenge = await ch_el.get_attribute("value")

            if gt and challenge:
                log.info(f"✅ gt={gt[:8]}..., challenge={challenge[:8]}...")
                return gt, challenge

        except PlaywrightTimeoutError:
            log.error("❌ Timeout while waiting for gt/challenge fields.")
        except Exception as e:
            log.error(f"❌ Error extracting Geetest params: {e}")

        return None, None   # note: tuple, not bare None

    async def detect_and_solve_captcha(self, page):
        """
        Returns:
          True      -> CAPTCHA detected and solved automatically.
          False     -> CAPTCHA not present.
          "manual"  -> DBC failed; let user solve manually.
          None      -> Fatal error; caller should stop and not continue.
        """
        log.info("🔍 Checking for CAPTCHA screen...")

        # Detect 'Please complete the CAPTCHA'
        try:
            await page.wait_for_selector("text=Please complete the CAPTCHA", timeout=4000)
            log.warning("⚠ CAPTCHA page detected.")
        except Exception:
            log.info("✅ No CAPTCHA text detected.")
            return False

        # Click "Click here" to reveal puzzle
        try:
            await page.click("text=Click here", timeout=10000)
            log.info("🖱 Clicked 'Click here' to reveal CAPTCHA.")
            await page.wait_for_timeout(5000)
        except Exception as e:
            log.error(f"❌ Failed to click 'Click here': {e}")
            return None

        # Extract Geetest params
        gt, challenge = await self.get_geetest_params(page)
        if not gt or not challenge:
            log.error("❌ Could not find gt/challenge; cannot solve CAPTCHA automatically.")
            # Allow manual solve instead of killing the run
            return "manual"

        current_url = page.url
        solved_data = await solve_puzzle_captcha(gt, challenge, current_url)
        if not solved_data:
            log.error("❌ DBC did not return a valid Geetest solution; switching to manual mode.")
            return "manual"

        # Submit tokens back to page (auto-solve path).
        VALIDATE_SELECTOR = "input[name='geetest_validate']"
        SECCODE_SELECTOR = "input[name='geetest_seccode']"
        CHALLENGE_SELECTOR_SUBMIT = "input[name='geetest_challenge']"

        try:
            await page.fill(CHALLENGE_SELECTOR_SUBMIT, solved_data["challenge"])
            await page.fill(VALIDATE_SELECTOR, solved_data["validate"])
            await page.fill(SECCODE_SELECTOR, solved_data["seccode"])
            log.info("✅ Filled Geetest token fields.")

            # Submit the main form (adjust selector if different)
            await page.click("button[type=submit]")
            log.info("✅ Submitted CAPTCHA form.")

            # Wait until the CAPTCHA text disappears or Case Summary appears
            try:
                await page.wait_for_function(
                    "() => !document.body.innerText.includes('Please complete the CAPTCHA')",
                    timeout=15000,
                )
                log.info("✅ CAPTCHA message gone; likely solved.")
            except PlaywrightTimeoutError:
                log.warning("⚠ CAPTCHA text still present after timeout; might have failed.")
                # If we got here, auto-solve probably failed; let user do it.
                return "manual"

        except PlaywrightTimeoutError:
            log.error("❌ Timeout while submitting Geetest tokens.")
            return None
        except Exception as e:
            log.error(f"❌ Failed to submit Geetest solution: {e}")
            return None

        return True

    async def run_scraper(self):
        """
        Run the scraper for the current JOB_CONFIG.
        On any *fatal* CAPTCHA error, returns None so the main loop stops
        and does not save HTML for that docket.

        If auto-solve fails but user solves manually, cookies will still
        be saved once Case Summary is loaded and reused for later dockets.
        """
        browser, context, page = await get_stealth_browser(False)

        case_url = self.build_case_url()
        docket = f"{self.config['docketYear']}{self.config['docketType']}{self.config['docketNumber']}"

        log.info(f"--- Starting scrape for {docket} ---")

        # --- STEP 1: LOAD COOKIES ---
        if os.path.exists(COOKIE_FILE):
            try:
                with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                await context.add_cookies(cookies)
                log.info(f"🍪 Loaded {len(cookies)} cookies from session file.")
            except Exception as e:
                log.error(f"Failed loading cookies: {e}")

        # --- STEP 2: NAVIGATE ---
        try:
            await page.goto(case_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log.error(f"Navigation failed: {e}")
            await browser.close()
            return None

        # --- STEP 3: HANDLE CAPTCHA ---
        max_retries = 3
        for attempt in range(max_retries):
            # If already inside, stop trying
            if await page.query_selector("text=Case Summary"):
                log.info("✅ Case Summary already visible; no CAPTCHA.")
                break

            result = await self.detect_and_solve_captcha(page)

            if result is True:
                # Solved automatically
                log.info("⌛ Waiting for page after CAPTCHA auto-solve...")
                await page.wait_for_timeout(3000)

            elif result == "manual":
                # User will solve Geetest manually in the browser.
                log.warning(
                    "🧑‍💻 Manual CAPTCHA mode: solve the puzzle in the browser window. "
                    "Waiting for the CAPTCHA message to disappear or Case Summary to load..."
                )

                try:
                    # Wait until either CAPTCHA text is gone OR Case Summary is visible.
                    await page.wait_for_function(
                        "() => !document.body.innerText.includes('Please complete the CAPTCHA') "
                        "|| document.body.innerText.includes('Case Summary')",
                        timeout=30000  # e.g. up to 5 minutes; adjust as you like
                    )
                    log.info("✅ Manual CAPTCHA solve detected.")
                except PlaywrightTimeoutError:
                    log.error("❌ Manual CAPTCHA not solved within allowed time.")
                    await browser.close()
                    return None

                # Small delay after success, then continue to STEP 4
                await page.wait_for_timeout(2000)
                break


            elif result is False:
                # No CAPTCHA present
                log.info("ℹ No CAPTCHA detected, continuing.")
                break
            else:
                # result is None → fatal error; abort this docket
                log.error("❌ CAPTCHA solving failed fatally; aborting this docket.")
                await browser.close()
                return None

                # --- STEP 4: VERIFY SUCCESS & SAVE COOKIES ---
        try:
            await page.wait_for_selector("text=Case Summary", timeout=15000)
            log.info("✅ Case Summary Loaded.")
            status = "ok"
        except PlaywrightTimeoutError:
            log.error("❌ Could not load Case Summary. CAPTCHA failed or case unavailable.")
            status = "failed"

        # 👉 ALWAYS try to save cookies, even if status == "failed"
        try:
            cookies = await context.cookies()
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
            log.info("💾 Session cookies saved for future use.")
        except Exception as e:
            log.error(f"❌ Failed to save cookies: {e}")

        html = await page.content()
        await context.close()
        await browser.close()

        return None


        # --- STEP 5: RETURN HTML ---
        html = await page.content()

        await context.close()
        await browser.close()

        return {"docket": docket, "html": html, "status": "ok"}