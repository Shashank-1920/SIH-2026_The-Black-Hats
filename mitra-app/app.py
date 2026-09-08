from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text, or_
from werkzeug.security import generate_password_hash, check_password_hash
import random
import secrets
import json
import urllib.request
import urllib.error
from datetime import date, datetime
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'mitra_super_secret_key')

# Use PostgreSQL via DATABASE_URL, fallback to SQLite if not provided for safety during dev
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///mitra.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
_schema_ready = False


def ensure_schema():
    """Apply additive schema updates needed by the current prototype models."""
    global _schema_ready
    if _schema_ready:
        return

    with app.app_context():
        db.create_all()
        inspector = inspect(db.engine)
        document_columns = {column['name'] for column in inspector.get_columns('document')}
        additions = {
            'extracted_data': 'TEXT',
            'verified_data': 'TEXT',
        }
        missing = {name: sql_type for name, sql_type in additions.items() if name not in document_columns}
        if missing:
            with db.engine.begin() as connection:
                for name, sql_type in missing.items():
                    connection.execute(text(f'ALTER TABLE document ADD COLUMN {name} {sql_type}'))
        appointment_columns = {column['name'] for column in inspector.get_columns('appointment')}
        if 'original_doctor_id' not in appointment_columns:
            with db.engine.begin() as connection:
                connection.execute(text('ALTER TABLE appointment ADD COLUMN original_doctor_id INTEGER'))
        if 'appointment_date' not in appointment_columns:
            with db.engine.begin() as connection:
                connection.execute(text('ALTER TABLE appointment ADD COLUMN appointment_date DATE'))
        for column_name, column_type in {
            'priority': 'INTEGER DEFAULT 0',
            'emergency_status': "VARCHAR(20) DEFAULT 'none'",
            'emergency_note': 'TEXT',
            'arrival_status': "VARCHAR(20) DEFAULT 'pending'",
            'arrival_verified_at': 'TIMESTAMP',
            'vitals_data': 'TEXT',
        }.items():
            if column_name not in appointment_columns:
                with db.engine.begin() as connection:
                    connection.execute(text(f'ALTER TABLE appointment ADD COLUMN {column_name} {column_type}'))
        with db.engine.begin() as connection:
            connection.execute(text('UPDATE appointment SET appointment_date = CURRENT_DATE WHERE appointment_date IS NULL'))
        user_columns = {column['name'] for column in inspector.get_columns('user')}
        if 'phone_number' not in user_columns:
            with db.engine.begin() as connection:
                connection.execute(text('ALTER TABLE "user" ADD COLUMN phone_number VARCHAR(20)'))
        document_columns = {column['name'] for column in inspector.get_columns('document')}
        if 'created_at' not in document_columns:
            with db.engine.begin() as connection:
                connection.execute(text('ALTER TABLE document ADD COLUMN created_at TIMESTAMP'))
                connection.execute(text('UPDATE document SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL'))
        _schema_ready = True


@app.before_request
def prepare_database_schema():
    ensure_schema()

# ================= Models =================

class Hospital(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    location = db.Column(db.String(255), nullable=False)
    contact_number = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False) # 'patient', 'desk', 'doctor'
    full_name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(20), nullable=True)

class HospitalDesk(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    hospital_id = db.Column(db.Integer, db.ForeignKey('hospital.id'), nullable=False)
    department = db.Column(db.String(100), nullable=True)

    user = db.relationship('User', backref=db.backref('desk_profile', uselist=False))
    hospital = db.relationship('Hospital')

class DoctorProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    hospital_id = db.Column(db.Integer, db.ForeignKey('hospital.id'), nullable=True)
    department = db.Column(db.String(100), nullable=False)
    daily_quota = db.Column(db.Integer, default=100)
    is_available = db.Column(db.Boolean, default=True) # Failsafe toggle if doctor backs out
    rating = db.Column(db.Float, default=0.0) # Doctor rating (e.g. 4.8)
    total_reviews = db.Column(db.Integer, default=0) # Number of reviews
    
    user = db.relationship('User', backref=db.backref('doctor_profile', uselist=False))
    hospital = db.relationship('Hospital')

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    original_doctor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    booking_type = db.Column(db.String(20)) # 'online' (max 40%) or 'offline' (max 60%)
    time_slot = db.Column(db.String(50)) # e.g., "10:00 AM - 11:00 AM" (Hourly batches)
    appointment_date = db.Column(db.Date, nullable=True)
    priority = db.Column(db.Integer, default=0)
    emergency_status = db.Column(db.String(20), default='none') # none, requested, confirmed, resolved
    emergency_note = db.Column(db.Text)
    arrival_status = db.Column(db.String(20), default='pending') # pending, arrived, no_show
    arrival_verified_at = db.Column(db.DateTime, nullable=True)
    vitals_data = db.Column(db.Text) # JSON entered by hospital desk
    status = db.Column(db.String(20), default='scheduled') # 'scheduled', 'completed', 're-routed'
    
    patient = db.relationship('User', foreign_keys=[patient_id])
    doctor = db.relationship('User', foreign_keys=[doctor_id])
    original_doctor = db.relationship('User', foreign_keys=[original_doctor_id])

class ClinicalRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=False)
    consent_given = db.Column(db.Boolean, default=False)
    chief_complaint = db.Column(db.Text)
    history_data = db.Column(db.Text) # JSON string of adaptive history
    is_ayush = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='intake_pending') # intake_pending, submitted, triage_complete
    
    appointment = db.relationship('Appointment', backref=db.backref('clinical_record', uselist=False))

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    doc_type = db.Column(db.String(50)) # e.g. 'prescription', 'lab_report'
    ocr_status = db.Column(db.String(20), default='pending') # pending, complete
    extracted_text = db.Column(db.Text)
    extracted_data = db.Column(db.Text)  # JSON: OCR entities awaiting verification
    verified_data = db.Column(db.Text)   # JSON: patient-confirmed entities
    is_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AIAnalysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=False)
    version = db.Column(db.Integer, default=1)
    analysis_json = db.Column(db.Text, nullable=False)
    doctor_status = db.Column(db.String(20), default='pending')  # pending, approved, modified, rejected
    certified_record = db.Column(db.Text)  # JSON: doctor-approved final record
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    appointment = db.relationship('Appointment', backref=db.backref('ai_analyses', lazy=True))

class Alert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=False)
    alert_type = db.Column(db.String(50), nullable=False)  # red_flag, intake_complete, arrival
    severity = db.Column(db.String(20), default='medium')  # low, medium, high
    message = db.Column(db.Text, nullable=False)
    recipient_role = db.Column(db.String(20), default='desk')  # desk, doctor
    status = db.Column(db.String(20), default='open')  # open, acknowledged, resolved
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    appointment = db.relationship('Appointment', backref=db.backref('alerts', lazy=True))


# ================= AI Engine (Gemini-ready orchestrator) =================

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
MAX_AI_INPUT_CHARS = 12000
MAX_CHAT_MESSAGES = 80

CLINICAL_SECTIONS = [
    'chief_complaint', 'onset', 'character', 'location', 'radiation',
    'aggravating', 'relieving', 'associated', 'past_medical', 'medications',
    'allergies', 'family_history', 'review_of_systems'
]

