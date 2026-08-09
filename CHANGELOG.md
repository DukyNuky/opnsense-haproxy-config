# Änderungen

## 2.2.0 — 9. August 2026

**Nichts mehr wurde gespeichert, ohne dass es jemand gemerkt hätte — und wo
das Programm nach einem Schlüssel fragt, steht jetzt der Weg dorthin.**

- **Einstellungen wurden nicht mehr geschrieben.** Ohne `--config` blieb der
  Pfad zur Datei leer, und jeder Versuch zu speichern brach mitten im Klick ab:
  ohne Meldung, ohne Zeile im Protokoll, einfach nichts. Das traf jeden
  Wechsel der Verbindung und jede Änderung an einem System. Der Pfad ist jetzt
  von Anfang an der, der in den Einstellungen unten auch angezeigt wird.
- **Der Umschalter oben rechts meint den Tab, der vorne ist.** Auf **HAProxy**
  wählt er die Firewall, auf **Portainer** den Docker-Host. Bisher schaltete er
  auf beiden Tabs die OPNsense um — auf dem zweiten also etwas, das dort gar
  nicht zu sehen war. Der zweite Umschalter im Portainer-Tab, der dasselbe
  tun sollte, ist damit weg; geblieben ist daneben die Auswahl der Umgebung.
- **Links zu den Seiten, die Schlüssel und Token ausgeben.** Unter *API-Secret*
  steht, wie in OPNsense Key und Secret zusammen entstehen, samt Link auf die
  **Benutzerverwaltung der eingetragenen Firewall**; unter *Zugriffstoken* der
  Link auf **My account → Access tokens** des eingetragenen Portainers. Beide
  Links werden aus der Adresse gebaut, die im Formular darüber steht, führen
  also zur eigenen Maschine und nicht in ein Handbuch.
- **Und beim privaten Repository steht, welche Rechte reichen.** Lesen genügt:
  bei einem GitHub *Fine-grained token* **Repository access → Only select
  repositories** und **Permissions → Repository permissions → Contents:
  Read-only**, bei GitLab der Scope `read_repository`. Daneben je ein Link zur
  Seite, auf der das Token angelegt wird.
- **Freie Host-Ports stehen im Formular für den neuen Stack.** Unter den
  Umgebungsvariablen liegt eine Liste der Ports, die auf der gewählten Umgebung
  **niemand belegt** — abgeglichen mit allem, was die Container dort nach außen
  veröffentlichen, Stacks und einzelne Container zusammen. **einsetzen**
  schreibt die Zahl an die Stelle, an der der Cursor steht. Darunter steht,
  was belegt ist, damit die Auswahl nachvollziehbar bleibt.
- **Ein Portainer allein genügt jetzt.** Wer nur einen Docker-Host einträgt und
  keine OPNsense, bekam einen leeren zweiten Tab mit „kein Portainer
  eingerichtet“ — die Verbindung wurde nur über die Firewall zusammengesetzt,
  und ohne Firewall blieb nichts übrig.
- **Die zuletzt benutzte Umgebung hängt am Portainer**, nicht mehr an der
  Firewall: bei zwei Docker-Hosts an einer OPNsense war die Umgebung des einen
  keine Antwort für den anderen.

## 2.1.0 — 8. August 2026

**Ein zweiter Stack aus demselben Repository scheitert nicht mehr erst beim
Deployen an einem Namen, den es auf dem Host schon gibt.**

- **Vor dem Deploy wird nachgesehen, was schon vergeben ist.** Das Programm
  liest die Compose-Datei, rechnet die Variablen mit dem aus, was im Feld
  steht, und vergleicht **Container-Namen** und **Host-Ports** mit dem, was auf
  der Umgebung läuft. Beides gehört dem ganzen Docker-Host, nicht dem einzelnen
  Stack — bisher fiel das erst auf, wenn Docker mitten im Anlegen mit
  `the container name "/…" is already in use` abbrach und in Portainer ein halb
  fertiger Stack stehen blieb.
- **Und ein Weg heraus wird gleich angeboten.** Kommt der Wert aus einer
  Variablen, schlägt das Fenster freie Werte vor — den Stacknamen für den
  Container, den nächsten freien Port darüber — und trägt sie auf Wunsch in die
  Umgebungsvariablen ein, an Ort und Stelle, wenn die Variable dort schon
  steht. *Nein* deployt unverändert, *Abbrechen* führt zurück ins Formular.
