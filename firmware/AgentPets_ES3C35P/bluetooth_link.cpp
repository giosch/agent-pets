#include <Arduino.h>
#include <NimBLEDevice.h>
#include <NimBLEHIDDevice.h>
#include <atomic>
#include "bluetooth_link.h"
#include "habitat.h"

// BLE UART pattern from Espressif's Arduino UART example, using NimBLE to
// leave RAM/flash for the renderer. Separate UUIDs identify habitat protocol v1.
static constexpr char SERVICE[] = "96a5d701-e7c7-4b8f-9df4-23dd0f624a01";
static constexpr char RX_UUID[] = "96a5d702-e7c7-4b8f-9df4-23dd0f624a01";
static constexpr char TX_UUID[] = "96a5d703-e7c7-4b8f-9df4-23dd0f624a01";
static NimBLEServer* server;
static NimBLECharacteristic* replies;
static NimBLECharacteristic *hidReplies, *hidCapabilities;
static std::atomic<bool> lastHid{false};
// One vendor application collection. No keyboard/mouse/consumer usages.
// Report 1: 8-byte Input ACK and 63-byte Output fragment.
// Report 2: 63-byte read-only capability/status Feature (16 meaningful bytes).
// Report 3: 63-byte Feature fragment (acknowledged Set_Report data path).
static uint8_t reportMap[] = {
  0x06,0x00,0xFF, 0x09,0x01, 0xA1,0x01,
  0x15,0x00, 0x26,0xFF,0x00, 0x75,0x08,
  0x85,0x01, 0x09,0x02, 0x95,0x08, 0x81,0x02,
  0x09,0x03, 0x95,0x3F, 0x91,0x02,
  0x85,0x02, 0x09,0x04, 0x95,0x3F, 0xB1,0x02,
  0x85,0x03, 0x09,0x05, 0x95,0x3F, 0xB1,0x02, 0xC0
};
static uint8_t capabilities[63] = {'A','P','H','1', 1,63, 0,16, 255,0,0,0,0,0,0,0};
static portMUX_TYPE capabilityLock = portMUX_INITIALIZER_UNLOCKED;
static std::atomic<bool> secured{false};
static std::atomic<uint32_t> generation{0};
static std::atomic<uint32_t> pairUntil{0};
static char deviceName[24];
struct Record { char text[4096]; uint16_t connection; uint32_t generation, tx; bool hid; };
static QueueHandle_t incoming;
static Record assembling;
static size_t used = 0;
static bool discarding = false;
static uint32_t lastChunk = 0;
// HID and GATT have separate assembly buffers so fallback cannot splice streams.
static Record hidAssembling;
static size_t hidUsed = 0;
static uint32_t hidTx = 0, lastHidChunk = 0;
static bool hidActive = false;

static void setHidStatus(uint8_t result, uint32_t tx)
{
  portENTER_CRITICAL(&capabilityLock);
  capabilities[8] = result;
  for (int i = 0; i < 4; ++i) capabilities[9 + i] = tx >> (8 * i);
  capabilities[13] = lastHid ? 1 : 2;
  portEXIT_CRITICAL(&capabilityLock);
}

const char* bluetoothTransport() { return lastHid ? "HID" : "GATT"; }
uint32_t bluetoothGeneration() { return generation.load(); }

unsigned bluetoothPairSeconds()
{
  int32_t remaining = int32_t(pairUntil.load() - millis());
  return remaining > 0 ? (remaining + 999) / 1000 : 0;
}
bool bluetoothConnected() { return secured.load(); }
bool bluetoothBonded() { return NimBLEDevice::getNumBonds() > 0; }
const char* bluetoothName() { return deviceName; }

class ServerCallbacks : public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* s, NimBLEConnInfo& peer) override {
    generation++;
    used = 0;
    discarding = false;
    hidActive = false;
    xQueueReset(incoming);
    if (!bluetoothPairSeconds() && !NimBLEDevice::isBonded(peer.getIdAddress())) {
      s->disconnect(peer);
      return;
    }
    s->updateConnParams(peer.getConnHandle(), 12, 24, 0, 200);
  }
  void onDisconnect(NimBLEServer*, NimBLEConnInfo&, int) override {
    secured = false;
    generation++;
    used = 0;
    discarding = false;
    hidActive = false;
    xQueueReset(incoming);
    Serial.println("{\"event\":\"bluetooth_disconnected\"}");
  }
  void onAuthenticationComplete(NimBLEConnInfo& peer) override {
    if (!peer.isEncrypted() || !peer.isBonded()) {
      server->disconnect(peer);
      return;
    }
    secured = true;
    pairUntil = 0;
    Serial.println("{\"event\":\"bluetooth_secured\"}");
  }
} serverCallbacks;

class ReceiveCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo& peer) override {
    if (!secured || !peer.isEncrypted()) return;
    if (millis() - lastChunk > 2000) {
      used = 0;
      discarding = false;
    }
    lastChunk = millis();
    auto value = characteristic->getValue();
    for (size_t i = 0; i < value.size(); ++i) {
      char c = value.data()[i];
      if (c == '\n') {
        if (used && !discarding) {
          assembling.text[used] = 0;
          assembling.connection = peer.getConnHandle();
          assembling.generation = generation.load();
          assembling.hid = false;
          assembling.tx = 0;
          // Parsing, scene changes and acknowledgements happen on the UI task.
          // A full queue drops this record; the PC times out and reconnects.
          xQueueSend(incoming, &assembling, 0);
        }
        used = 0;
        discarding = false;
      } else if (c != '\r' && !discarding) {
        if (used < sizeof(assembling.text) - 1) assembling.text[used++] = c;
        else discarding = true;
      }
    }
  }
} receiveCallbacks;

class HidReceiveCallbacks : public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* characteristic, NimBLEConnInfo& peer) override {
    if (!secured || !peer.isEncrypted()) return;
    auto value = characteristic->getValue();
    if (value.size() != 63) { hidActive = false; return; }
    const uint8_t* p = value.data();
    uint8_t flags = p[1], length = p[8];
    uint32_t tx = uint32_t(p[2]) | uint32_t(p[3]) << 8 | uint32_t(p[4]) << 16 | uint32_t(p[5]) << 24;
    size_t offset = size_t(p[6]) | size_t(p[7]) << 8;
    if (p[0] != 0xC1 || !tx || flags & ~3 || !length || length > 54 ||
        offset + length > sizeof(hidAssembling.text) - 1) { hidActive = false; return; }
    if (flags & 1) {
      hidActive = offset == 0;
      hidUsed = 0;
      hidTx = tx;
    }
    if (!hidActive || tx != hidTx || offset != hidUsed ||
        (!(flags & 1) && millis() - lastHidChunk > 2000)) { hidActive = false; return; }
    memcpy(hidAssembling.text + hidUsed, p + 9, length);
    hidUsed += length;
    lastHidChunk = millis();
    if (flags & 2) {
      hidAssembling.text[hidUsed] = 0;
      hidAssembling.connection = peer.getConnHandle();
      hidAssembling.generation = generation.load();
      hidAssembling.hid = true;
      hidAssembling.tx = tx;
      xQueueSend(incoming, &hidAssembling, 0);
      hidActive = false;
    }
  }
} hidReceiveCallbacks;

class CapabilityCallbacks : public NimBLECharacteristicCallbacks {
  void onRead(NimBLECharacteristic* characteristic, NimBLEConnInfo&) override {
    uint8_t value[63];
    portENTER_CRITICAL(&capabilityLock);
    memcpy(value, capabilities, sizeof(value));
    portEXIT_CRITICAL(&capabilityLock);
    characteristic->setValue(value, sizeof(value));
  }
} capabilityCallbacks;

