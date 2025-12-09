# scrapers/html_to_json.py
from bs4 import BeautifulSoup
import re
from datetime import datetime
from typing import Optional, Dict, Any, List


def _clean_text(node):
    if node is None:
        return ""
    text = " ".join(node.get_text(separator=" ", strip=True).split())
    return text if text != "\xa0" else ""


def _parse_money(text: str) -> Optional[float]:
    if not text:
        return None
    # remove commas, dollar signs
    m = re.search(r"-?\$?([\d,]+(?:\.\d+)?)", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except:
        return None


def _iso_date_from_mm_dd_yyyy(text: str) -> Optional[str]:
    """
    Converts '11-25-2025' or '11-25-2025 08:15 am' to '2025-11-25'.
    If text looks like '11-25-2025' returns '2025-11-25'.
    If text is '05-1989' returns '05-1989' (leave DOB monthly-year format).
    """
    if not text:
        return None
    text = text.strip()
    # try mm-dd-yyyy
    m = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})", text)
    if m:
        mm, dd, yyyy = m.groups()
        try:
            d = datetime(int(yyyy), int(mm), int(dd))
            return d.strftime("%Y-%m-%d")
        except:
            return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"
    # try mm-yyyy (DOB style)
    m2 = re.match(r"(\d{1,2})-(\d{4})$", text)
    if m2:
        mm, yyyy = m2.groups()
        return f"{mm.zfill(2)}-{yyyy}"  # keep as '05-1989' style
    # fallback: try parse yyyy-mm-dd-like
    try:
        d = datetime.fromisoformat(text.split()[0])
        return d.date().isoformat()
    except:
        return None


def _extract_dl_pairs_from_dl_section(section):
    """
    Accepts a soup section that contains a series of <dl><dt>Label</dt><dd>Value</dd></dl>.
    Returns a dict label->value
    """
    data = {}
    for dl in section.find_all("dl"):
        dt = dl.find("dt")
        dd = dl.find("dd")
        if not dt:
            continue
        key = _clean_text(dt).lower().strip()
        val = _clean_text(dd)
        data[key] = val
    return data


def _parse_address(addr: str) -> Dict[str, Optional[str]]:
    """
    Parse an address string like:
      - "18410 South St Apt 12, Whitehall, WI 54773"
      - "5367 Eagle St, White Bear Lake, MN 55110"
      - "123 Main St, Smalltown WI 12345" (no comma before state)
    Returns dict with keys: line1, city, state, zip
    """
    if not addr:
        return {"line1": None, "city": None, "state": None, "zip": None}

    addr = addr.strip()
    # Normalize multiple spaces
    addr = " ".join(addr.split())

    # If there are 3+ comma-separated parts, assume: line1, city, state_zip (extra commas in street handled by joining)
    parts = [p.strip() for p in addr.split(",")]
    if len(parts) >= 3:
        line1 = parts[0]
        # join middle parts except last as city (handles "City, Extra" edgecases)
        city = ", ".join(parts[1:-1]).strip()
        state_zip = parts[-1]
    elif len(parts) == 2:
        # Parts: [line1, city + state_zip] OR [line1, city state zip]
        line1 = parts[0]
        state_zip = parts[1]
        # Try to split state_zip into city/state/zip by regex: look for last ' STATE ZIP' pattern
        # If it doesn't match, treat everything before last two tokens as city.
        m = re.search(r"(.*)\b([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)\s*$", state_zip)
        if m:
            city = m.group(1).strip()
            state_zip = f"{m.group(2)} {m.group(3)}"
        else:
            # fallback: try to split the state_zip by whitespace, assume last two tokens state+zip or last token state
            toks = state_zip.split()
            if len(toks) >= 2 and re.match(r"^[A-Za-z]{2}$", toks[-2]) and re.match(r"^\d{5}(?:-\d{4})?$", toks[-1]):
                city = " ".join(toks[:-2])
                state_zip = f"{toks[-2]} {toks[-1]}"
            else:
                # can't reliably split, assume everything is city
                city = state_zip
                state_zip = ""
    else:
        # No comma at all — try to parse from the end using regex
        line1 = None
        city = None
        state_zip = addr
        m = re.search(r"(.*?),?\s*([A-Za-z]{2})\s+(\d{5}(?:-\d{4})?)\s*$", addr)
        if m:
            line1 = m.group(1).strip()
            # fallback: treat line1 as combined and then split
            parts2 = line1.split(",")
            if len(parts2) >= 2:
                line1 = parts2[0].strip()
                city = parts2[1].strip()
            else:
                # unknown: set line1 as first chunk
                line1 = parts2[0].strip()
            state_zip = f"{m.group(2)} {m.group(3)}"

    # Now parse state_zip for state and zip
    state = None
    zipc = None
    if state_zip:
        m2 = re.search(r"([A-Za-z]{2})\s*(\d{5}(?:-\d{4})?)?", state_zip)
        if m2:
            state = m2.group(1)
            zipc = m2.group(2) if m2.group(2) else None

    # Final trims and normalization
    def _none_if_empty(x: Optional[str]) -> Optional[str]:
        if x is None:
            return None
        x = x.strip()
        return x if x != "" else None

    return {
        "line1": _none_if_empty(line1),
        "city": _none_if_empty(city),
        "state": _none_if_empty(state),
        "zip": _none_if_empty(zipc)
    }


