# DOKUMEN TUGAS 2: IMPLEMENTASI PROGRAM

1. Halaman Login Berdasarkan Role 

Sistem menggunakan satu pintu masuk (halaman login) untuk semua jenis pengguna. Setelah kredensial (Nomor Induk dan Password) divalidasi oleh *backend*, sistem akan mengekstrak peran (*role*) dari token JWT dan secara otomatis mengarahkan (*redirect*) pengguna ke *dashboard* masing-masing (Admin, Guru, atau Siswa).

* **[SPACE UNTUK SCREENSHOT: Tampilan antarmuka `index.html` (Form Login)]**
* **[SPACE UNTUK SCREENSHOT: Proses *Redirect* di Network Tab / Tampilan *Dashboard* masing-masing Role setelah login berhasil]**

2. Form Input Data Siswa dan Nilai 

Input data dipisahkan berdasarkan wewenang (*Separation of Concerns*). Admin hanya bertugas membuat akun pengguna dasar. Sementara itu, Guru menggunakan formulir khusus di *dashboard* mereka untuk mendaftarkan siswa ke kelasnya (tabel relasi) dan memasukkan nilai Tugas, UTS, serta UAS secara spesifik untuk mata pelajarannya.

* **[SPACE UNTUK SCREENSHOT: Form "Tambah Siswa (Berdasarkan NIS)" di Dashboard Guru]**
* **[SPACE UNTUK SCREENSHOT: Form Modal/Area Input Nilai (Tugas, UTS, UAS) milik Guru]**

3. Proses Perhitungan Nilai Akhir 

Perhitungan nilai akhir dihitung secara *on-the-fly* oleh *backend* ketika data ditarik, menggunakan bobot 30% Tugas, 30% UTS, dan 40% UAS sesuai dengan ketentuan skenario. Logika ini dibungkus dalam modul `services.py` dan dieksekusi secara otomatis setiap kali *endpoint* relasi dipanggil.

* **[SPACE UNTUK SCREENSHOT: Tampilan baris kode yang memanggil fungsi perhitungan di `main.py`]**
* **[SPACE UNTUK SCREENSHOT: Tampilan antarmuka tabel Guru yang menunjukkan kolom "Nilai Akhir" otomatis terisi]**

4. Laporan Hasil Nilai Siswa 

Laporan hasil evaluasi dikonstruksi dalam bentuk Kartu Hasil Studi (KHS). Karena menggunakan relasi *Many-to-Many*, KHS secara dinamis menampilkan daftar nilai dari seluruh guru yang mengajar siswa tersebut, lalu menghitung rata-rata keseluruhan untuk menentukan kelulusan.

* **[SPACE UNTUK SCREENSHOT: Tampilan UI Laporan KHS di Dashboard Admin atau Siswa]**
* **[SPACE UNTUK SCREENSHOT: Tampilan KHS saat mode cetak (Print Preview) yang sudah disesuaikan desainnya (hide komponen non-print)]**

5. Bukti Pengujian Database 

Aplikasi telah terhubung ke database PostgreSQL di Aiven Cloud menggunakan SQLModel (SQLAlchemy). Operasi CRUD (Create, Read, Update, Delete) berjalan di atas objek relasional.

* **[SPACE UNTUK SCREENSHOT: Tampilan tabel `users`, `guru`, `siswa`, dan `relasigurusiswa` dari aplikasi *Database Client* seperti pgAdmin / DBeaver yang berisi data hasil input]**

6. Catatan Error/Debugging 

**Masalah Teridentifikasi:**

* **Error 1:** `AttributeError: 'Siswa' object has no attribute 'nilai_tugas'`. Terjadi saat Admin mencoba mengakses laporan karena skema database telah diubah ke bentuk *Many-to-Many*.
* **Error 2:** Nilai pada dasbor Guru selalu menunjukkan angka "0" meskipun sudah disimpan.
* **[SPACE UNTUK SCREENSHOT: Tangkapan layar *error console* di terminal / pesan *error* 500 di *browser* / *Network Tab*]**

7. Perbaikan Error dan Hasil Setelah Diperbaiki 

**Solusi & Perbaikan:**

