from contextlib import asynccontextmanager
import math
import os
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session, func, select

# Import modul-modul yang sudah kita buat
from database import engine, create_db_and_tables
from models import Users, Siswa, Guru
from repository import UserRepository
from schemas import UnifiedUserRequest, UserCreate, SiswaCreate, InputNilaiRequest, UserLogin
from security import RoleChecker, buat_access_token, cek_sesi_cookie, filter_api_admin, get_password_hash, verify_password
from services import hitung_nilai_akhir, tentukan_status_kelulusan


# Event saat aplikasi pertama kali berjalan (Membuat tabel di DB)
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Connecting to database")
    create_db_and_tables()
    yield

# Inisialisasi Aplikasi FastAPI
app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)

# Dependency Injection untuk sesi Database (Setara dengan EntityManager/Repository di Spring)
def get_session():
    with Session(engine) as session:
        yield session

# ==========================================
# CONTROLLER / ROUTER UNTUK HAK AKSES UI
# ==========================================

@app.get("/", tags=["Frontend UI"])
def root():
    """Otomatis mengarahkan user dari / ke /login"""
    return RedirectResponse(url="/login")

@app.get("/login", tags=["Frontend UI"])
def halaman_login(request: Request, user: dict = Depends(cek_sesi_cookie)):
    """
    Menyajikan halaman login.
    Jika user sudah memiliki cookie sesi yang valid, 
    langsung arahkan (redirect) ke halaman dashboard sesuai role-nya.
    """
    # Mengecek apakah filter cek_sesi_cookie menemukan token JWT yang valid
    if user:
        role = user.get("role")
        # Jika ada role (misal: "admin"), arahkan langsung ke /admin
        if role:
            return RedirectResponse(url=f"/{str.lower(role)}", status_code=303)
            
    # Jika tidak ada sesi (user == None), tampilkan halaman form login HTML
    return FileResponse(os.path.join("templates", "index.html"))

# (Nantinya Anda bisa tambahkan endpoint UI untuk role masing-masing)
@app.get("/admin", tags=["Frontend UI"])
def halaman_admin(request: Request, user: dict = Depends(cek_sesi_cookie)):
    """
    Menyajikan halaman Dashboard Admin. 
    Dilengkapi filter: Jika tidak login atau bukan admin, tendang ke /login.
    """
    # Mengecek hasil dari filter cek_sesi_cookie
    if not user or user.get("role") != "admin":
        # Redirect pengguna ke halaman login dengan HTTP status 303
        return RedirectResponse(url="/login", status_code=303)
    path_html = os.path.join("templates", "admin.html")
    return FileResponse(path_html)

@app.get("/guru", tags=["Frontend UI"])
def halaman_guru(request: Request, user: dict = Depends(cek_sesi_cookie)):
    # Redirect jika bukan guru
    if not user or user.get("role") != "guru":
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse(os.path.join("templates", "guru.html"))

@app.get("/siswa", tags=["Frontend UI"])
def halaman_siswa(request: Request, user: dict = Depends(cek_sesi_cookie)):
    # Redirect jika bukan siswa
    if not user or user.get("role") != "siswa":
        return RedirectResponse(url="/login", status_code=303)
    return FileResponse(os.path.join("templates", "siswa.html"))

@app.post("/api/logout", tags=["Autentikasi"])
def proses_logout(response: Response):
    """Menghapus sesi JWT dari HTTP-Only Cookie"""
    # Menghapus cookie dengan kunci yang sama ("session_token")
    response.delete_cookie(
        key="session_token",
        samesite="lax",
        secure=False # Set True jika menggunakan HTTPS
    )
    return {"message": "Berhasil logout, sesi telah dihapus"}

# ==========================================
# ENDPOINT ADMIN: Manajemen Data
# ==========================================

from fastapi import Response # Import Response untuk mengatur cookie

