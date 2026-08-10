# Änderungen

## 2.6.1 — 10. August 2026

**Listener lassen sich auch wieder entfernen, und der öffentliche Name setzt
sich aus Namen und Zertifikat selbst zusammen.**

- **Entfernen steht jetzt in der Kopfzeile jedes Public Service** — aber nur
  bei denen, an denen keine Rules hängen. Ein Eingang, an dem Hosts hängen,
  ist der Eingang, an dem diese Hosts antworten; wäre er weg, liefen die Rules
  weiter und zeigten ins Leere. Dort gibt es den Knopf deshalb nicht, und die
  Kommandozeile sagt in dem Fall, welche Rules im Weg sind.
- **Mit weg kommen Backend Pool und Real Server** — soweit sie nicht noch
  woanders benutzt werden. Zeigt eine Rule oder ein zweiter Public Service auf
  denselben Pool, bleibt er stehen und das Protokoll sagt, wer ihn noch hat.
  Der Public Service geht zuerst, damit nichts mehr auf einen Pool zeigt, der
  gleich verschwindet.
- **Und der DNS-Eintrag geht mit**, wenn der Listener mit einem angelegt
  wurde. Wohin er zeigte, steht seit dieser Version in der Beschreibung des
  Public Service (`managed: turn-tls dns=turn.example.com`): OPNsense weiß
  nichts von AdGuard, und ein anderes Feld dafür gibt es nicht. Bei einem von
  Hand angelegten Listener sagt die Rückfrage, dass er nicht von hier stammt.
- **Der öffentliche Name füllt sich selbst.** Das Zertifikat weiß schon,
  welche Namen nach außen gelten dürfen — dafür hat man es. Bei einem
  Wildcard-Zertifikat bleibt die erste Stelle frei, und genau dorthin gehört
  der Name des Listeners: `turn-tls` + `*.example.com` wird
  `turn-tls.example.com`. Lautet das Zertifikat auf einen einzigen Namen, ist
  das die Antwort. Sobald man selbst in das Feld tippt, hört das Zusammensetzen
  auf — unter dem Feld steht, was gerade gilt.
- Neu auf der Kommandozeile: `unlisten`.

## 2.6.0 — 10. August 2026

**Der HAProxy-Tab sieht aus wie die anderen beiden: die Liste über die ganze
Breite, die Formulare in eigenen Fenstern. Dazu ein zweites Formular für einen
eigenen Listener — TLS außen, Klartext innen.**

- **＋ Neuer Host öffnet ein Fenster.** Bisher war das Formular eine Spalte am
  linken Rand: ein Drittel des Fensters für Felder, die mehr wollen, und die
  Liste daneben hatte den Rest der Zeit zu schmal zu sein. Jetzt steht die
  Liste über die ganze Breite, und das Formular bekommt den Platz, den es
  braucht — genau wie **＋ Neuer Stack** im Portainer-Tab.
- **Modal ist dabei nichts.** Das Protokoll unten gehört zum Hauptfenster, und
  eine **Vorschau** will gelesen werden, während das Formular noch steht. Fertig
  angelegt schließt sich das Fenster; schlägt etwas fehl, bleibt es offen und
  sagt den Grund in seiner Fußzeile — dort, wo hingesehen wird.
- **Was eingetragen wurde, gehört dem Fenster**, nicht dem Formular: Zumachen
  und wieder aufmachen verliert keine Wahl, die schon getroffen war.
- **＋ TCP-Listener legt einen eigenen Public Service an.** Bis hierher konnte
  das Programm nur einen Namen in einen Eingang hängen, den es schon gab. Ein
  TURN-Server, ein IMAP-Server oder eine Datenbank haben aber keinen Namen im
  Protokoll, nach dem sich sortieren ließe — sie haben einen Port, und oft kein
  TLS. Der Listener nimmt die Verbindung auf einem eigenen Port an, beendet
  dort die Verschlüsselung mit einem öffentlichen Zertifikat und spricht nach
  innen so, wie der Dienst es will: Klartext, selbstsigniert oder gar nicht
  verschlüsselt. Angelegt werden Real Server, Backend Pool im Modus `tcp` und
  der Public Service — ohne Condition und ohne Rule, es gibt ja nichts zu
  prüfen.
- **Die Zertifikate kommen aus der Firewall selbst.** Eine refid ist nichts,
  was man raten kann; das Formular liest dieselbe Liste, die auch das
  HAProxy-Plugin in seinem eigenen Fenster anbietet. Neu auf der Kommandozeile:
  `certificates` zeigt sie, `listener` legt einen an.
