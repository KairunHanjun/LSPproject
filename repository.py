from sqlmodel import Session, select
from models import Guru, Siswa, Users

class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def find_user_by_nomor_induk(self, nomor_induk: str) -> Users | None:
        """Sama persis seperti findByNomorInduk di Spring Boot!"""
        statement = select(Users).where(Users.nomor_induk == nomor_induk)
        return self.db.exec(statement).first()
        
    def find_guru_by_nip(self, nip: str) -> Guru | None:
        statement = select(Guru).where(Guru.nip == nip)
        return self.db.exec(statement).first()

    def find_siswa_by_nis(self, nis: str) -> Guru | None:
        statement = select(Siswa).where(Siswa.nis == nis)
        return self.db.exec(statement).first()

    def save(self, user: Users) -> Users:
        """Sama seperti repository.save(user)"""
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user