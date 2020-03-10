"""CIP Client"""

# Standard Imports
import binascii
import logging
import queue
import socket
import threading
import time


_logger = logging.getLogger(__name__)


class SendThread(threading.Thread):
    """This thread processes outgoing CIP packets and generates heartbeat packets."""

    def __init__(self, cip):
        """Sets up the CIP outgoing packet processing thread."""
        self._stopEvent = threading.Event()
        self.cip = cip
        threading.Thread.__init__(self, name="Send")

    def run(self):
        """Starts the CIP outgoing packet processing thread."""
        _logger.debug("started")

        timeSlept = 0

        while not self._stopEvent.is_set():
            while not self.cip.tx_queue.empty():
                tx = self.cip.tx_queue.get()
                _logger.debug(f"TX: <{str(binascii.hexlify(tx), 'ascii')}>")
                self.cip.socket.sendall(tx)
                timeSlept = 0

            time.sleep(0.01)

            if self.cip.connected:
                timeSlept += 0.01
                if timeSlept >= 15:
                    self.cip.tx_queue.put(b"\x0D\x00\x02\x00\x00")
                    timeSlept = 0

        _logger.debug("stopped")

    def join(self, timeout=None):
        """Stops the CIP outgoing packet processing thread."""
        self._stopEvent.set()
        threading.Thread.join(self, timeout)


class ReceiveThread(threading.Thread):
    def __init__(self, cip):
        self._stopEvent = threading.Event()
        self.cip = cip
        threading.Thread.__init__(self, name="Receive")

    def run(self):
        _logger.debug("started")

        while not self._stopEvent.is_set():
            try:
                rx = self.cip.socket.recv(4096)
                _logger.debug(f'RX: <{str(binascii.hexlify(rx), "ascii")}>')

                position = 0
                length = len(rx)

                while position < length:
                    if (length - position) < 4:
                        _logger.warning("Packet is too short")
                        break

                    payloadLength = (rx[position + 1] << 8) + rx[position + 2]
                    packetLength = payloadLength + 3

                    if (length - position) < packetLength:
                        _logger.warning("Packet length mismatch")
                        break

                    packetType = rx[position]
                    payload = rx[position + 3 : position + 3 + payloadLength]

                    self.cip.processPayload(packetType, payload)
                    position += packetLength

            except socket.timeout as e:
                if e.args[0] == "timed out":
                    pass
                    # _logger.debug("nothing received")

        _logger.debug("stopped")

    def join(self, timeout=None):
        self._stopEvent.set()
        threading.Thread.join(self, timeout)