- **Nachgelesen wird, was ankam.** Das Plugin nimmt die Felder, die es kennt,
  und übergeht den Rest wortlos — ein Feldname, den eine andere Plugin-Version
  anders schreibt, kostet also keine Fehlermeldung, sondern einen Listener auf
  dem falschen Port. Der frisch angelegte wird deshalb sofort wieder gelesen
  und mit dem verglichen, was geschickt wurde; stimmt etwas nicht, wird alles
  abgeräumt und der Grund steht im Protokoll. Ein belegter Port wird schon
  vorher gemeldet, mit dem Namen dessen, der ihn hat.
- **Public Services ohne Rules stehen jetzt richtig in der Liste.** Wer alles
  auf seinem Port weiterreicht, hat keine Rule — dort stand bisher „keine
  Rules", als wäre nichts da. Jetzt steht da, wohin er alles schickt, mit der
  Marke **Listener** und einem **TLS** in der Kopfzeile, wenn die
  Verschlüsselung dort endet.
- **Das Ziel einer DNS-Umschreibung ist eine Auswahlliste geworden.** Darin
  stehen alle Adressen, auf die dieses AdGuard schon zeigt, die HAProxy-IP
  zuerst; eine neue tippt man weiterhin einfach ein. Darunter steht, was die
  gewählte Adresse bedeutet: *ist HAProxy*, *dorthin zeigen schon 3 andere
  Namen* oder *neue Adresse*.

## 2.5.0 — 10. August 2026

**Ein dritter Tab: alle DNS-Umschreibungen von AdGuard, zum Ansehen und zum
Anlegen. Und der Installieren-Knopf verschwindet, wenn schon installiert ist.**

- **Neuer Tab „AdGuard".** Bisher stand DNS nur am Rand der Hostliste — und
  auch dort nur zu Namen, für die es schon eine Rule in HAProxy gibt. Ein
  DNS-Server hält mehr als das: die NAS, den Drucker, die Maschine auf einem
  eigenen Port. Der dritte Tab zeigt die **ganze** Umschreibungsliste, mit
  Suchfeld über Name und Ziel, und schreibt auch hinein: **＋ Neue
  Umschreibung**, **Ändern**, **Löschen**. Bisher war dafür AdGuards eigene
  Oberfläche nötig.
- **Sortiert von hinten nach vorn**, also nach Domain: `example.de`,
  `*.example.de` und `app.example.de` stehen beieinander statt über die ganze
  Liste verteilt. Ein Eintrag, dessen Ziel die HAProxy-IP ist, trägt die
  Marke **HAProxy**; einer mit `*.` davor die Marke **alle darunter**.
- **AdGuard kennt kein „ändern" und keine eindeutigen Namen.** Derselbe Name
  darf zweimal dastehen, mit einer IPv4- und einer IPv6-Adresse. Steht ein
  Name schon da, wird deshalb gefragt, ob der neue Wert den alten **ersetzen**
  soll oder ob **beide** bleiben — statt still das eine oder das andere zu
  tun. Gelöscht wird immer mit Name *und* Ziel, damit die zweite Adresse eines
  Namens nicht nebenbei mit verschwindet.
- **Beide Tabs sehen dieselbe Liste.** Was hier geschrieben wird, steht sofort
  als DNS-Markierung an den Hosts im ersten Tab, und umgekehrt — gelesen wird
  sie dabei nur einmal.
- **Der Umschalter oben rechts wählt auf diesem Tab das AdGuard**, wie er auf
  den anderen beiden die OPNsense und den Portainer wählt. Es ist dieselbe
  Wahl wie **DNS-Eintrag in** im Formular; wer nur ein AdGuard eingerichtet
  hat und gar keine Firewall, kann den Tab allein benutzen.
- **⤓ Installieren ist weg, wenn nichts mehr zu installieren ist.** Läuft das
  Programm aus dem Ordner, auf den Startmenü-Eintrag und Terminal-Befehle
  zeigen, war der Knopf eine Einladung zu einer Arbeit, die schon getan ist —
  gedrückt hätte er nur dieselben Starter noch einmal geschrieben. Aus einem
  entpackten ZIP oder einer git-Arbeitskopie heraus ist er unverändert da.

## 2.4.3 — 9. August 2026

**Vor dem Deploy wird nach beiden Verbindungen gefragt — und wenn kein
DNS-Eintrag entsteht, steht ab jetzt im Protokoll, warum.**

