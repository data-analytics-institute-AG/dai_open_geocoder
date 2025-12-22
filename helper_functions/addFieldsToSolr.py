import requests
import json

###
#
# Diese Funktion soll einfach einen existierenden Solr-Core unseren Bedingungen anpassen. Es werden drei Schritte durchgeführt:
#
# 1. Leeren des Cores
# 2. Löschen des Schemas (Standardfelder id, _version_ und _text_ werden beibehalten)
# 3. Erstellen des neuen Schemas mit den Feldern aus "FIELDS" und nach den Regeln in der Funktion make_field_definition()
#
###

# -------------------------
# Configuration
# -------------------------
SOLR_URL = "http://127.0.0.1:8983/solr"  # base URL of Solr
CORE_NAME = "addresses"                    # existing core name

# Fields to create
FIELDS = [
    "daid",
    "plz",
    "ort",
    "ott",
    "stn",
    "hnr",
    "gemarkung",
    "koordinate",
    "additional_information"
]

# ----------------------------------------------------------------------
# Step 1 — Delete all documents in the core
# ----------------------------------------------------------------------
def delete_all_documents(solr_url, core):
    update_url = f"{solr_url}/{core}/update?commit=true"
    data = {"delete": {"query": "*:*"}}

    print("Deleting all documents...")
    resp = requests.post(update_url, json=data)
    print("  status:", resp.status_code, resp.text)


# ----------------------------------------------------------------------
# Step 2 — Delete all fields except 'id'
# ----------------------------------------------------------------------
def remove_all_custom_fields(solr_url, core):
    schema_url = f"{solr_url}/{core}/schema/fields"

    print("Fetching existing field list...")
    resp = requests.get(schema_url)
    fields = resp.json()["fields"]

    for field in fields:
        name = field["name"]
	# leave standard fields in
        if name in ["id","_version_","_text_"]:
            continue

        print(f"Removing field '{name}'...")
        del_url = f"{solr_url}/{core}/schema"
        payload = {"delete-field": {"name": name}}

        r = requests.post(del_url, json=payload)
        print("  status:", r.status_code, r.text)

# -------------------------
# Helper function to create field definition
# -------------------------
def make_field_definition(field_name):
    """
    Returns a field definition dict for Solr Schema API.
    """
    if field_name == "koordinate":
        return {
            "name": field_name,
            "type": "location",
            "stored": True,
            "indexed": True,
            "multiValued": False
        }
    elif field_name == "additional_information":
        return {
            "name": field_name,
            "type": "string",
            "stored": True,
            "indexed": False,
            "multiValued": False
        }
    elif field_name in ["hnr","stn","ort","ott","gemarkung"]:
        return {
            "name": field_name,
            "type": "text_general",
            "stored": True,
            "indexed": True,
            "multiValued": True
        }
    else:
        return {
            "name": field_name,
            "type": "text_general",
            "stored": True,
            "indexed": True,
            "multiValued": False
        }

# -------------------------
# Main: create fields via Schema API
# -------------------------
def create_fields(solr_url, core_name, fields):
    schema_url = f"{solr_url}/{core_name}/schema"
    for field in fields:
        field_def = make_field_definition(field)
        data = {"add-field": field_def}

        print(f"Creating field '{field}'...")
        resp = requests.post(schema_url, headers={"Content-Type": "application/json"}, data=json.dumps(data))

        if resp.status_code == 200:
            print(f"  OK: {resp.json()}")
        else:
            print(f"  ERROR ({resp.status_code}): {resp.text}")

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":

    delete_all_documents(SOLR_URL, CORE_NAME)
    remove_all_custom_fields(SOLR_URL, CORE_NAME)
    create_fields(SOLR_URL, CORE_NAME, FIELDS)