@app.get("/admin/dashboard-stats", tags=["Admin"])
def get_dashboard_stats(
    page: int = Query(1, ge=1), # Halaman saat ini, default 1
    limit: int = Query(5, ge=1, le=50), # Jumlah data per halaman, default 5
    db: Session = Depends(get_session), 
    admin: dict = Depends(filter_api_admin)
):
    # Hitung total keseluruhan
    total_siswa = db.exec(select(func.count(Siswa.nis))).one()
    total_guru = db.exec(select(func.count(Guru.nip))).one()
    
    # Hitung offset untuk pagination database
    offset = (page - 1) * limit
    
    # Ambil data siswa dengan limit dan offset
    siswa_terbaru = db.exec(select(Siswa).offset(offset).limit(limit)).all()
    
    # Hitung total halaman
    total_pages = math.ceil(total_siswa / limit) if total_siswa > 0 else 1
    
    return {
        "total_siswa": total_siswa,
        "total_guru": total_guru,
        "siswa_terbaru": siswa_terbaru,
        "pagination": {
            "current_page": page,
            "total_pages": total_pages,
            "total_items": total_siswa
        }
    }

@app.post("/api/login", tags=["Autentikasi"])
def proses_login(login_data: UserLogin, response: Response, db: Session = Depends(get_session)):
    statement = select(Users).where(Users.nomor_induk == login_data.nomor_induk)
    user = db.exec(statement).first()
    
    if not user or not verify_password(login_data.password, user.password):
        raise HTTPException(status_code=401, detail="Nomor Induk atau Password salah")
    
    # 1. Buat Token JWT berisi nomor induk dan role
    token_data = {"sub": user.nomor_induk, "role": user.role}
    access_token = buat_access_token(data=token_data)
    
    # 2. Set Token ke dalam HTTP-Only Cookie
    response.set_cookie(
        key="session_token",
        value=access_token,
        httponly=True, # JavaScript di frontend tidak bisa mencuri cookie ini
        max_age=3600,  # Expire dalam 1 jam (dalam detik)
        samesite="lax",
        secure=False   # Set True jika sudah menggunakan HTTPS (Produksi)
    )
    
    return {"message": "Login berhasil, sesi telah disimpan di backend", "role": user.role}

@app.get("/admin/laporan/{nis}", tags=["Admin"])
def get_laporan_nilai(nis: str, db: Session = Depends(get_session), admin = Depends(RoleChecker(["admin", "guru"]))):
    """Menghasilkan laporan nilai dengan kalkulasi on-the-fly"""
    repo = UserRepository(db)
    siswa = repo.find_siswa_by_nis(nis)
    
    if not siswa:
        raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan")
        
    # Kalkulasi on-the-fly
    tugas = siswa.nilai_tugas or 0.0
    uts = siswa.nilai_uts or 0.0
    uas = siswa.nilai_uas or 0.0
    
    nilai_akhir = (tugas * 0.30) + (uts * 0.30) + (uas * 0.40)
    
    # Penentuan Status Lulus
    status = "LULUS" if nilai_akhir >= 70.0 else "TIDAK LULUS"
    
    return {
        "nis": siswa.nis,
        "nama": siswa.nama,
        "kelas": siswa.kelas,
        "nilai_tugas": tugas,
        "nilai_uts": uts,
        "nilai_uas": uas,
        "nilai_akhir": round(nilai_akhir, 2),
        "status": status
    }

