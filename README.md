# opnsense-haproxy

Neue Webseite im Heimnetz erreichbar machen — mit einem Fenster, ein paar
Feldern und einem Knopf, statt mit fünf Formularen in der OPNsense-Oberfläche.

<img src="icon.png" alt="" width="96">

## Worum geht es hier?

Auf deiner OPNsense läuft **HAProxy**. Das ist ein Türsteher: Alle Anfragen aus
dem Netz kommen bei ihm an, und er entscheidet anhand des Namens, an welchen
Rechner dahinter sie weitergereicht werden. `wiki.example.com` geht an den
einen Server, `cloud.example.com` an den anderen — nach außen ist es dieselbe
Adresse und dasselbe Zertifikat.

Damit HAProxy einen neuen Namen kennt, müssen in OPNsense nacheinander vier
Dinge angelegt werden — Real Server, Backend Pool, Condition und Rule — und die
Rule muss danach noch beim Public Service eingehängt werden. Wer das zum ersten
Mal macht, sucht sich die Formulare zusammen; wer es zum zwanzigsten Mal macht,
hat keine Lust mehr darauf.

Dieses Programm macht alle vier Schritte auf einmal. Du tippst den Namen und
die IP-Adresse des Servers ein, klickst **Anlegen**, und es prüft anschließend
die Konfiguration und lädt HAProxy neu. Geht unterwegs etwas schief, wird alles
bereits Angelegte wieder entfernt — es bleibt nichts Halbfertiges zurück.

Auf Wunsch trägt es zusätzlich den passenden DNS-Eintrag in **AdGuard Home**
ein, damit der neue Name im Heimnetz auch gefunden wird.

Und weil die Dienste, die hinter HAProxy stehen, meist Docker-Container sind,
gibt es oben einen zweiten Tab: **Portainer**. Er zeigt, welche Stacks laufen
und welche Ports sie auf dem Host veröffentlicht haben — also genau die Ports,
die HAProxy ansprechen kann. Von dort aus lassen sich Stacks aus GitHub oder
GitLab ausrollen, mit einem Klick neu deployen (auf Wunsch mit frischen
Images), und ein veröffentlichter Port wandert mit **→ HAProxy** direkt in den
ersten Tab.

**Du brauchst dafür kein Terminal.** Die ganze Anleitung unten funktioniert mit
der Maus. (Wer lieber tippt, findet die Kommandozeile ganz unten.)

---

## Was du vorher brauchst

Drei Häkchen, bevor es losgeht:

* **OPNsense mit HAProxy.** Unter *System → Firmware → Plugins* muss
  `os-haproxy` installiert sein, und HAProxy muss laufen.
* **Mindestens einen Public Service.** Das ist der Eingang, an dem HAProxy auf
  Port 443 lauscht (in OPNsense unter *Services → HAProxy → Settings → Public
  Services*). Den legt dieses Programm **nicht** an — es hängt seine Regeln nur
  dort ein. Wenn du HAProxy schon benutzt, hast du ihn längst.
* **Einen Rechner mit Windows oder Linux**, von dem aus du die OPNsense-
  Oberfläche erreichst. Dort läuft dieses Programm.

Schön, aber nicht nötig: der **ACME-Client** (Plugin `os-acme-client`) für
Let's-Encrypt-Zertifikate. Wenn du ihn hast, bietet dir das Programm deine
Domains zur Auswahl an und du tippst nur noch `wiki` statt
`wiki.home.example.com`.

---

## Schritt 1: Python installieren

Das Programm ist in Python geschrieben. Einmalig muss Python auf deinem Rechner
sein — danach nie wieder.

