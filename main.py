import asyncio
import os
import json
from datetime import datetime
from scrapers.wisconsin_scraper import WisconsinScraper
from utils.logger import log
# from vpn.vpnbot import SurfsharkManager
import time
from api.api import ApiClient
from config import DATASET_ID_MAP
import signal
import sys

# ----------------------------------------
# VPN MANAGEMENT GLOBALS
# ----------------------------------------
# vpn_manager = None
# last_vpn_reconnect_time = None

# def initialize_vpn():
#     """Initialize VPN manager and connect"""
#     global vpn_manager, last_vpn_reconnect_time
#     vpn_manager = SurfsharkManager()
#     log.info("= Initializing VPN connection...")
#     vpn_manager.reconnect()
#     last_vpn_reconnect_time = time.time()
#     log.info(f"  VPN connected at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# def should_reconnect_vpn():
#     """Check if VPN should reconnect based on time interval"""
#     global last_vpn_reconnect_time
    
#     if last_vpn_reconnect_time is None:
#         return True
    
#     interval_minutes = vpn_manager.get_reconnect_interval_minutes()
#     elapsed_seconds = time.time() - last_vpn_reconnect_time
#     elapsed_minutes = elapsed_seconds / 60
    
#     if elapsed_minutes >= interval_minutes:
#         log.info(f"ï¿½ VPN reconnection needed: {elapsed_minutes:.1f} minutes elapsed (limit: {interval_minutes} minutes)")
#         return True
    
#     return False

# def reconnect_vpn_if_needed():
#     """Reconnect VPN and update timestamp"""
#     global last_vpn_reconnect_time
    
#     log.info("\n" + "="*60)
#     log.info("=  VPN RECONNECTION IN PROGRESS")
#     log.info("="*60)
#     log.info("ï¿½   All operations paused during VPN reconnection...")
    
#     vpn_manager.reconnect()
#     last_vpn_reconnect_time = time.time()
    
#     log.info(f"  VPN reconnected at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
#     log.info("ï¿½   Operations resumed")
#     log.info("="*60 + "\n")

def build_dataset_id(state_code: str, case_type: str) -> str:
    """
    Build dataset ID in format: {stateCode}-{mapValue}-{caseType}
    Example: WI-901-TR
    """
    map_value = DATASET_ID_MAP.get(case_type, "000")
    return f"{state_code}-{map_value}-{case_type}"

# ----------------------------------------
# GLOBAL STATE FOR GRACEFUL SHUTDOWN
# ----------------------------------------
shutdown_requested = False
current_job_state = {
    "api_client": None,
    "record_id": None,
    "initial_url": None,
    "url_format": None,
    "county_no": None,
    "county_name": None,
    "docket_year": None,
    "docket_type": None,
    "last_successful_docket": None
}

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    global shutdown_requested
    log.info("\n" + "="*60)
    log.info("🛑 SHUTDOWN SIGNAL RECEIVED - Cleaning up...")
    log.info("="*60)
    shutdown_requested = True
    
    # Call ADD API with last successful docket
    if current_job_state["last_successful_docket"] and current_job_state["api_client"]:
        log.info("📤 Calling ADD API to re-queue job from last successful docket...")
        try:
            add_payload = {
                "courtOfficeDetails": {
                    "InitialURL": current_job_state["initial_url"],
                    "stateName": "WISCONSIN",
                    "stateAbbreviation": "WI",
                    "urlFormat": current_job_state["url_format"],
                    "countyNo": current_job_state["county_no"],
                    "countyName": current_job_state["county_name"],
                    "docketNumber": current_job_state["last_successful_docket"],
                    "docketYear": current_job_state["docket_year"],
                    "docketType": current_job_state["docket_type"]
                }
            }
            add_response = current_job_state["api_client"].post("/WI_Downloader_Job_To_SQS_ADD", add_payload)
            log.info(f"✅ ADD API called successfully: {add_response}")
        except Exception as e:
            log.error(f"❌ Failed to call ADD API during shutdown: {e}")
    
    log.info("="*60)
    log.info("✅ Cleanup complete. Exiting...")
    log.info("="*60)
    sys.exit(0)

# Register signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ----------------------------------------
# CONFIG
# ----------------------------------------
# JOB_CONFIG = {
#     "InitialURL": "https://wcca.wicourts.gov",
#     "stateName": "WISCONSIN",
#     "stateAbbreviation": "WI",
#     "urlFormat": "https://wcca.wicourts.gov/caseDetail.html?caseNo={caseNo}&countyNo={CountyID}&index=0&isAdvanced=true&mode=details",
#     "countyNo": 6,
#     "countyName": "Buffalo County",
#     "docketNumber": "001544",
#     "docketType": "TR",
#     "docketYear": 2025,
#     "IsDownloadRequired": "true",
#     "docketUpdateDateTime": "2025-11-11T10:10:00Z"
# }

