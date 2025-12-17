import json

def process_node(field, mock_data=True):
    """
    Recursively processes a field node from the schema.
    
    Args:
        field (dict): The schema field object.
        mock_data (bool): If True, generates placeholder values to show logic.
                          If False, returns empty strings.
    """
    field_name = field.get('field_name')
    data_type = field.get('data_type')
    separator = field.get('value_separator', "")
    sub_fields = field.get('fields', [])

    # CASE 1: LISTS
    # If type is list, we return a list containing a single object representing the structure.
    if data_type == 'list':
        item_structure = {}
        for sub in sub_fields:
            item_structure[sub['field_name']] = process_node(sub, mock_data)
        return [item_structure]

    # CASE 2: GROUPS
    elif data_type == 'group':
        # LOGIC: Check if a value_separator exists (like "-" for acs_cdr_number)
        if separator:
            # If separator exists, do NOT return a dictionary.
            # Concatenate child values into a string.
            child_values = []
            for sub in sub_fields:
                # Since we don't have real input data, we create a placeholder
                # that looks like <type_code> to prove the logic works.
                if mock_data:
                    child_values.append(f"<{sub['field_name']}>")
                else:
                    child_values.append("") 
            
            return separator.join(child_values)
        else:
            # If NO separator, standard behavior: Return a nested dictionary.
            group_obj = {}
            for sub in sub_fields:
                group_obj[sub['field_name']] = process_node(sub, mock_data)
            return group_obj

    # CASE 3: PRIMITIVES (String, Date, etc.)
    else:
        # Return a placeholder or empty string
        if mock_data:
            # Returning "1" just to match your example style roughly, 
            # or simply empty string ""
            return "" 
        return ""

def generate_response_from_schema(file_path):
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Navigate to the fields list in the schema
        root_fields = data.get('ck_json_schema', {}).get('fields', [])
        
        output_json = {}
        
        # Process top-level fields
        for field in root_fields:
            output_json[field['field_name']] = process_node(field, mock_data=True)
            
        return output_json

    except FileNotFoundError:
        print("Error: test.json file not found.")
        return {}
    except json.JSONDecodeError:
        print("Error: Failed to decode JSON.")
        return {}

# --- Execution ---
if __name__ == "__main__":
    result = generate_response_from_schema('test.json')
    
    # Print the result formatted nicely
    print(json.dumps(result, indent=2))