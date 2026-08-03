# opnsense-haproxy

Legt einen kompletten HAProxy-Eintrag auf OPNsense mit **einem** Schritt an —
wahlweise im Fenster oder auf der Kommandozeile.

Statt in der OPNsense-GUI nacheinander Real Server → Backend Pool → Condition
→ Rule anzulegen und die Rule dann noch im Public Service zu verlinken, reicht:

```sh
./haproxy_gui.py                                                   # Fenster
./opnsense_haproxy.py add app.example.com -i 192.168.1.50 --no-ssl  # Terminal
```

Beide Wege legen alle vier Objekte an, hängen die Rule an den Public Service,
tragen auf Wunsch die DNS-Umschreibung in AdGuard Home ein, prüfen die
Konfiguration (`haproxy -c`) und laden HAProxy neu. Schlägt ein Schritt fehl,
wird alles bereits Angelegte wieder entfernt — es bleiben keine
Halb-Konfigurationen zurück.

Die auswählbaren **Basis-Domains** kommen aus den Zertifikaten des
ACME-Clients: du wählst `home.example.com` und tippst nur noch `wiki`.

Nur Python 3 (Standardbibliothek), keine weiteren Abhängigkeiten, kein
Build-Schritt.

| Datei | |
| --- | --- |
| `opnsense_haproxy.py` | Logik und CLI |
| `haproxy_gui.py` | Fenster (tkinter) |
| `HAProxy-Starter.bat` | Doppelklick-Start für Windows |

## Herunterladen

**[opnsense-haproxy-1.1.0.zip](releases/opnsense-haproxy-1.1.0.zip?raw=1)** —
entpacken und loslegen; unter Windows `HAProxy-Starter.bat` doppelklicken. Was
sich seit der letzten Fassung geändert hat, steht im
[Änderungsverzeichnis](CHANGELOG.md).

