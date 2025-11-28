import asyncio
import os
import json
from datetime import datetime
from scrapers.wisconsin_scraper import WisconsinScraper
from utils.logger import log
from scrapers.html_to_json import parse_html_file_to_json
# ----------------------------------------
# CONFIG
# ----------------------------------------
JOB_CONFIG = {
    "InitialURL": "https://wcca.wicourts.gov",
    "stateName": "WISCONSIN",
    "stateAbbreviation": "WI",
    "urlFormat": "https://wcca.wicourts.gov/caseDetail.html?caseNo={caseNo}&countyNo={CountyID}&index=0&isAdvanced=true&mode=details",
    "countyNo": 6,
    "countyName": "Buffalo County",
    "docketNumber": "001544",
    "docketType": "TR",
    "docketYear": 2025,
    "IsDownloadRequired": "true",
    "docketUpdateDateTime": "2025-11-11T10:10:00Z"
}

OUTPUT_DIR = "data"

UNAVAILABLE_TITLE = "Your request could not be processed."
UNAVAILABLE_SNIPPET_1 = "Your request could not be processed."
UNAVAILABLE_SNIPPET_2 = "That case does not exist or you are not allowed to see it."

# ----------------------------------------
# HELPERS
# ----------------------------------------
def save_html_file(html_content: str, docket: str, county_name: str) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{docket}{county_name.replace(' ', '')}_{timestamp}.html"
    file_path = os.path.join(OUTPUT_DIR, file_name)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return file_path

def save_json_file(obj: dict, docket: str, county_name: str) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{docket}{county_name.replace(' ', '')}_{timestamp}.json"
    file_path = os.path.join(OUTPUT_DIR, file_name)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    return file_path

def html_indicates_unavailable(html: str) -> bool:
    if not html:
        return True
    lower = html.lower()
    if UNAVAILABLE_TITLE.lower() in lower:
        return True
    return (UNAVAILABLE_SNIPPET_1.lower() in lower) and (UNAVAILABLE_SNIPPET_2.lower() in lower)

# ----------------------------------------
# MAIN LOOP
# ----------------------------------------
async def main():
    start_number = int(JOB_CONFIG["docketNumber"])
    max_attempts = 100  # Optional safety limit

    for i in range(max_attempts):
        docket_number = str(start_number + i).zfill(len(JOB_CONFIG["docketNumber"]))
        JOB_CONFIG["docketNumber"] = docket_number

        case_no = f"{JOB_CONFIG['docketYear']}{JOB_CONFIG['docketType']}{docket_number}"
        final_url = JOB_CONFIG["urlFormat"].format(
            caseNo=case_no,
            CountyID=JOB_CONFIG["countyNo"]
        )

        log.info(f"Scraping docket: {case_no} -> {final_url}")

        scraper = WisconsinScraper(config=JOB_CONFIG)
        results = await scraper.run_scraper()

        if results is None:
            log.error(f"Case {case_no} unavailable.")
            break

        if html_indicates_unavailable(results.get("html")):
            log.warning(f"Case {case_no} indicates unavailable, stopping loop.")
            break

        # Save HTML and JSON
        html_path = save_html_file(results.get("html", ""), docket_number, JOB_CONFIG["countyName"])
        
        log.info(f"Saved HTML: {html_path}")
                # parse saved html and produce structured json
        json_obj = parse_html_file_to_json(html_path, JOB_CONFIG)
        json_path = save_json_file(json_obj, docket_number, JOB_CONFIG["countyName"]); log.info(f"Saved JSON: {json_path}")

        

if __name__ == "__main__":
    asyncio.run(main())