- **Geprüft wird jetzt Portainer *und* OPNsense.** War Portainer verbunden und
  die Firewall nicht, ging der Deploy durch und die Rückfrage kam erst
  hinterher, beim Weg über HAProxy — also genau dann, wenn man dachte, man wäre
  fertig. *Wohin deployen?* kommt jetzt vorher und sagt, welche der beiden
  fehlt. Wer dort bei der OPNsense *— keiner —* wählt, wird in dieser Sitzung
  nicht wieder gefragt: Das ist eine Antwort, keine Lücke.
- **„dns rewrite : none" steht jetzt im Protokoll**, mit Grund — *kein AdGuard
  für diese Verbindung* oder *keine Ziel-IP für AdGuard*. Bisher fehlte die
  DNS-Zeile in dem Fall einfach, und ein Host ohne DNS-Eintrag löst nirgends
  auf, ohne dass irgendwo stünde, wonach zu suchen wäre.
- **Und im Fenster „→ HAProxy" steht es vorher.** Wo sonst das Häkchen *Passenden
  DNS-Eintrag in AdGuard anlegen* sitzt, steht jetzt der Grund, wenn es das
  Häkchen nicht gibt — bisher war dort nichts, und der Eintrag blieb
  kommentarlos aus.
- **An der Zahl im Namen liegt es nicht.** Im ganzen Weg vom Feld bis zu
  AdGuard wird keine Ziffer entfernt; nachgerechnet für Hostname, Real Server,
  Backend, Condition und den DNS-Eintrag. Was fehlte, war die Erklärung — die
  steht jetzt da, und beim nächsten Anlegen ist zu sehen, woran es tatsächlich
  liegt.
- **Der Konfigurationstest behauptet nichts mehr.** Antwortet OPNsense mit
  gar nichts, stand dort erst `warning: unexpected config test output:` und
  gleich darauf „configuration is valid" — eine Bestätigung, die niemand
  gegeben hatte. Jetzt heißt es „der Konfigurationstest sagte nichts" und
  danach schlicht „reloading HAProxy".

## 2.4.2 — 9. August 2026

**Ein Stack mit einer Zahl am Ende bekam einen Namen ohne sie. Abgeschnitten
wurde nichts — vorgeschlagen wurde der falsche Name.**

- **→ HAProxy schlug den Dienst aus der Compose-Datei vor, nicht den Stack.**
  Bei einer zweiten Kopie desselben Repositories heißt der Dienst darin
  unverändert wie in der ersten: Für den Stack `dhom-time2` stand also
  `dhom-time` im Feld — und genau so ging es in OPNsense und in AdGuard. Es
  sieht aus, als hätte jemand die Zahl verloren; tatsächlich war sie nie da.
- **Vorgeschlagen wird jetzt der Stack-Name.** Den hast du vergeben, und es
  gibt ihn auf dem Docker-Host genau einmal — der Dienst darin heißt in jeder
  Kopie gleich. Veröffentlicht ein Stack Ports aus **mehreren** Diensten, steht
  der Dienst vorne dabei (`web-shop`, `admin-shop`), denn dann sagt er etwas
  aus. Ein Container ohne Stack behält seinen eigenen Namen.
- **Was schon falsch angelegt ist**, räumt **Entfernen** in der Hostliste des
  ersten Tabs ab — Real Server, Backend, Condition, Rule und DNS-Eintrag —,
  danach über **→ HAProxy** neu anlegen.

## 2.4.1 — 9. August 2026

**Bei mehreren Public Services landete die Rule am erstbesten. Vorgewählt ist
jetzt der, der auf Port 443 hört.**

- **Die Liste begann bisher beim ersten nach dem Alphabet.** Wer neben dem
  HTTPS-Eingang noch einen Listener auf Port 80 hat, der Browser nur
  weiterschickt, bekam die Regel gut möglich dort hinein — sie hängt dann an
  einer Stelle, an der nichts ankommt, und man sucht den Fehler woanders.
- **Jetzt entscheidet, worauf ein Listener hört, nicht wie er heißt.**
  Vorgewählt ist der auf **443**; sind es mehrere, der erste davon,
  abgeschaltete zuletzt. Gelesen werden dabei alle Adressen eines Listeners,
  auch die IPv6-Form `[::]:443`.
- **Alles ohne 443 ist ausgeblendet.** Unter dem Feld steht, wie viele das
  sind — und **Erweiterte Optionen → „Auch Public Services ohne Port 443
  zeigen"** holt sie zurück, für einen Eingang auf etwa 8443. Der Schalter
  bleibt über Programmstarts hinweg gesetzt. Hört keiner auf 443, stehen
  ohnehin alle zur Wahl, und ein bewusst gewählter bleibt sichtbar.
