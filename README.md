# opnsense-haproxy — Version 4 („Pforte“)

Neue Webseite im Heimnetz erreichbar machen: einen Namen wählen, das Ziel
angeben, anlegen. Pforte legt dafür in OPNsense-HAProxy alles an, trägt den
DNS-Eintrag in AdGuard Home ein und lädt HAProxy neu.

<img src="icon.png" alt="" width="96">

## Starten

Gebraucht wird nur Python 3.9 oder neuer. Es muss nichts installiert werden.

* **Windows:** `HAProxy-Starter.bat` doppelklicken.
* **Linux/Mac:** `python3 haproxy_gui.py`

Es öffnet sich ein eigenes Programmfenster. Unter Linux (Mint, Ubuntu, Debian)
ist das ein natives Fenster mit GTK und WebKit, soweit `python3-gi` und
`gir1.2-webkit2-4.1` installiert sind. Sonst nimmt Pforte ein App-Fenster von
Edge oder Chrome (unter Windows ist Edge immer da) und erst zuletzt einen
Browser-Tab. Wird das Fenster geschlossen, beendet sich das Programm.
Mit `--browser` lässt sich der Tab erzwingen.

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

## Updates

Pforte prüft beim Start, ob auf GitHub eine neuere Version veröffentlicht ist.
Gibt es eine, erscheint oben der Knopf **Update x.y.z**. Ein Klick lädt die
Version, sichert die alte in `backup-<Version>` (die letzten drei bleiben),
ersetzt die Programmdateien und startet neu. Zugangsdaten und Einstellungen
bleiben unberührt. In einer Git-Arbeitskopie wird nichts überschrieben, dort
gilt `git pull`.

**Von Version 1 bis 3 auf 4:** Der Updater der alten Version holt Version 4
selbst, auch auf der Beta-Schiene. Dafür bleiben die alten Dateinamen
(`haproxy_gui.py`, `opnsense_haproxy.py`, `HAProxy-Starter.bat`) und das Format
der `channel.json` bestehen, und die Oberfläche liegt zusätzlich als
`pforte/_web.py` im Archiv, weil ein alter Updater nur `.py`-Dateien und ein
paar weitere Endungen mitnimmt. Die Einstellungen der alten Version lassen sich
beim ersten Start übernehmen. Die Kommandozeile der alten Versionen gibt es
nicht mehr.

## Wo liegen die Zugangsdaten?

In `~/.config/pforte/config.json` (Windows: `%APPDATA%\pforte`), nur für den
eigenen Benutzer lesbar. Das Programm lauscht ausschließlich auf `127.0.0.1` und
verlangt einen Zufallsschlüssel.

## Entwicklung

```
python3 tests/run.py                  # Tests, auch Update von 2.12 und 3.0-beta über deren echte Updater (braucht die Git-Tags)
python3 tests/build_web.py            # nach jeder Änderung an pforte/web neu erzeugen (pforte/_web.py)
python3 tests/mock_services.py 8999   # Attrappe zum Ausprobieren (key k, secret s)
```

Anzeigename und Version stehen in `pforte/__init__.py`; die Version steht zusätzlich in `opnsense_haproxy.py` (ein alter Updater liest sie dort), ein Test hält beide gleich.
