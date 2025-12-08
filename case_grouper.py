import os
import json
from datetime import datetime
from collections import defaultdict
from typing import List, Dict, Any

def load_json_files(data_dir: str = "data/jsonconverteddata") -> List[Dict[str, Any]]:
    """Load all JSON files from the data directory."""
    cases = []

    # ✅ Handle missing directory gracefully
    if not os.path.isdir(data_dir):
        print(f"⚠ Data directory not found: {data_dir}. No cases to load.")
        return cases

    files = [f for f in os.listdir(data_dir) if f.endswith(".json")]
    if not files:
        print(f"⚠ No JSON files found in: {data_dir}")
        return cases

    for filename in files:
        filepath = os.path.join(data_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            try:
                case_data = json.load(f)
                cases.append(case_data)
            except json.JSONDecodeError:
                print(f"⚠ Skipping invalid JSON: {filename}")
    return cases


def create_grouping_key(case: Dict[str, Any]) -> tuple:
    """
    Create a unique key for grouping cases based on matching criteria:
    - defendant name (first, middle, last)
    - defendant address (line1, city, state, zip)
    - violation_date
    - case_type
    - county
    - dob
    - court location
    """
    # Extract defendant info
    defendant = None
    for person in case.get('persons', []):
        if person.get('person_type') == 'defendant':
            defendant = person
            break
    
    if not defendant:
        return None
    
    # Extract docket information
    docket = case.get('docket_information', {})
    
    # Extract court location from court_activities
    location = ''
    activities = case.get('court_activities', [])
    if activities and len(activities) > 0:
        location = activities[0].get('location', '')
    
    # Extract address
    address = defendant.get('address', {})
    
    # Helper function to safely extract and normalize values
    def safe_str(value):
        return (value or '').strip().lower() if value else ''
    
    # Create the grouping key
    key = (
        safe_str(defendant.get('name_first')),
        safe_str(defendant.get('name_middle')),
        safe_str(defendant.get('name_last')),
        safe_str(address.get('line1')),
        safe_str(address.get('city')),
        safe_str(address.get('state')),
        safe_str(address.get('zip')),
        safe_str(docket.get('violation_date')),
        safe_str(docket.get('case_type')),
        safe_str(case.get('county')),
        safe_str(defendant.get('dob')),
        safe_str(location)
    )
    
    return key

def merge_cases(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge multiple cases into a single grouped case."""
    if not cases:
        return {}
    
    # Use the first case as base
    merged = {
        "state": cases[0].get('state'),
        "county": cases[0].get('county'),
        
        "case_title": cases[0].get('caption'),
        "download_date": datetime.now().isoformat() + "Z",
        "docket_information": cases[0].get('docket_information', {}).copy(),
        "charges": [],
        "persons": [],
        "court_activities": [],
        "court_records": []
    }
    county_no = cases[0].get('docket_information', {}).get('county_no') or 6

    # Build case URL helper
    def build_case_url(case_number: str) -> str:
        return f"https://wcca.wicourts.gov/caseDetail.html?caseNo={case_number}&countyNo={county_no}&index=0&isAdvanced=true&mode=details"
    
    # Collect all charges from all cases
    seen_charges = set()
    for case in cases:
        case_num_for_url = None
        # Get case number once for all charges in this case
        for charge in case.get('charges', []):
            if not case_num_for_url:
                case_num_for_url = charge.get('case_number')

            # Create unique identifier for this specific charge
            charge_key = (
                charge.get('case_number'),
                charge.get('count_number'),
                charge.get('statute'),
                charge.get('description')
            )

            if charge_key not in seen_charges:
                seen_charges.add(charge_key)
                charge_copy = charge.copy()
                if case_num_for_url:
                    charge_copy['case_url'] = build_case_url(case_num_for_url)
                merged['charges'].append(charge_copy)
    
    # Merge persons (avoid duplicates)
    seen_persons = set()
    for case in cases:
        for person in case.get('persons', []):
            person_key = json.dumps(person, sort_keys=True)
            if person_key not in seen_persons:
                seen_persons.add(person_key)
                merged['persons'].append(person)
    
    # Merge court activities (avoid duplicates)
    seen_activities = set()
    for case in cases:
        for activity in case.get('court_activities', []):
            activity_key = json.dumps(activity, sort_keys=True)
            if activity_key not in seen_activities:
                seen_activities.add(activity_key)
                merged['court_activities'].append(activity)
    
    # Sort court activities by date
    merged['court_activities'].sort(key=lambda x: x.get('date', ''))
    
    # Merge court records with docket_number
    for case in cases:
        # Get the case number for this case
        case_number = None
        for charge in case.get('charges', []):
            case_number = charge.get('case_number')
            if case_number:
                break

        # Add court records with docket_number
        for record in case.get('court_records', []):
            record_copy = record.copy()
            record_copy['docket_number'] = case_number

            # Ensure additional_text field exists
            if 'additional_text' not in record_copy:
                record_copy['additional_text'] = ""

            merged['court_records'].append(record_copy)
    
    # Sort court records by date
    merged['court_records'].sort(key=lambda x: x.get('date', '') or '')
    
    return merged

def group_cases(cases: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group cases by matching criteria."""
    groups = defaultdict(list)
    
    for case in cases:
        key = create_grouping_key(case)
        if key:
            groups[key].append(case)
    
    return groups

def save_grouped_cases(groups: Dict[str, List[Dict[str, Any]]], output_dir: str = "data/groupeddata"):
    """Save grouped cases to JSON files."""
    os.makedirs(output_dir, exist_ok=True)
    
    grouped_count = 0
    singleton_count = 0
    total_cases = 0
    
    for key, case_list in groups.items():
        total_cases += len(case_list)
        
        if len(case_list) > 1:
            # Multiple cases - create grouped file
            merged = merge_cases(case_list)
            
            # Create filename from case numbers
            case_numbers = []
            for case in case_list:
                for charge in case.get('charges', []):
                    cn = charge.get('case_number')
                    if cn:
                        case_numbers.append(cn)
            
            filename = "_".join(sorted(set(case_numbers))) + ".json"
            filepath = os.path.join(output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(merged, f, indent=2)
            
            print(f"✅ Grouped {len(case_list)} cases → {filename}")
            grouped_count += 1
        else:
            # Single case - also save it to grouped folder for completeness
            merged = merge_cases(case_list)
            
            # Get case number for filename
            case_number = None
            for charge in case_list[0].get('charges', []):
                cn = charge.get('case_number')
                if cn:
                    case_number = cn
                    break
            
            if case_number:
                filename = f"{case_number}.json"
                filepath = os.path.join(output_dir, filename)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(merged, f, indent=2)
                
                print(f"📄 Single case → {filename}")
            singleton_count += 1
    
    print(f"\n📊 Summary:")
    print(f"   - Grouped files created: {grouped_count}")
    print(f"   - Single cases saved: {singleton_count}")
    print(f"   - Total cases processed: {total_cases}")

if __name__ == "__main__":
    print("🔍 Loading cases from data directory...")
    cases = load_json_files("data")
    print(f"📂 Loaded {len(cases)} cases")
    
    print("\n🔗 Grouping cases by matching criteria...")
    groups = group_cases(cases)
    
    print(f"📦 Found {len(groups)} unique groups")
    
    print("\n💾 Saving grouped cases...")
    save_grouped_cases(groups)
    
    print("\n✨ Done!")


def run_grouping(data_dir: str = "data/jsonconverteddata", output_dir: str = "data/groupeddata"):
    """
    Main function to run the grouping process.
    Can be called from other scripts.
    """
    print("\n" + "="*60)
    print("🔗 GROUPING CASES")
    print("="*60)
    
    cases = load_json_files(data_dir)
    print(f"📂 Loaded {len(cases)} cases")
    
    if len(cases) == 0:
        print("⚠ No cases to group!")
        return
    
    groups = group_cases(cases)
    print(f"📦 Found {len(groups)} unique groups")
    
    save_grouped_cases(groups, output_dir)
    print("✨ Grouping complete!")
    print("="*60)