AYUSH_SECTIONS = ['prakriti', 'vikriti', 'agni', 'koshtha', 'ahara', 'vihara']

SYMPTOM_KEYWORDS = {
    'chest': ['chest', 'heart', 'చాతి', 'గుండె', 'sternal'],
    'breath': ['breath', 'breathing', 'breathless', 'ఊపిరి', 'shortness'],
    'head': ['headache', 'head', 'తల', 'తలనొప్పి'],
    'fever': ['fever', 'temperature', 'జ్వరం', 'heat'],
    'abdominal': ['stomach', 'abdomen', 'abdominal', 'pet', 'పేగు', 'బాగ'],
}

CHEST_PAIN_FLOW = [
    ('onset', 'When did the discomfort start? Was it sudden or gradual?',
             'ఈ సమస్య ఎప్పుడు మొదలైంది? అకస్మాత్తుగా వచ్చిందా లేదా క్రమంగా?'),
    ('character', 'What does the pain feel like — sharp, dull, pressure, or burning?',
                  'నొప్పి ఎలా ఉంది — పదునైన, మందమైన, ఒత్తిడి, లేదా మంట?'),
    ('location', 'Where exactly do you feel it? Does it spread to your arm, jaw, or back?',
                 'ఎక్కడ సరిగga అనిపిస్తుంది? చేతికి, దవడకు, లేదా వెనకకు వ్యాపిస్తుందా?'),
    ('aggravating', 'What makes it worse — walking, stress, or deep breathing?',
                   'ఏమి చేస్తే మరింత అవుతుంది — నడవడం, stress, లేదా లోతైన ఊపిరి?'),
    ('relieving', 'What makes it better — rest or medication?',
                 'ఏమి చేస్తే తగ్గుతుంది — విశ్రాంతి లేదా మందు?'),
    ('associated', 'Any breathlessness, sweating, dizziness, or nausea?',
                   'ఊపిరి తక్కువ, చెమట, తలతిరగ, లేదా వికారం ఉందా?'),
]

GENERIC_FLOW = [
    ('onset', 'How long have you had this problem?',
             'ఈ సమస్య ఎంత కాలంగా ఉంది?'),
    ('character', 'Can you describe how it feels?',
                  'అది ఎలా అనిపిస్తుంది?'),
    ('associated', 'Any other symptoms along with this?',
                   'దీనితో పాటు ఇతర లక్షణాలు ఉన్నాయా?'),
]


def call_gemini(system_prompt, user_prompt, json_mode=True):
    """Call Gemini when GEMINI_API_KEY is set; otherwise return None for fallback."""
    if not GEMINI_API_KEY:
        return None
    system_prompt = str(system_prompt)[:4000]
    user_prompt = str(user_prompt)[:MAX_AI_INPUT_CHARS]
    payload = {
        'contents': [{'parts': [{'text': f"{system_prompt}\n\n{user_prompt}"}]}],
        'generationConfig': {'temperature': 0.2, 'maxOutputTokens': 1200}
    }
    if json_mode:
        payload['generationConfig']['responseMimeType'] = 'application/json'
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}'
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}, method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            text = body['candidates'][0]['content']['parts'][0]['text']
            return json.loads(text) if json_mode else text
    except (urllib.error.URLError, TimeoutError, KeyError, TypeError, ValueError, json.JSONDecodeError, IndexError):
        return None


def safe_json(value, default):
    """Parse untrusted JSON without allowing one bad record to break the workflow."""
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, type(default)) else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def bounded_int(value, default=0, minimum=0, maximum=100):
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def bounded_float(value, default=0.5, minimum=0.0, maximum=1.0):
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return default


def clean_history(chat_history):
    """Bound and normalize client-provided chat history before AI processing."""
    cleaned = []
    for message in (chat_history or [])[-MAX_CHAT_MESSAGES:]:
        if not isinstance(message, dict) or message.get('role') not in ('patient', 'ai'):
            continue
        text = str(message.get('text', '')).strip()[:1000]
        if text:
            item = {'role': message['role'], 'text': text}
            if message['role'] == 'patient' and isinstance(message.get('structured_snapshot'), dict):
                item['structured_snapshot'] = message['structured_snapshot']
            cleaned.append(item)
    return cleaned


def detect_symptoms(text):
    text_lower = str(text or '').lower()
    found = []
    for symptom, keywords in SYMPTOM_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(symptom)
    return found


def get_patient_messages(chat_history):
    return [m['text'] for m in chat_history if m.get('role') == 'patient']


def intake_next_question(chat_history, structured, is_telugu=False, is_ayush=False):
    """Adaptive clinical intake — Gemini-enhanced with rule-based fallback."""
    chat_history = clean_history(chat_history)
    structured = structured if isinstance(structured, dict) else {}
    patient_msgs = get_patient_messages(chat_history)
    combined = ' '.join(patient_msgs).lower()

    if is_ayush and not structured.get('ayush_started'):
        structured['ayush_started'] = True
        q = ('Let us begin AYUSH assessment. What is your usual body constitution (Prakriti)?',
             'AYUSH అంచనా ప్రారంభిద్దాం. మీ సాధారణ శరీర స్వభావం (ప్రకృతి) ఏమిటి?')
        return _intake_response(q, structured, is_telugu, 10, ['Vata', 'Pitta', 'Kapha', 'Mixed'])

    gemini_result = call_gemini(
        'You are M.I.T.R.A clinical intake AI. Return JSON: {"question":"...","touch_options":["..."],"section":"...","completion_pct":N}. '
        'Ask ONE adaptive follow-up based on patient history. Never diagnose. Use clinical reasoning flow.',
        json.dumps({'history': chat_history, 'structured': structured, 'language': 'te' if is_telugu else 'en'})
    )
    if isinstance(gemini_result, dict) and gemini_result.get('question'):
        structured[gemini_result.get('section', 'general')] = True
        touch_options = gemini_result.get('touch_options', [])
        if not isinstance(touch_options, list):
            touch_options = []
        completion_pct = bounded_int(gemini_result.get('completion_pct', 50), 50)
        return {
            'question': str(gemini_result['question'])[:500],
            'touch_options': [str(option)[:100] for option in touch_options[:6]],
            'structured': structured,
            'completion_pct': completion_pct,
            'intake_complete': completion_pct >= 90
        }

    # Rule-based adaptive flow
    if not patient_msgs:
        q = ('Hello! What is the primary reason for your visit today?',
             'నమస్కారం! ఈ రోజు మీరు డాక్టర్‌ను ఎందుకు కలవాలనుకుంటున్నారు?')
        return _intake_response(q, structured, is_telugu, 5, [])

    symptoms = detect_symptoms(combined)
    flow = CHEST_PAIN_FLOW if 'chest' in symptoms else GENERIC_FLOW

    for section, en_q, te_q in flow:
        if not structured.get(section):
            structured[section] = True
            if section == 'chief_complaint' and patient_msgs:
                structured['chief_complaint'] = patient_msgs[0]
            touch = []
            if section == 'associated':
                touch = ['Breathlessness', 'Sweating', 'Dizziness', 'None']
            elif section == 'onset':
                touch = ['Sudden', 'Gradual', '1-3 days', 'More than a week']
            pct = int((list(structured.keys()).index(section) + 1) / len(flow) * 85)
            return _intake_response((en_q, te_q), structured, is_telugu, pct, touch)

    # Past history prompts after symptom flow
    for section, en_q, te_q in [
        ('medications', 'Are you currently taking any medications?', 'మీరు ప్రస్తుతం ఏ మందులు తీసుకుంటున్నారు?'),
        ('allergies', 'Do you have any drug allergies?', 'మీకు ఏ మందులకు అలర్జీ ఉందా?'),
    ]:
        if not structured.get(section):
            structured[section] = True
            return _intake_response((en_q, te_q), structured, is_telugu, 90, ['None', 'Penicillin', 'Other'])

    structured['complete'] = True
    q = ('Thank you. Clinical history is complete. You may proceed to upload documents.',
         'ధన్యవాదాలు. క్లినికల్ చరిత్ర పూర్తయింది. పత్రాలు upload చేయండి.')
    return _intake_response(q, structured, is_telugu, 100, [], intake_complete=True)


