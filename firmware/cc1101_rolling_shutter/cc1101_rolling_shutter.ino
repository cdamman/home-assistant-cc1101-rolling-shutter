// ---------------------------------------------------------------------------
// 868 MHz roller shutters - combined transmitter + receiver
//
// A pure protocol bridge: shutters are addressed by their 4-byte ID, and no
// device list is stored in the firmware. Friendly names, grouping and state
// tracking belong to the consumer (Home Assistant, MQTT bridge, ...).
//
// Serial interface (one command per line, 115200 baud):
//
//   <id> <action>    id     : 4-byte shutter ID as 8 hex digits.
//                             ':', '-' and '.' separators are accepted.
//                    action : open | up, stop, close | down
//   status           dump the rolling counter table
//
//   > 12345600 close
//   > 12:34:56:00 up
//
// Every received frame is reported as a JSON line. This is also how you learn
// the ID of a shutter: press a button on the original remote and read the
// "rx" line.
//
// Protocol: see PROTOCOL.md
// Driver:   https://github.com/LSatan/SmartRC-CC1101-Driver-Lib
// ---------------------------------------------------------------------------
#include <ELECHOUSE_CC1101_SRC_DRV.h>

#define SIGNAL_DURATION_MS 16   // 152 bits @ 9.57 kBaud
#define SIGNAL_LEN_BYTES   10
#define NB_SIGNALS         4    // frames per press (consecutive counters)
#define NB_RETRIES         4    // burst repetitions

#define LED_PIN D4
#define GDO0    D1

// Forward declaration, required by the Arduino IDE: it generates a prototype
// for every function and inserts them all ahead of the first function
// definition - which sits above the struct itself, further down. The
// generated prototypes only ever pass Device pointers, so an incomplete type
// is enough to keep them valid. Do not remove: without it the build fails
// with "'Device' does not name a type".
struct Device;

// --- Protocol --------------------------------------------------------------
// Only these three commands have been observed on air. A fourth button very
// likely exists (pairing), but neither its command bit nor its redundant
// counterpart can be extrapolated: the mapping between the rotation index k
// of ROR(0xAF, 2*k) and the command bit is already non-monotonic
// (k=0 -> bit 1, k=1 -> bit 0, k=2 -> bit 2). An unknown button therefore
// fails the redundancy check and is reported as a "raw" line, with the
// payload unmasked - which is exactly what is needed to identify it.
#define CMD_STOP 0x01
#define CMD_UP   0x02
#define CMD_DOWN 0x04

#define COUNTER_OFFSET 7        // byte[8] = byte[0] + 7
#define CMD_ALT_BASE   0xAF     // byte[6] = ROR(0xAF, 2*k)

// --- Protocol helpers ------------------------------------------------------
static byte cmdAlt(byte cmd) {
    byte k;                                   // rotation = 2 * button index
    switch (cmd) {
        case CMD_UP:   k = 0; break;
        case CMD_STOP: k = 2; break;
        case CMD_DOWN: k = 4; break;
        default: return 0;
    }
    return (byte)((CMD_ALT_BASE >> k) | (CMD_ALT_BASE << (8 - k)));
}

static void cmdLabel(byte cmd, char *out) {
    switch (cmd) {
        case CMD_UP:   strcpy(out, "open");  break;
        case CMD_STOP: strcpy(out, "stop");  break;
        case CMD_DOWN: strcpy(out, "close"); break;
        default:       sprintf(out, "0x%02x", cmd); break;
    }
}

void buildFrame(const byte id[4], byte cmd, byte counter, byte *out) {
    out[0] = counter;
    out[1] = id[0] ^ counter;
    out[2] = id[1] ^ counter;
    out[3] = id[2] ^ counter;
    out[4] = id[3] ^ counter;
    out[5] = cmd ^ counter;
    out[6] = cmdAlt(cmd) ^ counter;
    out[7] = counter;
    out[8] = counter + COUNTER_OFFSET;

    byte sum = 0;
    for (int i = 0; i < 9; i++) sum += out[i];
    out[9] = sum;
}

