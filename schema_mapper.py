import os
import json
from typing import Dict, Any, List

def map_grouped_to_schema(grouped_data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Maps grouped Wisconsin court data to the target schema format.
    Only maps charges - other fields remain empty as per requirements.
    """
    
    # Initialize the mapped structure based on schema
    mapped = {}
    
    # Get schema fields
    schema_fields = schema.get("ck_json_schema", {}).get("fields", [])
    
    # Initialize all top-level fields as empty
    for field in schema_fields:
        field_name = field.get("field_name")
        data_type = field.get("data_type")
        
        if data_type == "list":
            mapped[field_name] = []
        elif data_type == "group":
            mapped[field_name] = initialize_group_structure(field)
        else:
            mapped[field_name] = ""
    
    # Map charges from grouped data
    charges_from_grouped = grouped_data.get("charges", [])
    
    if charges_from_grouped and "defendants" in mapped:
        # Create one defendant entry with all charges
        defendant = {
            "defendant_number": "",
            "first_name": "",
            "middle_name": "",
            "last_name": "",
            "bail_status": "",
            "address_details": {
                "address_line1": "",
                "address_city": "",
                "address_state": "",
                "address_zip": ""
            },
            "postponements": "",
            "language": "",
            "finger_printed": "",
            "jail_information": {
                "inmate_name": "",
                "commitment_number": "",
                "commitment_date": "",
                "jail_location": "",
                "source_match_status": ""
            },
            "acs_cdr_number": "",
            "charges": []
        }
        
        # Map each charge
        for charge in charges_from_grouped:
            mapped_charge = {
                "charge_type": "",
                "statute": charge.get("statute", ""),
                "description": charge.get("description", ""),
                "degree": charge.get("severity", ""),  # Map severity to degree
                "cdr_number": charge.get("citation_number", ""),
                "offense_date": charge.get("case_number", "")  # Placeholder
            }
            defendant["charges"].append(mapped_charge)
        
        mapped["defendants"] = [defendant]
    
    return mapped


def initialize_group_structure(field: Dict[str, Any]) -> Dict[str, Any]:
    """Initialize a group structure with empty values."""
    group = {}
    for subfield in field.get("fields", []):
        field_name = subfield.get("field_name")
        data_type = subfield.get("data_type")
        
        if data_type == "group":
            group[field_name] = initialize_group_structure(subfield)
        elif data_type == "list":
            group[field_name] = []
        else:
            group[field_name] = ""
    
    return group


def process_all_grouped_files(
    grouped_dir: str = "data/groupeddata",
    mapped_dir: str = "data/mappeddata",
    schema_file: str = "test.json"
):
    """
    Process all grouped JSON files and create mapped versions.
    """
    
    # Create output directory
    os.makedirs(mapped_dir, exist_ok=True)
    
    # Load schema
    if not os.path.exists(schema_file):
        print(f"⚠ Schema file not found: {schema_file}")
        return
    
    with open(schema_file, 'r', encoding='utf-8') as f:
        schema = json.load(f)
    
    # Process each grouped file
    if not os.path.isdir(grouped_dir):
        print(f"⚠ Grouped data directory not found: {grouped_dir}")
        return
    
    files = [f for f in os.listdir(grouped_dir) if f.endswith(".json")]
    
    if not files:
        print(f"⚠ No JSON files found in: {grouped_dir}")
        return
    
    print(f"\n📋 Processing {len(files)} grouped files...")
    
    for filename in files:
        input_path = os.path.join(grouped_dir, filename)
        output_path = os.path.join(mapped_dir, filename)
        
        try:
            # Load grouped data
            with open(input_path, 'r', encoding='utf-8') as f:
                grouped_data = json.load(f)
            
            # Map to schema format
            mapped_data = map_grouped_to_schema(grouped_data, schema)
            
            # Save mapped data
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(mapped_data, f, indent=2)
            
            print(f"✅ Mapped: {filename}")
            
        except Exception as e:
            print(f"❌ Error processing {filename}: {e}")
    
    print(f"\n✨ Mapping complete! Files saved to: {mapped_dir}")


if __name__ == "__main__":
    process_all_grouped_files()