from app import app, db, User, DoctorProfile, Appointment, Hospital, HospitalDesk, ClinicalRecord, Document, AIAnalysis, Alert
from werkzeug.security import generate_password_hash
import os

def init_db():
    with app.app_context():
        # Drop all tables to ensure clean schema update
        db.drop_all()
        db.create_all()
        
        # Seed Hospital
        aiia_hospital = Hospital(
            name='All India Institute of Ayurveda',
            location='New Delhi',
            contact_number='+91-11-26950401'
        )
        db.session.add(aiia_hospital)
        db.session.commit()
        
        # Seed Patients
        patient_data = [
            ('PT-10482', 'patient123', 'Ravi Kumar', '+91-9876501048'),
            ('PT-20517', 'patient20517', 'Ananya Reddy', '+91-9876502051'),
            ('PT-31864', 'patient31864', 'Suresh Iyer', '+91-9876503186'),
            ('PT-42790', 'patient42790', 'Meena Krishnan', '+91-9876504279'),
            ('PT-53621', 'patient53621', 'Farhan Ahmed', '+91-9876505362'),
        ]
        patients = [User(username=username, password_hash=generate_password_hash(password), role='patient', full_name=name, phone_number=phone)
                    for username, password, name, phone in patient_data]
        
        # Seed Hospital Desk
        desk = User(
            username='desk_admin',
            password_hash=generate_password_hash('desk123'),
            role='desk',
            full_name='Nurse Priya'
        )
        
        # Seed Doctors
        doctor1 = User(
            username='dr_meera',
            password_hash=generate_password_hash('doctor123'),
            role='doctor',
            full_name='Dr. Meera Rao'
        )
        
        doctor2 = User(
            username='dr_arjun',
            password_hash=generate_password_hash('doctor123'),
            role='doctor',
            full_name='Dr. Arjun Patel'
        )
        
        db.session.add_all(patients + [desk, doctor1, doctor2])
        db.session.commit()
        
        # Seed Hospital Desk Profile
        desk_profile = HospitalDesk(
            user_id=desk.id,
            hospital_id=aiia_hospital.id,
            department='Main OPD Registration'
        )
        
        # Seed Doctor Profiles (with quotas, ratings, and hospital linking)
        prof1 = DoctorProfile(
            user_id=doctor1.id,
            hospital_id=aiia_hospital.id,
            department='Cardiology',
            daily_quota=120,
            is_available=True,
            rating=4.9,
            total_reviews=342
        )
        
        prof2 = DoctorProfile(
            user_id=doctor2.id,
            hospital_id=aiia_hospital.id,
            department='Cardiology', # Same department for failsafe testing
            daily_quota=100,
            is_available=True,
            rating=4.7,
            total_reviews=156
        )
        
        db.session.add_all([desk_profile, prof1, prof2])
        db.session.commit()
        
        print("Database re-initialized and seeded with Users and Doctor Quotas!")

if __name__ == '__main__':
    init_db()
