# M.I.T.R.A - Test Credentials

Here are the default users seeded into the Supabase database. You can use these to log into the working model.

## 🧑‍⚕️ Patient
*   **Role:** Patient
*   **Name:** Ravi Kumar
*   **Login ID (Username):** `PT-10482`
*   **Password:** `patient123`
*   *Note: Use the "Patient Portal" tab on the login page.*

### Additional Patients

| Patient ID | Password | Name |
|---|---|---|
| `PT-20517` | `patient20517` | Ananya Reddy |
| `PT-31864` | `patient31864` | Suresh Iyer |
| `PT-42790` | `patient42790` | Meena Krishnan |
| `PT-53621` | `patient53621` | Farhan Ahmed |

---

## 🏥 Hospital Desk (Admin/Nurse)
*   **Role:** Hospital Desk
*   **Name:** Nurse Priya
*   **Hospital:** All India Institute of Ayurveda
*   **Username:** `desk_admin`
*   **Password:** `desk123`
*   *Note: Use the "Hospital Staff" tab on the login page.*

---

## 👨‍⚕️ Doctors
Use these credentials to view the Doctor's Clinical Dashboard.
*(Note: Use the "Hospital Staff" tab on the login page.)*

**Doctor 1**
*   **Name:** Dr. Meera Rao
*   **Department:** Cardiology
*   **Username:** `dr_meera`
*   **Password:** `doctor123`

**Doctor 2**
*   **Name:** Dr. Arjun Patel
*   **Department:** Cardiology
*   **Username:** `dr_arjun`
*   **Password:** `doctor123`

---

## AI Engine (Gemini)

Add to your `.env` file when ready:

```
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-1.5-flash
```

Without a key, M.I.T.R.A uses the built-in rule-based clinical engine (fully functional for demo).
