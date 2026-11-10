# Anleitung für Claude (und andere Assistenten)

Diese Datei beschreibt, wie Pforte für jemanden installiert und eingerichtet
wird, ohne das Fenster zu bedienen. Pforte legt Hosts in OPNsense-HAProxy an
(Real Server, Backend Pool, Condition, Rule), trägt den DNS-Eintrag in AdGuard
Home ein und lädt HAProxy neu.

## 1. Installieren (Linux)

```
bash install.sh            # aus dem entpackten Archiv oder der Arbeitskopie
bash install.sh --deps     # zusätzlich GTK/WebKit per sudo apt (fragt nach dem Passwort)
```

Ohne Archiv: `curl -fsSL https://raw.githubusercontent.com/DukyNuky/opnsense-haproxy-config/main/install.sh | bash`

Ergebnis: Programm in `~/.local/share/opnsense-haproxy`, Befehl
`~/.local/bin/pforte`, Eintrag „Pforte“ im Startmenü. Root wird nicht gebraucht.
`--deps` nur nach Rückfrage verwenden, es installiert Systempakete. Ohne
GTK/WebKit öffnet sich Pforte in Chrome/Edge oder im Browser.

Windows: Archiv entpacken, `HAProxy-Starter.bat` starten (Python 3.9+ nötig).

## 2. Was der Mensch selbst tun muss

Den API-Schlüssel kann nur ein Administrator in der Oberfläche der OPNsense
erzeugen. Diese Schritte weitergeben und auf die Datei warten:

1. System → Firmware → Plugins: `os-haproxy` installieren, für Zertifikate
   `os-acme-client`.
2. System → Zugang → Benutzer (Access → Users): Benutzer `pforte` anlegen,
   Rechte „Services: HAProxy“ und „Services: ACME Client“.
3. In der Benutzerliste „API-Schlüssel erstellen“ anklicken. Der Browser lädt
   eine Datei mit `key=…` und `secret=…`. Das Secret gibt es nur einmal.

Optional: Adresse, Benutzer und Passwort von AdGuard Home; Adresse und
Zugriffstoken von Portainer (Mein Konto → Zugriffstoken).

Nach den Geheimnissen selbst nicht im Chat fragen, wenn eine Datei reicht:
den Pfad der Schlüsseldatei erfragen.

## 3. Einrichten ohne Fenster

```
OPNSENSE_URL=https://192.168.1.1 \
OPNSENSE_KEYFILE=~/Downloads/OPNsense_pforte_apikey.txt \
pforte --configure
```

Weitere Variablen: `OPNSENSE_KEY`/`OPNSENSE_SECRET` statt der Datei,
`ADGUARD_URL`, `ADGUARD_USER`, `ADGUARD_PASSWORD`, `ADGUARD_TARGET` (IP, auf
der HAProxy lauscht; Vorgabe ist die IP der OPNsense), `PORTAINER_URL`,
`PORTAINER_TOKEN`, `PFORTE_PROFILE` (Name), `PFORTE_INSECURE=1` für ein selbst
signiertes Zertifikat. Geheimnisse gehören in die Umgebung oder die Datei, nie
in die Befehlszeile.

Gespeichert wird nur, wenn jeder angegebene Zugang funktioniert. Die Ausgabe
nennt je Punkt den Zustand und bei Bedarf die Schritte in OPNsense:

* `[ok]` in Ordnung
* `[offen]` Pforte läuft eingeschränkt (kein Eingang auf Port 443, kein
  Zertifikat, HAProxy gestoppt). Die Schritte dazu an den Menschen weitergeben.
* `[FEHLT]` so nicht benutzbar (Schlüssel falsch, Recht oder Plugin fehlt)

## 4. Prüfen

```
pforte --check             # 0 = bereit, 1 = etwas fehlt, 2 = nichts eingerichtet
pforte --check --profile=NAME
```

`--check` liest nur. Danach startet der Mensch Pforte über das Startmenü oder
mit `pforte`.

## 5. Regeln

* Zugangsdaten liegen in `~/.config/pforte/config.json` (Rechte 600). Inhalt
  nicht ausgeben, nicht kopieren, nicht einchecken.
* Keine Hosts zum Ausprobieren auf einer echten OPNsense anlegen, ohne dass
  der Mensch zustimmt. Zum Ausprobieren gibt es die Attrappe:
  `python3 tests/mock_services.py 8999` (key `k`, secret `s`, AdGuard
  `admin`/`pw`, Portainer-Token `tok`).
* Von Pforte angelegte Objekte tragen `managed:` in der Beschreibung. Alles
  andere in HAProxy stammt von Hand und wird nicht verändert.
* In einer Git-Arbeitskopie aktualisiert `git pull`, sonst der Knopf
  „Update“ im Programm oder ein erneuter Lauf von `install.sh`.

## 6. Entwicklung

```
python3 tests/run.py          # alle Tests
python3 tests/build_web.py    # nach Änderungen unter pforte/web (erzeugt pforte/_web.py)
```

Die Version steht in `pforte/__init__.py` und `opnsense_haproxy.py`, jede
Änderung braucht einen Eintrag in `CHANGELOG.md`.