@app.get("/admin/users/{nomor_induk}", tags=["Admin"])
def get_user_data(nomor_induk: str, db: Session = Depends(get_session), admin: dict = Depends(filter_api_admin)):
    user_repo = UserRepository(db)
    """READ: Mencari data User beserta profil lengkapnya"""
    user = user_repo.find_user_by_nomor_induk(nomor_induk)
    if not user:
        raise HTTPException(status_code=404, detail="Data tidak ditemukan")
    
    # Siapkan dictionary data dasar
    data = {
        "nomor_induk": user.nomor_induk,
        "role": user.role
    } 
    
    # Gabungkan dengan profil spesifik
    if user.role == "guru":
        guru = user_repo.find_guru_by_nip(nomor_induk)
        print(guru)
        data["nama"] = guru.nama_guru
        data["mata_pelajaran"] = guru.mata_pelajaran
    elif user.role == "siswa":
        siswa = user_repo.find_siswa_by_nis(nomor_induk)
        data["nama"] = siswa.nama
        data["kelas"] = siswa.kelas
        data["nilai_tugas"] = siswa.nilai_tugas
        data["nilai_uts"] = siswa.nilai_uts
        data["nilai_uas"] = siswa.nilai_uas
        
    return data

@app.post("/admin/register-user", tags=["Admin"])
def daftarkan_user_terpadu(payload: UnifiedUserRequest, db: Session = Depends(get_session), admin: dict = Depends(filter_api_admin)):
    """CREATE: Mendaftarkan User sekaligus membuat profil Guru/Siswa"""
    user_repo = UserRepository(db)
    if user_repo.find_user_by_nomor_induk(payload.nomor_induk):
        raise HTTPException(status_code=400, detail="Nomor Induk sudah terdaftar")
        
    # 1. Buat User (Akun)
    hashed_password = get_password_hash(payload.password) if payload.password else get_password_hash("123456")
    user_baru = Users(nomor_induk=payload.nomor_induk, password=hashed_password, role=payload.role)
    db.add(user_baru)
    
    # 2. Buat Profil Spesifik
    if payload.role == "guru":
        profil_guru = Guru(nip=payload.nomor_induk, nama_guru=payload.nama or "-", mata_pelajaran=payload.mata_pelajaran or "-")
        db.add(profil_guru)
    elif payload.role == "siswa":
        profil_siswa = Siswa(nis=payload.nomor_induk, nama=payload.nama or "-", kelas=payload.kelas or "-", nilai_tugas=payload.nilai_tugas or 0, nilai_uts=payload.nilai_uts or 0, nilai_uas=payload.nilai_uas or 0)
        db.add(profil_siswa)
        
    db.commit()
    return {"message": "Data berhasil didaftarkan"}

@app.put("/admin/users/{nomor_induk}", tags=["Admin"])
def edit_user_terpadu(nomor_induk: str, payload: UnifiedUserRequest, db: Session = Depends(get_session), admin: dict = Depends(filter_api_admin)):
    """UPDATE: Memperbarui data User dan profilnya"""
    user_repo = UserRepository(db)
    user = user_repo.find_user_by_nomor_induk(nomor_induk)
    if not user:
        raise HTTPException(status_code=404, detail="Data tidak ditemukan")
        
    # Update Password jika diisi form
    if payload.password:
        user.password = get_password_hash(payload.password)
        db.add(user)
        
    # Update Profil
    if user.role == "guru":
        guru = user_repo.find_guru_by_nip(nomor_induk)
        guru.nama_guru = payload.nama or guru.nama_guru
        guru.mata_pelajaran = payload.mata_pelajaran or guru.mata_pelajaran
        db.add(guru)
    elif user.role == "siswa" and user.siswa:
        siswa = user_repo.find_siswa_by_nis(nomor_induk)
        siswa.nama = payload.nama or siswa.nama
        siswa.kelas = payload.kelas or siswa.kelas
        siswa.nilai_tugas = payload.nilai_tugas
        siswa.nilai_uts = payload.nilai_uts
        siswa.nilai_uas = payload.nilai_uas
        db.add(siswa)
        
    db.commit()
    return {"message": "Data berhasil diperbarui"}

