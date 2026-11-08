# Pforte

Neue Webseite im Heimnetz erreichbar machen: einen Namen wählen, das Ziel
angeben, anlegen. Pforte legt dafür in OPNsense-HAProxy alles an, trägt den
DNS-Eintrag in AdGuard Home ein und lädt HAProxy neu.

<img src="icon.png" alt="" width="96">

## Starten

Gebraucht wird nur Python 3.9 oder neuer. Es muss nichts installiert werden.

* **Windows:** `Pforte-Starter.bat` doppelklicken.
* **Linux/Mac:** `python3 pforte.py`

Es öffnet sich ein eigenes Fenster (Chrome, Edge oder Chromium) oder ein
Browser-Tab. Wird das Fenster geschlossen, beendet sich das Programm.

## Erster Start

Ein Assistent fragt drei Zugänge ab und testet jeden sofort:

1. **OPNsense** (Pflicht): Adresse, API-Key und API-Secret.
2. **AdGuard Home** (optional): damit der DNS-Eintrag automatisch entsteht.
3. **Portainer** (optional): damit beim Ziel die laufenden Container samt Port
   vorgeschlagen werden.

Hat die OPNsense ein selbst signiertes Zertifikat, bietet der Assistent
„Trotzdem verbinden“ an. Einstellungen aus Version 3 lassen sich übernehmen.

### API-Schlüssel in OPNsense

1. *System → Zugriff → Benutzer*: neuen Benutzer anlegen, z. B. `pforte`.
2. Benutzer öffnen, unter *Effektive Berechtigungen* **Services: HAProxy** und
   **Services: ACME Client** hinzufügen (ACME liefert die Domainliste).
3. In der Benutzerübersicht das Schlüssel-Symbol der Zeile anklicken. Die
   heruntergeladene Datei enthält `key=…` und `secret=…`.

## Neuen Host anlegen

1. Namen eintippen, z. B. `wiki`. Die Domain kommt aus den ACME-Zertifikaten der
   OPNsense; vorgewählt ist die, unter der schon die meisten Hosts hängen.
2. Ziel angeben: `192.168.0.20:8080`, oder `https://…`, wenn das Ziel selbst
   TLS spricht. Mit Portainer reicht ein Klick auf einen Container.
3. **Anlegen.**

Als Eingang ist der Public Service vorgewählt, der auf Port 443 lauscht und die
meisten Regeln trägt. Gibt es mehrere, stehen die übrigen in der Auswahl daneben.

Schlägt unterwegs etwas fehl oder lehnt HAProxy die Konfiguration ab, wird alles
Angelegte wieder entfernt. Unter **Deine Hosts** lassen sich von Pforte
angelegte Hosts samt DNS-Eintrag wieder löschen; von Hand angelegte Regeln
werden nur angezeigt.

## Wo liegen die Zugangsdaten?

In `~/.config/pforte/config.json` (Windows: `%APPDATA%\pforte`), nur für den
eigenen Benutzer lesbar. Das Programm lauscht ausschließlich auf `127.0.0.1` und
verlangt einen Zufallsschlüssel.

## Entwicklung

```
python3 tests/run.py                  # Tests, mit einer Attrappe von OPNsense/AdGuard/Portainer
python3 tests/mock_services.py 8999   # Attrappe zum Ausprobieren (key k, secret s)
```

Der Programmname steht nur in `pforte/__init__.py`.
