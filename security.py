from typing import Annotated

from passlib.context import CryptContext

import jwt
from datetime import datetime, timedelta

# Kunci rahasia untuk menandatangani token (DI PRODUKSI, GUNAKAN ENVIRONMENT VARIABLE!)
SECRET_KEY = "udinsedunia123111"
ALGORITHM = "HS256"

# Inisialisasi BCrypt
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def get_password_hash(password: str) -> str:
    """Melakukan hashing menggunakan algoritma default (Argon2)"""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Otomatis memverifikasi baik itu hash Argon2 maupun Bcrypt lama"""
    return pwd_context.verify(plain_password, hashed_password)

def buat_access_token(data: dict, expires_delta: timedelta = timedelta(hours=1)):
    """Membuat JWT token yang berisi data user"""
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

from fastapi import Depends, HTTPException, Header, Request

# Dependensi / Filter Backend untuk mengecek sesi aktif
def get_current_user(request: Request):
    # 1. Ambil cookie dari request browser
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Sesi tidak ditemukan, silakan login")
    
    try:
        # 2. Dekode token, validasi apakah kadaluwarsa atau dimanipulasi
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload # Mengembalikan dict: {"sub": "123", "role": "admin", "exp": ...}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sesi telah berakhir, silakan login ulang")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Sesi tidak valid")

# Dependensi khusus Role
def get_admin_user(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Akses ditolak: Khusus Admin")
    return current_user

def cek_sesi_cookie(request: Request):
    """
    Filter murni untuk membaca dan memvalidasi JWT dari cookie.
    Mengembalikan payload (data user) jika valid, atau None jika gagal.
    """
    token = request.cookies.get("session_token")
    if not token:
        return None
        
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError: # Menangkap token kadaluwarsa atau tidak valid
        return None

def filter_api_admin(user: dict = Depends(cek_sesi_cookie)):
    """
    Filter khusus untuk API Admin. 
    Jika gagal, langsung tolak dengan HTTP 403/401 (Format JSON).
    """
    if not user:
        raise HTTPException(status_code=401, detail="Silakan login terlebih dahulu")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Akses ditolak: Khusus Admin")
    return user

class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        # Menyimpan role apa saja yang diizinkan untuk endpoint tertentu
        self.allowed_roles = allowed_roles

    # Endpoint akan memanggil fungsi ini. 
    # Kita menyuntikkan (Depends) fungsi cek_sesi_cookie ke dalam paramater ini.
    def __call__(self, user_session: dict = Depends(cek_sesi_cookie)):
        
        # 1. Pastikan user sudah login (token valid)
        if not user_session:
            raise HTTPException(status_code=401, detail="Sesi tidak valid, silakan login")
            
        # 2. Ambil role dari payload JWT (yang didapat dari cookie)
        user_role = user_session.get("role")
        
        # 3. Cek apakah role tersebut ada di dalam daftar yang diizinkan
        if user_role not in self.allowed_roles:
            raise HTTPException(status_code=403, detail="Akses ditolak: Anda tidak memiliki izin (Role tidak sesuai)")
            
        # 4. Jika lolos, kembalikan data user agar bisa dipakai oleh controller
        return user_session