@app.delete("/admin/users/{nomor_induk}", tags=["Admin"])
def hapus_user(nomor_induk: str, db: Session = Depends(get_session), admin: dict = Depends(filter_api_admin)):
    """DELETE: Menghapus data User beserta profil terkait"""
    user_repo = UserRepository(db)
    user = user_repo.find_user_by_nomor_induk(nomor_induk)
    if not user:
        raise HTTPException(status_code=404, detail="Data tidak ditemukan")
        
    # Hapus profil terkait terlebih dahulu untuk mencegah error Foreign Key
    if user.role == "guru":
        guru = user_repo.find_guru_by_nip(nomor_induk)
        db.delete(guru)
    elif user.role == "siswa" and user.siswa:
        siswa = user_repo.find_siswa_by_nis(nomor_induk)
        db.delete(siswa)
        
    # Hapus akun utama
    db.delete(user)
    db.commit()
    return {"message": "Data berhasil dihapus"}

# ==========================================
# ENDPOINT GURU: Pengolahan Nilai
# ==========================================

@app.put("/guru/input-nilai/{nis}", response_model=Siswa, tags=["Guru"])
def input_nilai_siswa(nis: str, nilai_data: InputNilaiRequest, role: Annotated[dict, Depends(RoleChecker(["admin", "guru"]))] , db: Session = Depends(get_session)):
    user_repo = UserRepository(db)
    siswa = user_repo.find_siswa_by_nis(nis)
    if not siswa:
        raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan")
    
    # Cukup update nilai mentahnya saja
    siswa.nilai_tugas = nilai_data.nilai_tugas
    siswa.nilai_uts = nilai_data.nilai_uts
    siswa.nilai_uas = nilai_data.nilai_uas
    
    # Simpan nilai mentah ke database
    db.add(siswa)
    db.commit()
    db.refresh(siswa)
    
    # Saat objek 'siswa' dikembalikan (return), FastAPI akan memicu
    # @computed_field secara otomatis untuk menghasilkan JSON yang lengkap.
    return siswa

@app.get("/api/guru/profile", tags=["Guru"])
def get_profil_guru(guru_session: Annotated[dict, Depends(RoleChecker(["admin", "guru"]))], db: Session = Depends(get_session)):
    # MENGAMBIL NIP DARI SESSION (Sangat Aman)
    nip = guru_session.get("sub") 
    user_repo = UserRepository(db)
    guru = user_repo.find_guru_by_nip(nip)
    if not guru:
        raise HTTPException(status_code=404, detail="Profil tidak ditemukan")
        
    return {"nip": guru.nip, "nama_guru": guru.nama_guru, "mata_pelajaran": guru.mata_pelajaran}

@app.put("/api/guru/profile", tags=["Guru"])
def update_profil_guru(payload: UnifiedUserRequest, guru_session: Annotated[dict, Depends(RoleChecker(["admin", "guru"]))], db: Session = Depends(get_session)):
    nip = guru_session.get("sub") # Ekstrak NIP dari Session
    user_repo = UserRepository(db)
    guru = user_repo.find_guru_by_nip(nip)
    user_account = user_repo.find_user_by_nomor_induk(nip)
    
    if payload.nama_guru: guru.nama_guru = payload.nama
    if payload.mata_pelajaran: guru.mata_pelajaran = payload.mata_pelajaran
    if payload.password and user_account:
        user_account.password = get_password_hash(payload.password)
        db.add(user_account)
        
    db.add(guru)
    db.commit()
    return {"message": "Profil berhasil diperbarui"}

@app.get("/api/guru/siswa/{nis}", tags=["Guru"])
def cari_siswa_by_guru(nis: str, db: Session = Depends(get_session), guru_session: dict = Depends(RoleChecker(["guru"]))):
    siswa = db.get(Siswa, nis)
    if not siswa: raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan")
    return siswa

