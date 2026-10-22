from fastapi import FastAPI
from sqlalchemy import text

from app.database import engine,Base
from app.config import FRONTEND_ORIGINS
from app import models
from fastapi.middleware.cors import CORSMiddleware

from app.routers.auth import router as auth_router
from app.routers.profile import router as profile_router
from app.routers.matching import router as matching_router

from app.routers.websocket import router as websocket_router
from app.routers.transcription import router as transcription_router

app = FastAPI(
    title="English Speaking Practice Platform",
    description="Backend API for real-time English conversation practice",
    version="1.0.0"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


print("REGISTERED TABLES:")
print(Base.metadata.tables.keys())
Base.metadata.create_all(bind=engine)



# Register routes
app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(matching_router)
app.include_router(websocket_router)
app.include_router(transcription_router)





@app.get("/")
def root():
    return {
        "message": "English Speaking Practice Platform API is running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy"
    }


@app.get("/health/database")
def database_health_check():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    return {
        "status": "healthy",
        "database": "connected"
    }



@app.post("/setup/database")
def setup_database():
    Base.metadata.create_all(bind=engine)

    return {
        "message": "Database tables created successfully",
        "tables": list(Base.metadata.tables.keys())
    }