* **Fix Error 1:** Menghapus referensi atribut nilai pada instansiasi tabel master `Siswa` dan memindahkan pengambilan data melalui fungsi `.join()` ke tabel `RelasiGuruSiswa`.
* **Fix Error 2:** Memperbarui fungsi JavaScript `simpanDataSiswa()` di `guru.html` agar melakukan dua panggilan API terpisah: `PUT /api/guru/siswa/{nis}` untuk menyimpan profil dasar, dan `PUT /api/guru/relasi/{nis}/nilai` untuk menyimpan nilai ke tabel relasi.
* **[SPACE UNTUK SCREENSHOT: Tampilan tabel dasbor Guru yang nilainya sudah ter-update dengan benar (tidak lagi 0)]**

8. Potongan Kode Fungsi / Procedure (Pemrograman Terstruktur) 

Implementasi pemrograman terstruktur diterapkan dalam modul `services.py` untuk mengisolasi logika perhitungan agar mudah diuji secara independen.

```python
def validasi_nilai(nilai: float) -> bool:
    if nilai is None: return True
    return 0 <= nilai <= 100

def hitung_nilai_akhir(tugas: float, uts: float, uas: float) -> float:
    t = tugas or 0.0; ut = uts or 0.0; ua = uas or 0.0
    if not (validasi_nilai(t) and validasi_nilai(ut) and validasi_nilai(ua)):
        raise ValueError("Semua nilai harus berada dalam rentang 0-100")
    return round((0.30 * t) + (0.30 * ut) + (0.40 * ua), 2)

def tentukan_status_kelulusan(nilai_akhir: float) -> str:
    return "LULUS" if nilai_akhir >= 70 else "TIDAK LULUS"

```

9. Potongan Kode Class dan Method (OOP) 

Implementasi *Object-Oriented Programming* (OOP) diterapkan dalam pemodelan tabel database dengan SQLModel dan pembuatan objek pelindung hak akses (*Callable Dependency*).

```python
# Implementasi Class Model Relasi Many-to-Many
class RelasiGuruSiswa(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nip_guru: str = Field(foreign_key="guru.nip", index=True)
    nis_siswa: str = Field(foreign_key="siswa.nis", index=True)
    nilai_tugas: float = Field(default=0.0)
    nilai_uts: float = Field(default=0.0)
    nilai_uas: float = Field(default=0.0)

# Implementasi Class Method untuk Security Authorization
class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, user_session: dict = Depends(cek_sesi_cookie)):
        if not user_session:
            raise HTTPException(status_code=401, detail="Sesi tidak valid")
        if user_session.get("role") not in self.allowed_roles:
            raise HTTPException(status_code=403, detail="Akses ditolak")
        return user_session

```

10. Penjelasan Library atau Komponen yang Digunakan 

* **FastAPI:** *Framework web* utama yang digunakan untuk membangun *RESTful* API secara cepat dan asinkron.
* **SQLModel & SQLAlchemy:** Komponen ORM (*Object Relational Mapping*) untuk menghubungkan kode Python ke database PostgreSQL menggunakan konsep OOP.
* **PyJWT:** Komponen untuk mengenkripsi dan mendekode JSON Web Token (JWT) yang digunakan sebagai identitas sesi di dalam HTTP-Only Cookie.
* **Passlib (Argon2):** *Library* keamanan untuk melakukan *hashing* pada kata sandi pengguna agar tidak tersimpan dalam bentuk teks biasa (*plaintext*) di database.

11. Penjelasan Coding Guidelines dan Best Practices 

* **Separation of Concerns (Pemisahan Tanggung Jawab):** Arsitektur dipisah secara modular (`models.py`, `schemas.py`, `services.py`, `security.py`, `main.py`) agar kode tidak menumpuk di satu tempat dan mudah dirawat.
* **Repository Pattern:** Akses komunikasi ke database dibungkus ke dalam *class* `UserRepository` untuk membersihkan pengontrol (API) dari perintah kueri SQL secara langsung.
* **Secure Authentication:** Menggunakan metode JWT yang disuntikkan ke dalam *HTTP-Only Cookie* beserta pengecekan sesi menggunakan sistem *Dependency Injection* FastAPI, yang secara drastis mencegah serangan injeksi *Cross-Site Scripting* (XSS) dan manipulasi ID (*Insecure Direct Object Reference* / IDOR).