def _intake_response(q_tuple, structured, is_telugu, pct, touch, intake_complete=False):
    return {
        'question': q_tuple[1] if is_telugu else q_tuple[0],
        'touch_options': touch,
        'structured': structured,
        'completion_pct': pct,
        'intake_complete': intake_complete
    }


def process_document_ocr(filename, doc_type='lab_report'):
    """Simulated OCR pipeline — replace with real OCR when ready."""
    demo_extractions = {
        'prescription': [
            {'field': 'medication', 'value': 'Amlodipine — 5 mg — once daily', 'confidence': 0.92},
            {'field': 'diagnosis', 'value': 'Hypertension', 'confidence': 0.88},
        ],
        'lab_report': [
            {'field': 'investigation', 'value': 'Hb — 9.2 g/dL', 'confidence': 0.95},
            {'field': 'reference', 'value': 'Reference range: 13–17 g/dL', 'confidence': 0.94},
            {'field': 'status', 'value': 'Below normal', 'confidence': 0.90},
        ],
    }
    items = demo_extractions.get(doc_type, demo_extractions['lab_report'])
    return {
        'quality_ok': True,
        'quality_message': 'Document quality acceptable.',
        'extracted_text': f'OCR output for {filename}',
        'extractions': [{**item, 'status': 'pending'} for item in items]
    }


def run_clinical_analysis(record, verified_docs):
    """Generate structured AI health analysis from verified intake + documents."""
    history = clean_history(safe_json(record.history_data, []))
    structured = {}
    for msg in history:
        if msg.get('structured_snapshot'):
            structured = msg['structured_snapshot'] if isinstance(msg['structured_snapshot'], dict) else structured

    patient_text = ' '.join(get_patient_messages(history))[:MAX_AI_INPUT_CHARS]
    symptoms = detect_symptoms(patient_text)

    observed = []
    evidence = []
    if record.chief_complaint:
        observed.append(f"Chief complaint: {record.chief_complaint}")
        evidence.append({'source': 'patient_intake', 'field': 'chief_complaint',
                         'text': record.chief_complaint[:500]})
    elif patient_text:
        observed.append(f"Patient-reported: {patient_text[:200]}")
        evidence.append({'source': 'patient_intake', 'field': 'history',
                         'text': patient_text[:500]})

    for doc in verified_docs:
        if doc.verified_data:
            for item in safe_json(doc.verified_data, []):
                field = str(item.get('field', 'finding'))[:100]
                value = str(item.get('value', ''))[:300]
                observed.append(f"{field.title()}: {value}")
                evidence.append({'source': 'verified_document', 'document_id': doc.id,
                                 'document_type': doc.doc_type, 'field': field, 'text': value})

    concerns = []
    hypotheses = []
    uncertainty = []
    red_flags = []
    care_plan = {
        'tablet_schedule': [],
        'diet_plan': [
            'Prefer balanced meals with vegetables, fruit, pulses, and adequate water.',
            'Limit excess salt, packaged foods, and sugary drinks.'
        ],
        'status': 'AI suggestion - doctor certification required'
    }
    engine_source = 'rule_based'

    lower_text = patient_text.lower()
    if 'chest' in symptoms:
        concerns.append('Chest discomfort reported — requires clinician review')
        if any(w in lower_text for w in ['arm', 'radiat', 'spread', 'jaw', 'back', 'చేతి']):
            concerns.append('Possible pain radiation — priority review suggested')
            red_flags.append({'pattern': 'chest_pain + radiation', 'severity': 'high',
                              'message': 'Chest pain with possible radiation detected'})
        hypotheses.append({'text': 'Possible cardiac or musculoskeletal pain pattern', 'confidence': 0.55})

    if 'breath' in symptoms and 'chest' in symptoms:
        red_flags.append({'pattern': 'chest_pain + breathlessness', 'severity': 'high',
                          'message': 'Chest symptoms with breathlessness — urgent review'})
    if 'chest' in symptoms and any(w in lower_text for w in ['sweat', 'dizz', 'faint', 'nausea', 'vomit', 'చెమట']):
        red_flags.append({'pattern': 'chest_pain + associated_warning', 'severity': 'high',
                          'message': 'Chest symptoms with associated warning signs detected'})

    for doc in verified_docs:
        doc_data = safe_json(doc.verified_data, [])
        for item in doc_data:
            value = str(item.get('value', ''))
            if 'amlodipine' in value.lower():
                care_plan['tablet_schedule'].append('Amlodipine 5 mg - once daily - follow the doctor\'s prescribed timing.')
        if any('9.2' in str(item.get('value', '')) for item in doc_data):
            concerns.append('Hb 9.2 g/dL — below reference range (anemia pattern)')
            hypotheses.append({'text': 'Anemia — correlate with clinical presentation', 'confidence': 0.78})

    if not care_plan['tablet_schedule']:
        care_plan['tablet_schedule'].append('No tablet schedule proposed until a doctor reviews the medication history.')

    if not concerns:
        concerns.append('No acute patterns detected from available data — clinician review still required')
    uncertainty.append('AI analysis is preliminary — not a diagnosis')
    if 'associated' not in structured:
        uncertainty.append('Associated symptoms may be incomplete')

    gemini_result = call_gemini(
        'You are M.I.T.R.A clinical analysis AI. Return JSON with keys: observed_facts[], potential_concerns[], '
        'hypotheses[{text,confidence}], uncertainty[]. Never state confirmed diagnosis.',
        json.dumps({'history': history, 'verified_docs': [d.verified_data for d in verified_docs]})
    )
    if isinstance(gemini_result, dict):
        engine_source = 'gemini_with_rule_based_safety'
        model_observed = gemini_result.get('observed_facts')
        model_concerns = gemini_result.get('potential_concerns')
        model_hypotheses = gemini_result.get('hypotheses')
        model_uncertainty = gemini_result.get('uncertainty')
        if isinstance(model_observed, list) and model_observed:
            observed.extend(str(item)[:500] for item in model_observed if item)
            observed = list(dict.fromkeys(observed))[:20]
        if isinstance(model_concerns, list) and model_concerns:
            concerns.extend(str(item)[:500] for item in model_concerns if item)
            concerns = list(dict.fromkeys(concerns))[:20]
        if isinstance(model_hypotheses, list) and model_hypotheses:
            model_hypotheses = [{
                'text': str(item.get('text'))[:500],
                'confidence': bounded_float(item.get('confidence', 0.5))
            } for item in model_hypotheses if isinstance(item, dict) and item.get('text')][:20]
            hypotheses.extend(model_hypotheses)
        if isinstance(model_uncertainty, list) and model_uncertainty:
            uncertainty.extend(str(item)[:500] for item in model_uncertainty if item)
            uncertainty = list(dict.fromkeys(uncertainty))[:20]

    return {
        'observed_facts': observed,
        'evidence': evidence[:40],
        'relevant_context': [m for m in observed if 'Amlodipine' in m or 'Hb' in m],
        'potential_concerns': concerns,
        'hypotheses': hypotheses,
        'uncertainty': uncertainty,
        'red_flags': red_flags,
        'structured_history': structured,
        'care_plan': care_plan,
        'engine': {
            'source': engine_source,
            'version': 'mitra-clinical-v1',
            'doctor_required': True,
            'generated_at': datetime.utcnow().isoformat()
        },
    }


