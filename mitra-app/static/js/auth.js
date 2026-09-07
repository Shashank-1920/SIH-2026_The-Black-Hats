let currentTab = 'patient';

function switchTab(tabName) {
    currentTab = tabName;
    
    // Update active button
    document.getElementById('btn-patient').classList.remove('active');
    document.getElementById('btn-staff').classList.remove('active');
    document.getElementById(`btn-${tabName}`).classList.add('active');
    
    // Update UI elements based on tab
    const title = document.getElementById('form-title');
    const labelUsername = document.getElementById('label-username');
    const staffTypeContainer = document.getElementById('staff-type-container');
    const errorMsg = document.getElementById('error-message');
    
    // Clear form and errors
    document.getElementById('login-form').reset();
    errorMsg.classList.add('hidden');

    if (tabName === 'patient') {
        title.innerText = 'Welcome, Patient';
        labelUsername.innerText = 'Mobile Number / ABHA ID / Patient ID';
        staffTypeContainer.classList.add('hidden');
    } else {
        title.innerText = 'Hospital Staff Portal';
        labelUsername.innerText = 'Staff Username / ID';
        staffTypeContainer.classList.remove('hidden');
    }
}

async function handleLogin(event) {
    event.preventDefault();
    
    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    const errorMsg = document.getElementById('error-message');
    const submitBtn = document.getElementById('submit-btn');
    
    // Determine login type (patient vs staff)
    const loginType = currentTab;
    
    errorMsg.classList.add('hidden');
    submitBtn.disabled = true;
    submitBtn.innerText = 'Authenticating...';
    
    try {
        // LOGIN_API_URL is defined in the HTML template via Jinja
        const response = await fetch(LOGIN_API_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                login_type: loginType,
                username: username,
                password: password
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            submitBtn.innerText = 'Success! Redirecting...';
            submitBtn.style.backgroundColor = 'var(--success)';
            setTimeout(() => {
                window.location.href = data.redirect_url;
            }, 1000);
        } else {
            throw new Error(data.message || 'Login failed');
        }
    } catch (err) {
        errorMsg.innerText = err.message;
        errorMsg.classList.remove('hidden');
        submitBtn.disabled = false;
        submitBtn.innerText = 'Login to M.I.T.R.A';
    }
}
