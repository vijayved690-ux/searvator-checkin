import os
import re
from flask import Flask, request, jsonify, render_template
from pymongo import MongoClient
from datetime import datetime

app = Flask(__name__)

# MongoDB Setup (Connection Pooling ke sath taaki heavy load par glitch na ho)
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://<username>:<password>@cluster0.mongodb.net/hospital_db?retryWrites=true&w=majority")
client = MongoClient(MONGO_URI, maxPoolSize=50, waitQueueTimeoutMS=2500)
db = client.hospital_db

# Campaign Tracking Store (To record manual conversation counts campaign-wise)
manualConvStore = {}

# --- INTELLIGENCE MODULE ---
def intelligent_lead_router(purpose, age):
    # Rule: Process must NEVER terminate or return "NA"
    default_lead = "General Financial Planning"
    
    if not purpose:
        return "Health Insurance" if age and int(age) > 40 else "Mutual Funds"

    purpose_clean = re.sub(r'[^\w\s]', ' ', str(purpose).lower())
    
    health_keywords = {'mri': 3, 'scan': 2, 'surgery': 3, 'pain': 1, 'accident': 3, 'operation': 3, 'tumor': 3}
    life_keywords = {'cardiac': 3, 'heart': 3, 't2': 2, 'ecg': 2, 'chest': 2}
    mf_keywords = {'routine': 2, 'blood test': 3, 'fitness': 3, 'checkup': 2, 'parameters': 2, 'healthy': 3}

    scores = {'Health Insurance': 0, 'Life Insurance': 0, 'Mutual Funds': 0}

    for word, weight in health_keywords.items():
        if word in purpose_clean: scores['Health Insurance'] += weight
    for word, weight in life_keywords.items():
        if word in purpose_clean: scores['Life Insurance'] += weight
    for word, weight in mf_keywords.items():
        if word in purpose_clean: scores['Mutual Funds'] += weight

    if age:
        age_num = int(age)
        if age_num > 50: scores['Health Insurance'] += 2
        elif 25 <= age_num <= 40: scores['Mutual Funds'] += 2; scores['Life Insurance'] += 1

    max_score = max(scores.values())
    if max_score == 0:
        return "Health Insurance" if age and int(age) > 45 else "Mutual Funds"
    
    return max(scores, key=scores.get)


# --- API ENDPOINTS ---

@app.route('/')
def checkin_ui():
    return render_template('index.html')

@app.route('/admin')
def admin_ui():
    return render_template('admin.html')

@app.route('/api/submit_checkin', methods=['POST'])
def submit_checkin():
    data = request.json
    
    # Generate Unique ID
    patient_id = f"PAT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # 1. Process AI Lead Prediction
    predicted_lead = intelligent_lead_router(data.get('purpose'), data.get('age'))
    
    patient_record = {
        "patient_id": patient_id,
        "name": data['name'],
        "age": data['age'],
        "gender": data['gender'],
        "contact": data['contact'],
        "visit_type": data['visit_type'],
        "purpose": data.get('purpose', ''),
        "ai_predicted_lead": predicted_lead,
        "checkin_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    # 2. Save to MongoDB
    db.patients.insert_one(patient_record)
    
    # 3. Update Campaign Analytics (Campaign-wise tracking)
    campaign_id = data.get('campaign', 'direct_walkin')
    if campaign_id not in manualConvStore:
        manualConvStore[campaign_id] = 0
    manualConvStore[campaign_id] += 1

    return jsonify({"status": "success", "patient_id": patient_id, "lead_type": predicted_lead}), 201

# The API that formats MongoDB data to look like Google Sheets
@app.route('/api/sheet_data', methods=['GET'])
def get_sheet_data():
    patients = list(db.patients.find({}, {'_id': 0}).sort("checkin_time", -1))
    
    # Formatting as 2D Array for the Spreadsheet UI
    sheet_rows = []
    for p in patients:
        sheet_rows.append([
            p.get('checkin_time'), p.get('patient_id'), p.get('name'), 
            p.get('age'), p.get('contact'), p.get('visit_type'), 
            p.get('purpose'), p.get('ai_predicted_lead')
        ])
        
    return jsonify({"data": sheet_rows, "campaign_stats": manualConvStore}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, threaded=True)