- **Unter dem Feld steht ab jetzt, worauf der Gewählte hört** — `0.0.0.0:443,
  [::]:443` etwa. Ist es keine 443 oder ist der Listener abgeschaltet, steht
  das dabei.
- **Auf der Kommandozeile dasselbe:** Bei mehreren Public Services wird der
  eine auf 443 genommen, statt mit „mehrere vorhanden" abzubrechen. Gibt es
  dort mehrere, fragt das Programm weiterhin nach `--frontend`.

## 2.4.0 — 9. August 2026

**Aus dem Katalog heraus deployen, ohne vorher irgendwo verbunden gewesen zu
sein: ein Klick, eine Frage, und das Formular steht ausgefüllt da.**

- **„Wohin deployen?“** fragt jetzt beides auf einmal — den **Portainer**, auf
  den der Stack geht, und die **OPNsense** für den Weg über HAProxy danach.
  Vorher stand da nur *Jetzt verbinden?*, was zwar die Verbindung herstellte,
  aber eben die zuletzt benutzte: Wer zum ersten Mal etwas deployt oder mehrere
  Standorte hat, musste vorher wissen, dass er oben rechts das Richtige
  einstellen muss.
- **Die OPNsense darf dabei offen bleiben** (*— keiner —*). Deployt wird
  trotzdem; der Weg über HAProxy lässt sich danach jederzeit nachholen. Fehlt
  ein Portainer ganz, führt die Frage direkt in die Einstellungen.
- **Danach macht das Programm der Reihe nach weiter**: erst die Firewall, dann
  Portainer, dann das Formular — in dieser Reihenfolge, weil das Aufnehmen
  einer Firewall die Portainer-Seite neu aufsetzt und eine vorher gemachte
  Verbindung wieder verwerfen würde. Ist die Firewall nicht erreichbar, geht es
  trotzdem weiter: der Stack braucht sie nicht.
- **Und die Umgebungsvariablen stehen schon im Feld.** Wer aus einer Liste
  heraus deployt, hat gesagt, *was* er will, weiß aber nichts darüber, *was es
  braucht*. Also wird die Compose-Datei gleich gelesen und ihre Variablen samt
  Vorgaben eingetragen — derselbe Vorgang wie der Knopf *aus dem Repository*,
  nur ungefragt. Das gilt für jeden Deploy aus dem Katalog, auch für einen aus
  den Favoriten.
- **Die gewählte Paarung wird gemerkt**, wie überall sonst auch: Die OPNsense
  behält den Portainer, mit dem sie zusammenarbeitet, und beim nächsten Start
  ist wieder dasselbe Paar da.

## 2.3.2 — 9. August 2026

**Deployen aus dem Katalog ließ das Katalogfenster einfrieren. Es war nie
eingefroren — die Rückfrage stand dahinter.**

- **Wer aus dem Katalog etwas deployen wollte, ohne dass Portainer verbunden
  war**, bekam einen Hinweis, der dem *Hauptfenster* gehörte. Ein solches
  Fenster legt sich nicht über den Katalog, sondern dahinter, nimmt aber alle
  Klicks an sich: Der Katalog ließ sich nur noch verschieben, und passiert ist
  nichts, weil die Antwort auf eine Frage fehlte, die man nicht sehen konnte.
  Dasselbe galt für die Einstellungen, wenn noch kein Portainer eingerichtet
  war. Jede Rückfrage gehört jetzt zu dem Fenster, aus dem sie kommt.
- **Und sie ist eine Frage geworden.** Statt „Bitte zuerst verbinden“ steht da
  jetzt *Jetzt verbinden?* — wer zustimmt, bekommt die Verbindung und danach
  von allein das ausgefüllte Formular für den Eintrag, auf den er geklickt
  hat. Der Katalog selbst braucht keine Verbindung: *Meine Repos* liest der
  Token, gebraucht wird Portainer erst beim Deployen.
- **Ein Fehler in einer Rückmeldung legt das Programm nicht mehr lahm.** Die
  Schleife, die fertige Hintergrundarbeit ins Fenster zurückgibt, plant ihren
  nächsten Durchlauf am Ende ein — eine Ausnahme unterwegs nahm den mit, und
  das Fenster blieb für immer „beschäftigt“, mit abgeschalteten Knöpfen. Jetzt
  steht so etwas als Zeile im Protokoll, und es geht weiter.

## 2.3.1 — 9. August 2026

**Wer 2.3.0 über das eingebaute Update geholt hat, konnte es nicht mehr
starten. Das ist behoben — und die Ursache mit dazu.**

