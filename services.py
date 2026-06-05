def validasi_nilai(nilai: float) -> bool:
    if nilai is None:
        return True # Anggap valid jika belum diinput (default 0.0)
    return 0 <= nilai <= 100

def hitung_nilai_akhir(tugas: float, uts: float, uas: float) -> float:
    # Handle kasus di mana nilai belum diinput (None)
    t = tugas or 0.0
    ut = uts or 0.0
    ua = uas or 0.0
    
    if not (validasi_nilai(t) and validasi_nilai(ut) and validasi_nilai(ua)):
        raise ValueError("Semua nilai harus berada dalam rentang 0-100")
        
    nilai_akhir = (0.30 * t) + (0.30 * ut) + (0.40 * ua)
    return round(nilai_akhir, 2)

def tentukan_status_kelulusan(nilai_akhir: float) -> str:
    if nilai_akhir >= 70:   
        return "Lulus"
    else:
        return "Tidak Lulus"