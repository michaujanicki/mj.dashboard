from __future__ import annotations

# ── importy standardowej biblioteki ──────────────────────────────────────────
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean, median
from typing import Iterable
from urllib.parse import urlencode, urljoin
from urllib.request import urlopen


# ── stałe konfiguracyjne ─────────────────────────────────────────────────────
BAZOWY_URL_API           = "https://api.nfz.gov.pl/app-itl-api/"
DOMYSLNE_MIASTO          = "Włocławek"
DOMYSLNY_PRZYPADEK       = 1          # 1 = stabilny, 2 = pilny
DOMYSLNE_WOJEWODZTWO     = "02"       # kod wymagany przez API NFZ
DOMYSLNA_SCIEZKA_HISTORII     = Path("data") / "wloclawek_history.csv"
DOMYSLNA_SCIEZKA_INTERPOLACJI = Path("data") / "wloclawek_interpolated.csv"

# mapowanie polskich nazw metryk na pola klasy Migawka
MAPA_METRYK = {
    "minimum":  "minimalny_czas_oczekiwania_dni",
    "mediana":  "mediana_czasu_oczekiwania_dni",
    "srednia":  "sredni_czas_oczekiwania_dni",
}


# ── modele danych ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Migawka:
    czas_pomiaru: datetime
    miasto: str
    przypadek: int
    filtr_swiadczenia: str
    liczba_rekordow: int
    liczba_swiadczeniodawcow: int
    minimalny_czas_oczekiwania_dni: float
    mediana_czasu_oczekiwania_dni: float
    sredni_czas_oczekiwania_dni: float


@dataclass(frozen=True)
class OdcinekKubiczny:
    czas_startu: datetime
    czas_konca: datetime
    wartosc_poczatkowa: float
    a: float
    b: float
    c: float
    dlugosc_przedzialu_dni: float

    def oblicz(self, znacznik_czasu: datetime) -> float:
        x_dni = (znacznik_czasu - self.czas_startu).total_seconds() / 86400
        return self.wartosc_poczatkowa + (self.a * x_dni**3) + (self.b * x_dni**2) + (self.c * x_dni)

    def wzor(self) -> str:
        return (
            f"y = {self.wartosc_poczatkowa:.3f} + ({self.a:.6f})x^3 + ({self.b:.6f})x^2 + ({self.c:.6f})x, "
            f"dla x w dniach od {self.czas_startu.isoformat()}"
        )


# ── komunikacja z API NFZ ────────────────────────────────────────────────────
def zbuduj_url(zasob: str, **parametry: object) -> str:
    przefiltrowane = {klucz: wartosc for klucz, wartosc in parametry.items() if wartosc not in (None, "")}
    return urljoin(BAZOWY_URL_API, f"{zasob}?{urlencode(przefiltrowane)}")


def pobierz_json(url: str) -> dict:
    with urlopen(url) as odpowiedz:
        tresc = odpowiedz.read().decode("utf-8")
    return json.loads(tresc)


def pobierz_wszystkie_kolejki(miasto: str, przypadek: int, swiadczenie: str = "", wojewodztwo: str = "") -> list[dict]:
    strona = 1
    rekordy: list[dict] = []

    while True:
        url = zbuduj_url(
            "queues",
            page=strona,
            limit=25,
            format="json",
            case=przypadek,
            locality=miasto,
            benefit=swiadczenie,
            province=wojewodztwo,
        )
        odpowiedz = pobierz_json(url)
        dane = odpowiedz.get("data", [])
        rekordy.extend(dane)

        nastepny_link = odpowiedz.get("links", {}).get("next")
        if not nastepny_link:
            break
        strona += 1

    return rekordy