def parse_html_file_to_json(html_path: str, job_config: Optional[dict] = None) -> Dict[str, Any]:
    """
    Read html_path, parse it, and return dict structured per user's final JSON example.
    """
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "html.parser")

    content_col = soup.find("div", class_="content-column")
    if content_col is None:
        # fallback to whole soup
        content_col = soup

    result: Dict[str, Any] = {}
    # state and county
    state_abbr = (job_config.get("stateAbbreviation") if job_config else None) or ""
    result["state"] = state_abbr
    county_name = ""
    county_span = content_col.find("span", class_="countyName")
    if county_span:
        county_name = _clean_text(county_span)
    result["county"] = county_name.strip()

    # header: caption, case number
    caption_node = content_col.find("span", class_="caption")
    if caption_node:
        result["caption"] = _clean_text(caption_node)
    else:
        # fallback: look for h4 with caption
        h4 = content_col.find("h4")
        if h4:
            txt = _clean_text(h4)
            # heuristic: after 'caption' (if included)
            result["caption"] = txt

    # -------- docket_information --------
    docket_info = {
        "filing_date": None,
        "case_type": None,
        "case_status":None,
        "county_no": (job_config.get("countyNo") if job_config else None),
        "plate": None,
        "state_code": state_abbr,
        "expiration": None,
        "vin": None,
        "violation_date": None,
        "officer": None,
        "issuing_agency": None
    }

    # summary section dl fields
    summary_section = content_col.find("section", id="summary")
    if summary_section:
        summary_map = _extract_dl_pairs_from_dl_section(summary_section)
        # map likely names
        if "filing date" in summary_map:
            docket_info["filing_date"] = _iso_date_from_mm_dd_yyyy(summary_map["filing date"])
        if "case type" in summary_map:
            docket_info["case_type"] = summary_map["case type"]
        if "case status" in summary_map:
            docket_info["case_status"] = summary_map["case status"]
        # Extract address from summary
        summary_address = None
        for key in summary_map.keys():
            if key.startswith("address"):
                summary_address = summary_map[key]
                break
        # DOB format is sometimes here; address we'll parse elsewhere

    # citations section - there may be one or more .citation blocks
        citations = []
        cit_section = content_col.find("section", id="citations")
        if cit_section:
            for cit in cit_section.find_all("div", class_="citation"):
                # citation number header
                header = cit.find("h5", class_="detailHeader")
                citation_label = _clean_text(header) if header else ""
                
                # Extract citation number from header like "Citation BK1292303"
                citation_number = None
                if citation_label:
                    m = re.search(r'Citation\s+(\S+)', citation_label, re.I)
                    if m:
                        citation_number = m.group(1).strip()
                
                # inside citationDetail
                detail = cit.find("div", class_="citationDetail")
                fields = {}
                if detail:
                    # parse dl groups
                    for dl in detail.find_all("dl"):
                        dt = dl.find("dt")
                        dd = dl.find("dd")
                        if not dt:
                            continue
                        key = _clean_text(dt).lower()
                        val = _clean_text(dd)
                        fields[key] = val
                
                # Extract bond amount
                bond_val = None
                if detail:
                    bond_dd = detail.find("dt", string=re.compile(r"Bond amount", re.I))
                    if bond_dd:
                        dd = bond_dd.find_next_sibling("dd")
                        if dd:
                            bond_val = _parse_money(_clean_text(dd))
                
                # Build citation object
                description = fields.get("charge description") or fields.get("description", "")
                is_modified = "modifier:" in description.lower() or "modified:" in description.lower()
                
                citation_obj = {
                    "case_number": None,
                    "citation_number": citation_number,
                    "bond_amount": bond_val,
                    "statute": fields.get("statute"),
                    "description": description,
                    "severity": fields.get("severity"),
                    "ordinance_or_statute": fields.get("ordinance or statute"),
                    "plaintiff_agency": fields.get("plaintff agency") or fields.get("plaintiff agency"),
                    "mph_over": fields.get("mph over") or fields.get("MPH over") or fields.get("MPH over"),
                    "isModified": "true" if is_modified else "false"
                }
                
                # Update docket_info with citation details
                if "plate number" in fields:
                    docket_info["plate"] = fields.get("plate number")
                if "state" in fields:
                    docket_info["state_code"] = fields.get("state")
                if "expiration" in fields:
                    docket_info["expiration"] = fields.get("expiration")
                if "vin" in fields:
                    docket_info["vin"] = fields.get("vin")
                if "issuing agency" in fields:
                    docket_info["issuing_agency"] = fields.get("issuing agency")
                if "officer name" in fields:
                    docket_info["officer"] = fields.get("officer name")
                if "violation date" in fields:
                    docket_info["violation_date"] = _iso_date_from_mm_dd_yyyy(fields.get("violation date"))
                
                citations.append(citation_obj)

        # fallback: parse charges table in charges section (if citations empty)
        if not citations:
            charge_section = content_col.find("section", id="charges")
            if charge_section:
                charge_table = charge_section.find("table", class_=re.compile(r"charge-summary|group-colored", re.I))
                if charge_table:
                    # Find all tbody elements (each charge+modifier is in separate tbody)
                    tbodies = charge_table.find_all("tbody")
                    for tbody in tbodies:
                        rows = tbody.find_all("tr")
                        current_count = None
                        
                        for tr in rows:
                            tds = [_clean_text(td) for td in tr.find_all(["td", "th"])]
                            
                            # Check if this is a modifier row
                            is_modifier_row = (tr.get("class") and "modifier" in str(tr.get("class")))
                            
                            if is_modifier_row:
                                # This is a modifier row
                                if len(tds) >= 3:
                                    citations.append({
                                        "case_number": None,
                                        "citation_number": None,
                                        "bond_amount": None,
                                        "count_number": current_count,
                                        "statute": tds[1] if len(tds) > 1 else None,
                                        "description": tds[2] if len(tds) > 2 else None,
                                        "severity": tds[3] if len(tds) > 3 else None,
                                        "disposition": tds[4] if len(tds) > 4 else None,
                                        "ordinance_or_statute": None,
                                        "plaintiff_agency": None,
                                        "mph_over": None,
                                        "isModified": "true"
                                    })
                            else:
                                # This is a main charge row
                                if len(tds) >= 4:
                                    current_count = tds[0] if len(tds) > 0 else None
                                    citations.append({
                                        "case_number": None,
                                        "citation_number": None,
                                        "bond_amount": None,
                                        "count_number": current_count,
                                        "statute": tds[1] if len(tds) > 1 else None,
                                        "description": tds[2] if len(tds) > 2 else None,
                                        "severity": tds[3] if len(tds) > 3 else None,
                                        "disposition": tds[4] if len(tds) > 4 else None,
                                        "ordinance_or_statute": None,
                                        "plaintiff_agency": None,
                                        "mph_over": None,
                                        "isModified": "false"
                                    })

    # persons: defendant, plaintiff, prosecuting_agency, officer
    persons = []
    defendant_section = content_col.find("section", id="defendant")
    if defendant_section:
        # extract main defendant dl fields
        def_map = _extract_dl_pairs_from_dl_section(defendant_section)
        # name
        name_raw = def_map.get("defendant name") or def_map.get("defendant name")
        if name_raw:
            # format "Last, First Middle"
            parts = [p.strip() for p in name_raw.split(",")]
            last = parts[0] if len(parts) > 0 else ""
            rest = parts[1] if len(parts) > 1 else ""
            # split rest into first, middle
            first = ""
            middle = ""
            if rest:
                rest_parts = rest.split()
                first = rest_parts[0]
                if len(rest_parts) > 1:
                    middle = " ".join(rest_parts[1:])
            persons.append({
                "person_type": "defendant",
                "name_last": last,
                "name_first": first,
                "name_middle": middle,
                "sex": def_map.get("sex"),
                "race": def_map.get("race"),
                "dob": def_map.get("date of birth") or def_map.get("defendant date of birth"),
                "address": {
                    "line1": None,
                    "city": None,
                    "state": None,
                    "zip": None
                }
            })
        # address parsing (REPLACED BLOCK)
        # addr = None
        # for key in def_map.keys():
        #     if key.startswith("address"):
        #         addr = def_map[key]
        #         break
        if persons and summary_address:
            parsed_addr = _parse_address(summary_address)
            persons[0]["address"]["line1"] = parsed_addr["line1"]
            persons[0]["address"]["city"] = parsed_addr["city"]
            persons[0]["address"]["state"] = parsed_addr["state"]
            persons[0]["address"]["zip"] = parsed_addr["zip"]

    # plaintiff / prosecuting agency - from charges section top fields
        charges_section = content_col.find("section", id="charges")
        prosecutor = None
        prosecutor_attny = None
        responsible_official = None
        plaintiff_agency = None

        if charges_section:
            charge_map = _extract_dl_pairs_from_dl_section(charges_section)
            # responsible official/prosecuting agency/prosecuting agency attorney
            prosecutor = charge_map.get("prosecuting agency")
            prosecutor_attny = charge_map.get("prosecuting agency attorney")
            responsible_official = charge_map.get("responsible official") or charge_map.get("responsible official")

        # Get plaintiff_agency from first citation if available
        if citations:
            for citation in citations:
                if citation.get("plaintiff_agency"):
                    plaintiff_agency = citation["plaintiff_agency"]
                    break

        # Always add prosecuting_agency (even if empty)
        persons.append({
            "person_type": "prosecuting_agency",
            "is_organization": True,
            "name": prosecutor or ""
        })

        # Always add prosecuting_agency_attorney (even if empty)
        persons.append({
            "person_type": "prosecuting_agency_attorney",
            "is_organization": False,
            "name": prosecutor_attny or ""
        })

        # Always add plaintiff_agency (even if empty)
        persons.append({
            "person_type": "plaintiff_agency",
            "is_organization": True,
            "name": plaintiff_agency or ""
        })

        # Add officer/responsible official only if present
        if responsible_official:
            persons.append({
                "person_type": "officer",
                "name_last": responsible_official.split(",")[0] if "," in responsible_official else responsible_official,
                "name_first": responsible_official.split(",")[1].strip() if "," in responsible_official and len(responsible_official.split(","))>1 else None
            })

    # court_activities: parse activities table
    activities = []
    activities_section = content_col.find("section", id="activities")
    if activities_section:
        table = activities_section.find("table")
        if table:
            thead = [ _clean_text(th) for th in table.find_all("th") ]
            for tr in table.find("tbody").find_all("tr"):
                tds = [ _clean_text(td) for td in tr.find_all("td") ]
                if not tds:
                    continue
                # map columns by position heuristically
                # expected columns: Date, Time, Location, Description, Type, Court official
                act = {
                    "date": _iso_date_from_mm_dd_yyyy(tds[0]) if len(tds) > 0 else None,
                    "time": tds[1] if len(tds) > 1 else None,
                    "location": tds[2] if len(tds) > 2 else None,
                    "description": tds[3] if len(tds) > 3 else None,
                    "type": tds[4] if len(tds) > 4 else None,
                    "court_official": tds[5] if len(tds) > 5 else None
                }
                activities.append(act)

    # court_records: parse records table
    records = []
    records_section = content_col.find("section", id="records")
    if records_section:
        table = records_section.find("table")
        if table:
            # rows may be in multiple tbody groups
            for tbody in table.find_all("tbody"):
                for tr in tbody.find_all("tr"):
                    tds = [ _clean_text(td) for td in tr.find_all("td") ]
                    if not tds:
                        continue
                    # expected: Date, Event, Court official, Court reporter, Amount
                    rec = {
                        "date": _iso_date_from_mm_dd_yyyy(tds[0]) if len(tds) > 0 else None,
                        "event": tds[1] if len(tds) > 1 else None,
                        "court_official": tds[2] if len(tds) > 2 else None,
                        "court_reporter": tds[3] if len(tds) > 3 else None,
                        "amount": _parse_money(tds[4]) if len(tds) > 4 else None
                    }
                    records.append(rec)

    # --- POST-PROCESS: merge "Additional text:" rows into previous record as "additional_text" ---
    merged_records: List[Dict[str, Any]] = []
    additional_re = re.compile(r'^\s*Additional\s*text\s*:\s*(.*)', re.I)
    for rec in records:
        event_text = rec.get("event") or ""
        m = additional_re.match(event_text)
        if rec.get("date") is None and m:
            add_txt = m.group(1).strip()
            if merged_records:
                prev = merged_records[-1]
                # Only attach if previous exists; concatenate if already present
                if prev.get("additional_text"):
                    prev["additional_text"] = prev["additional_text"].rstrip() + "\n" + add_txt
                else:
                    prev["additional_text"] = add_txt
                # Do NOT append this 'Additional text' record to merged_records (it's merged)
            else:
                # No previous record: keep the record but move text into additional_text and keep it
                rec["additional_text"] = add_txt
                merged_records.append(rec)
        else:
            merged_records.append(rec)
    # replace records with merged_records
    records = merged_records

    # finalize docket_info from citations list (if values exist)
    if citations:
        # attach case numbers if job_config provided
        if job_config and job_config.get("docketYear") and job_config.get("docketType") and job_config.get("docketNumber"):
            case_no = f"{job_config['docketYear']}{job_config['docketType']}{job_config['docketNumber']}"
            for c in citations:
                if not c.get("case_number"):
                    c["case_number"] = case_no

    # make sure docket_info dates are in ISO form
    # if filing_date None, try top-level summary again
    if not docket_info.get("filing_date"):
        if summary_section:
            dd = summary_section.find("dt", string=re.compile(r"Filing date", re.I))
            if dd:
                filing = _clean_text(dd.find_next_sibling("dd"))
                docket_info["filing_date"] = _iso_date_from_mm_dd_yyyy(filing)

    # put everything into result
    result["docket_information"] = docket_info
    result["charges"] = citations
    result["persons"] = persons
    result["court_activities"] = activities
    result["court_records"] = records

    # Final small-normalizations
    # convert any empty strings to None where appropriate
    def _norm(v):
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    for k, v in result.items():
        if isinstance(v, str):
            result[k] = _norm(v)

    return result