//New transmission method.
//In addition, the gdo0 and gdo2 pin are not required.
//https://github.com/LSatan/SmartRC-CC1101-Driver-Lib
//by Little_S@tan
#include <ELECHOUSE_CC1101_SRC_DRV.h>

#define SIGNAL_DURATION_MS 16 // 152 bits @ 9.57 kBaud = 15.88 ms
#define SIGNAL_LEN_BYTES 10 // Total: 6 bytes preamble + 2 bytes sync + 1 byte lenght + 10 bytes data = 152 bits
#define NB_SIGNALS 4
#define NB_RETRIES 4 // (256 / NB_SIGNALS)

#define OPEN 0
#define STOP 1
#define CLOSE 2
#define NB_COMMANDS 3

// One entry per shutter. These are just indices into codes[] below: the id you
// send over serial ("2 open") selects SHUTTER_2. Rename them to suit your home.
#define SHUTTER_0 0
#define SHUTTER_1 1
#define SHUTTER_2 2
#define SHUTTER_3 3
#define SHUTTER_4 4
#define NB_SHUTTERS 5

// EXAMPLE DATA ONLY - these frames are placeholders and will not drive any
// shutter. Every rolling shutter remote has its own frames, so you have to
// capture yours and paste them in here. See the README ("Where the codes come
// from"): sniff the remote, or listen with this sketch itself - anything it
// receives is printed on the serial console in exactly the format below, ready
// to paste.
//
// Layout: codes[shutter][command][signal][byte], with command in the order
// open, stop, close.
byte codes[NB_SHUTTERS][NB_COMMANDS][NB_SIGNALS][SIGNAL_LEN_BYTES] = {
    { // shutter 0
        { // open
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x00, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x00, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x00, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x00, 0x03, 0xff},
        },
        { // stop
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x01, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x01, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x01, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x01, 0x03, 0xff},
        },
        { // close
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x02, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x02, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x02, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x00, 0x02, 0x03, 0xff},
        }
    },
    { // shutter 1
        { // open
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x00, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x00, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x00, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x00, 0x03, 0xff},
        },
        { // stop
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x01, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x01, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x01, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x01, 0x03, 0xff},
        },
        { // close
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x02, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x02, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x02, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x01, 0x02, 0x03, 0xff},
        }
    },
    { // shutter 2
        { // open
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x00, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x00, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x00, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x00, 0x03, 0xff},
        },
        { // stop
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x01, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x01, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x01, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x01, 0x03, 0xff},
        },
        { // close
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x02, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x02, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x02, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x02, 0x02, 0x03, 0xff},
        }
    },
    { // shutter 3
        { // open
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x00, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x00, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x00, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x00, 0x03, 0xff},
        },
        { // stop
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x01, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x01, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x01, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x01, 0x03, 0xff},
        },
        { // close
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x02, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x02, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x02, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x03, 0x02, 0x03, 0xff},
        }
    },
    { // shutter 4
        { // open
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x00, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x00, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x00, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x00, 0x03, 0xff},
        },
        { // stop
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x01, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x01, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x01, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x01, 0x03, 0xff},
        },
        { // close
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x02, 0x00, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x02, 0x01, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x02, 0x02, 0xff},
            {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x04, 0x02, 0x03, 0xff},
        }
    },
};

#define LED_PIN D4
#define GDO0 D1

