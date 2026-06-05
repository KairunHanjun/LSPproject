from pydantic import BaseModel, Field
from typing import Optional

# ==========================================
# DTO untuk Manajemen User & Autentikasi
# ==========================================
class UserCreate(BaseModel):
    nomor_induk: str = Field(..., description="Gunakan NIS untuk Siswa atau NIP untuk Guru")
    password: str = Field(..., min_length=6, description="Minimal 6 karakter")
    role: str

class UserLogin(BaseModel):
    nomor_induk: str
    password: str

# ==========================================
# DTO untuk Entitas Guru
# ==========================================
class GuruCreate(BaseModel):
    nip: str
    nama_guru: str
    mata_pelajaran: str

# ==========================================
# DTO untuk Entitas Siswa
# ==========================================
class SiswaCreate(BaseModel):
    nis: str
    nama: str
    kelas: str

# ==========================================
# DTO untuk Proses Input Nilai oleh Guru
# ==========================================
class InputNilaiRequest(BaseModel):
    nilai_tugas: float = Field(..., ge=0, le=100, description="Rentang nilai valid: 0-100")
    nilai_uts: float = Field(..., ge=0, le=100, description="Rentang nilai valid: 0-100")
    nilai_uas: float = Field(..., ge=0, le=100, description="Rentang nilai valid: 0-100")

class UnifiedUserRequest(BaseModel):
    nomor_induk: str
    role: str
    password: Optional[str] = None
    nama: Optional[str] = None
    mata_pelajaran: Optional[str] = None
    kelas: Optional[str] = None
    nilai_tugas: Optional[float] = 0.0
    nilai_uts: Optional[float] = 0.0
    nilai_uas: Optional[float] = 0.0