bool checksumOk(const byte *f, int len) {
    if (len != SIGNAL_LEN_BYTES) return false;
    byte sum = 0;
    for (int i = 0; i < 9; i++) sum += f[i];
    return sum == f[9];
}

bool parseFrame(const byte *f, int len, byte id[4], byte *cmd, byte *counter) {
    if (!checksumOk(f, len)) return false;

    byte c = f[0];
    if (f[7] != c) return false;
    if (f[8] != (byte)(c + COUNTER_OFFSET)) return false;

    byte command = f[5] ^ c;
    if ((f[6] ^ c) != cmdAlt(command)) return false;   // command redundancy

    for (int i = 0; i < 4; i++) id[i] = f[i + 1] ^ c;
    *cmd = command;
    *counter = c;
    return true;
}

// --- Per-ID state ----------------------------------------------------------
// The rolling counter belongs to the *remote*, not to the shutter: all the
// channels of one remote share a single counter. But frames only carry the
// shutter ID, so remotes cannot be told apart over the air. Tracking one
// counter per ID is therefore the correct granularity - a global counter
// would be corrupted as soon as a second remote is in use.
//
// IDs belonging to the same remote drift apart only through our own
// transmissions, and each is resynchronised the next time that shutter's
// button is pressed. Since receivers do not enforce counter monotonicity,
// the drift is harmless (which is also why the table is not persisted across
// reboots).
//
// The same entry carries the de-duplication state, so that presses on two
// different shutters interleaved in time are both reported.
#define MAX_DEVICES     16
#define BURST_WINDOW_MS 1500

struct Device {
    byte id[4];
    byte counter;             // last counter seen on air or emitted by us
    byte lastCmd;             // de-duplication: command of the last press
    unsigned long lastPress;  // de-duplication: millis of the last frame heard
    bool used;
};

Device devices[MAX_DEVICES];

Device *findDevice(const byte id[4]) {
    for (int i = 0; i < MAX_DEVICES; i++) {
        if (devices[i].used && memcmp(devices[i].id, id, 4) == 0) return &devices[i];
    }
    return NULL;
}

// Find the entry, allocating it if needed.
//
// Only frames that already passed the sync word, the checksum and both
// redundancy checks ever reach this table, so it is fed by real shutters
// only - yours plus any neighbour's within range. Overflowing 16 entries is
// not a realistic scenario, and the cost of recycling the wrong entry is a
// counter reset, which is harmless. Hence the deliberately dumb round-robin:
// no timestamp to maintain, and no millis() rollover to reason about.
byte nextVictim = 0;

Device *touchDevice(const byte id[4]) {
    Device *d = findDevice(id);
    if (d) return d;

    for (int i = 0; i < MAX_DEVICES; i++) {
        if (!devices[i].used) { d = &devices[i]; break; }
    }
    if (!d) {                                   // table full: recycle
        d = &devices[nextVictim];
        nextVictim = (nextVictim + 1) % MAX_DEVICES;
    }

    memcpy(d->id, id, 4);
    d->counter = 0;
    d->lastCmd = 0;
    d->lastPress = 0;
    d->used = true;
    return d;
}

// One press generates 4 to 16 frames; only the first is reported.
bool isNewPress(Device *d, byte cmd) {
    unsigned long now = millis();
    bool same = (cmd == d->lastCmd) && (now - d->lastPress < BURST_WINDOW_MS);
    d->lastCmd = cmd;
    d->lastPress = now;
    return !same;
}

