# Änderungen

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