UNAVAILABLE_TITLE = "Your request could not be processed."
UNAVAILABLE_SNIPPET_1 = "Your request could not be processed."
UNAVAILABLE_SNIPPET_2 = "That case does not exist or you are not allowed to see it."

# ----------------------------------------
# HELPERS
# ----------------------------------------
def get_output_directory(date_str: str, state: str, county: str, case_type: str):
    """
    Create hierarchical directory structure: date/state/county/case_type/htmldata
    Returns path for html storage
    """
    base_dir = os.path.join("data", date_str, state, county, case_type)
    html_dir = os.path.join(base_dir, "htmldata")
    os.makedirs(html_dir, exist_ok=True)
    return html_dir

#----------------------------------
# Commented out HTML saving function
#----------------------------------
# def save_html_file(html_content: str, state_abbr: str, county_id: str, docket_type: str, docket_year: str, docket_number: str, html_dir: str) -> str:
#     file_name = f"{state_abbr}_{county_id}_{docket_year}_{docket_type}_{docket_number}.html"
#     file_path = os.path.join(html_dir, file_name)
#     with open(file_path, "w", encoding="utf-8") as f:
#         f.write(html_content)
#     return file_path

def html_indicates_unavailable(html: str) -> bool:
    if not html:
        return True
    lower = html.lower()
    if UNAVAILABLE_TITLE.lower() in lower:
        return True
    return (UNAVAILABLE_SNIPPET_1.lower() in lower) and (UNAVAILABLE_SNIPPET_2.lower() in lower)

async def initialize_cookies_if_needed():
    """Check if cookies exist, if not run the cookie saver"""
    cookie_file = "wcca_cookies.json"
    
    if not os.path.exists(cookie_file):
        log.info("="*60)
        log.info("🍪 No cookies found - Running cookie initialization...")
        log.info("="*60)
        
        # Import and run save_cookies
        from save_cookies import save_wcca_cookies
        await save_wcca_cookies()
        
        log.info("✅ Cookies saved successfully")
        log.info("="*60 + "\n")
    else:
        log.info("✅ Existing cookies found - skipping initialization\n")

