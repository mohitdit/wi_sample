from dotenv import load_dotenv
import os

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_ENDPOINT = os.getenv("AWS_ENDPOINT")
DATASET_ID_MAP = {
    "TR": "901",  # Traffic Forfeiture
    "CT": "902",  # Criminal Traffic
    "CF": "903",  # Felony
    "HT": "904",  # Habitual Traffic Offender
    "CM": "905",  # Misdemeanor
    "FO": "906",  # Non-Traffic Ordinance Violation
    "SC": "907",  # Small Claims
    "CV": "908",  # Civil
    "WL": "909",  # Wills
    "WC": "910",  # Worker's Compensation
    "HL": "911"   # Hospital Lien
}