# opnsense-haproxy — Version 4 („Pforte“)

Neue Webseite im Heimnetz erreichbar machen: einen Namen wählen, das Ziel
angeben, anlegen. Pforte legt dafür in OPNsense-HAProxy alles an, trägt den
DNS-Eintrag in AdGuard Home ein und lädt HAProxy neu.

<img src="icon.png" alt="" width="96">

## Installieren

Gebraucht wird nur Python 3.9 oder neuer.

* **Linux:** im entpackten Ordner `bash install.sh`, oder ohne Download:

  ```
  curl -fsSL https://raw.githubusercontent.com/DukyNuky/opnsense-haproxy-config/main/install.sh | bash
  ```

  Das Skript legt das Programm nach `~/.local/share/opnsense-haproxy`, einen
  Eintrag „Pforte“ ins Startmenü und den Befehl `pforte` nach `~/.local/bin`.
  Root wird nicht gebraucht. `install.sh --deps` installiert zusätzlich die
  Pakete für das eigene Fenster per `sudo apt`, `install.sh --uninstall`
  entfernt alles außer den Zugangsdaten.
* **Windows:** Archiv entpacken, `HAProxy-Starter.bat` doppelklicken.
* **Ohne Installation:** `python3 haproxy_gui.py`

Es öffnet sich ein eigenes Programmfenster. Unter Linux (Mint, Ubuntu, Debian)
ist das ein natives Fenster mit GTK und WebKit, soweit `python3-gi` und
`gir1.2-webkit2-4.1` installiert sind. Sonst nimmt Pforte ein App-Fenster von
Edge oder Chrome (unter Windows ist Edge immer da) und erst zuletzt einen
Browser-Tab. Wird das Fenster geschlossen, beendet sich das Programm.
Mit `--browser` lässt sich der Tab erzwingen.

## Erster Start

Ein Assistent führt in sieben Schritten durch die Einrichtung und sagt bei
jedem, was wo in OPNsense einzustellen ist:

1. **Adresse** der OPNsense. Pforte prüft, ob sie erreichbar ist.
2. **Plugins:** `os-haproxy` und, für Zertifikate, `os-acme-client`.
3. **Benutzer** für Pforte mit den Rechten „Services: HAProxy“ und
   „Services: ACME Client“.
4. **API-Schlüssel:** die von OPNsense geladene Datei auswählen oder Key und
   Secret eintragen.
5. **Prüfung:** Anmeldung, Plugin, laufender Dienst, Eingang auf Port 443 und
   Zertifikate, je Punkt mit Anleitung, falls etwas fehlt.
6. **AdGuard Home** (optional): damit der DNS-Eintrag automatisch entsteht.
7. **Portainer** (optional): damit beim Ziel die laufenden Container samt Port
   vorgeschlagen werden.

Hat die OPNsense ein selbst signiertes Zertifikat, bietet der Assistent
„Trotzdem verbinden“ an. Einstellungen aus Version 3 lassen sich übernehmen.
Die Prüfung steht später in den Einstellungen unter „Einrichtung prüfen“.

## Ohne Fenster

```
pforte --check        # gespeicherte Zugänge prüfen: 0 bereit, 1 etwas fehlt, 2 nichts eingerichtet
pforte --configure    # Profil aus Umgebungsvariablen anlegen (siehe pforte --help)
```

Für Claude und andere Assistenten, die Pforte für jemanden einrichten, steht
der ganze Ablauf in [CLAUDE.md](CLAUDE.md).

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