def medication_safety_check(analysis_json, proposed_meds=None):
    """Check allergies, duplicates, and known interactions."""
    warnings = []
    data = safe_json(analysis_json, {})
    facts = ' '.join(data.get('observed_facts', [])).lower()
    proposed = [str(med).strip().lower() for med in (proposed_meds or []) if str(med).strip()]

    if 'amlodipine' in facts:
        warnings.append({'type': 'context', 'message': 'Patient on Amlodipine 5mg — review BP meds before adding calcium channel blockers'})

    if proposed:
        if len(proposed) != len(set(proposed)):
            warnings.append({'type': 'duplicate', 'severity': 'medium', 'message': 'Duplicate medication suggestion detected — review therapy list'})
        for med in proposed:
            if 'nitrate' in med and 'amlodipine' in facts:
                warnings.append({'type': 'interaction', 'severity': 'high',
                                 'message': 'Potential interaction — physician review required'})

    allergy_terms = ('allergy', 'allergic', 'penicillin', 'sulfa', 'aspirin')
    if any(term in facts for term in allergy_terms):
        warnings.append({'type': 'allergy', 'severity': 'high', 'message': 'Documented allergy context — verify before prescribing'})

    if not warnings:
        warnings.append({'type': 'info', 'message': 'No critical medication conflicts detected from available records'})
    return warnings


def copilot_suggest(appointment_id, consult_message):
    """Live consultation copilot suggestions."""
    record = ClinicalRecord.query.filter_by(appointment_id=appointment_id).first()
    analysis = AIAnalysis.query.filter_by(appointment_id=appointment_id).order_by(AIAnalysis.version.desc()).first()
    context = analysis.analysis_json if analysis else '{}'

    gemini_result = call_gemini(
        'You are M.I.T.R.A doctor copilot. Return JSON: {"suggestion":"...","follow_up_questions":[],"translation":null}. '
        'Assist only — never make final clinical decisions.',
        json.dumps({'context': context, 'consult_message': consult_message})
    )
    if gemini_result and gemini_result.get('suggestion'):
        return gemini_result

    suggestion = 'Review pre-consult summary and verify symptom timeline with patient.'
    if 'pain' in consult_message.lower() or 'నొప్పి' in consult_message:
        suggestion = 'Patient reports pain — consider ECG and troponin given chest symptom context and Amlodipine use.'
    if 'walk' in consult_message.lower() or 'నడ' in consult_message:
        suggestion = 'Pain worsens with walking — assess for exertional angina pattern. Consider stress test referral.'

    translation = None
    if any('\u0c00' <= c <= '\u0c7f' for c in consult_message):
        translation = 'Patient speech detected in Telugu — translated context available in summary.'
    elif consult_message:
        translation = consult_message  # English passthrough for demo

    return {
        'suggestion': suggestion,
        'follow_up_questions': ['Any breathlessness at rest?', 'Current medication adherence?'],
        'translation': translation
    }


def patient_ai_answer(question, appointment_id):
    """Patient AI — only doctor-approved / verified information."""
    analysis = AIAnalysis.query.filter_by(appointment_id=appointment_id, doctor_status='approved').first()
    if not analysis or not analysis.certified_record:
        return {
            'answer': 'Your doctor has not yet certified clinical information for this visit. '
                      'Please contact your care team for medical advice.',
            'source': 'system'
        }

    certified = json.loads(analysis.certified_record)
    q = question.lower()

    gemini_result = call_gemini(
        'You are Patient AI for M.I.T.R.A. Answer ONLY from certified_record JSON. Never diagnose. '
        'If concern is new, say to contact care team. Return JSON: {"answer":"...","source":"approved_record"}.',
        json.dumps({'certified_record': certified, 'question': question})
    )
    if gemini_result and gemini_result.get('answer'):
        return gemini_result

    if any(w in q for w in ['medicine', 'medication', 'tablet', 'మందు']):
        return {'answer': certified.get('medications', 'Follow your prescribed medications as advised by your doctor.'), 'source': 'approved_record'}
    if any(w in q for w in ['precaution', 'care', 'follow']):
        return {'answer': certified.get('precautions', 'Rest, avoid strenuous activity, follow up as scheduled.'), 'source': 'approved_record'}
    if any(w in q for w in ['diagnosis', 'finding', 'doctor say']):
        return {'answer': certified.get('diagnosis', 'Your doctor will discuss findings during your visit.'), 'source': 'approved_record'}

    return {'answer': 'I can only share doctor-approved information. Please ask about medications, precautions, or follow-up.', 'source': 'approved_record'}


def summarize_patient_documents(patient_id):
    """Create a non-diagnostic summary from the patient's verified records."""
    documents = Document.query.filter_by(patient_id=patient_id, is_verified=True).order_by(Document.created_at.desc()).all()
    findings = []
    for document in documents:
        items = safe_json(document.verified_data, [])
        for item in items:
            findings.append({
                'date': document.created_at.isoformat() if document.created_at else None,
                'document': document.filename,
                'type': document.doc_type,
                'field': item.get('field', 'finding'),
                'value': item.get('value', '')
            })
    return {
        'document_count': len(documents),
        'documents': findings,
        'summary': 'Verified record findings are listed chronologically for review. This is not a diagnosis.' if findings else 'No patient-verified records are available yet.'
    }


def create_red_flag_alerts(appointment_id, red_flags):
    for rf in red_flags:
        for role in ['desk', 'doctor']:
            alert = Alert(
                appointment_id=appointment_id,
                alert_type='red_flag',
                severity=rf.get('severity', 'high'),
                message=rf.get('message', rf.get('pattern', 'Clinical red flag')),
                recipient_role=role,
                status='open'
            )
            db.session.add(alert)