// --- Radio -----------------------------------------------------------------
void setup() {
    Serial.begin(115200);
    Serial.println();
    Serial.println(ELECHOUSE_cc1101.getCC1101() ? "Connection OK" : "Connection Error");

    ELECHOUSE_cc1101.Init();
    ELECHOUSE_cc1101.setGDO0(GDO0);
    ELECHOUSE_cc1101.setCCMode(1);
    ELECHOUSE_cc1101.setModulation(0);              // 2-FSK
    ELECHOUSE_cc1101.setMHZ(868.027 - 0.083);
    ELECHOUSE_cc1101.setDeviation(55.00);
    ELECHOUSE_cc1101.setChannel(0);
    ELECHOUSE_cc1101.setChsp(199.95);
    ELECHOUSE_cc1101.setRxBW(812.50);
    ELECHOUSE_cc1101.setDRate(9.57);
    ELECHOUSE_cc1101.setPA(12);
    ELECHOUSE_cc1101.setSyncMode(2);                // 16/16 bits: fewer false
                                                    // syncs. Revert to 1 if
                                                    // presses get missed.
    ELECHOUSE_cc1101.setSyncWord(0x4b, 0xd4);
    ELECHOUSE_cc1101.setAdrChk(0);
    ELECHOUSE_cc1101.setAddr(0);
    ELECHOUSE_cc1101.setWhiteData(0);
    ELECHOUSE_cc1101.setPktFormat(0);
    ELECHOUSE_cc1101.setLengthConfig(0);            // fixed length
    ELECHOUSE_cc1101.setPacketLength(SIGNAL_LEN_BYTES + 1);
    ELECHOUSE_cc1101.setCrc(0);
    ELECHOUSE_cc1101.setCRC_AF(0);
    ELECHOUSE_cc1101.setDcFilterOff(0);
    ELECHOUSE_cc1101.setManchester(0);
    ELECHOUSE_cc1101.setFEC(0);
    ELECHOUSE_cc1101.setPRE(3);                     // 6 preamble bytes
    ELECHOUSE_cc1101.setPQT(0);
    ELECHOUSE_cc1101.setAppendStatus(0);

    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);

    ELECHOUSE_cc1101.SetRx();
    Serial.println("{\"event\":\"ready\"}");
}

void transmit(const byte id[4], byte cmd) {
    Device *d = touchDevice(id);
    byte frame[SIGNAL_LEN_BYTES];
    char label[8];

    digitalWrite(LED_PIN, LOW);

    byte base = d->counter + 1;                 // continue this ID's sequence

    for (int r = 0; r < NB_RETRIES; r++) {
        for (int j = 0; j < NB_SIGNALS; j++) {
            buildFrame(id, cmd, base + j, frame);
            ELECHOUSE_cc1101.SendData(frame, SIGNAL_LEN_BYTES, 2 * SIGNAL_DURATION_MS);
        }
    }
    d->counter = base + NB_SIGNALS - 1;

    digitalWrite(LED_PIN, HIGH);
    ELECHOUSE_cc1101.SetRx();

    cmdLabel(cmd, label);
    Serial.printf("{\"event\":\"tx\",\"id\":\"%02x%02x%02x%02x\",\"cmd\":\"%s\","
                  "\"counter\":%u}\n",
                  id[0], id[1], id[2], id[3], label, d->counter);
}

// --- Serial command parsing ------------------------------------------------
void reportError(const char *reason, const char *detail) {
    Serial.printf("{\"event\":\"error\",\"reason\":\"%s\",\"input\":\"%s\"}\n",
                  reason, detail);
}

static int hexVal(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;                                   // input is lowercased already
}

// Accepts exactly 8 hex digits, with optional ':' '-' '.' separators.
bool parseId(const char *s, byte id[4]) {
    int nibbles[8];
    int n = 0;
    for (const char *p = s; *p; p++) {
        if (*p == ':' || *p == '-' || *p == '.') continue;
        int v = hexVal(*p);
        if (v < 0 || n >= 8) return false;
        nibbles[n++] = v;
    }
    if (n != 8) return false;
    for (int i = 0; i < 4; i++) id[i] = (nibbles[2 * i] << 4) | nibbles[2 * i + 1];
    return true;
}

