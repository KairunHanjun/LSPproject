from sqlmodel import SQLModel, Field
from typing import Optional
from enum import Enum

# Enum untuk Role

# 1. Tabel Master Guru (Berdiri Sendiri)
class Guru(SQLModel, table=True):
    nip: str = Field(primary_key=True) # NIP sebagai Primary Key
    nama_guru: str
    mata_pelajaran: str

# 2. Tabel Master Siswa (Berdiri Sendiri)
class Siswa(SQLModel, table=True):
    nis: str = Field(primary_key=True) # NIS sebagai Primary Key
    nama: str
    kelas: str
    
    nilai_tugas: Optional[float] = Field(default=0.0)
    nilai_uts: Optional[float] = Field(default=0.0)
    nilai_uas: Optional[float] = Field(default=0.0)

# 3. Tabel User (Targeting NIP atau NIS secara logikal)
class Users(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True) 
    
    # Menjadi referensi logikal ke NIS atau NIP (Bukan FK murni di level DB)
    nomor_induk: str = Field(unique=True, index=True) 
    password: str 
    role: str