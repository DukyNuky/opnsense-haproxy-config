# Änderungen

## 1.2.0 — 4. August 2026

**Ein fester Platz, ein Symbol, und AdGuard im Blick.**

- **Installieren.** Der Knopf **⤓** oben rechts — oder
  `opnsense_haproxy.py install` — kopiert das Programm nach
  `~/.local/share/opnsense-haproxy` (Zielordner frei wählbar), verlinkt die
  Befehle `haproxy-gui` und `opnsense-haproxy` in `~/.local/bin` und trägt es
  ins Anwendungsmenü ein, von wo es sich an die **Taskleiste** anheften lässt.
  Auf Wunsch zusätzlich auf den Schreibtisch. Unter Windows entsteht dieselbe
  Verknüpfung im Startmenü, gestartet über `pythonw.exe` — kein Konsolenfenster
  mehr daneben.
- **Ein Symbol** für Fenster, Taskleiste und Verknüpfung, unter Linux wie unter
  Windows (`icon.png`, `icon.ico`). Gezeichnet von `make_icon.py`, ohne
  Fremdpakete.
- **Die IP von HAProxy** steht jetzt bei der OPNsense, nicht mehr nur bei
  AdGuard: ein Feld `haproxy_ip` pro Verbindung, auf das die DNS-Einträge
  standardmäßig zeigen. Ein `target` im `adguard`-Abschnitt sticht sie weiterhin
  aus, `--dns-target` ebenso. Bestehende Konfigurationen laufen unverändert
  weiter.
- **Die Liste rechts ist anklickbar.** Ein Klick auf den Hostnamen öffnet die
  Seite im Browser — mit dem Schema und dem Port, auf denen der Public Service
  wirklich lauscht.
- **AdGuard pro Eintrag.** Jede Zeile zeigt, ob es eine DNS-Umschreibung gibt
  und ob sie auf HAProxy zeigt; ein Knopf trägt sie ein, biegt sie gerade oder
  löscht sie wieder — ohne HAProxy anzufassen.
- Rules, die in OPNsense von Hand über `hdr_beg` angelegt wurden, werden jetzt
  auch mit Hostnamen erkannt: Link und DNS-Knopf funktionieren für sie.
- Die Knöpfe in der Kopfzeile sagen bei Berührung, wofür sie da sind.

Behoben: Neuere Fassungen des HAProxy-Plugins liefern die Bind-Adresse eines
Public Service als Auswahlfeld statt als Text — im Fenster stand deshalb
Rohdaten-Kauderwelsch statt `192.168.1.1:443`.

## 1.1.0 — 3. August 2026

**Update-Funktion.** Das Programm holt sich neue Fassungen selbst von GitHub.

- Knopf **⇩** oben rechts im Fenster sucht auf Wunsch nach einer neueren
  Version, zeigt Versionsnummer und Änderungstext und installiert sie nach
  Rückfrage. Danach bietet der Dialog den Neustart gleich an.
- Einmal am Tag schaut das Programm beim Start selbst nach — im Hintergrund,
  ohne das Fenster aufzuhalten. Findet es etwas, trägt der Knopf nur die neue
  Versionsnummer; **installiert wird nie von allein.** Ist GitHub nicht
  erreichbar, bleibt das folgenlos. Abschaltbar mit `"update_check": false`
  in `~/.config/opnsense-haproxy/gui.json`.
- Neue Befehle: `opnsense_haproxy.py update [--check] [-y]` und `--version`.

Beim Installieren werden ausschließlich die Programmdateien ersetzt, ausgewählt
über eine feste Namensliste statt über das, was im Archiv steht — aus dem
Download kann damit nichts Fremdes im Ordner landen. Heruntergeladener
Python-Code wird vorher auf Syntax geprüft; ist das Archiv unvollständig oder
beschädigt, wird gar nichts angefasst. Die bisherigen Dateien landen in
`backup-<version>/`. Zugangsdaten und Einstellungen bleiben unangetastet.

Liegt das Programm in einer git-Arbeitskopie, verweigert das Update den Dienst
und verweist auf `git pull`.

## 1.0.0 — 3. August 2026

Erste Fassung.

- Legt aus URL, Server-IP, Port und der SSL-Frage alle vier HAProxy-Objekte auf
  einmal an — Real Server, Backend, Condition und Rule — und hängt die Rule in
  den Public Service. Danach Configtest und Reload.
- Geht ein Schritt schief, werden die bereits angelegten Objekte wieder
  entfernt; es bleibt nichts Halbfertiges stehen.
- **Basis-Domains** kommen aus den Zertifikaten des ACME-Clients, inklusive
  Wildcards. Im Formular reicht dann der Hostname.
- **DNS-Umschreibung in AdGuard Home** wird auf Wunsch gleich mit angelegt und
  beim Entfernen wieder abgeräumt — pro Verbindung einstellbar, und es darf
  auch gar kein AdGuard geben.
- **Mehrere OPNsense** als Verbindungen mit Umschalter oben rechts.
- Fenster (tkinter) und Kommandozeile, hell und dunkel, deutschsprachig.
- `HAProxy-Starter.bat` für Windows: sucht Python, prüft Version und tkinter
  und sagt im Klartext, was fehlt.
- Nur die Python-Standardbibliothek, keine weiteren Pakete.