void printStatus() {
    Serial.print("{\"event\":\"status\",\"devices\":[");
    bool first = true;
    for (int i = 0; i < MAX_DEVICES; i++) {
        if (!devices[i].used) continue;
        if (!first) Serial.print(",");
        first = false;
        Serial.printf("{\"id\":\"%02x%02x%02x%02x\",\"counter\":%u,\"last_rx_ms\":",
                      devices[i].id[0], devices[i].id[1], devices[i].id[2],
                      devices[i].id[3], devices[i].counter);
        // null when the ID was only ever transmitted to, never heard.
        if (devices[i].lastPress) Serial.printf("%lu}", millis() - devices[i].lastPress);
        else                      Serial.print("null}");
    }
    Serial.println("]}");
}

void handleCommand(char *line) {
    for (char *p = line; *p; p++) *p = tolower(*p);

    char *target = strtok(line, " \t");
    if (!target) return;
    char *action = strtok(NULL, " \t");

    if (!action) {
        if (!strcmp(target, "status")) printStatus();
        else reportError("missing action", target);
        return;
    }

    byte cmd;
    if (!strcmp(action, "open") || !strcmp(action, "up"))         cmd = CMD_UP;
    else if (!strcmp(action, "stop"))                             cmd = CMD_STOP;
    else if (!strcmp(action, "close") || !strcmp(action, "down")) cmd = CMD_DOWN;
    else { reportError("unknown action", action); return; }

    byte id[4];
    if (!parseId(target, id)) { reportError("bad id", target); return; }

    transmit(id, cmd);
}

// Non-blocking line reader: a blocking read would stall RX and drop frames.
// A line is also flushed after a short idle, for terminals sending no newline.
#define LINE_MAX      64
#define LINE_IDLE_MS  60

char lineBuf[LINE_MAX];
uint8_t lineLen = 0;
unsigned long lastChar = 0;

void pollSerial() {
    while (Serial.available()) {
        char ch = Serial.read();
        lastChar = millis();
        if (ch == '\r') continue;
        if (ch == '\n') {
            lineBuf[lineLen] = '\0';
            if (lineLen) handleCommand(lineBuf);
            lineLen = 0;
            return;
        }
        if (lineLen < LINE_MAX - 1) lineBuf[lineLen++] = ch;
    }
    if (lineLen && millis() - lastChar > LINE_IDLE_MS) {
        lineBuf[lineLen] = '\0';
        handleCommand(lineBuf);
        lineLen = 0;
    }
}

// --- Reception -------------------------------------------------------------
byte buffer[256];

void pollRadio() {
    if (!ELECHOUSE_cc1101.CheckRxFifo(SIGNAL_DURATION_MS)) return;

    int rssi = ELECHOUSE_cc1101.getRssi();
    int len = ELECHOUSE_cc1101.ReceiveData(buffer);
    if (len <= 0) return;

    byte id[4], cmd, counter;
    if (parseFrame(buffer, len, id, &cmd, &counter)) {
        Device *d = touchDevice(id);
        d->counter = counter;                        // resynchronise

        if (isNewPress(d, cmd)) {
            char label[8];
            cmdLabel(cmd, label);
            Serial.printf(
                "{\"event\":\"rx\",\"id\":\"%02x%02x%02x%02x\",\"cmd\":\"%s\","
                "\"counter\":%u,\"rssi\":%d}\n",
                id[0], id[1], id[2], id[3], label, counter, rssi);
        }
        return;
    }

    // Frame we cannot validate: an unknown button, or noise. Dump it raw.
    Serial.printf("{\"event\":\"raw\",\"rssi\":%d,\"data\":\"", rssi);
    for (int i = 0; i < len && i < 32; i++) Serial.printf("%02x", buffer[i]);
    Serial.print("\"");

    // Right length and valid checksum: very likely our protocol with an
    // unknown command. Show the payload unmasked, so the ID and both command
    // bytes can be read off directly.
    if (checksumOk(buffer, len)) {
        Serial.print(",\"unmasked\":\"");
        for (int i = 0; i < SIGNAL_LEN_BYTES; i++)
            Serial.printf("%02x", buffer[i] ^ buffer[0]);
        Serial.print("\"");
    }
    Serial.println("}");
}

void loop() {
    pollSerial();
    pollRadio();
}