def wyciagnij_czas_oczekiwania_dni(rekord_kolejki: dict, czas_pomiaru: datetime) -> float | None:
    atrybuty = rekord_kolejki.get("attributes") or {}
    if not isinstance(atrybuty, dict):
        return None

    daty = atrybuty.get("dates") or {}
    if not isinstance(daty, dict):
        return None

    tekst_daty = daty.get("date")
    if not tekst_daty:
        return None

    dostepny_termin = datetime.fromisoformat(tekst_daty)
    czas_oczekiwania_dni = (dostepny_termin.date() - czas_pomiaru.date()).days
    return max(float(czas_oczekiwania_dni), 0.0)


def zbuduj_migawke(
    rekordy: Iterable[dict],
    miasto: str,
    przypadek: int,
    filtr_swiadczenia: str,
    czas_pomiaru: datetime,
) -> Migawka:
    czasy_oczekiwania: list[float] = []
    swiadczeniodawcy: set[str] = set()

    for rekord in rekordy:
        atrybuty = rekord.get("attributes") or {}
        if not isinstance(atrybuty, dict):
            continue

        swiadczeniodawca = atrybuty.get("provider")
        if swiadczeniodawca:
            swiadczeniodawcy.add(swiadczeniodawca)

        czas_oczekiwania_dni = wyciagnij_czas_oczekiwania_dni(rekord, czas_pomiaru)
        if czas_oczekiwania_dni is not None:
            czasy_oczekiwania.append(czas_oczekiwania_dni)

    if not czasy_oczekiwania:
        raise ValueError("NFZ API nie zwrocilo rekordow z data pierwszego wolnego terminu dla podanych filtrow.")

    return Migawka(
        czas_pomiaru=czas_pomiaru,
        miasto=miasto,
        przypadek=przypadek,
        filtr_swiadczenia=filtr_swiadczenia,
        liczba_rekordow=len(czasy_oczekiwania),
        liczba_swiadczeniodawcow=len(swiadczeniodawcy),
        minimalny_czas_oczekiwania_dni=min(czasy_oczekiwania),
        mediana_czasu_oczekiwania_dni=float(median(czasy_oczekiwania)),
        sredni_czas_oczekiwania_dni=float(fmean(czasy_oczekiwania)),
    )


# ── operacje na plikach CSV ──────────────────────────────────────────────────
def utworz_katalog_nadrzedny(sciezka_pliku: Path) -> None:
    sciezka_pliku.parent.mkdir(parents=True, exist_ok=True)


def dopisz_wiersz_migawki(sciezka_pliku: Path, migawka: Migawka) -> None:
    utworz_katalog_nadrzedny(sciezka_pliku)
    plik_istnieje = sciezka_pliku.exists()

    with sciezka_pliku.open("a", newline="", encoding="utf-8-sig") as uchwyt:
        zapis = csv.DictWriter(
            uchwyt,
            fieldnames=[
                "observed_at",
                "city",
                "case",
                "benefit_filter",
                "records_count",
                "provider_count",
                "min_wait_days",
                "median_wait_days",
                "mean_wait_days",
            ],
        )
        if not plik_istnieje:
            zapis.writeheader()

        zapis.writerow(
            {
                "observed_at": migawka.czas_pomiaru.isoformat(timespec="seconds"),
                "city": migawka.miasto,
                "case": migawka.przypadek,
                "benefit_filter": migawka.filtr_swiadczenia,
                "records_count": migawka.liczba_rekordow,
                "provider_count": migawka.liczba_swiadczeniodawcow,
                "min_wait_days": f"{migawka.minimalny_czas_oczekiwania_dni:.3f}",
                "median_wait_days": f"{migawka.mediana_czasu_oczekiwania_dni:.3f}",
                "mean_wait_days": f"{migawka.sredni_czas_oczekiwania_dni:.3f}",
            }
        )


