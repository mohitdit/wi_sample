# utils/captcha_solver.py
import asyncio
import tempfile
import os
import json
#import deathbycaptcha

from utils.logger import log

# 🚨 Set your real credentials
DBC_USERNAME = "hr@dharani.co.in" 
DBC_PASSWORD = "Dh@r@ni@gnt99!"


# ---------------- Image captcha (if ever needed) ----------------

async def solve_captcha(image_bytes: bytes) -> str | None:
    """
    Solve a classic image CAPTCHA via DeathByCaptcha.
    """
    temp_filename = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
            f.write(image_bytes)
            temp_filename = f.name

        log.info(f"📤 Sending image CAPTCHA to DeathByCaptcha ({len(image_bytes)} bytes)")
        client = deathbycaptcha.HttpClient(DBC_USERNAME, DBC_PASSWORD)

        captcha = client.decode(temp_filename, 60)

        if captcha and "text" in captcha and captcha["text"]:
            solved = captcha["text"]
            log.info(f"🤖 DBC image solved: {solved} (ID: {captcha['captcha']})")
            return solved

        log.error("❌ DBC returned empty text for image CAPTCHA.")
        return None

    except deathbycaptcha.AccessDeniedException:
        log.error("❌ DBC Access Denied: check username/password or balance.")
        return None
    except Exception as e:
        log.error(f"❌ DBC Error (image): {e}")
        return None
    finally:
        if temp_filename and os.path.exists(temp_filename):
            os.remove(temp_filename)


# ---------------- Geetest puzzle captcha (main) ----------------

async def solve_puzzle_captcha(gt: str, challenge: str, pageurl: str) -> dict | None:
    """
    Solve Geetest v3 puzzle using DeathByCaptcha Geetest API.

    DBC returns tokens in captcha["text"], which is JSON containing:
      - challenge
      - validate
      - seccode

    This is NOT visible text from the puzzle image; it is the server-side
    token set required to pass the CAPTCHA. [web:11]
    """
    if DBC_USERNAME == "hr@dharani.co.in" or DBC_PASSWORD == "Dh@r@ni@gnt99!":
        log.error("❌ DBC credentials are placeholders.")
        return None

    client = deathbycaptcha.HttpClient(DBC_USERNAME, DBC_PASSWORD)

    geetest_payload = {
        'proxy': 'http://hr@dharani.co.in:Dh@r@ni@gnt99!@127.0.0.1:1234',
        'proxytype': 'HTTP',
        'googlekey': '5b7abc991b26fda8f33bc23e40a8560b9a0a52c4',
        'pageurl': pageurl,
        'action': "example/action",
        'min_score': 0.3}
    
    
    # {
    #     "gt": gt,
    #     "challenge": challenge,
    #     "pageurl": pageurl,
    #     # Optional: uncomment and configure if DBC requires proxy
    #     # "proxy": "http://user:password@127.0.0.1:1234",
    #     # "proxytype": "HTTP",
    # }
    geetest_json = json.dumps(geetest_payload)

    log.info(f"📤 Sending Geetest to DBC (gt={gt[:8]}..., challenge={challenge[:8]}...)")

    try:
        # Geetest v3 uses type=8 and geetest_params. [web:11]
        captcha = client.decode(type=8, geetest_params=geetest_json, timeout=120)

        if not captcha or "text" not in captcha or not captcha["text"]:
            log.error("❌ DBC returned empty text for Geetest.")
            return None

        solution_text = captcha["text"]

        # Some client versions already return dict; others return JSON string. [web:11]
        if isinstance(solution_text, dict):
            solved_data = solution_text
        else:
            solved_data = json.loads(solution_text)

        if all(k in solved_data for k in ("challenge", "validate", "seccode")):
            log.info(
                f"🤖 DBC Geetest solved: validate={str(solved_data['validate'])[:10]}... "
                f"(ID: {captcha.get('captcha')})"
            )
            return solved_data

        log.error("❌ DBC Geetest solution missing required keys (challenge/validate/seccode).")
        return None

    except deathbycaptcha.AccessDeniedException:
        log.error("❌ DBC Access Denied: check credentials/balance.")
        return None
    except Exception as e:
        log.error(f"❌ DBC Error (Geetest): {e}")
        return None