void bluetoothBegin()
{
  snprintf(deviceName, sizeof(deviceName), "Agent Pets %04X", unsigned(ESP.getEfuseMac() & 0xFFFF));
  incoming = xQueueCreate(2, sizeof(Record));
  if (!incoming || !NimBLEDevice::init(deviceName)) {
    Serial.println("{\"event\":\"bluetooth_init_failed\"}");
    return;
  }
  NimBLEDevice::setMTU(247);
  // Bonded Secure Connections, with new peers accepted only during Pair PC.
  NimBLEDevice::setSecurityAuth(true, false, true);
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);
  server = NimBLEDevice::createServer();
  server->setCallbacks(&serverCallbacks, false); // Static callback object is not owned by NimBLE.
  server->advertiseOnDisconnect(false);
  auto hid = new NimBLEHIDDevice(server);
  hid->setManufacturer("Agent Pets");
  // Development identity on this Espressif board; product identifier is local.
  hid->setPnp(0x02, 0x303A, 0xA937, 0x0100);
  hid->setHidInfo(0, 0x02); // normally connectable, no remote wake
  hid->setReportMap(reportMap, sizeof(reportMap));
  auto serialNumber = hid->getDeviceInfoService()->createCharacteristic(uint16_t(0x2A25), NIMBLE_PROPERTY::READ);
  serialNumber->setValue(deviceName);
  hidReplies = hid->getInputReport(1);
  uint8_t initialAck[8] = {0xC1,255,0,0,0,0,1,0};
  hidReplies->setValue(initialAck, sizeof(initialAck));
  uint8_t emptyReport[63] = {};
  hid->getOutputReport(1)->setValue(emptyReport, sizeof(emptyReport));
  hid->getOutputReport(1)->setCallbacks(&hidReceiveCallbacks);
  hidCapabilities = hid->getFeatureReport(2);
  hidCapabilities->setCallbacks(&capabilityCallbacks);
  hidCapabilities->setValue(capabilities, sizeof(capabilities));
  hid->getFeatureReport(3)->setCallbacks(&hidReceiveCallbacks);
  hid->getFeatureReport(3)->setValue(emptyReport, sizeof(emptyReport));
  hid->setBatteryLevel(100); // USB-powered development board
  hid->getHidService()->start();
  hid->getDeviceInfoService()->start();
  hid->getBatteryService()->start();
  auto service = server->createService(SERVICE);
  auto rx = service->createCharacteristic(RX_UUID, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_ENC, 512);
  rx->setCallbacks(&receiveCallbacks);
  replies = service->createCharacteristic(TX_UUID, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::READ_ENC | NIMBLE_PROPERTY::NOTIFY, 20);
  service->start();
  auto advertising = NimBLEDevice::getAdvertising();
  advertising->enableScanResponse(true);
  advertising->setName(deviceName);
  advertising->setAppearance(GENERIC_HID);
  advertising->addServiceUUID(uint16_t(0x1812));
  advertising->addServiceUUID(SERVICE);
}

void bluetoothPair() { if (server) pairUntil = millis() + 120000; }
void bluetoothCancelPair() { pairUntil = 0; }
void bluetoothForget()
{
  if (!server) return;
  pairUntil = 0;
  secured = false;
  for (auto peer : server->getPeerDevices()) server->disconnect(peer);
  NimBLEDevice::deleteAllBonds();
  generation++;
  xQueueReset(incoming);
}

void bluetoothTick()
{
  if (!server) return;
  auto advertising = NimBLEDevice::getAdvertising();
  bool wanted = !server->getConnectedCount() && (bluetoothBonded() || bluetoothPairSeconds());
  if (wanted && !advertising->isAdvertising()) advertising->start();
  else if (!wanted && advertising->isAdvertising()) advertising->stop();
  static Record record;
  if (xQueueReceive(incoming, &record, 0) == pdTRUE && secured && record.generation == generation.load()) {
    cJSON* root = cJSON_Parse(record.text);
    const cJSON* tx = cJSON_GetObjectItemCaseSensitive(root, "tx");
    uint32_t sequence = cJSON_IsNumber(tx) && tx->valuedouble >= 1 && tx->valuedouble <= UINT32_MAX
                        ? uint32_t(tx->valuedouble) : 0;
    bool applied = sequence && (!record.hid || record.tx == sequence) && habitatReceive(root, true);
    cJSON_Delete(root);
    // Five bytes fit even the minimum BLE MTU. Echo tx so a stale ACK cannot
    // acknowledge the next snapshot after a timeout or reconnect.
    uint8_t ack[5] = {uint8_t(applied ? 0 : 1), uint8_t(sequence), uint8_t(sequence >> 8),
                      uint8_t(sequence >> 16), uint8_t(sequence >> 24)};
    if (applied) lastHid = record.hid;
    if (record.hid) {
      uint8_t report[8] = {0xC1,ack[0],ack[1],ack[2],ack[3],ack[4],1,0};
      setHidStatus(ack[0], record.tx);
      hidReplies->setValue(report, sizeof(report));
      hidReplies->notify(record.connection);
    } else {
      replies->setValue(ack, sizeof(ack));
      replies->notify(record.connection);
    }
  }
}

void bluetoothSleep()
{
  if (!server) return;
  NimBLEDevice::getAdvertising()->stop();
  for (auto peer : server->getPeerDevices()) server->disconnect(peer);
  NimBLEDevice::deinit(false); // Stop radio; retain objects until deep sleep discards RAM. Bonds stay in NVS.
  server = nullptr;
}
