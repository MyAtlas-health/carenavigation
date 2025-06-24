from flask import Flask, request, jsonify
import pandas as pd
import math
import csv
import requests
from io import StringIO

app = Flask(__name__)

# Public Google Sheets CSV export URL
SHEET_URL = "https://docs.google.com/spreadsheets/d/1n1Zb-Ld6eGSWbkZnVKimrS_8YQfP6suzItqvuJnEAp4/export?format=csv&gid=1322572119"
ZIP_COORDS_CSV_URL = "https://your-public-zip-code-csv-url.com"  # ← replace if needed

# Load ZIP coordinates
def load_zip_coordinates_from_url(url):
    response = requests.get(url)
    content = response.content.decode('utf-8')
    zip_coords = {}
    reader = csv.DictReader(StringIO(content))
    for row in reader:
        zip_coords[row['zip']] = (float(row['lat']), float(row['lng']))
    return zip_coords

def haversine(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def zip_code_within_radius(user_zip, resource_zip_list, zip_coords, radius=50):
    if not user_zip or user_zip not in zip_coords:
        return False
    lat1, lon1 = zip_coords[user_zip]
    for z in resource_zip_list:
        z = z.strip()
        if z in zip_coords:
            lat2, lon2 = zip_coords[z]
            if haversine(lat1, lon1, lat2, lon2) <= radius:
                return True
    return False

def map_response_to_tags(typeform_response):
    mood_map = {
        '1': 'High Risk',
        '2': 'High Risk',
        '3': 'Medium Risk',
        '4': 'Low Risk',
        '5': 'Low Risk'
    }

    support_type_map = {
        'I want to talk to a professional': ['Clinical'],
        'I'm looking for something calming': ['Podcast', 'Playlist', 'Guided Meditation', 'Tool'],
        'I want to get energized or motivated': ['Playlist', 'Event', 'Support Groups']
    }

    delivery_map = {
        'Virtual/Remote': ['Remote/Virtual', 'Online'],
        'In person': ['In-Person']
    }

    cost_map = {
        'Free only': ['Free'],
        'Up to $25': ['Paid Low'],
        'Willing to pay more for the right fit': ['Paid Low', 'Paid High']
    }

    return {
        'Risk Level': [mood_map.get(str(typeform_response.get('mood_score')), '')],
        'Resource Type': support_type_map.get(typeform_response.get('support_type'), []) or [],
        'Geo Location': delivery_map.get(typeform_response.get('support_delivery'), []) or [],
        'Zip Code': [typeform_response.get('zip_code')],
        'Cost': cost_map.get(typeform_response.get('budget'), []) or [],
        'User Segment': [typeform_response.get('user_segment')],
        'Sentiment/ Mood': typeform_response.get('sentiment_tags', [])
    }

def score_resources(resources, mapped_answers, weights, zip_coords):
    results = []
    max_score_possible = sum(weights.values())

    for res in resources:
        score = 0
        details = {}
        for field, tags in mapped_answers.items():
            field_val = res.get(field, '')
            match_found = False

            if field == 'Zip Code':
                zip_list = str(res.get('Zip Code', '')).split(',')
                if zip_code_within_radius(tags[0], zip_list, zip_coords):
                    score += weights.get(field, 1)
                    match_found = True
            else:
                for tag in tags:
                    if tag and tag.lower() in str(field_val).lower():
                        score += weights.get(field, 1)
                        match_found = True
                        break

            details[field] = '✔' if match_found else '✘'

        results.append({
            'resource': res.get('Resource Name', 'Unnamed'),
            'score': score,
            'score_pct': round((score / max_score_possible) * 100, 1),
            'breakdown': details
        })

    sorted_results = sorted(results, key=lambda x: x['score'], reverse=True)
    top_matches = sorted_results[:3]
    overall_score = round((sum([r['score'] for r in results]) / (len(results) * max_score_possible)) * 100, 1)

    return {
        'top_3_resources': top_matches,
        'overall_percent_fit': overall_score
    }

@app.route("/match", methods=["POST"])
def match():
    try:
        form_data = request.json
        resource_df = pd.read_csv(SHEET_URL)
        zip_coords = load_zip_coordinates_from_url(ZIP_COORDS_CSV_URL)
    except Exception as e:
        return jsonify({"error": "Failed to load data", "details": str(e)}), 500

    weights = {
        'Risk Level': 2,
        'Resource Type': 2,
        'Geo Location': 2,
        'Zip Code': 3,
        'Cost': 1,
        'User Segment': 1,
        'Sentiment/ Mood': 1
    }

    mapped_answers = map_response_to_tags(form_data)
    resource_dicts = resource_df.to_dict(orient="records")
    results = score_resources(resource_dicts, mapped_answers, weights, zip_coords)
    return jsonify(results)
