from contextlib import asynccontextmanager
import math
import os
from typing import Annotated

from fastapi import FastAPI, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session, func, select

# Import modul-modul yang sudah kita buat
from database import engine, create_db_and_tables
from models import Users, Siswa, Guru, RelasiGuruSiswa
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
def get_laporan_nilai(nis: str, db: Session = Depends(get_session), admin: dict = Depends(RoleChecker(["admin", "guru"]))):
    """Menghasilkan laporan nilai (KHS) multi-mata pelajaran untuk Admin/Guru"""
    # 1. Pastikan data siswa eksis
    user_repo = UserRepository(db)
    siswa = user_repo.find_siswa_by_nis(nis)
    
    if not siswa:
        raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan")
        
    # 2. Ambil semua relasi nilai dari berbagai guru (Bisa lebih dari 1 mata pelajaran)
    statement = select(RelasiGuruSiswa, Guru).join(Guru, RelasiGuruSiswa.nip_guru == Guru.nip).where(RelasiGuruSiswa.nis_siswa == nis)
    results = db.exec(statement).all()
    
    laporan_mapel = []
    total_akhir_keseluruhan = 0.0
    
    for relasi, guru in results:
        # Kalkulasi per mata pelajaran
        na = (relasi.nilai_tugas * 0.3) + (relasi.nilai_uts * 0.3) + (relasi.nilai_uas * 0.4)
        total_akhir_keseluruhan += na
        laporan_mapel.append({
            "nama_guru": guru.nama_guru,
            "mata_pelajaran": guru.mata_pelajaran,
            "tugas": relasi.nilai_tugas,
            "uts": relasi.nilai_uts,
            "uas": relasi.nilai_uas,
            "nilai_akhir": round(na, 2)
        })
        
    # 3. Kalkulasi rata-rata keseluruhan untuk menentukan Lulus/Tidak
    rata_rata = round(total_akhir_keseluruhan / len(results), 2) if results else 0.0
    status = "LULUS" if rata_rata >= 70.0 else "TIDAK LULUS"
    
    return {
        "nis": siswa.nis,
        "nama": siswa.nama,
        "kelas": siswa.kelas,
        "detail_mapel": laporan_mapel,
        "rata_rata_keseluruhan": rata_rata,
        "status_akhir": status
    }

@app.get("/admin/users/{nomor_induk}", tags=["Admin"])
def get_user_data(nomor_induk: str, db: Session = Depends(get_session), admin: dict = Depends(filter_api_admin)):
    """READ: Mencari data User beserta profil dasarnya (Tanpa Nilai)"""
    user_repo = UserRepository(db)
    user = user_repo.find_user_by_nomor_induk(nomor_induk)
    if not user:
        raise HTTPException(status_code=404, detail="Data tidak ditemukan")
    
    data = {
        "nomor_induk": user.nomor_induk,
        "role": user.role
    } 
    
    if user.role == "guru":
        guru = user_repo.find_guru_by_nip(nomor_induk)
        data["nama"] = guru.nama_guru if guru else ""
        data["mata_pelajaran"] = guru.mata_pelajaran if guru else ""
    elif user.role == "siswa":
        siswa = user_repo.find_siswa_by_nis(nomor_induk)
        data["nama"] = siswa.nama if siswa else ""
        data["kelas"] = siswa.kelas if siswa else ""
        # HAPUS: nilai_tugas, nilai_uts, dan nilai_uas tidak lagi dipanggil di sini
        
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
        # PERBAIKAN: Hapus nilai_tugas, nilai_uts, nilai_uas dari instansiasi Siswa
        profil_siswa = Siswa(nis=payload.nomor_induk, nama=payload.nama or "-", kelas=payload.kelas or "-")
        db.add(profil_siswa)
        
    db.commit()
    return {"message": "Data berhasil didaftarkan"}

@app.put("/admin/users/{nomor_induk}", tags=["Admin"])
def edit_user_terpadu(nomor_induk: str, payload: UnifiedUserRequest, db: Session = Depends(get_session), admin: dict = Depends(filter_api_admin)):
    """UPDATE: Memperbarui data User dan profil dasarnya (Tanpa Nilai)"""
    user_repo = UserRepository(db)
    user = user_repo.find_user_by_nomor_induk(nomor_induk)
    if not user:
        raise HTTPException(status_code=404, detail="Data tidak ditemukan")
        
    if payload.password:
        user.password = get_password_hash(payload.password)
        db.add(user)
        
    if user.role == "guru":
        guru = user_repo.find_guru_by_nip(nomor_induk)
        if guru:
            guru.nama_guru = payload.nama or guru.nama_guru
            guru.mata_pelajaran = payload.mata_pelajaran or guru.mata_pelajaran
            db.add(guru)
    elif user.role == "siswa":
        siswa = user_repo.find_siswa_by_nis(nomor_induk)
        if siswa:
            siswa.nama = payload.nama or siswa.nama
            siswa.kelas = payload.kelas or siswa.kelas
            # HAPUS: Update nilai_tugas, nilai_uts, nilai_uas sudah tidak ada di sini
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