void setup() {
    Serial.begin(115200);
    Serial.println();
    if (ELECHOUSE_cc1101.getCC1101()) {      // Check the CC1101 Spi connection.
        Serial.println("Connection OK");
    } else {
        Serial.println("Connection Error");
    }
 
    ELECHOUSE_cc1101.Init();                // must be set to initialize the cc1101!
    ELECHOUSE_cc1101.setGDO0(GDO0);         // set lib internal gdo pin (gdo0). Gdo2 not use for this example.
    ELECHOUSE_cc1101.setCCMode(1);          // set config for internal transmission mode.
    ELECHOUSE_cc1101.setModulation(0);      // set modulation mode. 0 = 2-FSK, 1 = GFSK, 2 = ASK/OOK, 3 = 4-FSK, 4 = MSK.
    ELECHOUSE_cc1101.setMHZ(868.027 - 0.083); // Here you can set your basic frequency. The lib calculates the frequency automatically (default = 433.92).The cc1101 can: 300-348 MHZ, 387-464MHZ and 779-928MHZ. Read More info from datasheet.
    ELECHOUSE_cc1101.setDeviation(55.00);   // Set the Frequency deviation in kHz. Value from 1.58 to 380.85. Default is 47.60 kHz.
    ELECHOUSE_cc1101.setChannel(0);         // Set the Channelnumber from 0 to 255. Default is channel 0.
    ELECHOUSE_cc1101.setChsp(199.95);       // The channel spacing is multiplied by the channel number CHAN and added to the base frequency in kHz. Value from 25.39 to 405.45. Default is 199.95 kHz.
    ELECHOUSE_cc1101.setRxBW(812.50);       // Set the Receive Bandwidth in kHz. Value from 58.03 to 812.50. Default is 812.50 kHz.
    ELECHOUSE_cc1101.setDRate(9.57);        // Set the Data Rate in kBaud. Value from 0.02 to 1621.83. Default is 99.97 kBaud!
    ELECHOUSE_cc1101.setPA(12);             // Set TxPower. The following settings are possible depending on the frequency band.  (-30  -20  -15  -10  -6    0    5    7    10   11   12) Default is max!
    ELECHOUSE_cc1101.setSyncMode(1);        // Combined sync-word qualifier mode. 0 = No preamble/sync. 1 = 16 sync word bits detected. 2 = 16/16 sync word bits detected. 3 = 30/32 sync word bits detected. 4 = No preamble/sync, carrier-sense above threshold. 5 = 15/16 + carrier-sense above threshold. 6 = 16/16 + carrier-sense above threshold. 7 = 30/32 + carrier-sense above threshold.
    ELECHOUSE_cc1101.setSyncWord(0x4b, 0xd4); // Set sync word. Must be the same for the transmitter and receiver. (Syncword high, Syncword low)
    ELECHOUSE_cc1101.setAdrChk(0);          // Controls address check configuration of received packages. 0 = No address check. 1 = Address check, no broadcast. 2 = Address check and 0 (0x00) broadcast. 3 = Address check and 0 (0x00) and 255 (0xFF) broadcast.
    ELECHOUSE_cc1101.setAddr(0);            // Address used for packet filtration. Optional broadcast addresses are 0 (0x00) and 255 (0xFF).
    ELECHOUSE_cc1101.setWhiteData(0);       // Turn data whitening on / off. 0 = Whitening off. 1 = Whitening on.
    ELECHOUSE_cc1101.setPktFormat(0);       // Format of RX and TX data. 0 = Normal mode, use FIFOs for RX and TX. 1 = Synchronous serial mode, Data in on GDO0 and data out on either of the GDOx pins. 2 = Random TX mode; sends random data using PN9 generator. Used for test. Works as normal mode, setting 0 (00), in RX. 3 = Asynchronous serial mode, Data in on GDO0 and data out on either of the GDOx pins.
    ELECHOUSE_cc1101.setLengthConfig(0);    // 0 = Fixed packet length mode. 1 = Variable packet length mode. 2 = Infinite packet length mode. 3 = Reserved
    ELECHOUSE_cc1101.setPacketLength(SIGNAL_LEN_BYTES + 1); // Indicates the packet length when fixed packet length mode is enabled. If variable packet length mode is used, this value indicates the maximum packet length allowed.
    ELECHOUSE_cc1101.setCrc(0);             // 1 = CRC calculation in TX and CRC check in RX enabled. 0 = CRC disabled for TX and RX.
    ELECHOUSE_cc1101.setCRC_AF(0);          // Enable automatic flush of RX FIFO when CRC is not OK. This requires that only one packet is in the RXIFIFO and that packet length is limited to the RX FIFO size.
    ELECHOUSE_cc1101.setDcFilterOff(0);     // Disable digital DC blocking filter before demodulator. Only for data rates ≤ 250 kBaud The recommended IF frequency changes when the DC blocking is disabled. 1 = Disable (current optimized). 0 = Enable (better sensitivity).
    ELECHOUSE_cc1101.setManchester(0);      // Enables Manchester encoding/decoding. 0 = Disable. 1 = Enable.
    ELECHOUSE_cc1101.setFEC(0);             // Enable Forward Error Correction (FEC) with interleaving for packet payload (Only supported for fixed packet length mode. 0 = Disable. 1 = Enable.
    ELECHOUSE_cc1101.setPRE(3);             // Sets the minimum number of preamble bytes to be transmitted. Values: 0 : 2, 1 : 3, 2 : 4, 3 : 6, 4 : 8, 5 : 12, 6 : 16, 7 : 24
    ELECHOUSE_cc1101.setPQT(0);             // Preamble quality estimator threshold. The preamble quality estimator increases an internal counter by one each time a bit is received that is different from the previous bit, and decreases the counter by 8 each time a bit is received that is the same as the last bit. A threshold of 4∙PQT for this counter is used to gate sync word detection. When PQT=0 a sync word is always accepted.
    ELECHOUSE_cc1101.setAppendStatus(0);    // When enabled, two status bytes will be appended to the payload of the packet. The status bytes contain RSSI and LQI values, as well as CRC OK.

    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);
}