def get_authorized_appointment(appointment_id, role):
    """Return an appointment only when the signed-in role owns its context."""
    appt = Appointment.query.get(appointment_id)
    if not appt:
        return None
    if role == 'patient' and appt.patient_id != session.get('user_id'):
        return None
    if role == 'doctor' and appt.doctor_id != session.get('user_id'):
        return None
    if role == 'desk':
        desk = HospitalDesk.query.filter_by(user_id=session.get('user_id')).first()
        doctor_profile = DoctorProfile.query.filter_by(user_id=appt.doctor_id).first()
        if not desk or not doctor_profile or doctor_profile.hospital_id != desk.hospital_id:
            return None
    return appt

# ================= Authentication Routes =================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET'])
def login():
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    login_type = data.get('login_type')
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'success': False, 'message': 'Missing credentials'}), 400

    user = User.query.filter_by(username=username).first()

    if user and check_password_hash(user.password_hash, password):
        if login_type == 'patient' and user.role != 'patient':
            return jsonify({'success': False, 'message': 'Invalid login type.'}), 403
        if login_type == 'staff' and user.role not in ['desk', 'doctor']:
             return jsonify({'success': False, 'message': 'Invalid login type.'}), 403

        session['user_id'] = user.id
        session['role'] = user.role
        session['name'] = user.full_name
        return jsonify({
            'success': True, 
            'message': 'Login successful',
            'redirect_url': '/dashboard'
        })
    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401


@app.route('/api/register', methods=['POST'])
def api_register():
    """Create a patient account and start its authenticated session."""
    data = request.get_json(silent=True) or {}
    full_name = str(data.get('full_name', '')).strip()
    password = str(data.get('password', ''))
    confirm_password = str(data.get('confirm_password', ''))
    phone_number = str(data.get('phone_number', '')).strip()[:20]

    if len(full_name) < 2 or len(full_name) > 100:
        return jsonify({'success': False, 'message': 'Enter a valid full name.'}), 400
    if len(password) < 8:
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters.'}), 400
    if password != confirm_password:
        return jsonify({'success': False, 'message': 'Passwords do not match.'}), 400

    patient_id = None
    for _ in range(10):
        candidate = f'PT-{random.randint(10000, 99999)}'
        if not User.query.filter_by(username=candidate).first():
            patient_id = candidate
            break
    if not patient_id:
        return jsonify({'success': False, 'message': 'Could not create a patient ID. Please try again.'}), 503

    patient = User(
        username=patient_id,
        password_hash=generate_password_hash(password),
        role='patient',
        full_name=full_name,
        phone_number=phone_number or None
    )
    db.session.add(patient)
    db.session.commit()
    session['user_id'] = patient.id
    session['role'] = patient.role
    session['name'] = patient.full_name
    return jsonify({
        'success': True,
        'message': 'Patient account created successfully.',
        'patient_id': patient.username,
        'redirect_url': '/dashboard'
    })

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    role = session.get('role')
    
    if role == 'patient':
        # Fetch active doctors for the booking UI
        doctors = DoctorProfile.query.filter_by(is_available=True).all()
        
        # Format doctor data
        doc_list = []
        for d in doctors:
            doc_list.append({
                'id': d.user_id,
                'name': d.user.full_name,
                'department': d.department,
                'rating': d.rating,
                'reviews': d.total_reviews,
                'hospital': d.hospital.name if d.hospital else "General"
            })
            
        latest_appt = Appointment.query.filter_by(patient_id=session['user_id']).order_by(Appointment.id.desc()).first()
        certified = {}
        if latest_appt:
            latest_analysis = AIAnalysis.query.filter_by(appointment_id=latest_appt.id, doctor_status='approved').order_by(AIAnalysis.version.desc()).first()
            certified = safe_json(latest_analysis.certified_record, {}) if latest_analysis and latest_analysis.certified_record else {}
        patient_documents = Document.query.filter_by(patient_id=session['user_id']).order_by(Document.created_at.desc()).all()
        return render_template('patient_dashboard.html', user=session, doctors=doc_list,
                               latest_appt=latest_appt, certified_record=certified,
                               patient_documents=patient_documents,
                               today=date.today().isoformat())
        
    elif role == 'desk':
        desk = HospitalDesk.query.filter_by(user_id=session['user_id']).first()
        doctors = DoctorProfile.query.filter_by(hospital_id=desk.hospital_id).all() if desk else []
        appts = Appointment.query.join(DoctorProfile, Appointment.doctor_id == DoctorProfile.user_id).filter(DoctorProfile.hospital_id == desk.hospital_id).all() if desk else []
        alerts = Alert.query.filter_by(recipient_role='desk', status='open').order_by(Alert.created_at.desc()).limit(20).all()
        schedules = {doctor.user_id: {
            'name': doctor.user.full_name,
            'department': doctor.department,
            'appointments': sorted(
                [appt for appt in appts if appt.doctor_id == doctor.user_id],
                key=lambda item: (item.appointment_date or date.max, -item.priority, item.time_slot or '')
            )
        } for doctor in doctors}
        patients = User.query.filter_by(role='patient').order_by(User.full_name.asc()).all()
        return render_template('desk_dashboard.html', user=session, doctors=doctors, appointments=appts,
                               schedules=schedules, patients=patients, alerts=alerts)
        
    elif role == 'doctor':
        appts = Appointment.query.filter(
            or_(Appointment.doctor_id == session['user_id'],
                Appointment.original_doctor_id == session['user_id'])
        ).all()
        alerts = Alert.query.filter_by(recipient_role='doctor', status='open').order_by(Alert.created_at.desc()).limit(20).all()
        return render_template('doctor_dashboard.html', user=session, appointments=appts, alerts=alerts)
        
    return f"<h1>Welcome {session['name']}!</h1><p>Role: {role}</p><a href='/logout'>Logout</a>"


# ================= Appointment System Routes =================

def get_doctor_availability(doctor_id, booking_type):
    """Calculates if a doctor has quota left based on the 40/60 split rule."""
    doc = DoctorProfile.query.filter_by(user_id=doctor_id).first()
    if not doc or not doc.is_available:
        return False
    
    max_online = int(doc.daily_quota * 0.40)
    max_offline = int(doc.daily_quota * 0.60)
    
    current_count = Appointment.query.filter_by(doctor_id=doctor_id, booking_type=booking_type, status='scheduled').count()
    
    if booking_type == 'online' and current_count >= max_online:
        return False
    if booking_type == 'offline' and current_count >= max_offline:
        return False
        
    return True

