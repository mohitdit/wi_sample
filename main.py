import asyncio
import os
import json
from datetime import datetime
from scrapers.wisconsin_scraper import WisconsinScraper
from utils.logger import log
from scrapers.html_to_json import parse_html_file_to_json
from case_grouper import run_grouping
from vpn.vpnbot import SurfsharkManager
import time
from api.api import ApiClient
# ----------------------------------------
# VPN MANAGEMENT GLOBALS
# ----------------------------------------
# vpn_manager = None
# last_vpn_reconnect_time = None

def initialize_vpn():
    """Initialize VPN manager and connect"""
    global vpn_manager, last_vpn_reconnect_time
    vpn_manager = SurfsharkManager()
    log.info("= Initializing VPN connection...")
    vpn_manager.reconnect()
    last_vpn_reconnect_time = time.time()
    log.info(f"  VPN connected at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# def should_reconnect_vpn():
#     """Check if VPN should reconnect based on time interval"""
#     global last_vpn_reconnect_time
    
#     if last_vpn_reconnect_time is None:
#         return True
    
#     interval_minutes = vpn_manager.get_reconnect_interval_minutes()
#     elapsed_seconds = time.time() - last_vpn_reconnect_time
#     elapsed_minutes = elapsed_seconds / 60
    
#     if elapsed_minutes >= interval_minutes:
#         log.info(f"� VPN reconnection needed: {elapsed_minutes:.1f} minutes elapsed (limit: {interval_minutes} minutes)")
#         return True
    
#     return False

# def reconnect_vpn_if_needed():
#     """Reconnect VPN and update timestamp"""
#     global last_vpn_reconnect_time
    
    log.info("\n" + "="*60)
    log.info("=  VPN RECONNECTION IN PROGRESS")
    log.info("="*60)
    log.info("�   All operations paused during VPN reconnection...")
    
#     vpn_manager.reconnect()
#     last_vpn_reconnect_time = time.time()
    
    log.info(f"  VPN reconnected at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("�   Operations resumed")
    log.info("="*60 + "\n")
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

UNAVAILABLE_TITLE = "Your request could not be processed."
UNAVAILABLE_SNIPPET_1 = "Your request could not be processed."
UNAVAILABLE_SNIPPET_2 = "That case does not exist or you are not allowed to see it."

# ----------------------------------------
# HELPERS
# ----------------------------------------
def get_output_directories(date_str: str, state: str, county: str, case_type: str):
    """
    Create hierarchical directory structure: date/state/county/case_type/
    Returns paths for html, json, and grouped data
    """
    base_dir = os.path.join("data", date_str, state, county, case_type)
    
    html_dir = os.path.join(base_dir, "htmldata")
    json_dir = os.path.join(base_dir, "jsonconverteddata")
    grouped_dir = os.path.join(base_dir, "groupeddata")
    
    os.makedirs(html_dir, exist_ok=True)
    os.makedirs(json_dir, exist_ok=True)
    os.makedirs(grouped_dir, exist_ok=True)
    
    return html_dir, json_dir, grouped_dir

def save_html_file(html_content: str, state_abbr: str, county_id: str, docket_type: str, docket_year: str, docket_number: str, html_dir: str) -> str:
    file_name = f"{state_abbr}_{county_id}_{docket_year}_{docket_type}_{docket_number}.html"
    file_path = os.path.join(html_dir, file_name)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return file_path

def save_json_file(obj: dict, state_abbr: str, county_id: str, docket_type: str, docket_year: str, docket_number: str, json_dir: str) -> str:
    file_name = f"{state_abbr}_{county_id}_{docket_year}_{docket_type}_{docket_number}.json"
    file_path = os.path.join(json_dir, file_name)
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
    # Initialize VPN once at startup
    initialize_vpn()
    
    while True:
        api_client = ApiClient()

        try:
            api_response = api_client.post("/WI_Downloader_Job_SQS_GET", {})
            log.info(f"API call successful. Response: {api_response}")
            print()

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

        # Get today's date for directory structure
        today_date = datetime.now().strftime("%d-%m-%Y")
        
        # Get output directories based on hierarchy
        html_dir, json_dir, grouped_dir = get_output_directories(
            today_date,
            JOB_CONFIG["stateName"],
            JOB_CONFIG["countyName"].replace(" ", "_"),
            JOB_CONFIG["docketType"]
        )

        start_number = int(JOB_CONFIG["docketNumber"]) + 1
        max_attempts = 100
        last_successful_docket = None
        initial_docket_number = JOB_CONFIG["docketNumber"]
        scraper_error_occurred = False

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

            # ❌ CASE 1 — SCRAPER FAILURE
            if results is None:
                log.error(f"❌ Scraper failed for case {case_no}.")
                scraper_error_occurred = True
                break

            # ❗ CASE 2 — NO RECORD FOUND
            if html_indicates_unavailable(results.get("html")):
                log.warning(f"⚠ Case {case_no} indicates 'no record found'. Stopping loop.")
                break

            # ✅ SUCCESS - Save HTML and JSON
            last_successful_docket = docket_number
            
            html_path = save_html_file(
                results.get("html", ""), 
                JOB_CONFIG["stateAbbreviation"],
                str(JOB_CONFIG["countyNo"]),
                str(JOB_CONFIG["docketYear"]),
                str(JOB_CONFIG["docketType"]),
                docket_number,
                html_dir
            )
            log.info(f"Saved HTML: {html_path}")
            
            json_obj = parse_html_file_to_json(html_path, JOB_CONFIG)
            json_path = save_json_file(
                json_obj, 
                JOB_CONFIG["stateAbbreviation"],
                str(JOB_CONFIG["countyNo"]),
                str(JOB_CONFIG["docketYear"]),
                str(JOB_CONFIG["docketType"]),
                docket_number,
                json_dir
            )
            log.info(f"Saved JSON: {json_path}")

        # ----------------------------------------
        # GROUP ALL CASES AFTER SCRAPING
        # ----------------------------------------
        log.info("\n" + "="*60)
        log.info("Scraping complete! Starting case grouping...")
        log.info("="*60)

        run_grouping(data_dir=json_dir, output_dir=grouped_dir)

        # ----------------------------------------
        # DETERMINE API CALLS BASED ON OUTCOME
        # ----------------------------------------
        has_data = last_successful_docket is not None
        
        if scraper_error_occurred:
            # Error occurred - use ADD API with previous docket
            log.info("\n🚨 Error occurred - Calling ADD API")
            prev_docket = str(int(JOB_CONFIG["docketNumber"]) - 1).zfill(len(initial_docket_number))
            
            add_payload = {
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
                add_response = api_client.post("/WI_Downloader_Job_To_SQS_ADD", add_payload)
                log.info(f"✅ ADD API called: {add_response}")
            except Exception as e:
                log.error(f"❌ ADD API failed: {e}")
                
        else:
            # No error - use UPDATE API if we have new data
            if has_data and last_successful_docket > initial_docket_number:
                log.info("\n✅ Success - Calling UPDATE API")
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
                    log.info(f"✅ UPDATE API called: {update_response}")
                except Exception as e:
                    log.error(f"❌ UPDATE API failed: {e}")
            else:
                log.info("ℹ️ No new data to update")

        # ----------------------------------------
        # SEND GROUPED DATA TO INSERT API (SINGLE CALL)
        # ----------------------------------------
        if has_data:
            log.info("\n📤 Preparing grouped data for INSERT API...")
            grouped_files = [f for f in os.listdir(grouped_dir) if f.endswith('.json')]
            
            if grouped_files:
                # Load ALL grouped files into a single array
                all_grouped_data = []
                for filename in grouped_files:
                    filepath = os.path.join(grouped_dir, filename)
                    with open(filepath, 'r', encoding='utf-8') as f:
                        grouped_data = json.load(f)
                        all_grouped_data.append(grouped_data)
                
                # Single API call with all data
                try:
                    insert_response = api_client.post("/WI_DataDockets_INSERT", all_grouped_data)
                    log.info(f"✅ INSERT API called with {len(all_grouped_data)} records: {insert_response}")
                except Exception as e:
                    log.error(f"❌ INSERT API failed: {e}")
            else:
                log.info("ℹ️ No grouped files to send")
        else:
            log.info("ℹ️ No data scraped - Skipping INSERT API")
        
        # VPN reconnection logic
        needs_vpn_reconnect = scraper_error_occurred or should_reconnect_vpn()
        
        if needs_vpn_reconnect:
            reconnect_vpn_if_needed()
        else:
            elapsed = (time.time() - last_vpn_reconnect_time) / 60
            log.info(f"ℹ️ VPN reconnection not needed (elapsed: {elapsed:.1f} minutes)")
        
        log.info("🔄 Fetching next job from queue...")
        await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())