- **Steht der Wert fest in der Compose-Datei**, sagt das Fenster genau das,
  samt dem Namen dessen, der ihn gerade hält: zu ändern ist er dann nur im
  Repository, indem `container_name` auf eine Variable zeigt oder ganz
  entfällt.
- **Kommt die Absage doch von Portainer**, weil die Compose-Datei vorher nicht
  zu lesen war oder in der Zwischenzeit ein Container dazukam, steht unter der
  Meldung des Docker-Daemons jetzt dieselbe Erklärung in verständlichen Worten
  statt nur seiner englischen Zeile.

## 2.0.0 — 6. August 2026

**Die Einstellungen sind aufgeräumt: drei Listen statt einem langen Formular,
und beim Anlegen wird gefragt, wohin.**

- **OPNsense, AdGuard und Portainer haben je eine eigene Liste.** Das Zahnrad ⚙
  zeigt sie untereinander, jede mit **＋ Hinzufügen** und **Bearbeiten** je
  Eintrag; bearbeitet wird immer nur ein System auf einmal, in einem Fenster,
  das auf einen Blick zu lesen ist. Vorher stand alles drei in einem einzigen
  Formular untereinander, und jede Verbindung brauchte ihr eigenes AdGuard —
  dieselben Zugangsdaten mehrfach in der Datei.
- **Ein AdGuard für mehrere Standorte.** Eine OPNsense nennt das AdGuard und
  den Portainer, mit denen sie gewöhnlich arbeitet, beim Namen. Wer nichts
  nennt, arbeitet ohne.
- **Beim Anlegen wird gefragt, wohin.** Im Formular für den neuen Host steht
  **DNS-Eintrag in** — dort geht auch ein anderes AdGuard oder gar keins, für
  genau diesen Host. Aus dem Häkchen von früher ist damit eine Auswahl
  geworden.
- **Beim Deployen genauso.** Das Fenster für einen neuen Stack führt ganz oben
  **Deployen auf** mit Portainer und Umgebung. Ein Stack landet nicht mehr
  versehentlich auf dem falschen Docker-Host.
- **Der Deploy ist ein eigenes Fenster.** Er saß bisher in einer schmalen
  Spalte am linken Rand des Portainer-Tabs, in der Repository-Pfade und der
  Block Umgebungsvariablen kaum Platz hatten. Jetzt ist er ein breiter Dialog
  in zwei Spalten — und die Liste der Stacks bekommt die ganze Breite zurück.
- **Lange Portlisten klappen ein.** Ab dem sechsten Port zeigt eine Karte die
  ersten vier und darunter **▾ n weitere Ports**. Bei genau fünf bleibt alles
  stehen; eine einzelne Zeile zu verstecken hilft niemandem.
- **Die Konfigurationsdatei wird beim Lesen umgesetzt**, von Hand ist nichts zu
  tun. Zwei Profile, die auf dasselbe AdGuard zeigten, teilen sich danach einen
  Eintrag. Geschrieben wird die neue Form erst beim nächsten Speichern; die
  Kommandozeile liest beide Fassungen, `-P` meint weiterhin die OPNsense.

## 1.4.1 — 6. August 2026

**Nachreichen, was beim Sprung auf 1.4.0 liegengeblieben ist.**

- **Der fehlende Portainer-Tab holt sich seine Dateien selbst.** Wer von 1.3.0
  aus aktualisiert hat, bekam `portainer.py` und `portainer_gui.py` nicht mit —
  die alte Fassung kannte diese Namen noch nicht und kopierte nur, was auf
  ihrer Liste stand. Der Tab sagte daraufhin, man solle das Paket von Hand
  holen. Das ist nicht mehr nötig: ein Update von 1.4.0 aus bringt beide
  Dateien mit, und der Knopf im leeren Tab startet es. Nach einem Neustart des
  Programms ist der Tab da.
- **Installieren nimmt die Portainer-Dateien mit.** Beim Kopieren in einen
  festen Ordner blieben sie bisher zurück, mit demselben leeren Tab als Folge.

## 1.4.0 — 6. August 2026

**Zwei Tabs: HAProxy wie bisher, und daneben Portainer.**

- **Oben große Tabs.** Der erste ist das Programm, wie es war — Formular
  links, bestehende Hosts rechts, Protokoll unten. Der zweite ist neu.
