import asyncio
import os
import json
from datetime import datetime
from scrapers.wisconsin_scraper import WisconsinScraper
from utils.logger import log
from scrapers.html_to_json import parse_html_file_to_json
from case_grouper import run_grouping
from api.api import ApiClient

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

HTML_OUTPUT_DIR = "data/htmldata"
JSON_OUTPUT_DIR = "data/jsonconverteddata"
GROUPED_OUTPUT_DIR = "data/groupeddata"

UNAVAILABLE_TITLE = "Your request could not be processed."
UNAVAILABLE_SNIPPET_1 = "Your request could not be processed."
UNAVAILABLE_SNIPPET_2 = "That case does not exist or you are not allowed to see it."

# ----------------------------------------
# HELPERS
# ----------------------------------------
def save_html_file(html_content: str, state_abbr: str, county_id: str, docket_type: str, docket_year: str, docket_number: str) -> str:
    os.makedirs(HTML_OUTPUT_DIR, exist_ok=True)
    file_name = f"{state_abbr}_{county_id}_{docket_year}_{docket_type}_{docket_number}.html"
    file_path = os.path.join(HTML_OUTPUT_DIR, file_name)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return file_path

def save_json_file(obj: dict, state_abbr: str, county_id: str,docket_type: str, docket_year: str, docket_number: str) -> str:
    os.makedirs(JSON_OUTPUT_DIR, exist_ok=True)
    file_name = f"{state_abbr}_{county_id}_{docket_year}_{docket_type}_{docket_number}.json"
    file_path = os.path.join(JSON_OUTPUT_DIR, file_name)
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

    api_client = ApiClient()

    try:
        api_response = api_client.post("/WI_Downloader_Job_SQS_GET", {})
        log.info(f"API call successful. Response: {api_response}")
        print("API Response:", api_response)
        print()  # one line space

        # Extract docket details from API response
        court_details = api_response.get("courtOfficeDetails")
        if not court_details:
            log.error("No docket details received from API.")
            return

        # Create JOB_CONFIG from API response
        JOB_CONFIG = {
            "InitialURL": court_details.get("InitialURL"),
            "stateName": court_details.get("stateName"),
            "stateAbbreviation": court_details.get("stateAbbreviation"),
           "urlFormat": court_details.get("urlFormat")
                    .replace('[','{')
                    .replace(']','}')
                    .replace('{DocketYear}{DocketType}{MaxDocketNumber}', '{caseNo}'),
            "countyNo": court_details.get("countyNo"),
            "countyName": court_details.get("countyName"),
            "docketNumber": court_details.get("docketNumber"),
            "docketType": court_details.get("docketType"),
            "docketYear": court_details.get("docketYear"),
            # Add static fields if needed
            "IsDownloadRequired": "true",
            "docketUpdateDateTime": "2025-11-11T10:10:00Z"
        }

    except Exception as e:
        log.error(f"API call failed: {e}")
        print("API call failed:", e)
        return

    start_number = int(JOB_CONFIG["docketNumber"]) + 1
    max_attempts = 100  # Optional safety limit
    last_successful_docket = None  # Track last successful docket

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

        # if results is None:
        #     log.error(f"Case {case_no} unavailable.")
        #     break

        # if html_indicates_unavailable(results.get("html")):
        #     log.warning(f"Case {case_no} indicates unavailable, stopping loop.")
        #     break
        
               
        # ----------------------------------------------------
        # ❌ CASE 1 — SCRAPER FAILURE
        # ----------------------------------------------------
        if results is None:
            log.error(f"❌ Scraper failed for case {case_no}. Adding next job and stopping.")

            prev_docket = str(int(JOB_CONFIG["docketNumber"]) - 1).zfill(len(JOB_CONFIG["docketNumber"]))

            next_job_payload = {
                "courtOfficeDetails": {
                    "InitialURL": JOB_CONFIG["InitialURL"],
                    "stateName": JOB_CONFIG["stateName"],
                    "stateAbbreviation": JOB_CONFIG["stateAbbreviation"],
                    "urlFormat": court_details.get("urlFormat"),
                    "countyNo": JOB_CONFIG["countyNo"],
                    "countyName": JOB_CONFIG["countyName"],
                    "docketNumber": prev_docket,
                    "docketYear": JOB_CONFIG["docketYear"],
                    "docketType": JOB_CONFIG["docketType"]
                }
            }

            try:
                add_response = api_client.post("/WI_Downloader_Job_To_SQS_ADD", next_job_payload)
                log.info(f"Next job added (failure case): {add_response}")
            except Exception as e:
                log.error(f"Failed to add next job: {e}")

            break

        # ----------------------------------------------------
        # ❗ CASE 2 — SUCCESS BUT NO RECORD FOUND
        # ----------------------------------------------------
        if html_indicates_unavailable(results.get("html")):
            log.warning(f"⚠ Case {case_no} indicates 'no record found'. Calling UPDATE API and stopping.")
            
            if last_successful_docket:
                update_payload = {
                    "stateName": JOB_CONFIG["stateName"],
                    "countyNo": JOB_CONFIG["countyNo"],
                    "countyName": JOB_CONFIG["countyName"],
                    "docketNumber": last_successful_docket,
                    "docketYear": JOB_CONFIG["docketYear"],
                    "docketType": JOB_CONFIG["docketType"]
                }
        
                try:
                    update_response = api_client.post("/WI_County_DocketNumber_UPDATE", update_payload)
                    log.info(f"✅ UPDATE API called with docket {last_successful_docket}: {update_response}")
                except Exception as e:
                    log.error(f"❌ UPDATE API failed: {e}")
            else:
                log.warning("⚠ No successful docket found to update")
            
            break

        last_successful_docket = docket_number

        # Save HTML and JSON
        html_path = save_html_file(
            results.get("html", ""), 
            JOB_CONFIG["stateAbbreviation"],
            str(JOB_CONFIG["countyNo"]),
            str(JOB_CONFIG["docketYear"]),
            str(JOB_CONFIG["docketType"]),
            docket_number
        )
        
        log.info(f"Saved HTML: {html_path}")
        
        # Parse saved html and produce structured json
        json_obj = parse_html_file_to_json(html_path, JOB_CONFIG)
        json_path = save_json_file(
            json_obj, 
            JOB_CONFIG["stateAbbreviation"],
            str(JOB_CONFIG["countyNo"]),
            str(JOB_CONFIG["docketYear"]),
            str(JOB_CONFIG["docketType"]),
            docket_number
        )
        log.info(f"Saved JSON: {json_path}")

    # ----------------------------------------
    # GROUP ALL CASES AFTER SCRAPING IS DONE
    # ----------------------------------------
    log.info("\n" + "="*60)
    log.info("All scraping complete! Starting case grouping...")
    log.info("="*60)

    # Track existing files BEFORE grouping
    existing_grouped_files = set()
    if os.path.exists(GROUPED_OUTPUT_DIR):
        existing_grouped_files = set(os.listdir(GROUPED_OUTPUT_DIR))

    # Run grouping
    run_grouping(data_dir=JSON_OUTPUT_DIR, output_dir=GROUPED_OUTPUT_DIR)

    # Find NEW files AFTER grouping
    current_grouped_files = set(os.listdir(GROUPED_OUTPUT_DIR))
    new_files = current_grouped_files - existing_grouped_files

    # Send each NEW file to INSERT API
    if new_files:
        log.info(f"\n📤 Sending {len(new_files)} new grouped files to INSERT API...")
        for filename in new_files:
            filepath = os.path.join(GROUPED_OUTPUT_DIR, filename)
            with open(filepath, 'r', encoding='utf-8') as f:
                grouped_data = json.load(f)

            try:
                api_payload = [grouped_data]
                insert_response = api_client.post("/WI_DataDockets_INSERT", api_payload)
                log.info(f"✅ INSERT API called for {filename}: {insert_response}")
            except Exception as e:
                log.error(f"❌ INSERT API failed for {filename}: {e}")
    else:
        log.info("ℹ️ No new grouped files created")
    
    log.info("\n" + "="*60)
    log.info("✅ ALL TASKS COMPLETE!")
    log.info("="*60)

if __name__ == "__main__":
    asyncio.run(main())