@app.route('/api/appointments/book', methods=['POST'])
def book_appointment():
    """Handles both specific doctor selection and 'quick appointment' (random assignment)"""
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    data = request.json
    patient_id = session['user_id']
    created_new_patient = False
    if session.get('role') == 'desk':
        patient_name = str(data.get('patient_name', '')).strip()
        patient_id_value = data.get('patient_id')
        patient = User.query.filter_by(id=patient_id_value, role='patient').first() if patient_id_value else None
        if not patient and patient_name:
            patient = User.query.filter(
                User.role == 'patient',
                or_(User.full_name.ilike(patient_name), User.username.ilike(patient_name))
            ).first()
        desk = HospitalDesk.query.filter_by(user_id=session['user_id']).first()
        if not patient_name and not patient:
            return jsonify({'success': False, 'message': 'Enter a patient name or Patient ID.'}), 400
        if not desk:
            return jsonify({'success': False, 'message': 'Hospital desk profile not found.'}), 403
        if not patient:
            generated_id = None
            for _ in range(10):
                candidate = f'PT-{random.randint(10000, 99999)}'
                if not User.query.filter_by(username=candidate).first():
                    generated_id = candidate
                    break
            if not generated_id:
                return jsonify({'success': False, 'message': 'Could not create a Patient ID. Please try again.'}), 503
            patient = User(
                username=generated_id,
                password_hash=generate_password_hash(secrets.token_urlsafe(18)),
                role='patient',
                full_name=patient_name,
                phone_number=str(data.get('phone_number', '')).strip()[:20] or None
            )
            db.session.add(patient)
            db.session.flush()
            created_new_patient = True
        if not DoctorProfile.query.filter_by(user_id=data.get('doctor_id'), hospital_id=desk.hospital_id).first():
            return jsonify({'success': False, 'message': 'Doctor is outside your hospital.'}), 403
    elif session.get('role') != 'patient':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    booking_type = data.get('booking_type', 'online') # online (patient app) or offline (desk)
    department = data.get('department')
    doctor_id = data.get('doctor_id') # If None, do random assignment
    time_slot = data.get('time_slot') # e.g. "10:00-11:00"
    appointment_date = data.get('appointment_date') or date.today().isoformat()
    try:
        appointment_date = date.fromisoformat(appointment_date)
    except (TypeError, ValueError):
        return jsonify({'success': False, 'message': 'Choose a valid appointment date.'}), 400
    if appointment_date < date.today():
        return jsonify({'success': False, 'message': 'Appointment date cannot be in the past.'}), 400

    # Quick Appointment / Random Assignment
    if not doctor_id:
        if not department:
            return jsonify({'success': False, 'message': 'Department required for quick appointment.'}), 400
            
        available_doctors = DoctorProfile.query.filter_by(department=department, is_available=True).all()
        valid_doctors = [d for d in available_doctors if get_doctor_availability(d.user_id, booking_type)]
        
        if not valid_doctors:
            return jsonify({'success': False, 'message': 'No doctors available in this department right now.'}), 404
            
        selected_doctor = random.choice(valid_doctors)
        doctor_id = selected_doctor.user_id
    else:
        # Specific Doctor Booking
        if not get_doctor_availability(doctor_id, booking_type):
            return jsonify({'success': False, 'message': 'Doctor quota full for this booking type.'}), 400

    new_appt = Appointment(
        patient_id=patient_id,
        doctor_id=doctor_id,
        booking_type=booking_type,
        time_slot=time_slot,
        appointment_date=appointment_date,
        status='scheduled',
        priority=0
    )
    db.session.add(new_appt)
    db.session.flush()

    # Carry verified standalone records into the new visit and analyze them immediately.
    standalone_docs = Document.query.filter_by(
        patient_id=patient_id, appointment_id=None, is_verified=True
    ).all()
    document_analysis_created = False
    if standalone_docs:
        record = ClinicalRecord(appointment_id=new_appt.id, status='intake_pending')
        db.session.add(record)
        db.session.flush()
        analysis_data = run_clinical_analysis(record, standalone_docs)
        db.session.add(AIAnalysis(
            appointment_id=new_appt.id,
            version=1,
            analysis_json=json.dumps(analysis_data),
            doctor_status='pending'
        ))
        for document in standalone_docs:
            document.appointment_id = new_appt.id
        db.session.add(Alert(
            appointment_id=new_appt.id,
            alert_type='document_analysis',
            severity='low',
            message=f'{len(standalone_docs)} verified patient record(s) analyzed for this appointment.',
            recipient_role='doctor',
            status='open'
        ))
        document_analysis_created = True
    db.session.commit()
    
    doc_name = User.query.get(doctor_id).full_name
    return jsonify({
        'success': True, 
        'message': f'Appointment booked successfully with {doc_name} for batch {time_slot}.',
        'doctor_id': doctor_id,
        'appointment_id': new_appt.id,
        'patient_id': patient.username if session.get('role') == 'desk' else None,
        'new_patient': created_new_patient,
        'document_analysis_created': document_analysis_created
    })


@app.route('/api/appointments/emergency', methods=['POST'])
def request_emergency():
    if session.get('role') != 'patient':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    data = request.get_json(silent=True) or {}
    appt = get_authorized_appointment(data.get('appointment_id'), 'patient')
    if not appt:
        return jsonify({'success': False, 'message': 'Appointment not found'}), 404
    appt.emergency_status = 'requested'
    appt.emergency_note = str(data.get('note', 'Patient requested emergency assistance.'))[:500]
    appt.priority = 100
    db.session.add(Alert(appointment_id=appt.id, alert_type='emergency_request', severity='high',
                         message=f'Emergency contact requested: {appt.emergency_note}',
                         recipient_role='desk', status='open'))
    db.session.commit()
    return jsonify({'success': True, 'message': 'Emergency request sent to the hospital desk.'})


@app.route('/api/appointments/emergency/confirm', methods=['POST'])
def confirm_emergency():
    if session.get('role') != 'desk':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    data = request.get_json(silent=True) or {}
    appt = get_authorized_appointment(data.get('appointment_id'), 'desk')
    if not appt or appt.emergency_status != 'requested':
        return jsonify({'success': False, 'message': 'Emergency request not found.'}), 404
    appt.emergency_status = 'confirmed'
    appt.priority = 100
    db.session.add(Alert(appointment_id=appt.id, alert_type='emergency_confirmed', severity='high',
                         message='Hospital desk contacted and confirmed emergency assistance.',
                         recipient_role='doctor', status='open'))
    db.session.commit()
    return jsonify({'success': True, 'message': 'Emergency confirmed and patient moved to priority queue.'})


@app.route('/api/appointments/arrival-vitals', methods=['POST'])
def save_arrival_vitals():
    """Hospital desk verifies arrival and records configurable basic vitals."""
    if session.get('role') != 'desk':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    data = request.get_json(silent=True) or {}
    appointment = get_authorized_appointment(data.get('appointment_id'), 'desk')
    if not appointment:
        return jsonify({'success': False, 'message': 'Appointment not found'}), 404

    def clean_vital(key, maximum=30):
        return str(data.get(key, '')).strip()[:maximum]

    vitals = {
        'height_cm': clean_vital('height_cm'),
        'weight_kg': clean_vital('weight_kg'),
        'temperature_c': clean_vital('temperature_c'),
        'blood_pressure': clean_vital('blood_pressure'),
        'pulse_bpm': clean_vital('pulse_bpm'),
        'oxygen_saturation': clean_vital('oxygen_saturation'),
        'notes': clean_vital('notes', 200),
    }
    if not any(vitals.values()):
        return jsonify({'success': False, 'message': 'Enter at least one vital sign.'}), 400

    appointment.arrival_status = 'arrived'
    appointment.arrival_verified_at = datetime.utcnow()
    appointment.vitals_data = json.dumps(vitals)
    db.session.add(Alert(
        appointment_id=appointment.id,
        alert_type='arrival_vitals',
        severity='low',
        message='Patient arrival and vitals verified by hospital desk.',
        recipient_role='doctor',
        status='open'
    ))
    db.session.commit()
    return jsonify({'success': True, 'message': 'Arrival and vitals sent to the doctor.'})