**Windows:** [python.org/downloads](https://www.python.org/downloads/) öffnen,
den großen gelben Knopf drücken, die heruntergeladene Datei starten. Wichtig:
im ersten Fenster des Installers ganz unten **„Add python.exe to PATH"**
ankreuzen, erst dann auf *Install Now*. Ohne dieses Häkchen findet Windows
Python später nicht.

**Linux:** Python ist schon da. Es fehlt nur die Fenster-Bibliothek; unter
Debian, Ubuntu oder Mint installiert sie die Paketverwaltung als `python3-tk`.
Falls sie fehlt, sagt dir das Programm beim Start genau das.

**Mac:** funktioniert ebenfalls (Python von python.org installieren), ist aber
weniger getestet als Windows und Linux.

## Schritt 2: Programm herunterladen

**[opnsense-haproxy-1.4.0.zip](https://github.com/DukyNuky/opnsense-haproxy-config/releases/latest/download/opnsense-haproxy-1.4.0.zip)**
herunterladen und **entpacken** — in einen Ordner deiner Wahl, zum Beispiel
`Dokumente\opnsense-haproxy`. Nicht direkt im ZIP starten, sonst findet das
Programm seine eigenen Dateien nicht.

Alle Fassungen liegen unter
[Releases](https://github.com/DukyNuky/opnsense-haproxy-config/releases), und
was sich zuletzt geändert hat, steht im
[Änderungsverzeichnis](CHANGELOG.md).

## Schritt 3: Programm starten

**Windows:** im entpackten Ordner **`HAProxy-Starter.bat`** doppelklicken.

Meldet Windows „Der Computer wurde durch Windows geschützt", ist das der
SmartScreen-Filter, der jede unbekannte Datei anhält: *Weitere Informationen* →
*Trotzdem ausführen*. Fehlt Python oder ist es zu alt, sagt der Starter das im
Klartext, statt sich wortlos zu schließen.

**Linux:** `haproxy_gui.py` doppelklicken (im Dateimanager ggf. „Ausführen"
bestätigen).

Es geht ein Fenster auf und fragt nach deinen Zugangsdaten. Die holen wir uns
jetzt.

## Schritt 4: In OPNsense einen Benutzer und einen Schlüssel anlegen

Das Programm meldet sich nicht mit deinem Passwort an der OPNsense an, sondern
mit einem **API-Schlüssel**. Das ist ein Paar aus zwei langen Zeichenketten —
*Key* und *Secret* —, das nur für Programme gedacht ist und genau die Rechte
hat, die du dem zugehörigen Benutzer gibst.

Wichtig ist die Reihenfolge: **erst der Benutzer, dann der Schlüssel.** Der
Schlüssel wird dem fertigen Benutzer angehängt — und zwar aus der
Benutzer*übersicht* heraus, nicht aus der Maske, in der du ihn gerade
bearbeitest. Das ist die Stelle, an der die meisten suchen.

**4a — Benutzer anlegen.** In der OPNsense-Oberfläche zu
**System → Zugriff → Benutzer** gehen und rechts unten das **+** drücken.

* *Benutzername*: zum Beispiel `haproxy-tool`.
* *Passwort*: irgendetwas Langes. Du wirst es nie brauchen — angemeldet wird
  sich mit dem Schlüssel.
* Bei *Anmeldeshell* nichts ändern.

Unten **Speichern**.

**4b — Rechte geben.** Den Benutzer wieder öffnen (das Stift-Symbol rechts in
seiner Zeile) und zum Abschnitt **Effektive Berechtigungen** (*Effective
Privileges*) scrollen. Über das **+** daneben zwei Rechte hinzufügen:

| Recht | wofür |
| --- | --- |
| **Services: HAProxy** | zwingend — ohne das geht gar nichts. |
| **Services: ACME Client** | liest die Zertifikate für die Domain-Auswahl. Fehlt es, bleibt die Liste leer und du tippst den ganzen Namen selbst; alles andere funktioniert weiter. |

Wieder **Speichern**. Die Rechte hängen am *Benutzer*, nicht am Schlüssel — ein
Schlüssel kann nie mehr als sein Benutzer.

**4c — Schlüssel erzeugen.** Der Schlüssel wird **nicht** in der
Bearbeitungsmaske angelegt — dort steht nichts davon. Zurück in der
**Benutzerübersicht** (*System → Zugriff → Benutzer*): ganz rechts in der Zeile
deines Benutzers stehen ein paar kleine Symbole. Eines davon sieht aus wie ein
Viereck mit gezacktem Rand, wie eine **Briefmarke** — das ist „API-Schlüssel
erstellen". Ein Klick darauf, und der ganze Vorgang ist erledigt: OPNsense legt
den Schlüssel an und lädt sofort eine kleine Textdatei namens **`apikey.txt`**
herunter (schau im Download-Ordner deines Browsers). Darin stehen zwei Zeilen:

```
key=Ab3dEf…
secret=Xy9zQ…
```

**Diese Datei ist deine einzige Gelegenheit.** Das Secret zeigt OPNsense nie
wieder an. Ist sie weg, klickst du einfach noch einmal auf die Briefmarke — das
kostet nichts, du hast dann nur zwei Schlüssel und kannst den alten löschen.

## Schritt 5: Verbindung eintragen

Zurück im Programm-Fenster, das seit Schritt 3 wartet. Es füllt sich so:

| Feld | was hinein gehört |
| --- | --- |
| **Name der Verbindung** | Ein Name für dich, z.B. `Zuhause`. |
| **Adresse** | Die Adresse deiner OPNsense-Oberfläche, z.B. `https://192.168.1.1` oder `https://opnsense.fritz.box`. |
| **API-Key** | Die Zeile `key=…` aus `apikey.txt` — **ohne** das `key=` davor. |
| **API-Secret** | Entsprechend die Zeile `secret=…`. |
| **IP von HAProxy** | Die Adresse, unter der HAProxy erreichbar ist — meistens die IP deiner OPNsense, z.B. `192.168.1.1`. Darauf zeigen später die DNS-Einträge. |

Das Häkchen **TLS-Zertifikat der OPNsense prüfen** bleibt aus, solange deine
OPNsense ein selbstsigniertes Zertifikat hat (der Normalfall im Heimnetz).
Sonst schlägt die Verbindung mit einem Zertifikatsfehler fehl.

Darunter kannst du **AdGuard Home** dazunehmen — Haken setzen, Adresse
(`https://adguard.example.de`, oder mit Port: `http://192.168.1.2:3000`),
Benutzer und Passwort. Dann legt das Programm zu jedem neuen Host gleich den
DNS-Eintrag mit an. Ohne Haken bleibt DNS unangetastet; du kannst es jederzeit
nachtragen.

**Speichern & verbinden** — das Programm holt sich, was auf der OPNsense schon
da ist. Oben rechts wechselt die Anzeige von „nicht verbunden" auf den Namen
deiner Verbindung, und rechts füllt sich die Liste der bestehenden Hosts.

Deine Eingaben landen in einer Datei in deinem Benutzerprofil
(`~/.config/opnsense-haproxy/config.json`, unter Windows entsprechend), die nur
du lesen darfst.

## Schritt 6: Den ersten Host anlegen

Links im Fenster steht das Formular **Neuer Host**:

1. **Basis-Domain** aus der Liste wählen (z.B. `home.example.com`) — das sind
   deine Zertifikats-Domains. Ist die Liste leer, macht das nichts: dann trägst
   du unten einfach den vollen Namen ein.
2. **Hostname**: `wiki` — darunter steht laufend mit, welcher Name daraus wird,
   also `wiki.home.example.com`. Oder gleich der volle Name.
3. **Server-IP**: die Adresse des Rechners, der die Seite ausliefert, z.B.
   `192.168.10.20`.
4. **Port**: auf dem der Rechner lauscht, z.B. `8080`.
5. **SSL zum Backend**: aus, wenn dein Server intern nur HTTP spricht (der
   häufigste Fall). An, wenn er HTTPS erwartet. Unter dem Schalter steht immer,
   was gerade gilt.
6. **Vorschau** drücken. Das ändert noch **nichts**, sondern zeigt unten im
   Protokoll, was angelegt würde. Ein guter Reflex beim ersten Mal.
7. **Anlegen**. Unten läuft mit, was passiert: die vier Objekte, das Einhängen
   in den Public Service, der Konfigurationstest, der Reload.

Danach steht der Name rechts in der Liste **Bestehende Hosts**. Ein Klick
darauf öffnet die Seite im Browser.

Klappt der Aufruf nicht sofort: Dein Rechner muss den Namen erst zur HAProxy-IP
auflösen können. Mit AdGuard erledigt das Programm das mit; ohne trägst du den
Namen in deinem DNS-Server oder Router selbst ein.

## Schritt 7: Ordentlich einrichten (optional, aber angenehm)

Damit das Programm nicht für immer im Download-Ordner wohnt, kann es sich
selbst an einen festen Platz legen: oben rechts **⤓ Installieren**, Zielordner
bestätigen, fertig.

Es kopiert sich dorthin, trägt sich mit seinem Symbol ins Startmenü
(Windows) bzw. ins Anwendungsmenü (Linux) ein, und von dort lässt es sich an
die **Taskleiste anheften**. Auf Wunsch legt es auch eine Verknüpfung auf den
Schreibtisch. Deine Zugangsdaten fasst es dabei nicht an.

Den ursprünglich entpackten Ordner kannst du danach löschen.

---

## Das Fenster im Überblick

**Oben links** die beiden großen Tabs, **HAProxy** und **Portainer**. Dieser
Abschnitt beschreibt den ersten; der zweite hat weiter unten seinen eigenen.
Die Kopfzeile und das Protokoll unten gehören beiden: der Umschalter für die
Verbindung, die Statusanzeige und **Verbinden** meinen immer den Tab, der
gerade vorne ist.

**Oben rechts** liegen die Knöpfe: der Umschalter für die Verbindung, das
Zahnrad ⚙ zum Bearbeiten, **Verbinden**, **⇩ Update**, **⤓ Installieren** und
der Mond/Sonne-Knopf für hell oder dunkel. Was ein Knopf tut, verrät ein
Hinweis, wenn die Maus einen Moment darauf liegt.

**Von allein verbindet sich nichts.** Das Fenster geht auf und wartet; erst
**Verbinden** holt die Daten von der OPNsense. Danach heißt derselbe Knopf
**Neu laden**. Beim Wechsel der Verbindung und nach dem Speichern im
Zahnrad-Dialog wird automatisch gelesen — das ist ja schon die Ansage, dass es
losgehen soll.

**Links** das Formular für den neuen Host, darunter **Erweiterte Optionen** für
alles, was man selten braucht (Backend-Zertifikat prüfen, X-Forwarded-For,
Health Monitor, Backend-Modus, Namens-Präfix, „nur speichern, nicht neu
laden").

**Rechts** die bestehenden Hosts, sortiert nach Public Service. Jede Zeile
zeigt, was AdGuard zu diesem Namen weiß:

| | |
| --- | --- |
| **DNS ✓** | Es gibt eine Umschreibung, und sie zeigt auf die HAProxy-IP. |
| **DNS → …** | Es gibt eine, sie zeigt aber woanders hin. |
| **kein DNS** | AdGuard kennt den Namen nicht. |

Der Knopf daneben bringt das in Ordnung: **DNS eintragen**, **auf HAProxy
zeigen** oder **DNS löschen**, je nachdem was fehlt. Das geht nur an AdGuard,
an HAProxy ändert sich dabei nichts. **Entfernen** räumt umgekehrt den ganzen
Eintrag ab — Real Server, Backend, Condition, Rule und DNS.

Rules, die du früher in OPNsense von Hand angelegt hast, stehen mit in der
Liste: ihr Hostname wird auch aus einer `hdr_beg`-Bedingung gelesen, sie sind
also anklickbar und bekommen ihren DNS-Knopf. **Entfernen** gibt es für sie
nicht — dafür müssten die Objekte so heißen, wie dieses Programm sie benennt.

**Unten** das Protokoll: jede Zeile, die das Programm gerade tut, farblich nach
Anlegen, Löschen und Fehler getrennt. Wenn etwas schiefgeht, steht der Grund
dort — nicht in einem Popup, das man wegklickt und dann nicht mehr findet.

Alle Abfragen laufen im Hintergrund, das Fenster friert also nicht ein, während
die OPNsense antwortet. Theme und Fenstergröße merkt es sich.

## Der zweite Tab: Portainer

Oben sitzen zwei große Tabs. **HAProxy** ist alles, was oben beschrieben ist.
**Portainer** ist die andere Hälfte: die Docker-Container, die hinter HAProxy
stehen.

Beide gehören zur selben Verbindung. Ein Standort hat eine OPNsense und einen
Portainer, also steht beides im selben Profil — der Umschalter oben rechts
schaltet beide zugleich um, und **Verbinden** gilt immer für den Tab, der
gerade vorne ist.

### Einrichten

Im Zahnrad ⚙ gibt es den Abschnitt **Portainer**:

* **Adresse** deines Portainers, z.B. `https://portainer.example.de:9443`.
* **Anmeldung** — entweder ein **Zugriffstoken** (in Portainer oben rechts auf
  den Benutzer, dann *My account → Access tokens*) oder **Benutzer und
  Passwort** wie in der Weboberfläche. Beim Token wird nichts weiter gebraucht;
  beim Passwort holt sich das Programm bei jedem Start selbst ein Token.
* **IP des Docker-Hosts** — die Adresse, an die HAProxy die Anfragen schickt.
  Bleibt sie leer, wird der Rechner aus der Portainer-Adresse genommen. Das
  stimmt, solange Portainer auf demselben Host läuft wie die Container;
  ansonsten hier die richtige IP eintragen.

Läuft Portainer über mehrere Umgebungen (*Environments*), erscheint rechts oben
in der Liste ein Auswahlfeld. Welche du zuletzt benutzt hast, merkt sich das
Programm.

### Was die Liste zeigt

Jeder Stack als Karte: Name, Art (**Compose**), ob er sich selbst aktualisiert
(**⟳ auto**), wie viele seiner Container laufen (**2/2**), und darunter das
Repository, aus dem er kommt. Danach folgt Zeile für Zeile jeder Port, den er
**auf dem Host veröffentlicht** hat:

```
8080  →  80/tcp     app                        HAProxy ✓
9000  →  9000/tcp   app          nur lokal     → HAProxy
```

Links der Port auf dem Host, rechts daneben der Port im Container. Das ist die
Zahl, die du für HAProxy brauchst: die linke.

| | |
| --- | --- |
| **nur lokal** | Der Port ist an `127.0.0.1` gebunden. Von einem anderen Rechner — also auch von HAProxy — ist er nicht erreichbar. |
| **HAProxy ✓** | Es gibt schon eine Rule, deren Real Server auf genau diese IP und diesen Port zeigt. |
| **→ HAProxy** | Noch keine. Der Knopf legt sie an. |

Container, die ohne Stack gestartet wurden, stehen darunter als eigene Gruppe —
sie belegen dieselben Ports auf demselben Host, und ein Port, der schon vergeben
ist, ist beim Planen genauso wichtig.

Ob ein Port **wirklich aus dem Internet** erreichbar ist, kann Docker nicht
sagen; das entscheidet die Firewall davor. Die Liste sagt daher, was sie weiß:
woran der Port gebunden ist.

### Vom Port zum Namen

**→ HAProxy** öffnet ein kleines Fenster mit allem schon ausgefüllt: der
Dienstname als Vorschlag, die IP des Docker-Hosts, der veröffentlichte Port.
Du wählst noch die Basis-Domain und den Public Service, drückst **Anlegen** —
und der Rest läuft wie im ersten Tab, samt DNS-Eintrag in AdGuard und
Protokoll unten.

Dafür muss der HAProxy-Tab verbunden sein; ohne die Public Services von der
OPNsense weiß das Programm nicht, wo die Rule hin soll.

### Einen Stack neu deployen

**Neu deployen** auf der Karte fragt zwei Dinge:

* **Images neu herunterladen (Update)** — an: Portainer holt die Images
  frisch, der Stack läuft danach auf dem neuesten Stand. Aus: dieselben Images
  werden noch einmal gestartet.
* **Container entfernen, die nicht mehr in der Compose-Datei stehen** (prune).

Kommt der Stack aus einem privaten Repository, kannst du Benutzer und Token
angeben. Lässt du die Felder leer, benutzt Portainer die Zugangsdaten, die es
für diesen Stack schon gespeichert hat — das ist der Normalfall.

Stacks ohne Repository (in Portainer aus dem Editor angelegt) gehen genauso:
dann wird die Compose-Datei benutzt, die Portainer für sie aufbewahrt.

### Einen neuen Stack anlegen

Links das Formular:

* **Name** — Kleinbuchstaben, wie bei Portainer. Er wird zum Compose-Projekt.
* **Repository** — die HTTPS-Adresse bei GitHub oder GitLab. Für Portainer ist
  beides nur eine Git-URL, einen Unterschied gibt es nicht.
* **Branch oder Tag** — leer heißt Standardbranch.
* **Datei im Repository** — der Pfad zur Compose-Datei, voreingestellt
  `docker-compose.yml`.
* **Umgebungsvariablen** — eine Zeile je Variable, `KEY=wert`, genau wie im
  Textfeld von Portainer. Leere Zeilen und `#`-Kommentare werden übergangen,
  Anführungszeichen um den Wert fallen weg. Den Anfang macht der Knopf
  **aus dem Repository** daneben, siehe unten.
* **Privates Repository** — Benutzer und Token. Sie gehen an Portainer, das sie
  beim Stack hinterlegt; **in der Konfigurationsdatei dieses Programms landen
  sie nicht**.
* **Automatisch aktualisieren** — *regelmäßig nachsehen* (Abstand als `5m`,
  `30m`, `24h`) oder *auf Webhook warten*. Beim Webhook steht die fertige
  URL nach dem Deploy im Protokoll; wer sie in GitHub oder GitLab als Webhook
  einträgt, bekommt den Stack bei jedem Push neu ausgerollt.
* **danach den Weg über HAProxy anbieten** — sobald die Container laufen, wird
  für den ersten veröffentlichten Port gleich das Fenster von oben geöffnet.

### Die Variablen aus dem Repository holen

Neben *Umgebungsvariablen* sitzt der Knopf **aus dem Repository**. Er füllt das
Feld schon einmal vor, damit du nur noch die Werte anpasst.

Was dabei passiert:

1. Die **Compose-Datei** wird gelesen — an dem Pfad, dem Branch und mit den
   Zugangsdaten, die im Formular stehen. Daraus jedes `${VAR}`, samt Vorgabe
   bei `${VAR:-wert}`. Das ist die verbindliche Liste dessen, was der Stack
   braucht.
2. Zeigt sie mit `env_file:` auf eine Datei, wird dort nachgesehen. Sonst
   werden daneben und im Wurzelverzeichnis die üblichen Namen probiert:
   `.env.example`, `.env`, `example.env`, `.env.sample`, `.env.template`,
   `stack.env`. Beim ersten Treffer ist Schluss.
3. Beides wird zusammengeführt und ins Feld geschrieben — mit einer
   Kommentarzeile, woher welcher Teil kommt.

```
# aus docker/example.env
UPLOAD_LOCATION=./library
DB_PASSWORD=postgres

# in docker/docker-compose.yml verwendet, bitte ausfüllen
IMMICH_SERVER_URL=
```

**Was du schon eingetippt hast, bleibt.** Ergänzt wird nur, was noch fehlt —
ein zweiter Druck fügt also nichts doppelt ein. Die Kommentarzeilen dürfen
stehen bleiben, sie werden beim Deploy überlesen.

Gelesen wird über Portainer, nicht von hier aus: GitHub und GitLab sind für
Portainer dieselbe Git-URL, und ein privates Repository geht mit denselben
Zugangsdaten, die auch der Deploy benutzt. Nebenbei ist das eine **Probe vor
dem Deploy** — kommt die Compose-Datei zurück, stimmen Adresse, Branch, Pfad
und Zugangsdaten. Sonst steht der Grund im Protokoll.

Liegt im Repository eine echte `.env` (nicht `.env.example`), liest Docker
Compose sie beim Deploy ohnehin selbst aus dem geklonten Verzeichnis. Was hier
im Feld steht, setzt Portainer zusätzlich — praktisch zum Anpassen, aber nicht
der einzige Weg, wie die Werte wirken.

## Mehrere OPNsense

Der Umschalter oben rechts ist auch bei einer einzigen Verbindung da, denn über
ihn legst du weitere an (**＋ neue Verbindung …**) und bearbeitest oder löschst
die aktuelle (**⚙ diese bearbeiten …**).

Jede Verbindung hat ihre eigene Adresse, ihren eigenen Schlüssel, ihre eigene
HAProxy-IP und — falls vorhanden — ihr eigenes AdGuard. Standort A mit DNS,
Standort B ohne: kein Problem.

## Updates

Einmal am Tag schaut das Programm beim Start still bei GitHub nach, ohne zu
fragen und ohne das Fenster aufzuhalten. Gibt es etwas Neues, trägt der Knopf
**⇩ Update** die neue Versionsnummer und ist farbig hinterlegt. Mehr passiert
von allein nicht — installiert wird erst, wenn du drückst.

Der Knopf zeigt dann die Versionsnummer und, sofern hinterlegt, was sich
geändert hat. Nach der Installation ist ein Neustart nötig, den der Dialog
gleich anbietet.

Ersetzt werden nur die Programmdateien selbst. **Zugangsdaten und
Einstellungen bleiben unangetastet**, und die alten Dateien landen vorher in
einem Ordner `backup-<version>/` daneben. Heruntergeladener Code wird vor dem
Schreiben geprüft; ist das Archiv unvollständig oder beschädigt, wird nichts
angefasst. Ist GitHub nicht erreichbar, bleibt das folgenlos.

Wer die tägliche Nachfrage nicht möchte, setzt in
`~/.config/opnsense-haproxy/gui.json` `"update_check": false`; der Knopf
funktioniert weiter.

---

## Wenn etwas nicht klappt

**Das Fenster geht gar nicht auf / schließt sich sofort.**
Unter Windows `HAProxy-Starter.bat` benutzen, nicht die `.py`-Datei — der
Starter prüft Python und sagt, was fehlt. Unter Linux fehlt meist `python3-tk`.

**„cannot reach" oder Zeitüberschreitung beim Verbinden.**
Stimmt die Adresse, inklusive `https://`? Erreichst du dieselbe Adresse im
Browser? Hängt dein Rechner im richtigen Netz?

**Zertifikatsfehler beim Verbinden.**
Das Häkchen *TLS-Zertifikat der OPNsense prüfen* im Zahnrad-Dialog ausschalten.
Selbstsignierte Zertifikate sind im Heimnetz normal.

**„401" oder „Authentifizierung fehlgeschlagen".**
Key und Secret vertauscht, oder das `key=` bzw. `secret=` aus der Datei
mitkopiert. Beide Felder noch einmal sauber einfügen. Zur Not in der
Benutzerübersicht mit der Briefmarke einen neuen Schlüssel erzeugen.

**„403" oder leere Listen.**
Dem Benutzer fehlen die Rechte — siehe Schritt 4b. Sie hängen am Benutzer, auch
wenn der Schlüssel längst existiert.

**Die Basis-Domains bleiben leer.**
Der ACME-Client ist nicht installiert oder dem Benutzer fehlt das Recht
*Services: ACME Client*. Kein Beinbruch: den vollen Hostnamen eintippen.

**„Es gibt mehrere Public Services".**
Dann muss das Programm wissen, an welchen die Regel soll — im Formular unten
das Feld **Public Service** auswählen.

**Der Name ist schon vergeben.**
Bestehendes wird nie überschrieben. Das Programm bricht ab und sagt, welches
Objekt im Weg ist.

**Angelegt, aber die Seite lädt nicht.**
Erst prüfen, ob der Name überhaupt auf die HAProxy-IP zeigt (Spalte *DNS* in
der Liste). Dann, ob der Zielserver auf der angegebenen IP und dem Port
antwortet. Spricht er HTTPS, muss der Schalter *SSL zum Backend* an sein.

---

## Was genau angelegt wird

Für `app.example.com` mit Ziel `192.168.1.50:8080`:

| Objekt in OPNsense | Name | Inhalt |
| --- | --- | --- |
| Real Server | `srv_app.example.com` | 192.168.1.50:8080 |
| Backend Pool | `be_app.example.com` | verweist auf den Real Server |
| Condition | `acl_app_example_com` | `hdr` — Host-Header ist `app.example.com` |
| Rule | `rule_app_example_com` | `if` Condition → `use_backend` |
| Public Service | (bestehend) | Rule wird an `linkedActions` angehängt |
| AdGuard-Umschreibung | — | `app.example.com` → HAProxy-IP (optional) |

Bei einem Pfad (`example.com/api`) kommt eine zweite Condition `path_beg` dazu;
beide werden mit **AND** verknüpft.

## Entscheidungen, die das Programm trifft

* **Public Service**: gibt es nur einen, wird er automatisch benutzt. Bei
  mehreren musst du wählen.
* **Host-Header oder SNI**: läuft der Public Service im Modus `http`, wird auf
  den Host-Header gematcht. Bei `ssl`/`tcp` (SSL-Passthrough) sieht HAProxy
  keinen Host-Header, deshalb wird dort auf **SNI** gematcht und der Backend
  Pool auf `tcp` gesetzt. Ein Pfad ist in diesen Modi nicht möglich und wird
  mit einer Fehlermeldung abgelehnt.
* **Das Backend-Zertifikat wird nicht geprüft**, wenn *SSL zum Backend* an ist.
  OPNsense schaltet die Prüfung per Default an, was bei internen Hosts mit
  selbstsignierten Zertifikaten sofort zu 503ern führt. Wer eine saubere
  interne CA hat, setzt den Haken in den erweiterten Optionen.
* **`X-Forwarded-For` ist bei HTTP-Backends an** — damit der Zielserver die
  echte Besucher-IP sieht.
* **Health-Monitor**: standardmäßig keiner. In den erweiterten Optionen lässt
  sich ein bereits in OPNsense angelegter verknüpfen.
* **Namen**: `srv_`/`be_`/`acl_`/`rule_` + Hostname. Real Server und Backend
  dürfen Punkte enthalten, Conditions und Rules nicht (Vorgabe des Plugins) —
  dort werden Punkte zu `_`.
* **Reload**: nach dem Anlegen läuft `haproxy -c`. Nur wenn der Test sauber
  ist, wird neu geladen.
* **Public Service**: es wird ausschließlich die Rule-Liste geschrieben, nie
  der ganze Eintrag. Ein Roundtrip über alle Felder quittiert die OPNsense-API
  je nach Feldtyp mit einem 500er — und könnte im Vorbeigehen Einstellungen wie
  das SSL-Zertifikat leeren.

## Grenzen

* **Entfernen** findet die Objekte über das Namensschema. Wurden sie in
  OPNsense umbenannt, greift es nicht mehr — dann per Hand löschen.
* Bestehende Einträge werden nicht verändert; ist ein Name schon vergeben,
  bricht das Anlegen ab und sagt, was im Weg ist.
* Zertifikate für den Public Service (Let's Encrypt o.ä.) verwaltet das
  Programm nicht — das bleibt Sache des ACME-Clients.
* Den Public Service selbst legt es nicht an.
* Bei Portainer geht es um **Compose-Stacks auf einem einzelnen Docker-Host**.
  Swarm- und Kubernetes-Stacks werden in der Liste als solche gekennzeichnet,
  aber nicht deployt — dort kommen die Ports aus den Services und nicht aus den
  Containern, das wäre eine eigene Baustelle.
* Ein Stack wird angelegt und neu deployt, aber nicht gelöscht und nicht
  bearbeitet. Dafür ist Portainer selbst da.
* Ob ein Port von außerhalb des Heimnetzes erreichbar ist, weiß Docker nicht;
  die Liste sagt nur, an welche Adresse er auf dem Host gebunden ist.

---

# Für Fortgeschrittene

Ab hier geht es um die Kommandozeile und die Konfigurationsdatei. Für den
normalen Gebrauch ist nichts davon nötig.

## Dateien

| Datei | |
| --- | --- |
| `opnsense_haproxy.py` | Logik und CLI |
| `haproxy_gui.py` | Fenster (tkinter) |
| `portainer.py` | Portainer-API: Stacks, Container, Ports, Deploys |
| `portainer_gui.py` | der zweite Tab |
| `HAProxy-Starter.bat` | Doppelklick-Start für Windows |
| `icon.png` / `icon.ico` | Symbol für Fenster und Starter |

Nur Python 3 (Standardbibliothek), keine weiteren Abhängigkeiten, kein
Build-Schritt.

## Kommandozeile

```sh
./opnsense_haproxy.py init                                         # einrichten
./opnsense_haproxy.py add app.example.com -i 192.168.1.50 --no-ssl # anlegen
./haproxy_gui.py                                                   # Fenster
```

Ohne Argumente fragt `add` die vier Werte nacheinander ab:

```
$ ./opnsense_haproxy.py add
URL / hostname: wiki.example.com
real server IP: 192.168.10.20
use SSL to the backend? (yes/no) [no]: yes
real server port [443]: 8443
```

Oder alles direkt:

```sh
# Basis-Domain wählen und nur den Hostnamen angeben
./opnsense_haproxy.py add wiki -b home.example.com -i 192.168.10.20 -p 8443 --ssl

# HTTP zum Backend, voller Name
./opnsense_haproxy.py add app.example.com -i 192.168.1.50 -p 8080 --no-ssl

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
./opnsense_haproxy.py -P Zweitstandort list       # eine bestimmte Verbindung
./opnsense_haproxy.py remove app.example.com      # alle vier Objekte wieder weg
./opnsense_haproxy.py apply                       # Configtest + Reload
./opnsense_haproxy.py status                      # läuft HAProxy?
./opnsense_haproxy.py install                     # fester Platz + Starter
./opnsense_haproxy.py update --check              # nur nachsehen
./opnsense_haproxy.py update                      # nachsehen und installieren
./opnsense_haproxy.py gui                         # Fenster
./opnsense_haproxy.py --version
```

Zugangsdaten gehen auch über `--url/--key/--secret` bzw. die Umgebung
`OPNSENSE_URL`/`OPNSENSE_KEY`/`OPNSENSE_SECRET`. Bei selbstsigniertem
Zertifikat: `--insecure`.

`install` legt die Befehle `haproxy-gui` und `opnsense-haproxy` in
`~/.local/bin` an; andere Ziele über `install /pfad`, `--bin ~/bin`,
`--desktop`, `--no-menu`, `--no-commands`. Von Hand geht es auch:

```sh
chmod +x opnsense_haproxy.py
sudo ln -s "$PWD/opnsense_haproxy.py" /usr/local/bin/haproxy-add
```

Liegt das Programm in einer git-Arbeitskopie, verweigert `update` den Dienst und
verweist auf `git pull` — sonst wären eigene Änderungen weg.

## Konfigurationsdatei

`~/.config/opnsense-haproxy/config.json` (Modus 600), siehe
[config.example.json](config.example.json). Sie hält eine Liste von
Verbindungen:

```json
{
  "active": "Zuhause",
  "profiles": [
    { "name": "Zuhause", "url": "…", "key": "…", "secret": "…",
      "haproxy_ip": "192.168.1.1",
      "verify_ssl": false,
      "adguard": { "url": "https://adguard.example.de",
                   "username": "admin", "password": "…",
                   "target": "", "verify_ssl": false },
      "portainer": { "url": "https://portainer.example.de:9443",
                     "api_key": "ptr_…",
                     "host_ip": "192.168.1.20", "verify_ssl": false } },
    { "name": "Zweitstandort", "url": "…", "key": "…", "secret": "…" }
  ]
}
```

`haproxy_ip` ist das Ziel aller DNS-Einträge; ein `target` im
`adguard`-Abschnitt sticht es für diese Verbindung aus, `--dns-target` für einen
einzelnen Aufruf. Bei der AdGuard-`url` genügt die Adresse der Oberfläche — die
kopierte Browser-Zeile (`https://adguard.example.de/#dns_rewrites`) geht
genauso, der API-Pfad wird selbst angehängt. Fehlt das Schema, wird `https://`
angenommen.

Im `portainer`-Abschnitt gilt entweder `api_key` **oder** `username` und
`password` — beim Speichern über das Zahnrad wird der jeweils andere Weg
geleert, damit später nicht ein vergessener Rest entscheidet, womit angemeldet
wird. `host_ip` ist die Adresse, an die HAProxy Anfragen an Container schickt;
ohne Angabe wird der Rechner aus der `url` genommen. Zugangsdaten für private
Git-Repositories stehen hier bewusst **nicht** — die werden beim Deploy
abgefragt und gehen direkt an Portainer.

Eine ältere Datei mit nur einer Verbindung ganz oben funktioniert unverändert
weiter — sie erscheint als Verbindung „Standard".

## Basis-Domains

Die Auswahlliste kommt aus dem **ACME-Client** und braucht keine eigene
Einrichtung — die dort gepflegten Zertifikate werden gelesen:

* Ein Wildcard-Zertifikat `*.home.example.com` ergibt die Basis-Domain
  `home.example.com`, unter der jeder Hostname möglich ist.
* Ein Zertifikat für einen einzelnen Namen wird als exakter Name angeboten.

Passt der zusammengesetzte Name nicht zum Zertifikat (`a.b.home.example.com`
unter einem Wildcard, das nur eine Ebene abdeckt), gibt es eine Warnung —
angelegt wird trotzdem, denn das Zertifikat kann auch von woanders kommen.

## Ein Paket bauen

`./make_release.py` liest die Versionsnummer aus `opnsense_haproxy.py` und legt
`releases/opnsense-haproxy-<version>.zip` an. Das Symbol zeichnet
`./make_icon.py` neu — reine Standardbibliothek, jede Form als Abstand
beschrieben, daraus fallen `icon.png` und `icon.ico` heraus.
