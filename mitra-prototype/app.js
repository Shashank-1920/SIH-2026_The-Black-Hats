// State Management
let state = {
    hospital: '',
    role: '',
    patientId: 'PT-10482',
    name: 'Ravi Kumar',
    token: '037',
    intakeStep: 0
};

// Navigation Utility
function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    document.getElementById('screen-' + screenId).classList.add('active');
}

function updateContext(text) {
    document.getElementById('nav-context').innerText = text;
}

// 1. Hospital Selection
function selectHospital(name) {
    state.hospital = name;
    document.getElementById('role-hospital-name').innerText = name;
    updateContext(`Hospital: ${name}`);
    showScreen('role-selection');
}

// 2. Role Selection
function selectRole(role) {
    state.role = role;
    updateContext(`${state.hospital} | Role: ${role}`);
    
    if(role === 'Patient') {
        showScreen('patient-login');
    } else if(role === 'Nurse') {
        showScreen('nurse-dashboard');
    } else if(role === 'Doctor') {
        showScreen('doctor-dashboard');
    } else if(role === 'Management') {
        showScreen('management-dashboard');
    }
}

// 3. Patient Login
function simulateLogin() {
    document.getElementById('login-input').disabled = true;
    document.getElementById('otp-section').classList.remove('hidden');
}

function verifyLogin() {
    showScreen('patient-consent');
}

// 4. Patient Consent
function playAudio(type) {
    alert("Audio Guidance: Playing explanation in Telugu & English...");
}

function acceptConsent() {
    if(!document.getElementById('consent-check').checked) {
        alert("Please explicitly consent to continue.");
        return;
    }
    showScreen('patient-home');
}

// 5. Patient Intake
function startIntake() {
    showScreen('patient-intake');
}

function addChatMessage(text, sender) {
    const chat = document.getElementById('intake-chat');
    const msg = document.createElement('div');
    msg.className = `msg ${sender}`;
    msg.innerText = text;
    chat.appendChild(msg);
    chat.scrollTop = chat.scrollHeight;
}

function simulatePatientVoice() {
    if(state.intakeStep === 0) {
        addChatMessage("Naaku 3 rojula nunchi chest lo discomfort undi. (Telugu: I have chest discomfort for 3 days)", 'user');
        setTimeout(() => {
            addChatMessage("I understand you have chest discomfort. Is the pain sudden or gradual? Does it spread to your arms?", 'ai');
        }, 1000);
        state.intakeStep++;
    } else if(state.intakeStep === 1) {
        addChatMessage("It spreads to my left arm.", 'user');
        setTimeout(() => {
            addChatMessage("Thank you. I have recorded this. Are you experiencing any sweating or breathlessness?", 'ai');
        }, 1000);
        state.intakeStep++;
    } else {
        addChatMessage("No, just the pain.", 'user');
        setTimeout(() => {
            addChatMessage("Clinical history captured successfully. Please proceed to upload any previous documents.", 'ai');
        }, 1000);
    }
}

function simulatePatientUpload() {
    showScreen('patient-upload');
}

// 6. OCR & Extraction
function simulateOCR() {
    alert("Scanning document and performing quality check...");
    setTimeout(() => {
        document.getElementById('ocr-results').classList.remove('hidden');
    }, 1500);
}

function confirmData(btn) {
    btn.innerText = "Confirmed ✓";
    btn.classList.remove('success');
    btn.style.backgroundColor = 'var(--success)';
    btn.style.color = 'white';
}

function finishPatientFlow() {
    alert("Information verified and saved securely. AI has generated a clinical summary. Awaiting nurse triage.");
    // Auto switch to Nurse to show the journey
    selectRole('Nurse');
}

// 7. Nurse Flow
function nurseVerifyArrival() {
    document.getElementById('nurse-vitals-modal').classList.remove('hidden');
    document.getElementById('nurse-vitals-modal').style.display = 'block';
    document.getElementById('nurse-vitals-modal').style.position = 'fixed';
    document.getElementById('nurse-vitals-modal').style.top = '50%';
    document.getElementById('nurse-vitals-modal').style.left = '50%';
    document.getElementById('nurse-vitals-modal').style.transform = 'translate(-50%, -50%)';
    document.getElementById('nurse-vitals-modal').style.zIndex = '1000';
}

function sendToDoctor() {
    document.getElementById('nurse-vitals-modal').classList.add('hidden');
    document.getElementById('nurse-vitals-modal').style.display = 'none';
    alert("Patient arrival verified, vitals captured, and priority alert sent to Doctor.");
    selectRole('Doctor');
}

// 8. Doctor Flow
function loadDoctorPatient() {
    alert("Loaded pre-consult summary for Token 037.");
}

function simulateDoctorConsult() {
    const chat = document.getElementById('doctor-copilot-chat');
    
    const docMsg = document.createElement('div');
    docMsg.className = 'msg user';
    docMsg.innerText = "Ravi, how is the pain now?";
    chat.appendChild(docMsg);
    
    setTimeout(() => {
        const aiMsg = document.createElement('div');
        aiMsg.className = 'msg ai';
        aiMsg.innerHTML = "<strong>Copilot Suggestion:</strong> Since patient is on Amlodipine and reporting arm radiation, consider an immediate ECG.";
        chat.appendChild(aiMsg);
        chat.scrollTop = chat.scrollHeight;
    }, 1500);
}

function certifyRecord() {
    alert("Clinical Record Finalized. Medication changes certified by Dr. Meera Rao. Syncing to Hospital HIS via FHIR.");
    // Reset or show Management
    selectRole('Management');
}

// Initialize
updateContext('System Ready');