@app.route('/api/appointments/failsafe', methods=['POST'])
def trigger_failsafe():
    """Fail-safe: If a doctor backs out, re-route all their patients to other available doctors in the same department."""
    if session.get('role') not in ['desk', 'management']:
         return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    data = request.json
    backed_out_doctor_id = data.get('doctor_id')
    
    doc_profile = DoctorProfile.query.filter_by(user_id=backed_out_doctor_id).first()
    if not doc_profile:
        return jsonify({'success': False, 'message': 'Doctor not found'}), 404
        
    # Mark as unavailable
    doc_profile.is_available = False
    
    # Get all scheduled appointments for this doctor
    affected_appts = Appointment.query.filter_by(doctor_id=backed_out_doctor_id, status='scheduled').all()
    
    # Find replacement doctors in the same department
    available_replacements = DoctorProfile.query.filter(
        DoctorProfile.department == doc_profile.department,
        DoctorProfile.user_id != backed_out_doctor_id,
        DoctorProfile.is_available == True
    ).all()
    
    if not available_replacements:
        db.session.commit()
        return jsonify({'success': False, 'message': 'Doctor marked unavailable. No replacement doctors available for re-routing!'}), 400
        
    rerouted_count = 0
    for appt in affected_appts:
        # Try to find a replacement doctor that still has quota
        for rep_doc in available_replacements:
            if get_doctor_availability(rep_doc.user_id, appt.booking_type):
                appt.original_doctor_id = backed_out_doctor_id
                appt.doctor_id = rep_doc.user_id
                appt.status = 're-routed'
                rerouted_count += 1
                break
                
    db.session.commit()
    return jsonify({
        'success': True,
        'message': f'Failsafe triggered. {rerouted_count} appointments successfully re-routed.'
    })


@app.route('/api/appointments/failsafe/revert', methods=['POST'])
def revert_failsafe():
    """Return a re-routed appointment to the doctor it originally belonged to."""
    role = session.get('role')
    if role not in ['desk', 'doctor']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403

    data = request.get_json(silent=True) or {}
    appt = Appointment.query.get(data.get('appointment_id'))
    if not appt or appt.status != 're-routed' or not appt.original_doctor_id:
        return jsonify({'success': False, 'message': 'No reversible failsafe found for this appointment.'}), 404
    if role == 'doctor' and appt.original_doctor_id != session.get('user_id'):
        return jsonify({'success': False, 'message': 'Only the original doctor can revert this failsafe.'}), 403
    if role == 'desk' and not get_authorized_appointment(appt.id, 'desk'):
        return jsonify({'success': False, 'message': 'Appointment is outside your hospital.'}), 403

    original_doctor_id = appt.original_doctor_id
    appt.doctor_id = original_doctor_id
    appt.original_doctor_id = None
    appt.status = 'scheduled'
    db.session.add(Alert(
        appointment_id=appt.id,
        alert_type='failsafe_reverted',
        severity='low',
        message='Appointment returned to its original doctor.',
        recipient_role='doctor',
        status='open'
    ))
    db.session.commit()
    return jsonify({'success': True, 'message': 'Failsafe reverted. Appointment returned to the original doctor.'})


# ================= Clinical Intake & Document Routes =================

@app.route('/intake/<int:appt_id>')
def patient_intake(appt_id):
    """Renders the frontend intake UI (Consent -> Chat -> Upload)"""
    if session.get('role') != 'patient':
        return redirect(url_for('login'))
        
    appt = Appointment.query.get_or_404(appt_id)
    if appt.patient_id != session['user_id']:
        return "Unauthorized", 403
        
    # Create a blank clinical record if it doesn't exist
    record = ClinicalRecord.query.filter_by(appointment_id=appt_id).first()
    if not record:
        record = ClinicalRecord(appointment_id=appt_id)
        db.session.add(record)
        db.session.commit()
        
    return render_template('intake.html', user=session, appointment=appt, record=record)

@app.route('/api/intake/submit', methods=['POST'])
def submit_intake():
    """Receives intake, runs AI analysis, creates alerts."""
    if session.get('role') != 'patient':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    data = request.json
    appt_id = data.get('appointment_id')
    
    record = ClinicalRecord.query.filter_by(appointment_id=appt_id).first()
    if not record:
        return jsonify({'success': False, 'message': 'Record not found'}), 404
        
    record.consent_given = data.get('consent_given', False)
    record.chief_complaint = data.get('chief_complaint', '')
    record.history_data = data.get('history_data', '[]')
    record.is_ayush = data.get('is_ayush', False)
    record.status = 'submitted'

    verified_docs = Document.query.filter_by(appointment_id=appt_id, is_verified=True).all()
    analysis_data = run_clinical_analysis(record, verified_docs)

    last_version = AIAnalysis.query.filter_by(appointment_id=appt_id).order_by(AIAnalysis.version.desc()).first()
    new_version = (last_version.version + 1) if last_version else 1
    analysis = AIAnalysis(
        appointment_id=appt_id,
        version=new_version,
        analysis_json=json.dumps(analysis_data),
        doctor_status='pending'
    )
    db.session.add(analysis)

    if analysis_data.get('red_flags'):
        create_red_flag_alerts(appt_id, analysis_data['red_flags'])

    db.session.add(Alert(
        appointment_id=appt_id, alert_type='intake_complete', severity='low',
        message=f'Patient intake completed — AI Analysis v{new_version} ready',
        recipient_role='doctor', status='open'
    ))
    db.session.commit()

    msg = 'Intake submitted. AI analysis complete.'
    if analysis_data.get('red_flags'):
        msg += ' Priority alert sent to care team.'
    return jsonify({'success': True, 'message': msg, 'analysis_version': new_version,
                    'red_flags': len(analysis_data.get('red_flags', []))})


# ================= AI API Routes =================

@app.route('/api/ai/intake/next', methods=['POST'])
def ai_intake_next():
    if session.get('role') != 'patient':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    data = request.json
    result = intake_next_question(
        data.get('chat_history', []),
        data.get('structured', {}),
        data.get('is_telugu', False),
        data.get('is_ayush', False)
    )
    return jsonify({'success': True, **result})


@app.route('/api/ai/documents/process', methods=['POST'])
def ai_process_document():
    if session.get('role') != 'patient':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    data = request.json
    appt_id = data.get('appointment_id')
    if appt_id and not get_authorized_appointment(appt_id, 'patient'):
        return jsonify({'success': False, 'message': 'Appointment not found'}), 404
    filename = data.get('filename', 'uploaded_report.pdf')
    doc_type = data.get('doc_type', 'lab_report')

    ocr_result = process_document_ocr(filename, doc_type)
    if not ocr_result['quality_ok']:
        return jsonify({'success': False, 'message': ocr_result['quality_message']}), 400

    doc = Document(
        patient_id=session['user_id'],
        appointment_id=appt_id,
        filename=filename,
        doc_type=doc_type,
        ocr_status='complete',
        extracted_text=ocr_result['extracted_text'],
        extracted_data=json.dumps(ocr_result['extractions']),
        is_verified=False
    )
    db.session.add(doc)
    db.session.commit()
    return jsonify({'success': True, 'document_id': doc.id, **ocr_result})


