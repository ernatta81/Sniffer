# RS232 Sniffer / Bridge

Sniffer seriale RS232 "in linea" con interfaccia grafica (Tkinter) per Linux/Debian/Win11.

```
[Apparato A] <--> Seriale 1  [PC con lo sniffer]  Seriale 2 <--> [Apparato B]
```

## Cosa fa

- Fa da **ponte full-duplex**: ciò che arriva dalla seriale 1 viene ritrasmesso
  **as-is** (byte per byte, senza modifiche) sulla seriale 2 e viceversa.
  Ogni verso si può disattivare (**Inoltra 1 → 2**, **Inoltra 2 → 1**).
- Mostra tutto il traffico in un'**unica lista cronologica di pacchetti**, come
  negli sniffer professionali, con le righe colorate per direzione
  (azzurro = 1 → 2, verde = 2 → 1).
- **Collega ogni risposta al comando** a cui risponde e ne misura la latenza.

## Installazione su Debian

### Metodo consigliato: pacchetto .deb

Copia `dist/rs232-sniffer_1.0.0_all.deb` sul PC Debian e installalo:

```bash
sudo apt install ./rs232-sniffer_1.0.0_all.deb
```

`apt` installa da solo le dipendenze (`python3`, `python3-tk`,
`python3-serial`). Dopo l'installazione il programma si avvia con il comando
`rs232-sniffer` oppure dal menu applicazioni (**RS232 Sniffer**).
Disinstallazione: `sudo apt remove rs232-sniffer`.

Per rigenerare il pacchetto dopo aver modificato il programma (funziona anche
da Windows):

```bash
python3 packaging/build_deb.py
```

### Eseguibile unico (senza installazione)

Se serve un singolo file eseguibile che non richiede Python sul PC di
destinazione, va compilato **su Debian** (PyInstaller non compila per Linux
da Windows). Sul PC Debian, nella cartella del progetto:

```bash
sh packaging/build_eseguibile.sh
./dist/rs232-sniffer
```

L'eseguibile funziona sulla stessa versione di Debian su cui è stato
compilato e sulle successive.

### Avvio diretto dallo script

```bash
sudo apt install python3-tk python3-serial
python3 sniffer_rs232.py
```

## Permessi sulle porte seriali

Su Debian le porte seriali sono file in `/dev`:

| Dispositivo        | Tipo                                                  |
|--------------------|-------------------------------------------------------|
| `/dev/ttyS0`, `ttyS1`…   | Porte COM native della scheda madre (COM1, COM2…) |
| `/dev/ttyUSB0`, `ttyUSB1`… | Adattatori USB-seriale (FTDI, CP210x, CH340, PL2303) |
| `/dev/ttyACM0`…    | Dispositivi USB CDC (alcuni adattatori e schede)      |

Appartengono all'utente `root` e al gruppo **`dialout`**, quindi un utente
normale può usarle solo se fa parte di quel gruppo:

```bash
sudo usermod -aG dialout $USER
```

Poi **esci dalla sessione e rientra** (o riavvia): l'appartenenza ai gruppi
viene letta solo al login. Per verificare:

```bash
groups                 # deve comparire "dialout"
ls -l /dev/ttyUSB*     # crw-rw---- 1 root dialout ...
```
**Nomi stabili.** Con due adattatori USB, `ttyUSB0` e `ttyUSB1` possono
scambiarsi a ogni riavvio. Usa invece i percorsi fissi in
`/dev/serial/by-id/` (dipendono dal numero di serie dell'adattatore) e
scrivili nel campo **Porta**:

```bash
ls -l /dev/serial/by-id/
```

1. Per ciascuna seriale scegli la porta (es. `/dev/ttyUSB0` e `/dev/ttyUSB1`;
   se non compare nell'elenco digitane il percorso a mano) e imposta baud
   (dall'elenco o scritto a mano, vedi sotto), bit dati, parità, bit di stop
   e flusso.
2. Facoltativo: dai un **nome agli apparati** (es. "Cassa" e "Periferica"),
   così la direzione si legge come `Cassa → Periferica`.
3. Clicca **Connetti**.

### Baud rate

L'elenco propone i valori standard da 300 a 4000000 baud (tra cui 230400,
460800, 921600, 1000000…), ma il campo è **editabile**: puoi scrivere
qualsiasi baud rate personalizzato (es. `250000`, `31250`, `74880`). Le due
seriali possono avere baud diversi.

Su Linux pyserial imposta anche i valori non standard, ma il valore deve
essere **supportato dall'adattatore** (FTDI, CP210x, CH340… hanno limiti e
divisori diversi). Se il chip non lo accetta, all'apertura compare un errore;
alcuni chip invece arrotondano al valore più vicino che riescono a generare.

## La lista dei pacchetti

| Colonna     | Significato                                                              |
|-------------|--------------------------------------------------------------------------|
| N°          | Numero progressivo del pacchetto                                         |
| Ora         | Orario di arrivo del primo byte (ms)                                     |
| Δt          | Silenzio dalla fine del pacchetto precedente (qualsiasi direzione)       |
| Direzione   | Chi ha trasmesso e verso chi (`Nome1 → Nome2`)                           |
| Byte        | Lunghezza del pacchetto                                                  |
| Risposta a  | Se il pacchetto è una risposta: numero del comando e latenza             |
| Dati HEX    | Byte in esadecimale (primi 128; il dettaglio li mostra tutti)            |
| Dati ASCII  | Testo, con i caratteri di controllo per nome: `<STX>`, `<ACK>`, `<CR>`…  |

Sotto la lista c'è il **dettaglio del pacchetto selezionato**: orari di inizio
e fine, relazione comando/risposta, testo completo e hex dump classico
(offset, 16 byte per riga, ASCII).

## Comandi e opzioni

| Comando / opzione         | Effetto                                                          |
|---------------------------|------------------------------------------------------------------|
| Connetti / Disconnetti    | Apre / chiude le due porte                                       |
| Aggiorna porte            | Rilegge l'elenco delle porte seriali                             |
| Pausa cattura             | Smette di registrare i pacchetti; **il ponte continua a inoltrare** |
| Pulisci                   | Svuota la lista                                                  |
| Esporta CSV               | Salva tutti i pacchetti (`;` come separatore, apribile con Excel) |
| Inoltra 1 → 2 / 2 → 1     | Attiva/disattiva la ritrasmissione per ciascun verso (default ON) |
| Fine pacchetto (ms)       | Silenzio che chiude un pacchetto (default 50, 0 = ogni lettura)  |
| Timeout risposta (ms)     | Ritardo massimo per considerare un pacchetto risposta (0 = senza limite) |
| Auto-scroll               | Segue l'ultimo pacchetto arrivato                                |
| Mostra                    | Filtra la lista per direzione                                    |

## Note

- I dati sono decodificati come **Latin-1** (1 byte = 1 carattere, senza
  perdita).
- La lista conserva gli ultimi 20000 pacchetti; per catture lunghe usa
  **Esporta CSV**.
- Le due porte devono essere **diverse**.
- Per vedere i nomi delle porte disponibili: `ls /dev/tty*` oppure il pulsante
  **Aggiorna porte**. Per i permessi vedi *Permessi sulle porte seriali*.