class EventThread(threading.Thread):
    def __init__(self, cip):
        self._stopEvent = threading.Event()
        self.cip = cip
        threading.Thread.__init__(self, name="Event")

    def run(self):
        _logger.debug("started")

        while not self._stopEvent.is_set():
            if not self.cip.event_queue.empty():
                direction, sigType, join, value = self.cip.event_queue.get()
                with self.cip.txLock:
                    try:
                        self.cip.join[direction][sigType][join][0] = value
                        for callback in self.cip.join[direction][sigType][join][1:]:
                            callback(value)
                    except KeyError:
                        self.cip.join[direction][sigType][join] = [
                            value,
                        ]
                _logger.debug(f"  : {sigType} {direction} {join} = {value}")

                if direction == "out":
                    tx = bytearray(self.cip.cipPacket[sigType])
                    join -= 1
                    if sigType == "d":
                        packedJoin = (join // 256) + ((join % 256) * 256)
                        if value == 0:
                            packedJoin |= 0x80
                        tx += packedJoin.to_bytes(2, "big")
                    elif sigType == "a":
                        tx += join.to_bytes(2, "big")
                        tx += value.to_bytes(2, "big")
                    elif sigType == "s":
                        tx[2] = 8 + len(value)
                        tx[6] = 4 + len(value)
                        tx += bytearray(value, "ascii")

                    self.cip.tx_queue.put(tx)

            time.sleep(0.001)

        _logger.debug("stopped")

    def join(self, timeout=None):
        self._stopEvent.set()
        threading.Thread.join(self, timeout)


class ConnectionThread(threading.Thread):
    def __init__(self, cip):
        self._stopEvent = threading.Event()
        self.cip = cip
        threading.Thread.__init__(self, name="Connection")

    def run(self):
        _logger.debug("started")

        warningPosted = False

        while not self._stopEvent.is_set():

            try:
                self.cip.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.cip.socket.settimeout(self.cip.timeout)
                self.cip.socket.connect((self.cip.host, self.cip.port))
            except socket.error:
                self.cip.socket.close()
                if warningPosted is False:
                    _logger.debug(
                        f"attempting to connect to {self.cip.host}:{self.cip.port}, "
                        "no success yet"
                    )
                    warningPosted = True
                if not self._stopEvent.is_set():
                    time.sleep(1)
            else:
                warningPosted = False
                _logger.debug(f"connected to host {self.cip.host}:{self.cip.port}")
                self.cip.eventThread.start()
                self.cip.sendThread.start()
                self.cip.receiveThread.start()
                while not self._stopEvent.is_set():
                    time.sleep(1)
                self.cip.sendThread.join()
                self.cip.eventThread.join()
                self.cip.receiveThread.join()

        self.cip.socket.close()

        _logger.debug("stopped")

    def join(self, timeout=None):
        self._stopEvent.set()
        threading.Thread.join(self, timeout)


class CIPSocketClient:
    cipPacket = {
        "d": b"\x05\x00\x06\x00\x00\x03\x00",
        "a": b"\x05\x00\x08\x00\x00\x05\x14",
        "s": b"\x12\x00\x00\x00\x00\x00\x00\x34\x00\x00\x03",
    }

    def __init__(self, host, ipid, port=41794, timeout=2):
        self.host = host
        self.ipid = ipid.to_bytes(length=1, byteorder="big")
        self.port = port
        self.timeout = timeout
        self.socket = None
        self.connected = False

        self.txLock = threading.Lock()
        self.sendThread = SendThread(self)
        self.receiveThread = ReceiveThread(self)
        self.eventThread = EventThread(self)
        self.connectionThread = ConnectionThread(self)

        self.tx_queue = queue.Queue()
        self.rx_queue = queue.Queue()
        self.event_queue = queue.Queue()

        self.join = {
            "in": {"d": {}, "a": {}, "s": {}},
            "out": {"d": {}, "a": {}, "s": {}},
        }

    def start(self):
        if self.connectionThread.is_alive():
            _logger.error("start() called while already running")
        else:
            _logger.debug("start requested")
            self.connectionThread.start()

    def stop(self):
        if not self.connectionThread.is_alive():
            _logger.error("stop() called while already stopped")
        else:
            _logger.debug("stop requested")
            self.connectionThread.join()

    def set(self, sigType, join, value):
        if sigType == "d":
            if (value != 0) and (value != 1):
                _logger.error(f"set(): '{value}' is not a valid digital signal state")
                return
        elif sigType == "a":
            if (type(value) is not int) or (value > 65535):
                _logger.error(f"set(): '{value}' is not a valid analog signal value")
                return
        elif sigType == "s":
            value = str(value)
        else:
            _logger.debug(f"set(): '{sigType}' is not a valid signal type")
            return

        self.event_queue.put(("out", sigType, join, value))

    def get(self, sigType, join, direction="in"):
        if (direction != "in") and (direction != "out"):
            raise ValueError(f"get(): '{direction}' is not a valid signal direction")
        if (sigType != "d") and (sigType != "a") and (sigType != "s"):
            raise ValueError(f"get(): '{sigType}' is not a valid signal type")

        with self.txLock:
            try:
                value = self.join[direction][sigType][join][0]
            except KeyError:
                if sigType == "s":
                    value = ""
                else:
                    value = 0
        return value

    def subscribe(self, sigType, join, callback, direction="in"):
        if (direction != "in") and (direction != "out"):
            raise ValueError(
                f"subscribe(): '{direction}' is not a valid signal direction"
            )
        if (sigType != "d") and (sigType != "a") and (sigType != "s"):
            raise ValueError(f"subscribe(): '{sigType}' is not a valid signal type")

        with self.txLock:
            if join not in self.join[direction][sigType]:
                if sigType == "s":
                    value = ""
                else:
                    value = 0
                self.join[direction][sigType][join] = [
                    value,
                ]
            self.join[direction][sigType][join].append(callback)

    def processPayload(self, cipType, payload):
        _logger.debug(
            f'> Type 0x{cipType:02x} <{str(binascii.hexlify(payload), "ascii")}>'
        )
        length = len(payload)

        if cipType == 0x0D or cipType == 0x0E:
            # heartbeat
            _logger.debug("  Heartbeat")
        elif cipType == 0x05:
            # data
            dataType = payload[3]

            if dataType == 0x00:
                # digital join
                join = (((payload[5] & 0x7F) << 8) | payload[4]) + 1
                state = ((payload[5] & 0x80) >> 7) ^ 0x01
                self.event_queue.put(("in", "d", join, state))
                _logger.debug(f"  Incoming Digital Join {join:04} = {state}")
            elif dataType == 0x14:
                join = ((payload[4] << 8) | payload[5]) + 1
                value = (payload[6] << 8) + payload[7]
                self.event_queue.put(("in", "a", join, value))
                _logger.debug(f"  Incoming Analog Join {join:04} = {value}")
            elif dataType == 0x03:
                # update request
                updateRequestType = payload[4]
                if updateRequestType == 0x00:
                    # standard update request
                    _logger.debug("  Standard update request")
                elif updateRequestType == 0x16:
                    # penultimate update request
                    _logger.debug("  Mysterious penultimate update-response")
                elif updateRequestType == 0x1C:
                    # end-of-query
                    _logger.debug("  End-of-query")
                    self.tx_queue.put(b"\x05\x00\x05\x00\x00\x02\x03\x1d")
                    self.tx_queue.put(b"\x0D\x00\x02\x00\x00")
                    self.connected = True
                elif updateRequestType == 0x1D:
                    # end-of-query acknowledgement
                    _logger.debug("  End-of-query acknowledgement")
                else:
                    # unexpected update request packet
                    _logger.debug("! We don't know what to do with this update request")
            elif dataType == 0x08:
                # date/time
                cipDate = str(binascii.hexlify(payload[4:]), "ascii")
                _logger.debug(
                    f"  Received date/time from control processor <"
                    f"{cipDate[2:4]}:{cipDate[4:6]}:"
                    f"{cipDate[6:8]} {cipDate[8:10]}/{cipDate[10:12]}/20{cipDate[12:]}>"
                )
            else:
                # unexpected data packet
                _logger.debug("! We don't know what to do with this data")
        elif cipType == 0x12:
            join = ((payload[5] << 8) | payload[6]) + 1
            value = str(payload[8:], "ascii")
            self.event_queue.put(("in", "s", join, value))
            _logger.debug(f"  Incoming Serial Join {join:04} = {value}")
        elif cipType == 0x0F:
            # registration request
            _logger.debug("  Client registration request")
            tx = (
                b"\x01\x00\x0b\x00\x00\x00\x00\x00"
                + self.ipid
                + b"\x40\xff\xff\xf1\x01"
            )
            self.tx_queue.put(tx)
        elif cipType == 0x02:
            # registration result
            ipidString = str(binascii.hexlify(self.ipid), "ascii")

            if length == 3 and payload == b"\xff\xff\x02":
                _logger.error(f"! The specified IPID (0x{ipidString}) does not exist")
            elif length == 4 and payload == b"\x00\x00\x00\x1f":
                _logger.debug(f"  Registered IPID 0x{ipidString}")
                self.tx_queue.put(b"\x05\x00\x05\x00\x00\x02\x03\x00")
            else:
                _logger.error(f"! Error registering IPID 0x{ipidString}")
                # this is a problem - restart connection
        elif cipType == 0x03:
            # control system disconnect
            _logger.debug("! Control system disconnect")
            # at this point we will have to restart the connection
        else:
            # unexpected packet
            _logger.debug("! We don't know what to do with this packet")
