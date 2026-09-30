
#  structure

app/
├── auth/
│   ├── __init__.py
│   ├── security.py
│   └── dependencies.py
│
├── routers/
│   ├── __init__.py
│   └── auth.py          ← API endpoints
│
├── schemas/
│   ├── __init__.py
│   └── auth.py          ← request/response data validation
│
├── models/
│   ├── __init__.py
│   ├── user.py
│   ├── profile.py
│   ├── matching_queue.py
│   ├── conversation.py
│   └── conversation_participant.py
│
├── main.py
├── database.py
└── config.py



# AUTH workflow
REGISTER
   ↓
User + Profile
   ↓
LOGIN
   ↓
JWT Token
   ↓
/auth/me
   ↓
Verify JWT
   ↓
Identify User