# ----------------------------------------
# MAIN LOOP
# ----------------------------------------
async def main():
    global shutdown_requested, current_job_state
    
    # Initialize cookies on the first run
    await initialize_cookies_if_needed()

    # Initialize VPN once at startup
    # initialize_vpn()
    
    while not shutdown_requested:
        api_client = ApiClient()
        current_job_state["api_client"] = api_client

        # ----------------------------------------
        # STEP 1: GET JOB FROM QUEUE
        # ----------------------------------------
        try:
            api_response = api_client.post("/WI_Downloader_Job_SQS_GET", {})
            log.info(f"✅ GET API call successful. Response: {api_response}")
            print()

            court_details = api_response.get("courtOfficeDetails")
            if not court_details:
                log.error("🛑 No more jobs in queue - Stopping loop")
                break

            # Extract job details
            record_id = court_details.get("recordId")
            initial_url = court_details.get("InitialURL")
            url_format = court_details.get("urlFormat")
            consecutive_skip_count = court_details.get("consecutiveSkipCount", 50)
            county_no = court_details.get("countyNo")
            county_name = court_details.get("countyName")
            docket_year = court_details.get("docketYear")
            docket_number = court_details.get("docketNumber")
            docket_type = court_details.get("docketType")

            # Update global state
            current_job_state.update({
                "record_id": record_id,
                "initial_url": initial_url,
                "url_format": url_format,
                "county_no": county_no,
                "county_name": county_name,
                "docket_year": docket_year,
                "docket_type": docket_type,
                "last_successful_docket": str(docket_number).zfill(6)
            })

            log.info(f"📋 Job Details: County={county_name}, Year={docket_year}, Type={docket_type}, StartDocket={docket_number}, SkipCount={consecutive_skip_count}")

        except Exception as e:
            log.error(f"❌ GET API call failed: {e}")
            print("API call failed:", e)
            return

        # ----------------------------------------
        # STEP 2: PREPARE SCRAPING CONFIGURATION
        # ----------------------------------------
        JOB_CONFIG = {
            "InitialURL": initial_url,
            "stateName": "WISCONSIN",
            "stateAbbreviation": "WI",
            "urlFormat": url_format.replace('{year}', '{docketYear}').replace('{seqNo}', '{docketNumber}'),
            "countyNo": county_no,
            "countyName": county_name,
            "docketNumber": str(docket_number).zfill(6),
            "docketType": docket_type,
            "docketYear": docket_year
        }

        # Get dataset ID in format: WI-901-TR
        dataset_id = build_dataset_id("WI", docket_type)
        
        # Get output directory (keeping for potential future use)
        today_date = datetime.now().strftime("%d-%m-%Y")
        html_dir = get_output_directory(
            today_date,
            JOB_CONFIG["stateName"],
            JOB_CONFIG["countyName"].replace(" ", "_"),
            JOB_CONFIG["docketType"]
        )

        # ----------------------------------------
        # STEP 3: SCRAPING LOOP WITH SKIP COUNT LOGIC
        # ----------------------------------------
        start_number = int(docket_number) + 1
        last_successful_docket = str(docket_number).zfill(6)  # For UPDATE API
        last_inserted_docket = str(docket_number).zfill(6)    # Track last SUCCESSFULLY INSERTED docket
        scraper_error_occurred = False
        captcha_error_occurred = False
        consecutive_failures = 0
        total_scraped = 0
        network_error_count = 0
        MAX_NETWORK_ERRORS = 3

        i = 0
        while not shutdown_requested:
            current_docket_number = str(start_number + i).zfill(6)
            JOB_CONFIG["docketNumber"] = current_docket_number

            # Build case number and URL
            case_no = f"{JOB_CONFIG['docketYear']}{JOB_CONFIG['docketType']}{current_docket_number}"
            
            # Replace placeholders in URL format
            final_url = url_format.replace('{year}', str(docket_year)).replace('{seqNo}', current_docket_number)
            
            log.info(f"🔍 Scraping docket: {case_no} -> {final_url}")

            # ----------------------------------------
            # SCRAPE THE PAGE
            # ----------------------------------------
            JOB_CONFIG["case_url"] = final_url
            scraper = WisconsinScraper(config=JOB_CONFIG)
            results = await scraper.run_scraper()

            # ❌ CASE 1 – SCRAPER FAILURE (Critical Error)
            if results is None:
                log.error(f"❌ Scraper failed critically for case {case_no}.")
                network_error_count += 1
                
                # Check if this is a persistent network issue
                if network_error_count >= MAX_NETWORK_ERRORS:
                    log.error(f"🚨 Multiple network errors ({network_error_count}). Pausing before retry...")
                    scraper_error_occurred = True
                    break
                else:
                    # Wait and retry same docket
                    log.warning(f"⚠ Network error {network_error_count}/{MAX_NETWORK_ERRORS}. Waiting 30 seconds before retry...")
                    await asyncio.sleep(30)
                    continue  # Retry the same docket (don't increment i)

            # Reset network error counter on success
            network_error_count = 0

            # ISSUE 2 FIX: Check for CAPTCHA failure or empty HTML
            html_content = results.get("html", "")
            if not html_content or len(html_content.strip()) < 100:  # Too short = likely failed
                log.error(f"❌ Empty or invalid HTML received for case {case_no} (likely CAPTCHA failure)")
                captcha_error_occurred = True
                break

            # Check if CAPTCHA page is still present in HTML
            if "Please complete the CAPTCHA" in html_content:
                log.error(f"❌ CAPTCHA still present in HTML for case {case_no}")
                captcha_error_occurred = True
                break

            # ⚠ CASE 2 – NO RECORD FOUND
            if html_indicates_unavailable(html_content):
                log.warning(f"⚠ Case {case_no} indicates 'no record found'.")
                consecutive_failures += 1
                
                # Check if we've hit the skip count limit
                if consecutive_failures >= consecutive_skip_count:
                    log.info(f"🛑 Reached consecutive skip count limit ({consecutive_skip_count}). Stopping.")
                    break
                else:
                    log.info(f"⏭ Skipping to next docket. Failures: {consecutive_failures}/{consecutive_skip_count}")
                    i += 1
                    continue

            # ✅ SUCCESS - Send to INSERT API (NO HTML SAVING)
            consecutive_failures = 0  # Reset failure counter
            # last_successful_docket = current_docket_number  # Update last successful
            # total_scraped += 1
            
            # # Save HTML file
            # html_path = save_html_file(
            #     results.get("html", ""), 
            #     JOB_CONFIG["stateAbbreviation"],
            #     str(JOB_CONFIG["countyNo"]),
            #     str(JOB_CONFIG["docketYear"]),
            #     str(JOB_CONFIG["docketType"]),
            #     current_docket_number,
            #     html_dir
            # )
            # log.info(f"💾 Saved HTML: {html_path}")
            
            # ----------------------------------------
            # SEND TO INSERT API IMMEDIATELY
            # ----------------------------------------
            insert_payload = {
                "agencyID": str(county_no).zfill(4),  # Pad to 4 digits (e.g., "0004")
                "agencyName": county_name,
                "datasetID": dataset_id,  # Format: WI-901-TR
                "year": str(docket_year),
                "seqNo": current_docket_number,
                "htmlContent": html_content,
                "docketType": docket_type,
                "emailID": ""
            }
            
            try:
                insert_response = api_client.post("/WI_CounterBasedEntry_INSERT", insert_payload)
                log.info(f"📤 INSERT API called for {case_no}: {insert_response}")
                
                # ONLY update tracking variables if INSERT was successful
                last_successful_docket = current_docket_number
                last_inserted_docket = current_docket_number  # Track last INSERTED
                current_job_state["last_successful_docket"] = current_docket_number
                total_scraped += 1
                
            except Exception as e:
                log.error(f"❌ INSERT API failed for {case_no}: {e}")
                # If INSERT fails, treat it as an error and break
                scraper_error_occurred = True
                break
            
            # ISSUE 1 FIX: Commented out HTML saving
            # html_path = save_html_file(
            #     html_content, 
            #     JOB_CONFIG["stateAbbreviation"],
            #     str(JOB_CONFIG["countyNo"]),
            #     str(JOB_CONFIG["docketYear"]),
            #     str(JOB_CONFIG["docketType"]),
            #     current_docket_number,
            #     html_dir
            # )
            # log.info(f"💾 Saved HTML: {html_path}")
            
            i += 1

        # ----------------------------------------
        # STEP 4: DETERMINE FINAL API CALL (UPDATE OR ADD)
        # ----------------------------------------
        log.info("\n" + "="*60)
        log.info(f"📊 Scraping Summary: Total Scraped = {total_scraped}, Last Successful = {last_successful_docket}")
        log.info("="*60)
        
        # ISSUE 2 FIX: Handle CAPTCHA and scraper errors by calling ADD API
        if scraper_error_occurred or captcha_error_occurred:
            # ❌ ERROR OCCURRED - USE ADD API with last SUCCESSFULLY INSERTED docket
            error_type = "CAPTCHA" if captcha_error_occurred else "Network"
            log.info(f"\n🚨 {error_type} error occurred - Calling ADD API to re-queue job")
            log.info(f"   Re-queuing from last successfully inserted: {last_inserted_docket}")
            
            add_payload = {
                "courtOfficeDetails": {
                    "InitialURL": initial_url,
                    "stateName": "WISCONSIN",
                    "stateAbbreviation": "WI",
                    "urlFormat": url_format,
                    "countyNo": county_no,
                    "countyName": county_name,
                    "docketNumber": last_inserted_docket,  # Use last INSERTED docket
                    "docketYear": docket_year,
                    "docketType": docket_type
                }
            }
            
            try:
                add_response = api_client.post("/WI_Downloader_Job_To_SQS_ADD", add_payload)
                log.info(f"✅ ADD API called: {add_response}")
            except Exception as e:
                log.error(f"❌ ADD API failed: {e}")
            
            # Add delay before fetching next job after errors
            log.info("⏸ Waiting 60 seconds before fetching next job due to errors...")
            await asyncio.sleep(60)
                
        else:
            # ✅ SUCCESS - USE UPDATE API
            if total_scraped > 0:
                log.info("\n✅ Scraping successful - Calling UPDATE API")
                
                # Convert docket number to integer (remove leading zeros)
                docket_number_int = int(last_successful_docket)
                
                update_payload = {
                    "recordId": record_id,
                    "docketYear": docket_year,
                    "docketNumber": docket_number_int  # Send as integer (e.g., 183 not 000183)
                }
                
                log.info(f"   Updating to docket: {docket_number_int}")
                
                try:
                    update_response = api_client.post("/WI_County_DocketNumber_UPDATE", update_payload)
                    log.info(f"✅ UPDATE API called: {update_response}")
                except Exception as e:
                    log.error(f"❌ UPDATE API failed: {e}")
            else:
                log.info("ℹ️ No new data scraped - No UPDATE call needed")
        # # VPN reconnection logic
        # needs_vpn_reconnect = scraper_error_occurred or should_reconnect_vpn()
        
        # if needs_vpn_reconnect:
        #     reconnect_vpn_if_needed()
        # else:
        #     elapsed = (time.time() - last_vpn_reconnect_time) / 60
        #     log.info(f"ℹ️ VPN reconnection not needed (elapsed: {elapsed:.1f} minutes)")
        
        # log.info("🔄 Fetching next job from queue...")
        # await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())