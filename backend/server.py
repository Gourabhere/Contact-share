from fastapi import FastAPI, APIRouter, Request, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional
import uuid
from datetime import datetime, timezone
import qrcode
import io
from authlib.integrations.starlette_client import OAuth
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleRequest
import json


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI()

# Add session middleware
app.add_middleware(
    SessionMiddleware, 
    secret_key=os.environ.get('SESSION_SECRET', 'dev_super_secret_key')
)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# OAuth setup
oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.environ['GOOGLE_CLIENT_ID'],
    client_secret=os.environ['GOOGLE_CLIENT_SECRET'],
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    token_url='https://oauth2.googleapis.com/token',
    userinfo_url='https://openidconnect.googleapis.com/v1/userinfo',
    client_kwargs={
        'scope': 'openid email profile https://www.googleapis.com/auth/user.phonenumbers.read'
    }
)

# Define Models
class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    google_id: str
    email: str
    name: str
    picture: Optional[str] = None
    phone: Optional[str] = None
    consent_given: Optional[bool] = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UserPhoneUpdate(BaseModel):
    phone: str
    consent_given: bool = True

class StatusCheck(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class StatusCheckCreate(BaseModel):
    client_name: str

# Add your routes to the router instead of directly to app
@api_router.get("/")
async def root():
    return {"message": "OAuth Social Login API"}

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.dict()
    status_obj = StatusCheck(**status_dict)
    _ = await db.status_checks.insert_one(status_obj.dict())
    return status_obj

@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks():
    status_checks = await db.status_checks.find().to_list(1000)
    return [StatusCheck(**status_check) for status_check in status_checks]

# OAuth Routes
@api_router.get("/auth/google")
async def google_login(request: Request):
    # Store the frontend URL for redirect after OAuth
    redirect_uri = f"{os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001')}/api/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)

@api_router.get("/auth/google/callback")
async def google_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo')
        
        if user_info:
            # Check if user exists
            existing_user = await db.users.find_one({"google_id": user_info['sub']})
            
            if not existing_user:
                # Create new user
                new_user = User(
                    google_id=user_info['sub'],
                    email=user_info['email'],
                    name=user_info['name'],
                    picture=user_info.get('picture')
                )
                await db.users.insert_one(new_user.dict())
                user_data = new_user
            else:
                user_data = User(**existing_user)
            
            # Store user in session
            request.session['user'] = {
                'id': user_data.id,
                'google_id': user_data.google_id,
                'email': user_data.email,
                'name': user_data.name,
                'picture': user_data.picture,
                'phone': user_data.phone,
                'consent_given': user_data.consent_given
            }
            
            # Try to get phone number from Google
            phone_number = None
            try:
                if 'access_token' in token:
                    service = build('people', 'v1', credentials=token)
                    profile = service.people().get(
                        resourceName='people/me',
                        personFields='phoneNumbers'
                    ).execute()
                    
                    phone_numbers = profile.get('phoneNumbers', [])
                    if phone_numbers:
                        phone_number = phone_numbers[0].get('value')
            except Exception as e:
                logging.warning(f"Could not fetch phone number: {e}")
            
            # Redirect to frontend phone collection page
            frontend_url = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:3000').replace(':8001', ':3000')
            if phone_number:
                return HTMLResponse(f'<script>window.location.href="{frontend_url}/phone?prefilled={phone_number}"</script>')
            else:
                return HTMLResponse(f'<script>window.location.href="{frontend_url}/phone"</script>')
        
        raise HTTPException(status_code=400, detail="Authentication failed")
        
    except Exception as e:
        logging.error(f"OAuth callback error: {e}")
        frontend_url = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:3000').replace(':8001', ':3000')
        return HTMLResponse(f'<script>window.location.href="{frontend_url}/?error=auth_failed"</script>')

@api_router.get("/user/me")
async def get_current_user(request: Request):
    user_session = request.session.get('user')
    if not user_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_session

@api_router.post("/user/phone")
async def update_user_phone(request: Request, phone_data: UserPhoneUpdate):
    user_session = request.session.get('user')
    if not user_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Update user in database
    await db.users.update_one(
        {"google_id": user_session['google_id']},
        {
            "$set": {
                "phone": phone_data.phone,
                "consent_given": phone_data.consent_given,
                "updated_at": datetime.now(timezone.utc)
            }
        }
    )
    
    # Update session
    user_session['phone'] = phone_data.phone
    user_session['consent_given'] = phone_data.consent_given
    request.session['user'] = user_session
    
    return {"message": "Phone number updated successfully", "user": user_session}

@api_router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out successfully"}

@api_router.get("/users", response_model=List[User])
async def get_all_users():
    users = await db.users.find().to_list(1000)
    return [User(**user) for user in users]

# QR Code endpoint
@api_router.get("/qr")
async def generate_qr():
    frontend_url = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:3000').replace(':8001', ':3000')
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(frontend_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to bytes
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)
    
    return Response(content=img_bytes.getvalue(), media_type="image/png")

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()