@app.route('/api/ai/documents/verify', methods=['POST'])
def ai_verify_document():
    if session.get('role') != 'patient':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    data = request.json
    doc = Document.query.get(data.get('document_id'))
    if not doc or doc.patient_id != session['user_id'] or (doc.appointment_id and not get_authorized_appointment(doc.appointment_id, 'patient')):
        return jsonify({'success': False, 'message': 'Document not found'}), 404

    doc.verified_data = json.dumps(data.get('verified_items', []))
    doc.is_verified = True
    db.session.commit()
    return jsonify({'success': True, 'message': 'Verified information saved.'})


@app.route('/api/ai/summary/<int:appt_id>')
def ai_summary(appt_id):
    role = session.get('role')
    if role not in ['doctor', 'desk'] or not get_authorized_appointment(appt_id, role):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    record = ClinicalRecord.query.filter_by(appointment_id=appt_id).first()
    analysis = AIAnalysis.query.filter_by(appointment_id=appt_id).order_by(AIAnalysis.version.desc()).first()
    docs = Document.query.filter_by(appointment_id=appt_id).order_by(Document.id.desc()).all()
    if not analysis:
        return jsonify({'success': False, 'message': 'No analysis available'}), 404
    return jsonify({
        'success': True,
        'chief_complaint': record.chief_complaint if record else '',
        'arrival': {
            'status': appt.arrival_status,
            'verified_at': appt.arrival_verified_at.isoformat() if appt.arrival_verified_at else None,
            'vitals': safe_json(appt.vitals_data, {}) if appt.vitals_data else {}
        },
        'patient': {
            'name': analysis.appointment.patient.full_name,
            'patient_id': analysis.appointment.patient.username,
            'phone_number': analysis.appointment.patient.phone_number or 'Not provided'
        },
        'history': safe_json(record.history_data, []) if record and record.history_data else [],
        'analysis': safe_json(analysis.analysis_json, {}),
        'version': analysis.version,
        'doctor_status': analysis.doctor_status,
        'verified_documents': [safe_json(d.verified_data, []) for d in docs if d.verified_data],
        'documents': [{
            'id': d.id,
            'filename': d.filename,
            'doc_type': d.doc_type,
            'ocr_status': d.ocr_status,
            'is_verified': d.is_verified,
            'extracted_data': safe_json(d.extracted_data, []),
            'verified_data': safe_json(d.verified_data, []) if d.verified_data else []
        } for d in docs],
        'certified_record': safe_json(analysis.certified_record, {}) if analysis.certified_record else None
    })


@app.route('/api/ai/copilot', methods=['POST'])
def ai_copilot():
    if session.get('role') != 'doctor':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    data = request.json
    if not get_authorized_appointment(data.get('appointment_id'), 'doctor'):
        return jsonify({'success': False, 'message': 'Appointment not found'}), 404
    result = copilot_suggest(data.get('appointment_id'), data.get('message', ''))
    return jsonify({'success': True, **result})


@app.route('/api/ai/medication-check', methods=['POST'])
def ai_medication_check():
    if session.get('role') != 'doctor':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    data = request.json
    if not get_authorized_appointment(data.get('appointment_id'), 'doctor'):
        return jsonify({'success': False, 'message': 'Appointment not found'}), 404
    analysis = AIAnalysis.query.filter_by(appointment_id=data.get('appointment_id')).order_by(AIAnalysis.version.desc()).first()
    if not analysis:
        return jsonify({'success': False, 'message': 'No analysis found'}), 404
    warnings = medication_safety_check(analysis.analysis_json, data.get('proposed_medications', []))
    return jsonify({'success': True, 'warnings': warnings})


@app.route('/api/ai/review', methods=['POST'])
def ai_doctor_review():
    """Doctor Approve / Modify / Reject + certification."""
    if session.get('role') != 'doctor':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    data = request.json
    if not get_authorized_appointment(data.get('appointment_id'), 'doctor'):
        return jsonify({'success': False, 'message': 'Appointment not found'}), 404
    analysis = AIAnalysis.query.filter_by(appointment_id=data.get('appointment_id')).order_by(AIAnalysis.version.desc()).first()
    if not analysis:
        return jsonify({'success': False, 'message': 'No analysis found'}), 404

    action = data.get('action', 'approve')
    status_map = {'approve': 'approved', 'approved': 'approved', 'modify': 'modified',
                  'modified': 'modified', 'reject': 'rejected', 'rejected': 'rejected'}
    analysis.doctor_status = status_map.get(action, 'approved')

    if analysis.doctor_status in ('approved', 'modified'):
        base = safe_json(analysis.analysis_json, {})
        analysis.certified_record = json.dumps({
            'diagnosis': data.get('diagnosis', 'Under clinical review — see approved findings'),
            'medications': data.get('medications', 'Continue current medications unless changed by physician'),
            'medication_schedule': data.get('medication_schedule', 'Take medicines only as prescribed.'),
            'diet': data.get('diet', 'Follow the diet guidance provided by your doctor.'),
            'precautions': data.get('precautions', 'Follow doctor instructions. Return if symptoms worsen.'),
            'follow_up': data.get('follow_up', 'As advised by treating physician'),
            'approved_findings': base.get('observed_facts', []),
            'certified_by': session.get('name'),
            'certified_at': datetime.utcnow().isoformat()
        })
        record = ClinicalRecord.query.filter_by(appointment_id=data.get('appointment_id')).first()
        if record:
            record.status = 'triage_complete'

    db.session.commit()
    return jsonify({'success': True, 'message': f'Analysis {analysis.doctor_status}.', 'status': analysis.doctor_status})


@app.route('/api/ai/patient-chat', methods=['POST'])
def ai_patient_chat():
    if session.get('role') != 'patient':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    data = request.json
    appt_id = data.get('appointment_id')
    question = data.get('question', '')
    if not get_authorized_appointment(appt_id, 'patient'):
        return jsonify({'success': False, 'message': 'Appointment not found'}), 404

    # Route new concerns to care team — never frighten patient
    concern_words = ['serious', 'cancer', 'heart attack', 'stroke', 'dying', 'emergency']
    if any(w in question.lower() for w in concern_words):
        db.session.add(Alert(
            appointment_id=appt_id, alert_type='patient_concern', severity='medium',
            message='Patient AI detected possible new clinical concern — review required',
            recipient_role='doctor', status='open'
        ))
        db.session.commit()
        return jsonify({
            'success': True,
            'answer': 'Possible new clinical concern detected. Please contact your care team for guidance.',
            'source': 'escalation'
        })

    result = patient_ai_answer(question, appt_id)
    return jsonify({'success': True, **result})


@app.route('/api/ai/patient-record-summary')
def ai_patient_record_summary():
    if session.get('role') != 'patient':
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    return jsonify({'success': True, **summarize_patient_documents(session['user_id'])})


@app.route('/api/ai/alerts/acknowledge', methods=['POST'])
def acknowledge_alert():
    if session.get('role') not in ['desk', 'doctor']:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
    alert = Alert.query.get(request.json.get('alert_id'))
    if alert:
        alert.status = 'acknowledged'
        db.session.commit()
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
