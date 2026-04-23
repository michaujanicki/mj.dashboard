# Dashboard ekspercki NFZ (Wloclawek)

## Kontekst klienta
Projekt przygotowalem dla koordynatora dostepnosci swiadczen medycznych (ekspert operacyjny),
ktory na biezaco monitoruje kolejki i obciazenie swiadczeniodawcow.

## Zakres danych
- Miasto: Wloclawek
- Zrodlo: API NFZ (snapshoty zapisywane do CSV)
- Metryki: min/mediana/sredni czas oczekiwania, liczba rekordow, liczba swiadczeniodawcow

## Co pokazuje panel
- KPI operacyjne z porownaniem do poprzedniego pomiaru
- Trend czasu oczekiwania + srednia kroczaca 7 dni
- Obciazenie systemu (rekordy vs liczba swiadczeniodawcow)
- Automatyczny sygnal ekspercki (stabilnie / uwaga / wysoki priorytet)

## Dlaczego ten projekt jest profesjonalny
- Stonowana paleta i czytelna typografia (bez krzykliwej grafiki)
- Uklad wspierajacy szybka decyzje operacyjna
- Polaczenie danych biezacych z komentarzem analitycznym

## Pytania do dyskusji na forum
1. Czy sygnal ekspercki powinien mocniej opierac sie na trendzie 14-dniowym zamiast 7-dniowego?
2. Czy dodac podzial na pilnosc przypadku (stabilny vs pilny) jako osobne zakladki?
3. Jakie progi alarmowe dla mediany czasu oczekiwania uznalibyscie za uzasadnione?

## Jak uruchomic
1. `pip install -r requirements.txt`
2. `streamlit run dashboard_nfz.py`