def wczytaj_historie(sciezka_pliku: Path) -> list[Migawka]:
    with sciezka_pliku.open("r", newline="", encoding="utf-8-sig") as uchwyt:
        wiersze = list(csv.DictReader(uchwyt))

    migawki = [
        Migawka(
            czas_pomiaru=datetime.fromisoformat(wiersz["observed_at"]),
            miasto=wiersz["city"],
            przypadek=int(wiersz["case"]),
            filtr_swiadczenia=wiersz.get("benefit_filter", ""),
            liczba_rekordow=int(wiersz["records_count"]),
            liczba_swiadczeniodawcow=int(wiersz["provider_count"]),
            minimalny_czas_oczekiwania_dni=float(wiersz["min_wait_days"]),
            mediana_czasu_oczekiwania_dni=float(wiersz["median_wait_days"]),
            sredni_czas_oczekiwania_dni=float(wiersz["mean_wait_days"]),
        )
        for wiersz in wiersze
    ]
    migawki.sort(key=lambda migawka: migawka.czas_pomiaru)
    return migawki


# ── algorytm interpolacji kubicznej Hermite'a ────────────────────────────────
# wzór: y = y0 + ax^3 + bx^2 + cx
def oblicz_nachylenia(migawki: list[Migawka], nazwa_metryki: str) -> list[float]:
    if len(migawki) < 2:
        raise ValueError("Do interpolacji potrzebne sa co najmniej 2 snapshoty.")

    nachylenia: list[float] = []
    for indeks, migawka in enumerate(migawki):
        if indeks == 0:
            prawa = migawki[indeks + 1]
            delta_y = getattr(prawa, nazwa_metryki) - getattr(migawka, nazwa_metryki)
            delta_t = (prawa.czas_pomiaru - migawka.czas_pomiaru).total_seconds() / 86400
        elif indeks == len(migawki) - 1:
            lewa = migawki[indeks - 1]
            delta_y = getattr(migawka, nazwa_metryki) - getattr(lewa, nazwa_metryki)
            delta_t = (migawka.czas_pomiaru - lewa.czas_pomiaru).total_seconds() / 86400
        else:
            lewa = migawki[indeks - 1]
            prawa = migawki[indeks + 1]
            delta_y = getattr(prawa, nazwa_metryki) - getattr(lewa, nazwa_metryki)
            delta_t = (prawa.czas_pomiaru - lewa.czas_pomiaru).total_seconds() / 86400

        nachylenia.append(delta_y / delta_t)

    return nachylenia


def zbuduj_odcinki_kubiczne(migawki: list[Migawka], nazwa_metryki: str) -> list[OdcinekKubiczny]:
    nachylenia = oblicz_nachylenia(migawki, nazwa_metryki)
    odcinki: list[OdcinekKubiczny] = []

    for indeks in range(len(migawki) - 1):
        poczatek = migawki[indeks]
        koniec = migawki[indeks + 1]
        y0 = getattr(poczatek, nazwa_metryki)
        y1 = getattr(koniec, nazwa_metryki)
        dlugosc_przedzialu_dni = (koniec.czas_pomiaru - poczatek.czas_pomiaru).total_seconds() / 86400
        roznica_y = y1 - y0
        m0 = nachylenia[indeks]
        m1 = nachylenia[indeks + 1]

        a = ((dlugosc_przedzialu_dni * (m0 + m1)) - (2 * roznica_y)) / (dlugosc_przedzialu_dni**3)
        b = ((3 * roznica_y) - (dlugosc_przedzialu_dni * ((2 * m0) + m1))) / (dlugosc_przedzialu_dni**2)
        c = m0

        odcinki.append(
            OdcinekKubiczny(
                czas_startu=poczatek.czas_pomiaru,
                czas_konca=koniec.czas_pomiaru,
                wartosc_poczatkowa=y0,
                a=a,
                b=b,
                c=c,
                dlugosc_przedzialu_dni=dlugosc_przedzialu_dni,
            )
        )

    return odcinki