- **Portainer-Tab.** Er liest Stacks und Container aus deinem Portainer und
  zeigt zu jedem Stack, **welche Ports er auf dem Host veröffentlicht** — also
  die Ports, die HAProxy ansprechen kann. Ports, die nur an `127.0.0.1`
  hängen, sind als **nur lokal** gekennzeichnet, denn von der Firewall aus
  sind sie nicht erreichbar. Container ohne Stack stehen als eigene Gruppe
  darunter, weil sie dieselben Ports belegen.
- **Vom Port direkt zum Namen.** Steht schon eine HAProxy-Rule auf diesem Port,
  zeigt die Zeile **HAProxy ✓**. Sonst steht dort **→ HAProxy**: ein Klick,
  ein Fenster mit Dienstname, Docker-Host-IP und Port bereits ausgefüllt,
  Basis-Domain und Public Service dazu — angelegt wird dann genau wie im ersten
  Tab, inklusive DNS-Eintrag in AdGuard.
- **Stacks neu deployen**, auf Wunsch mit frisch heruntergeladenen Images
  (das ist das Update) und mit Aufräumen verwaister Container. Stacks aus einem
  Repository und Stacks aus Portainers Editor gehen beide.
- **Neue Stacks aus GitHub oder GitLab.** Name, Branch, Pfad zur Compose-Datei,
  Umgebungsvariablen als Freitext wie bei Portainer, Zugangsdaten für private
  Repositories und automatische Updates — entweder in einem Abstand wie `5m`
  oder über einen Webhook, dessen URL danach im Protokoll steht.
- **Die Variablen aus dem Repository holen.** Der Knopf neben dem ENV-Feld
  liest die Compose-Datei, sammelt jedes `${VAR}` samt Vorgabewert und sucht
  daneben eine `.env` oder `.env.example` — auch die, auf die die Compose-Datei
  mit `env_file:` selbst zeigt. Beides landet vorbereitet im Feld, du passt nur
  noch die Werte an. Getipptes wird dabei nicht überschrieben. Nebenbei ist das
  eine Probe vor dem Deploy: kommt die Compose-Datei zurück, stimmen Adresse,
  Branch, Pfad und Zugangsdaten.
- **Zugangsdaten für private Repositories werden nicht gespeichert.** Sie gehen
  beim Deploy an Portainer, das sie beim Stack hinterlegt; in der
  Konfigurationsdatei dieses Programms stehen sie nicht.
- **Anmeldung wahlweise** über ein Zugriffstoken oder über Benutzer und
  Passwort. Beim Passwort wird das Token bei Bedarf selbst geholt und
  erneuert, wenn es abläuft.
- Beide Hälften gehören zur selben Verbindung: ein Standort hat eine OPNsense
  und einen Portainer, der Umschalter oben schaltet beides um.

Nur Compose-Stacks auf einem einzelnen Docker-Host. Swarm und Kubernetes
werden in der Liste als solche benannt, aber nicht ausgerollt.

## 1.3.0 — 4. August 2026

**Nichts passiert mehr von allein, und man sieht wieder, worauf man drückt.**

- **Beim Start wird nicht mehr verbunden.** Das Fenster geht auf und wartet;
  erst **Verbinden** oben rechts liest Public Services, Zertifikate und
  DNS-Einträge. Danach heißt derselbe Knopf **Neu laden**. Beim Umschalten der
  Verbindung und nach dem Speichern im Zahnrad-Dialog wird weiterhin gelesen —
  das ist ja die Ansage, dass es losgehen soll.
- **Die Knöpfe oben rechts sind Knöpfe geworden**: größer, mit eigener Fläche
  und Rand statt schwebender Zeichen, und die beiden Pfeile nach unten heißen
  jetzt **⇩ Update** und **⤓ Installieren** — vorher waren sie nicht
  auseinanderzuhalten.
- **Die Links springen nicht mehr.** Sie waren unterstrichen, sobald die Maus
  darauf lag, und ein unterstrichener Zeichensatz misst sich anders — die ganze
  Zeile rutschte. Jetzt sind sie durchgehend unterstrichen, und nur die Farbe
  reagiert.
- **Versionsnummer** neben dem Titel und unten rechts am Protokoll, dort
  zusammen mit **DukyNuky** als Verweis aufs Projekt.

Ergänzt in der Anleitung: der API-Benutzer braucht neben *Services: HAProxy*
auch *Services: ACME Client*, sonst bleibt die Liste der Basis-Domains leer.

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
