import os
import asyncio
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from scrapers.base_scraper import BaseScraper
from utils.browser_manager import get_stealth_browser
from utils.logger import log

# <-- NEW: parser functions to convert HTML -> JSON
from scrapers.virginia_html_to_json import parse_case_div, save_parsed_json

class VirginiaScraper(BaseScraper):
    """
    Scraper for Virginia General District Courts
    Handles both Civil (GV) and Criminal (GC, GT) cases
    Case format: XX000000-00 (2 letters + 6 digits + dash + 2 digits)
    
    For criminal cases: If GC prefix fails, try GT with same number (and vice versa)
    """
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = "https://eapps.courts.state.va.us/gdcourts/criminalCivilCaseSearch.do"
        self.case_prefixes = {
            'civil': ['GV'],
            'criminal': ['GC', 'GT']
        }
    
    def build_case_number(self, prefix: str, year: str, number: str, suffix: str = "00") -> str:
        """
        Build formatted case number: XX000000-00
        prefix: 2 letters (GV, GC, GT)
        year: 2 digits (25 for 2025)
        number: 6 digits (000000-999999)
        suffix: 2 digits (usually 00)
        """
        # Ensure number is 6 digits with leading zeros
        number_padded = str(number).zfill(6)
        return f"{prefix}{year}{number_padded}-{suffix}"
    
    async def check_no_results(self, page) -> bool:
        """Check if page contains 'No results found' message"""
        try:
            # Wait a bit for page to stabilize after navigation
            await page.wait_for_load_state("networkidle", timeout=5000)
            content = await page.content()
            return "No results found for the search criteria." in content
        except Exception as e:
            # If we can't check, assume there might be results
            log.warning(f"Could not verify no results status: {e}")
            return False
    
    async def scrape_case(self, case_number: str, prefix: str) -> dict:
        """
        Scrape a single case by submitting POST form
        Returns: dict with status, html, and case_number
        """
        browser, context, page = await get_stealth_browser(headless=True)
        
        try:
            log.info(f"Scraping case: {case_number}")
            
            # Navigate to the search page first
            referer_url = (
                f"{self.base_url}?fromSidebar=true&formAction=searchLanding"
                f"&searchDivision={self.config['searchDivision']}"
                f"&searchFipsCode={self.config['searchFipsCode']}"
                f"&curentFipsCode={self.config['searchFipsCode']}"
            )
            
            await page.goto(referer_url, wait_until="domcontentloaded", timeout=30000)
            
            # Set up request interception to add custom headers
            await page.set_extra_http_headers({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Cache-Control': 'max-age=0',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://eapps.courts.state.va.us',
                'Referer': referer_url,
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1',
                'Upgrade-Insecure-Requests': '1'
            })
            
            # Fill the form fields
            form_data = {
                'formAction': 'submitCase',
                'searchFipsCode': str(self.config['searchFipsCode']),
                'searchDivision': self.config['searchDivision'],
                'searchType': 'caseNumber',
                'displayCaseNumber': case_number,
                'localFipsCode': str(self.config['searchFipsCode'])
            }
            
            # Submit the form by evaluating JavaScript
            await page.evaluate(f"""
                () => {{
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = '{self.base_url}';
                    
                    const fields = {form_data};
                    for (const [key, value] of Object.entries(fields)) {{
                        const input = document.createElement('input');
                        input.type = 'hidden';
                        input.name = key;
                        input.value = value;
                        form.appendChild(input);
                    }}
                    
                    document.body.appendChild(form);
                    form.submit();
                }}
            """)
            
            # Wait for navigation after form submission
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            
            # Give page extra time to fully load
            await asyncio.sleep(1)
            
            # Check if no results found
            no_results = await self.check_no_results(page)
            
            if no_results:
                log.info(f"No results found for {case_number}")
                return {
                    'status': 'no_results',
                    'case_number': case_number,
                    'html': None
                }
            
            # Wait for network to be idle before getting content
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except:
                pass  # Continue even if networkidle times out
            
            # Get the HTML content
            html_content = await page.content()
            
            log.info(f"✅ Successfully scraped {case_number}")
            
            return {
                'status': 'success',
                'case_number': case_number,
                'html': html_content
            }
            
        except PlaywrightTimeoutError as e:
            log.error(f"Timeout error for {case_number}: {e}")
            return {'status': 'timeout', 'case_number': case_number, 'html': None}
        
        except Exception as e:
            log.error(f"Error scraping {case_number}: {e}")
            return {'status': 'error', 'case_number': case_number, 'html': None}
        
        finally:
            await context.close()
            await browser.close()
    
    def get_alternate_prefix(self, current_prefix: str) -> str:
        """Get the alternate criminal prefix (GC <-> GT)"""
        if current_prefix == 'GC':
            return 'GT'
        elif current_prefix == 'GT':
            return 'GC'
        else:
            return None  # No alternate for civil cases
    
    async def run_scraper(self):
        """
        Main scraper method - iterates through case numbers
        For criminal cases: tries alternate prefix if first one fails
        """
        case_type = self.config.get('caseType', 'civil')
        prefixes = self.case_prefixes.get(case_type, ['GV'])
        
        start_number = int(self.config['docketNumber'])
        docket_year = str(self.config['docketYear'])[-2:]
        
        results = []
        
        # Start with first prefix for this case type
        current_prefix = prefixes[0]
        log.info(f"Starting scrape with prefix: {current_prefix}")
        
        current_number = start_number
        consecutive_failures = 0
        max_consecutive_failures = 5
        
        while consecutive_failures < max_consecutive_failures:
            number_str = str(current_number).zfill(6)
            case_number = self.build_case_number(current_prefix, docket_year, number_str)
            
            # Try with current prefix
            result = await self.scrape_case(case_number, current_prefix)
            
            if result['status'] == 'success':
                # Success! Save and continue with same prefix
                results.append(result)
                consecutive_failures = 0
                self.save_html(result['html'], case_number)
                current_number += 1
                
            elif result['status'] == 'no_results':
                # Failed with current prefix
                # For criminal cases, try alternate prefix
                alternate_prefix = self.get_alternate_prefix(current_prefix)
                
                if alternate_prefix and case_type == 'criminal':
                    log.info(f"🔄 Trying alternate prefix: {alternate_prefix}")
                    alt_case_number = self.build_case_number(alternate_prefix, docket_year, number_str)
                    alt_result = await self.scrape_case(alt_case_number, alternate_prefix)
                    
                    if alt_result['status'] == 'success':
                        # Success with alternate! Switch prefix and continue
                        log.info(f"✅ Found with alternate prefix! Switching from {current_prefix} to {alternate_prefix}")
                        current_prefix = alternate_prefix
                        results.append(alt_result)
                        consecutive_failures = 0
                        self.save_html(alt_result['html'], alt_case_number)
                        current_number += 1
                    else:
                        # Both prefixes failed
                        log.warning(f"❌ Both {result['case_number']} and {alt_case_number} not found")
                        consecutive_failures += 1
                        log.warning(f"No results count: {consecutive_failures}/{max_consecutive_failures}")
                        current_number += 1
                else:
                    # Civil case or no alternate available
                    consecutive_failures += 1
                    log.warning(f"No results count: {consecutive_failures}/{max_consecutive_failures}")
                    current_number += 1
            
            else:
                # Timeout or error
                log.warning(f"Failed to scrape {case_number}, status: {result['status']}")
                current_number += 1
            
            # Small delay to avoid overwhelming the server
            await asyncio.sleep(2)
        
        log.info(f"Completed scraping. Found {len(results)} cases total.")
        return results
    
    def save_html(self, html_content: str, case_number: str):
        """Save HTML to data/htmldata folder, then parse it to JSON and save parsed JSON."""
        html_dir = os.path.join(self.output_dir, "htmldata")
        os.makedirs(html_dir, exist_ok=True)
        
        filename = f"{case_number}_{self.config['courtName'].replace(' ', '_')}.html"
        filepath = os.path.join(html_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        log.info(f"Saved HTML: {filepath}")

        # -------------------------
        # NEW: parse HTML -> JSON
        # -------------------------
        try:
            # parse_case_div accepts path or html string; we pass the filepath
            parsed = parse_case_div(filepath)
        except Exception as e:
            parsed = {}
            log.error(f"Parsing HTML failed for {case_number}: {e}")
        
        try:
            json_dir = os.path.join(self.output_dir, "jsondata")
            os.makedirs(json_dir, exist_ok=True)
            json_path = save_parsed_json(case_number, parsed, json_dir)
            log.info(f"Saved parsed JSON: {json_path}")
        except Exception as e:
            log.error(f"Saving parsed JSON failed for {case_number}: {e}")
            json_path = None
        
        # Return HTML path (keeps original function signature)
        return filepath