@app.put("/api/guru/siswa/{nis}", tags=["Guru"])
def edit_siswa_by_guru(nis: str, payload: UnifiedUserRequest, db: Session = Depends(get_session), guru_session: dict = Depends(RoleChecker(["guru"]))):
    siswa = db.get(Siswa, nis)
    if not siswa: raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan")
    
    siswa.nama = payload.nama or siswa.nama
    siswa.kelas = payload.kelas or siswa.kelas
    siswa.nilai_tugas = payload.nilai_tugas
    siswa.nilai_uts = payload.nilai_uts
    siswa.nilai_uas = payload.nilai_uas
    
    db.add(siswa)
    db.commit()
    return {"message": "Data siswa berhasil diperbarui"}

@app.get("/api/guru/laporan/{nis}", tags=["Guru"])
def get_laporan_guru(nis: str, db: Session = Depends(get_session), guru_session: dict = Depends(RoleChecker(["guru"]))):
    # Logika sama persis dengan laporan admin, namun terkunci untuk role guru
    siswa = db.get(Siswa, nis)
    if not siswa: raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan")
        
    tugas, uts, uas = siswa.nilai_tugas or 0.0, siswa.nilai_uts or 0.0, siswa.nilai_uas or 0.0
    nilai_akhir = (tugas * 0.30) + (uts * 0.30) + (uas * 0.40)
    status = "LULUS" if nilai_akhir >= 70.0 else "TIDAK LULUS"
    
    return {
        "nis": siswa.nis, "nama": siswa.nama, "kelas": siswa.kelas,
        "nilai_tugas": tugas, "nilai_uts": uts, "nilai_uas": uas,
        "nilai_akhir": round(nilai_akhir, 2), "status": status
    }

# ==========================================
# ENDPOINT SISWA: Melihat Hasil
# ==========================================

@app.get("/api/siswa/profile", tags=["Siswa"])
def get_profil_siswa(db: Session = Depends(get_session), siswa_session = Depends(RoleChecker(["siswa"]))):
    nis = siswa_session.get("sub") 
    user_repo = UserRepository(db)
    siswa = user_repo.find_siswa_by_nis(nis)
    
    if not siswa:
        raise HTTPException(status_code=404, detail="Profil tidak ditemukan")
        
    return siswa

@app.put("/api/siswa/profile", tags=["Siswa"])
def update_profil_siswa(payload: UnifiedUserRequest, siswa_session = Depends(RoleChecker(["siswa"])), db: Session = Depends(get_session)):
    nis = siswa_session.get("sub")
    user_repo = UserRepository(db)
    
    siswa = user_repo.find_siswa_by_nis(nis)
    user_account = user_repo.find_user_by_nomor_induk(nis)
    
    if payload.nama: siswa.nama = payload.nama
    if payload.kelas: siswa.kelas = payload.kelas
    if payload.password and user_account:
        user_account.password = get_password_hash(payload.password)
        db.add(user_account)
        
    db.add(siswa)
    db.commit()
    return {"message": "Profil berhasil diperbarui"}

@app.get("/api/siswa/laporan", tags=["Siswa"])
def get_laporan_siswa(siswa_session = Depends(RoleChecker(["siswa"])), db: Session = Depends(get_session)):
    # PERHATIKAN: Tidak ada parameter {nis} di URL. Murni dari session!
    nis = siswa_session.get("sub") 
    user_repo = UserRepository(db)
    siswa = user_repo.find_siswa_by_nis(nis)
    
    if not siswa:
        raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan")
        
    tugas = siswa.nilai_tugas or 0.0
    uts = siswa.nilai_uts or 0.0
    uas = siswa.nilai_uas or 0.0
    nilai_akhir = (tugas * 0.30) + (uts * 0.30) + (uas * 0.40)
    status = "LULUS" if nilai_akhir >= 70.0 else "TIDAK LULUS"
    
    return {
        "nis": siswa.nis, "nama": siswa.nama, "kelas": siswa.kelas,
        "nilai_tugas": tugas, "nilai_uts": uts, "nilai_uas": uas,
        "nilai_akhir": round(nilai_akhir, 2), "status": status
    }