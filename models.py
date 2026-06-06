from sqlmodel import SQLModel, Field
from typing import Optional

# 1. Tabel Master Guru
class Guru(SQLModel, table=True):
    nip: str = Field(primary_key=True)
    nama_guru: str
    mata_pelajaran: str

# 2. Tabel Master Siswa (Tanpa kolom nilai)
class Siswa(SQLModel, table=True):
    nis: str = Field(primary_key=True)
    nama: str
    kelas: str

# 3. TABEL RELASI & NILAI (Junction Table)
class RelasiGuruSiswa(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nip_guru: str = Field(foreign_key="guru.nip", index=True)
    nis_siswa: str = Field(foreign_key="siswa.nis", index=True)
    
    # Nilai sekarang berada spesifik di tiap relasi mata pelajaran
    nilai_tugas: float = Field(default=0.0)
    nilai_uts: float = Field(default=0.0)
    nilai_uas: float = Field(default=0.0)

# 4. Tabel Kredensial User
class Users(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True) 
    nomor_induk: str = Field(unique=True, index=True) 
    password: str 
    role: str