Wer lieber den aktuellen Stand von `main` will, nimmt den grünen **Code**-Knopf
oben oder ein Tag unter [Tags](../../tags). Ist das Programm einmal da, holt es
sich neue Fassungen selbst — siehe [Updates](#updates).

## Einrichten

1. In OPNsense unter **System → Zugriff → Benutzer → API-Schlüssel** einen
   Schlüssel anlegen. Der Benutzer braucht die Rechte für *Services: HAProxy*.
2. Konfiguration anlegen:

```sh
./opnsense_haproxy.py init
```

Das schreibt `~/.config/opnsense-haproxy/config.json` (Modus 600) und testet
die Verbindung. Alternativ die Datei von Hand anlegen, siehe
[config.example.json](config.example.json), oder alles über
`--url/--key/--secret` bzw. `OPNSENSE_URL`/`OPNSENSE_KEY`/`OPNSENSE_SECRET`
übergeben.

Wenn OPNsense ein selbstsigniertes Zertifikat hat: `"verify_ssl": false` in
der Konfiguration oder `--insecure`.

### Mehrere OPNsense

Die Konfigurationsdatei hält eine Liste von **Verbindungen**, jede mit eigenem
Namen, eigenem Public Service und — falls vorhanden — eigenem AdGuard:

```json
{
  "active": "Zuhause",
  "profiles": [
    { "name": "Zuhause", "url": "…", "key": "…", "secret": "…",
      "adguard": { "url": "…", "target": "192.168.1.1" } },
    { "name": "Zweitstandort", "url": "…", "key": "…", "secret": "…" }
  ]
}
```

Der zweite Eintrag hat kein AdGuard — dann bleibt DNS dort einfach unberührt.

Im Fenster steht oben rechts ein Umschalter — auch bei nur einer Verbindung,
denn über ihn legst du weitere an („＋ neue Verbindung …") und bearbeitest oder
löschst die aktuelle („⚙ diese bearbeiten …"). Auf der Kommandozeile wählt `-P NAME` aus,
`profiles` zeigt alle:

```sh
./opnsense_haproxy.py profiles
./opnsense_haproxy.py -P Zweitstandort list
./opnsense_haproxy.py init                # legt eine weitere Verbindung an
```

Eine ältere Datei mit nur einer Verbindung ganz oben funktioniert unverändert
weiter — sie erscheint als Verbindung „Standard", nichts muss umgeschrieben
werden.

### Basis-Domains

Die Auswahlliste kommt aus dem **ACME-Client** (Plugin `os-acme-client`) und
braucht keine eigene Einrichtung — die dort gepflegten Zertifikate werden
gelesen:

* Ein Wildcard-Zertifikat `*.home.example.com` ergibt die Basis-Domain
  `home.example.com`, unter der jeder Hostname möglich ist.
* Ein Zertifikat für einen einzelnen Namen wird als exakter Name angeboten.

Passt der zusammengesetzte Name nicht zum Zertifikat (`a.b.home.example.com`
unter einem Wildcard, das nur eine Ebene abdeckt), gibt es eine Warnung —
angelegt wird trotzdem, denn das Zertifikat kann auch von woanders kommen.

Ist der ACME-Client nicht installiert, bleibt die Liste leer und du trägst
weiterhin den vollen Namen ein.

```sh
./opnsense_haproxy.py domains        # zeigt, was zur Auswahl steht
```

### DNS-Umschreibung in AdGuard Home

Optional. Ist in der Konfiguration ein `adguard`-Abschnitt mit `url` und
`target` hinterlegt, wird zu jedem neuen Host eine DNS-Umschreibung angelegt,
die auf `target` zeigt — also üblicherweise auf die IP von HAProxy. Beim
Entfernen verschwindet der Eintrag wieder.

```json
"adguard": {
  "url": "https://adguard.example.de",
  "username": "admin",
  "password": "…",
  "target": "192.168.1.1",
  "verify_ssl": false
}
```

Bei `url` genügt die Adresse der Oberfläche — die kopierte Browser-Zeile
(`https://adguard.example.de/#dns_rewrites`) geht genauso, der API-Pfad wird
selbst angehängt. Fehlt das Schema, wird `https://` angenommen; bei einer
AdGuard-Installation auf Port 3000 ohne TLS also `http://…:3000` angeben.

Im Fenster lässt sich das pro Host mit einem Schalter abwählen, auf der
Kommandozeile mit `--no-dns`. Zeigt ein Eintrag für den
Namen schon woanders hin, wird er **nicht** überschrieben, sondern gemeldet.

## Fenster

```sh
./haproxy_gui.py                 # oder: ./opnsense_haproxy.py gui
```

Braucht `tkinter`. Das gehört zu Python, wird auf Linux aber separat verpackt —
falls es fehlt, sagt das Programm beim Start, was zu installieren ist
(`sudo apt install python3-tk` auf Debian/Ubuntu). Unter Windows ist tkinter
im Installer von python.org bereits enthalten.

**Windows:** Ordner herunterladen und `HAProxy-Starter.bat` doppelklicken. Der
Starter sucht Python, prüft Version und tkinter und meldet im Klartext, was
fehlt, statt sich wortlos zu schließen. Voraussetzung ist einmalig Python 3.8
oder neuer von <https://www.python.org/downloads/> — beim Setup **„Add
python.exe to PATH"** ankreuzen.

Beim allerersten Start fragt ein Dialog nach Name, Adresse, API-Key und Secret
— und, wenn du den Haken setzt, nach AdGuard Home — und legt die
Konfigurationsdatei an; danach verbindet es sich von selbst. Oben rechts steht
der Umschalter für die Verbindungen, daneben das Zahnrad zum Bearbeiten.

Links das Formular — Basis-Domain, Hostname, Server-IP, Port, ein Schalter für
SSL zum Backend und einer für den AdGuard-Eintrag. Unter dem Hostnamen steht
laufend mit, welcher Name daraus wird. Rechts alles, was aktuell an den Public
Services hängt, mit **Entfernen** pro Eintrag. **Vorschau** zeigt, was angelegt
würde, ohne etwas zu ändern. Unten läuft das Protokoll mit denselben Zeilen wie
die CLI, farblich nach Anlegen, Löschen und Fehler getrennt. Hell/Dunkel
schaltet der Knopf oben rechts um; Theme und Fenstergröße werden gemerkt.
Der Knopf **⇩** daneben sucht nach Updates, siehe unten.

Alle API-Aufrufe laufen in einem Hintergrund-Thread, das Fenster friert also
nicht ein, während die OPNsense antwortet. Was gerade passiert, steht unter der
Kopfzeile — beim Start also „lese Public Services und Rules …", beim Anlegen
jeder Schritt, sobald er erledigt ist.

Der Dialog hinter dem Zahnrad bearbeitet immer **eine** Verbindung: oben die
OPNsense, darunter — hinter einem Haken — das dazugehörige AdGuard Home. Ist
der Haken aus, bleibt DNS für diese Verbindung unberührt. Ab der zweiten
Verbindung gibt es dort auch einen Löschen-Knopf.

## Updates

Der Knopf **⇩** oben rechts fragt bei GitHub nach einer neueren Fassung. Gibt es
keine, sagt er das; gibt es eine, zeigt ein Fenster die Versionsnummer und —
sofern hinterlegt — was sich geändert hat, und installiert sie auf Wunsch.
Danach ist ein Neustart des Programms nötig, den der Dialog gleich anbietet.

Einmal am Tag schaut das Programm beim Start selbst nach, ohne zu fragen und
ohne das Fenster aufzuhalten. Findet es etwas, trägt der Knopf die neue
Versionsnummer und ist farbig hinterlegt — mehr passiert von allein nicht.
Ist GitHub nicht erreichbar, bleibt das folgenlos. Wer das nicht möchte, setzt
in `~/.config/opnsense-haproxy/gui.json` `"update_check": false`; der Knopf
funktioniert weiter.

Auf der Kommandozeile:

```sh
./opnsense_haproxy.py update --check    # nur nachsehen
./opnsense_haproxy.py update            # nachsehen und nach Rückfrage installieren
./opnsense_haproxy.py --version
```

Ersetzt werden ausschließlich `opnsense_haproxy.py`, `haproxy_gui.py`,
`HAProxy-Starter.bat`, `README.md` und `config.example.json` — alles andere aus
dem Download wird ignoriert, Zugangsdaten und Einstellungen bleiben unangetastet.
Die bisherigen Dateien landen vorher in `backup-<version>/` daneben, falls du
zurück willst. Heruntergeladener Python-Code wird vor dem Schreiben auf Syntax
geprüft; ist das Archiv unvollständig oder beschädigt, wird nichts angefasst.

Liegt das Programm in einer git-Arbeitskopie, verweigert das Update den Dienst
und verweist auf `git pull` — sonst wären eigene Änderungen weg.

Ein neues Paket zum Herunterladen baut `./make_release.py`: es liest die
Versionsnummer aus `opnsense_haproxy.py` und legt
`releases/opnsense-haproxy-<version>.zip` an.

## Kommandozeile

Ganz ohne Argumente fragt das Tool die vier Werte nacheinander ab:

```
$ ./opnsense_haproxy.py add
URL / hostname: wiki.example.com
real server IP: 192.168.10.20
use SSL to the backend? (yes/no) [no]: yes
real server port [443]: 8443
```

Oder alles direkt auf der Kommandozeile:

```sh
# Basis-Domain wählen und nur den Hostnamen angeben
./opnsense_haproxy.py add wiki -b home.example.com -i 192.168.10.20 -p 8443 --ssl

# HTTP zum Backend, voller Name
./opnsense_haproxy.py add app.example.com -i 192.168.1.50 -p 8080 --no-ssl

# HTTPS zum Backend (Zertifikat wird bewusst nicht geprüft, s.u.)
./opnsense_haproxy.py add cloud.example.com -i 10.0.0.7 -p 443 --ssl

# nur ein Pfad-Präfix auf ein eigenes Backend
./opnsense_haproxy.py add https://example.com/api -i 10.0.0.9 -p 3000 --no-ssl

# die Basis-Domain selbst, ohne Subdomain
./opnsense_haproxy.py add @ -b home.example.com -i 10.0.0.8 --no-ssl

# ohne AdGuard-Eintrag
./opnsense_haproxy.py add test -b home.example.com -i 10.0.0.5 --no-ssl --no-dns

# erst mal nur anschauen, nichts ändern
./opnsense_haproxy.py add test.example.com -i 10.0.0.5 --no-ssl --dry-run
```

Weitere Befehle:

```sh
./opnsense_haproxy.py list                        # was hängt an welchem Public Service
./opnsense_haproxy.py domains                     # Basis-Domains aus dem ACME-Client
./opnsense_haproxy.py profiles                    # eingerichtete Verbindungen
./opnsense_haproxy.py remove app.example.com      # alle vier Objekte wieder weg
./opnsense_haproxy.py apply                       # Configtest + Reload
./opnsense_haproxy.py status                      # läuft HAProxy?
./opnsense_haproxy.py update                      # neue Version von GitHub holen
./opnsense_haproxy.py gui                         # Fenster
```

Für bequemeren Aufruf:

```sh
chmod +x opnsense_haproxy.py
sudo ln -s "$PWD/opnsense_haproxy.py" /usr/local/bin/haproxy-add
```

Der Symlink funktioniert auch für `gui` — `haproxy_gui.py` wird relativ zum
echten Skript gesucht, nicht zum Link.

## Was genau angelegt wird

Für `app.example.com` mit Ziel `192.168.1.50:8080`:

| Objekt in OPNsense | Name | Inhalt |
| --- | --- | --- |
| Real Server | `srv_app.example.com` | 192.168.1.50:8080 |
| Backend Pool | `be_app.example.com` | verweist auf den Real Server |
| Condition | `acl_app_example_com` | `hdr` — Host-Header ist `app.example.com` |
| Rule | `rule_app_example_com` | `if` Condition → `use_backend` |
| Public Service | (bestehend) | Rule wird an `linkedActions` angehängt |
| AdGuard-Umschreibung | — | `app.example.com` → konfiguriertes Ziel (optional) |

Bei einem Pfad (`example.com/api`) kommt eine zweite Condition `path_beg`
dazu; beide werden mit **AND** verknüpft.

## Entscheidungen, die das Tool trifft

* **Public Service**: gibt es nur einen, wird er automatisch benutzt. Bei
  mehreren muss `--frontend NAME` gesetzt werden (oder `"frontend"` in der
  Konfiguration).
* **Host-Header oder SNI**: läuft der Public Service im Modus `http`, wird auf
  den Host-Header gematcht. Bei `ssl`/`tcp` (SSL-Passthrough) sieht HAProxy
  keinen Host-Header, deshalb wird dort auf **SNI** gematcht und der Backend
  Pool auf `tcp` gesetzt. Ein Pfad ist in diesen Modi nicht möglich und wird
  mit einer Fehlermeldung abgelehnt.
* **`sslVerify` ist bei `--ssl` standardmäßig aus.** OPNsense schaltet es per
  Default an, was bei internen Hosts mit selbstsignierten Zertifikaten sofort
  zu 503ern führt. Wer eine saubere interne CA hat, nimmt `--ssl-verify`.
* **`X-Forwarded-For` ist bei HTTP-Backends an** (abschaltbar mit
  `--no-forward-for`).
* **Health-Monitor**: standardmäßig keiner. Mit `--healthcheck NAME` wird ein
  bereits in OPNsense angelegter Health Monitor verknüpft.
* **Namen**: `srv_`/`be_`/`acl_`/`rule_` + Hostname. Real Server und Backend
  dürfen Punkte enthalten, Conditions und Rules nicht (Vorgabe des Plugins) —
  dort werden Punkte zu `_`. Ein eigener Präfix geht mit `--prefix`.
* **Reload**: nach dem Anlegen läuft `haproxy -c`. Nur wenn der Test sauber
  ist, wird neu geladen. Mit `--no-apply` wird nur gespeichert.
* **Public Service**: es wird ausschließlich die Rule-Liste geschrieben, nie
  der ganze Eintrag. Ein Roundtrip über alle Felder quittiert die OPNsense-API
  je nach Feldtyp mit einem 500er — und könnte im Vorbeigehen Einstellungen wie
  das SSL-Zertifikat leeren.

## Grenzen

* `remove` findet die Objekte über das Namensschema. Wurden sie in OPNsense
  umbenannt, greift es nicht mehr — dann per Hand löschen.
* Bestehende Einträge werden nicht verändert; ist ein Name schon vergeben,
  bricht `add` ab und sagt, was im Weg ist.
* Zertifikate für den Public Service (Let's Encrypt o.ä.) verwaltet das Tool
  nicht.