# CARI DAN HAPUS BLOK KODE INI DARI main.py ANDA!
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
    nip = guru_session.get("sub")
    siswa = db.get(Siswa, nis)
    
    if not siswa: 
        raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan")
        
    # Ambil nilainya dari tabel relasi (agar form Edit terisi nilai yang benar)
    relasi = db.exec(select(RelasiGuruSiswa).where(RelasiGuruSiswa.nip_guru == nip, RelasiGuruSiswa.nis_siswa == nis)).first()
    
    return {
        "nis": siswa.nis,
        "nama": siswa.nama,
        "kelas": siswa.kelas,
        "nilai_tugas": relasi.nilai_tugas if relasi else 0.0,
        "nilai_uts": relasi.nilai_uts if relasi else 0.0,
        "nilai_uas": relasi.nilai_uas if relasi else 0.0
    }

@app.put("/api/guru/siswa/{nis}", tags=["Guru"])
def edit_siswa_by_guru(nis: str, payload: UnifiedUserRequest, db: Session = Depends(get_session), guru_session: dict = Depends(RoleChecker(["guru"]))):
    siswa = db.get(Siswa, nis)
    if not siswa: raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan")
    
    # Endpoint ini sekarang murni hanya untuk update Nama dan Kelas saja
    siswa.nama = payload.nama or siswa.nama
    siswa.kelas = payload.kelas or siswa.kelas
    
    # HAPUS BARIS UPDATE NILAI DI SINI (Karena nilai sudah diurus oleh endpoint /relasi/{nis}/nilai)
    
    db.add(siswa)
    db.commit()
    return {"message": "Profil siswa berhasil diperbarui"}

# TIMPA/GANTI FUNGSI LAMA DENGAN INI DI main.py ANDA
@app.get("/api/guru/laporan/{nis}", tags=["Guru"])
def get_laporan_guru(nis: str, db: Session = Depends(get_session), guru_session: dict = Depends(RoleChecker(["guru"]))):
    nip = guru_session.get("sub")
    
    # 1. Pastikan siswa ada
    siswa = db.get(Siswa, nis)
    if not siswa: raise HTTPException(status_code=404, detail="Data siswa tidak ditemukan")
        
    # 2. Cari nilainya di tabel relasi khusus untuk Guru ini saja
    relasi = db.exec(select(RelasiGuruSiswa).where(RelasiGuruSiswa.nip_guru == nip, RelasiGuruSiswa.nis_siswa == nis)).first()
    
    if not relasi:
        raise HTTPException(status_code=403, detail="Siswa ini tidak terdaftar di mata pelajaran Anda")

    # 3. Kalkulasi dari tabel relasi
    tugas = relasi.nilai_tugas or 0.0
    uts = relasi.nilai_uts or 0.0
    uas = relasi.nilai_uas or 0.0
    nilai_akhir = (tugas * 0.30) + (uts * 0.30) + (uas * 0.40)
    status = "LULUS" if nilai_akhir >= 70.0 else "TIDAK LULUS"
    
    return {
        "nis": siswa.nis, "nama": siswa.nama, "kelas": siswa.kelas,
        "nilai_tugas": tugas, "nilai_uts": uts, "nilai_uas": uas,
        "nilai_akhir": round(nilai_akhir, 2), "status": status
    }

@app.post("/api/guru/relasi/{nis}", tags=["Guru"])
def tambah_relasi_siswa(nis: str, guru_session = Depends(RoleChecker(["guru"])), db: Session = Depends(get_session)):
    """Guru menambahkan siswa ke daftar bimbingannya"""
    nip = guru_session.get("sub")
    
    # Cek apakah siswa eksis di master data
    siswa = db.get(Siswa, nis)
    if not siswa:
        raise HTTPException(status_code=404, detail="NIS tidak terdaftar di sistem")
        
    # Cek apakah relasi sudah ada
    cek_relasi = db.exec(select(RelasiGuruSiswa).where(
        RelasiGuruSiswa.nip_guru == nip, 
        RelasiGuruSiswa.nis_siswa == nis
    )).first()
    
    if cek_relasi:
        raise HTTPException(status_code=400, detail="Siswa ini sudah ada di daftar Anda")
        
    # Buat relasi baru
    relasi_baru = RelasiGuruSiswa(nip_guru=nip, nis_siswa=nis)
    db.add(relasi_baru)
    db.commit()
    return {"message": "Siswa berhasil ditambahkan ke daftar Anda"}