byte buffer[500] = {0};

void transmit(int room, int cmd) {
    Serial.printf("Sending codes for room %d, cmd %d\n", room, cmd);
    digitalWrite(LED_PIN, LOW);
    for (int i = 0; i < NB_RETRIES; i++) {
        for (int j = 0; j < NB_SIGNALS; j++) {
            ELECHOUSE_cc1101.SendData(codes[room][cmd][j], SIGNAL_LEN_BYTES, 2 * SIGNAL_DURATION_MS);
        }
    }
    digitalWrite(LED_PIN, HIGH);
}

void loop() {
    if (Serial.available() > 0) {
        String cmd = Serial.readString();
        cmd.trim();

        Serial.println(cmd);
        if (cmd == "0 open") {
            transmit(SHUTTER_0, OPEN);
        } else if (cmd == "0 stop") {
            transmit(SHUTTER_0, STOP);
        } else if (cmd == "0 close") {
            transmit(SHUTTER_0, CLOSE);
        } else if (cmd == "1 open") {
            transmit(SHUTTER_1, OPEN);
        } else if (cmd == "1 stop") {
            transmit(SHUTTER_1, STOP);
        } else if (cmd == "1 close") {
            transmit(SHUTTER_1, CLOSE);
        } else if (cmd == "2 open") {
            transmit(SHUTTER_2, OPEN);
        } else if (cmd == "2 stop") {
            transmit(SHUTTER_2, STOP);
        } else if (cmd == "2 close") {
            transmit(SHUTTER_2, CLOSE);
        } else if (cmd == "3 open") {
            transmit(SHUTTER_3, OPEN);
        } else if (cmd == "3 stop") {
            transmit(SHUTTER_3, STOP);
        } else if (cmd == "3 close") {
            transmit(SHUTTER_3, CLOSE);
        } else if (cmd == "4 open") {
            transmit(SHUTTER_4, OPEN);
        } else if (cmd == "4 stop") {
            transmit(SHUTTER_4, STOP);
        } else if (cmd == "4 close") {
            transmit(SHUTTER_4, CLOSE);
        }
    }

    // Checks whether something has been received.
    // When something is received we give some time to receive the message in full.(time in millis)
    if (ELECHOUSE_cc1101.CheckRxFifo(SIGNAL_DURATION_MS)) {
        int rssi = ELECHOUSE_cc1101.getRssi();
        // Rssi Level in dBm
        Serial.printf("Received (%d dBm):            ", rssi);

        // Get received Data and calculate length
        int len = ELECHOUSE_cc1101.ReceiveData(buffer);
        buffer[len] = 0;

        // Print received in bytes format.
        Serial.print("{");
        for (int i = 0; i < len; i++) {
            if (i > 0) Serial.print(", ");
            Serial.printf("0x%02x", buffer[i]);
        }
        Serial.println("},");
    }
}