def interpoluj_historie(migawki: list[Migawka], nazwa_metryki: str, krok_godziny: int) -> list[dict[str, str]]:
    odcinki = zbuduj_odcinki_kubiczne(migawki, nazwa_metryki)
    punkty: list[dict[str, str]] = []
    krok = timedelta(hours=krok_godziny)

    for indeks_odcinka, odcinek in enumerate(odcinki):
        aktualny_czas = odcinek.czas_startu
        while aktualny_czas < odcinek.czas_konca:
            zrodlo = "observed" if aktualny_czas == odcinek.czas_startu else "interpolated"
            punkty.append(
                {
                    "timestamp": aktualny_czas.isoformat(timespec="seconds"),
                    "metric": f"{odcinek.oblicz(aktualny_czas):.3f}",
                    "source": zrodlo,
                    "segment_formula": odcinek.wzor(),
                }
            )
            aktualny_czas += krok

        if indeks_odcinka == len(odcinki) - 1:
            punkty.append(
                {
                    "timestamp": odcinek.czas_konca.isoformat(timespec="seconds"),
                    "metric": f"{odcinek.oblicz(odcinek.czas_konca):.3f}",
                    "source": "observed",
                    "segment_formula": odcinek.wzor(),
                }
            )

    return punkty


def zapisz_csv_interpolacji(sciezka_pliku: Path, wiersze: list[dict[str, str]]) -> None:
    utworz_katalog_nadrzedny(sciezka_pliku)
    with sciezka_pliku.open("w", newline="", encoding="utf-8-sig") as uchwyt:
        zapis = csv.DictWriter(uchwyt, fieldnames=["timestamp", "metric", "source", "segment_formula"])
        zapis.writeheader()
        zapis.writerows(wiersze)


# ── obsługa poleceń (wywoływanych z menu) ───────────────────────────────────
def wykonaj_snapshot(
    sciezka_wyjsciowa: Path,
    swiadczenie: str = "",
) -> None:
    czas_pomiaru = datetime.now().replace(microsecond=0)
    rekordy = pobierz_wszystkie_kolejki(
        miasto=DOMYSLNE_MIASTO,
        przypadek=DOMYSLNY_PRZYPADEK,
        swiadczenie=swiadczenie,
        wojewodztwo=DOMYSLNE_WOJEWODZTWO,
    )
    migawka = zbuduj_migawke(
        rekordy=rekordy,
        miasto=DOMYSLNE_MIASTO,
        przypadek=DOMYSLNY_PRZYPADEK,
        filtr_swiadczenia=swiadczenie,
        czas_pomiaru=czas_pomiaru,
    )
    dopisz_wiersz_migawki(sciezka_wyjsciowa, migawka)

    print(f"Zapisano snapshot do {sciezka_wyjsciowa}")
    print(f"Miasto: {migawka.miasto}")
    print(f"Filtr swiadczenia: {migawka.filtr_swiadczenia or 'brak'}")
    print(f"Rekordy: {migawka.liczba_rekordow}, swiadczeniodawcy: {migawka.liczba_swiadczeniodawcow}")
    print(f"Minimalny czas oczekiwania [dni]: {migawka.minimalny_czas_oczekiwania_dni:.3f}")
    print(f"Mediana czasu oczekiwania [dni]: {migawka.mediana_czasu_oczekiwania_dni:.3f}")
    print(f"Sredni czas oczekiwania [dni]: {migawka.sredni_czas_oczekiwania_dni:.3f}")


def wykonaj_interpolacje(
    sciezka_wejsciowa: Path,
    sciezka_wyjsciowa: Path,
    metryka: str,
    krok_godzin: int,
) -> None:
    nazwa_metryki = MAPA_METRYK[metryka]
    migawki = wczytaj_historie(sciezka_wejsciowa)
    punkty = interpoluj_historie(migawki, nazwa_metryki=nazwa_metryki, krok_godziny=krok_godzin)
    zapisz_csv_interpolacji(sciezka_wyjsciowa, punkty)

    print(f"Zapisano interpolacje do {sciezka_wyjsciowa}")
    print(f"Liczba punktow: {len(punkty)}")
    print(f"Krok interpolacji: {krok_godzin} h")
    print(f"Metryka: {metryka}")
    print("Przykladowy wielomian:")
    print(punkty[0]["segment_formula"])