@app.delete("/api/guru/relasi/{nis}", tags=["Guru"])
def hapus_relasi_siswa(nis: str, guru_session = Depends(RoleChecker(["guru"])), db: Session = Depends(get_session)):
    """Guru menghapus siswa dari daftarnya"""
    nip = guru_session.get("sub")
    relasi = db.exec(select(RelasiGuruSiswa).where(RelasiGuruSiswa.nip_guru == nip, RelasiGuruSiswa.nis_siswa == nis)).first()
    
    if not relasi:
        raise HTTPException(status_code=404, detail="Siswa tidak ditemukan dalam daftar Anda")
        
    db.delete(relasi)
    db.commit()
    return {"message": "Relasi siswa berhasil dihapus"}

@app.get("/api/guru/relasi", tags=["Guru"])
def get_daftar_siswa_guru(guru_session: Annotated[dict, Depends(RoleChecker(["admin", "guru"]))], db: Session = Depends(get_session)):
    """Menampilkan semua siswa yang diajar oleh guru ini beserta kalkulasi nilainya"""
    nip = guru_session.get("sub")
    
    # JOIN query: Menggabungkan tabel Relasi dengan tabel Siswa
    statement = select(RelasiGuruSiswa, Siswa).join(Siswa, RelasiGuruSiswa.nis_siswa == Siswa.nis).where(RelasiGuruSiswa.nip_guru == nip)
    results = db.exec(statement).all()
    
    daftar_siswa = []
    for relasi, siswa in results:
        # Kalkulasi on-the-fly di backend
        tugas = relasi.nilai_tugas or 0.0
        uts = relasi.nilai_uts or 0.0
        uas = relasi.nilai_uas or 0.0
        
        nilai_akhir = (tugas * 0.30) + (uts * 0.30) + (uas * 0.40)
        status = "LULUS" if nilai_akhir >= 70.0 else "TIDAK LULUS"
        
        daftar_siswa.append({
            "nis": siswa.nis,
            "nama": siswa.nama,
            "kelas": siswa.kelas,
            "nilai_tugas": tugas,
            "nilai_uts": uts,
            "nilai_uas": uas,
            "nilai_akhir": round(nilai_akhir, 2),
            "status": status
        })
    return daftar_siswa

@app.put("/api/guru/relasi/{nis}/nilai", tags=["Guru"])
def update_nilai_siswa(nis: str, payload: InputNilaiRequest, guru_session = Depends(RoleChecker(["guru"])), db: Session = Depends(get_session)):
    """Guru memperbarui nilai pada siswa spesifik di mata pelajarannya"""
    nip = guru_session.get("sub")
    relasi = db.exec(select(RelasiGuruSiswa).where(RelasiGuruSiswa.nip_guru == nip, RelasiGuruSiswa.nis_siswa == nis)).first()
    
    if not relasi:
        raise HTTPException(status_code=404, detail="Siswa tidak ada di daftar Anda")
        
    relasi.nilai_tugas = payload.nilai_tugas
    relasi.nilai_uts = payload.nilai_uts
    relasi.nilai_uas = payload.nilai_uas
    db.add(relasi)
    db.commit()
    return {"message": "Nilai berhasil diperbarui"}



# ==========================================
# ENDPOINT SISWA: Melihat Hasil
# ==========================================

@app.get("/api/siswa/relasi", tags=["Siswa"])
def get_daftar_guru_siswa(siswa_session = Depends(RoleChecker(["siswa"])), db: Session = Depends(get_session)):
    """Menampilkan daftar guru dan nilai per mata pelajaran untuk siswa"""
    nis = siswa_session.get("sub")
    
    statement = select(RelasiGuruSiswa, Guru).join(Guru, RelasiGuruSiswa.nip_guru == Guru.nip).where(RelasiGuruSiswa.nis_siswa == nis)
    results = db.exec(statement).all()
    
    laporan = []
    total_akhir_keseluruhan = 0.0
    for relasi, guru in results:
        na = (relasi.nilai_tugas * 0.3) + (relasi.nilai_uts * 0.3) + (relasi.nilai_uas * 0.4)
        total_akhir_keseluruhan += na
        laporan.append({
            "nama_guru": guru.nama_guru,
            "mata_pelajaran": guru.mata_pelajaran,
            "tugas": relasi.nilai_tugas,
            "uts": relasi.nilai_uts,
            "uas": relasi.nilai_uas,
            "nilai_akhir": round(na, 2)
        })
        
    rata_rata = round(total_akhir_keseluruhan / len(results), 2) if results else 0.0
    status = "LULUS" if rata_rata >= 70.0 else "TIDAK LULUS"
    
    return {
        "detail_mapel": laporan,
        "rata_rata_keseluruhan": rata_rata,
        "status_akhir": status
    }

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