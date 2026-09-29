# SmartBank — Text File Edition

A responsive Flask banking dashboard that uses **only a local JSON text file** as its database. MongoDB is completely removed.

## 🎥 Project Demo

<video src="data/Bank_Dashboard.mp4" controls width="900"></video>

## Run on Windows

```bat
cd SmartBank_TextDB
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open `http://127.0.0.1:5000`.

## Storage

All application data is stored in:

`data/database.json`

The app creates/updates this file automatically. There is no MongoDB dependency and no database credentials are required.

## Included

- Responsive desktop/tablet/mobile UI
- Registration with generated account number
- 4-digit hashed PIN
- Login/logout
- Forgot PIN + development OTP recovery
- Dashboard and balance
- Account-to-account transfers
- Transaction history
- Printable statement
- UPI ID management
- Debit card view
- Profile management
- Spending and monthly analytics
- Validation and error handling
- 404/500 pages
- Atomic JSON-file writes

### OTP note
For a local/demo application, the recovery OTP is displayed in the application's flash message instead of being sent by SMS. A real SMS provider can be integrated later without changing the core data model.

## Important
This is a **demo/academic banking application**, not production banking software. The JSON file is intentionally used instead of a real database and does not provide the security, concurrency, audit, encryption, regulatory controls, or transaction guarantees required by a real financial system.