def wygeneruj_dane_testowe(sciezka_wyjsciowa: Path, liczba_dni: int) -> None:
    import random
    random.seed(42)

    bazowa_mediana = 54.0
    bazowa_srednia = 125.666
    liczba_rekordow = 293
    liczba_swiadczeniodawcow = 62
    dzisiaj = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)

    wiersze = []
    for dzien_wstecz in range(liczba_dni, 0, -1):
        czas = dzisiaj - timedelta(days=dzien_wstecz)
        trend = dzien_wstecz * 0.3
        mediana = round(max(1.0, bazowa_mediana - trend + random.uniform(-3, 3)), 3)
        srednia = round(max(1.0, bazowa_srednia - trend * 2 + random.uniform(-8, 8)), 3)
        min_dni = round(max(0.0, random.uniform(0, 2)), 3)
        wiersze.append({
            "observed_at": czas.isoformat(),
            "city": DOMYSLNE_MIASTO,
            "case": DOMYSLNY_PRZYPADEK,
            "benefit_filter": "",
            "records_count": liczba_rekordow + random.randint(-10, 10),
            "provider_count": liczba_swiadczeniodawcow + random.randint(-2, 2),
            "min_wait_days": min_dni,
            "median_wait_days": mediana,
            "mean_wait_days": srednia,
        })

    utworz_katalog_nadrzedny(sciezka_wyjsciowa)
    pola = ["observed_at", "city", "case", "benefit_filter", "records_count",
            "provider_count", "min_wait_days", "median_wait_days", "mean_wait_days"]
    with sciezka_wyjsciowa.open("w", newline="", encoding="utf-8-sig") as uchwyt:
        zapis = csv.DictWriter(uchwyt, fieldnames=pola)
        zapis.writeheader()
        zapis.writerows(wiersze)

    print(f"Wygenerowano {len(wiersze)} wierszy testowych -> {sciezka_wyjsciowa}")


# ── interfejs tekstowy (menu) ─────────────────────────────────────────────────
def pobierz_lub_domysl(etykieta: str, domyslna_wartosc: str) -> str:
    wartosc = input(f"  {etykieta} [{domyslna_wartosc}]: ").strip()
    return wartosc or domyslna_wartosc


def run_menu() -> None:
    print()
    print("=" * 50)
    print("  Interpolacja kolejek NFZ  -  Włocławek")
    print("=" * 50)
    print("  1.  Pobierz snapshot z NFZ (dzis)")
    print("  2.  Interpoluj plik historii")
    print("  3.  Wygeneruj dane testowe")
    print("  4.  Koniec")
    print("=" * 50)

    wybor = input("Wybor [1-4]: ").strip()

    if wybor == "1":
        wykonaj_snapshot(DOMYSLNA_SCIEZKA_HISTORII)
        return

    if wybor == "2":
        sciezka_wejsciowa = Path(pobierz_lub_domysl("Plik historii CSV", str(DOMYSLNA_SCIEZKA_HISTORII)))
        sciezka_wyjsciowa = Path(pobierz_lub_domysl("Plik wyjsciowy CSV", str(DOMYSLNA_SCIEZKA_INTERPOLACJI)))
        metryka = pobierz_lub_domysl("Metryka [minimum/mediana/srednia]", "mediana")
        krok_godzin = int(pobierz_lub_domysl("Krok interpolacji w godzinach", "6"))
        wykonaj_interpolacje(sciezka_wejsciowa, sciezka_wyjsciowa, metryka, krok_godzin)
        return

    if wybor == "3":
        liczba_dni = int(pobierz_lub_domysl("Liczba dni wstecz", "30"))
        sciezka_wyjsciowa = Path(pobierz_lub_domysl("Plik wyjsciowy CSV", str(DOMYSLNA_SCIEZKA_HISTORII)))
        wygeneruj_dane_testowe(sciezka_wyjsciowa, liczba_dni)
        return

    if wybor == "4":
        print("Koniec.")
        return

    print("Nieznana opcja. Uruchom program ponownie i wybierz 1, 2, 3 lub 4.")


def main() -> None:
    run_menu()


if __name__ == "__main__":
    main()