- **`ModuleNotFoundError: No module named 'catalog'` beim Start.** Ein Update
  wird von der Fassung ausgeführt, die gerade installiert ist, und 2.2.0 kannte
  die Liste der zu kopierenden Dateien von 2.2.0 — `catalog.py` war darin
  logischerweise nicht enthalten. Nach dem Update lag also 2.3.0 im Ordner,
  ohne eine Datei, die es beim Start unbedingt braucht.
- **Wer davon betroffen ist**, hat zwei Wege: das
  [ZIP](https://github.com/DukyNuky/opnsense-haproxy-config/releases/latest)
  herunterladen und über den Ordner entpacken — oder nur `catalog.py` und
  `catalog.json` aus dem Release dorthin legen. Beides genügt, die
  Konfiguration bleibt unberührt.
- **Das Fenster geht jetzt auch ohne diese Datei auf.** Fehlt sie, arbeitet der
  HAProxy-Tab wie immer, und der Portainer-Tab sagt, welche Datei fehlt — mit
  dem Update-Knopf daneben, der sie nachholt. Bisher stand an dieser Stelle
  fest „portainer.py und portainer_gui.py"; jetzt wird nachgesehen, was
  tatsächlich fehlt, und genau das benannt.
- **Und der Updater geht nicht mehr nach einer Liste von Namen.** Er nimmt aus
  dem Archiv, was zum Programm gehört — `.py`, `.json`, `.md`, `.bat` und die
  Symbole, ohne `config.json` und `gui.json`, die dir gehören. Eine feste Liste
  wird von der alten Fassung gelesen und kann eine neue Datei gar nicht kennen;
  eine Regel kann das. Dasselbe gilt jetzt fürs Installieren.

Damit ist dieser Fehler auch für künftige Fassungen erledigt: er hatte 1.4.0
schon einmal den Portainer-Tab gekostet, und die Lehre war damals nur, die
Liste zu erweitern.

## 2.3.0 — 9. August 2026

**Ein Katalog, aus dem heraus deployt wird — und ein Stack lässt sich endlich
auch wieder abräumen, samt dem Weg, der zu ihm führte.**

- **★ Katalog** oben im Portainer-Tab öffnet drei Listen. **Bekannte Stacks**
  kommen aus der `catalog.json` im Repository dieses Programms: gepflegte
  Einträge mit Beschreibung, deren Compose-Datei an der angegebenen Stelle
  liegt — Immich, Paperless-ngx, Uptime Kuma und ein paar mehr. Die Liste wird
  einmal am Tag geholt; ist GitHub nicht erreichbar, gilt die Fassung, die mit
  dem Programm gekommen ist. Ein Pull Request mit einem weiteren Eintrag ist
  willkommen.
- **Meine Favoriten** sind dasselbe, selbst hinterlegt: Name, Beschreibung,
  Repository, Branch und Pfad zur Compose-Datei. ★ an einer der anderen Listen
  übernimmt einen Eintrag dorthin, **＋ Eigener Favorit** legt einen von Grund
  auf an. Sie stehen in derselben Datei wie die Systeme.
- **Meine Repos** listet auf, was der Token eines Git-Kontos sehen darf — bei
  GitHub und bei GitLab, private wie öffentliche. Aus der Liste heraus deployen
  heißt: das Formular geht auf, Repository und Pfad stehen drin, und
  **Benutzername und Token des passenden Kontos sind eingesetzt**. Zugeordnet
  wird über den Host der Repository-Adresse, es ist also nichts weiter zu
  wählen.
- **Ein Git-Konto ist die vierte Sorte System** unter dem Zahnrad ⚙: Adresse,
  Benutzername, Token. Darunter steht, welche Rechte reichen — bei einem
  GitHub-Fine-grained-Token **Contents: Read-only**, bei GitLab
  `read_repository` — und ein Link führt auf die Seite, die auf genau diesem
  Host neue Token ausgibt.
- **Stacks lassen sich löschen.** **Löschen** an der Karte zeigt vorher, was
  dabei stehen bleibt und was geht: die Container beim Namen, die Host-Ports,
  die wieder frei werden. Benannte Volumes bleiben liegen, die Daten sind also
  nicht weg.
- **Und die HAProxy-Einträge gehen mit.** Zeigt eine Rule auf einen Port dieses
  Stacks, steht sie im Löschen-Fenster namentlich, und ein Haken nimmt sie mit:
  Real Server, Backend Pool, Condition, Rule und der DNS-Eintrag, wenn ein
  AdGuard gewählt ist. Ohne den Haken bleiben sie stehen und zeigen ins Leere —
  bisher war das die einzige Möglichkeit.

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
