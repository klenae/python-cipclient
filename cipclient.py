"""A Python module for communicating with a Crestron control processor via CIP."""

# Standard Imports
import binascii
import logging
import queue
import socket
import threading
import time


_logger = logging.getLogger(__name__)


class SendThread(threading.Thread):
    """Process outgoing CIP packets and generates heartbeat packets."""

    def __init__(self, cip):
        """Set up the CIP outgoing packet processing thread."""
        self._stop_event = threading.Event()
        self.cip = cip
        threading.Thread.__init__(self, name="Send")

    def run(self):
        """Start the CIP outgoing packet processing thread."""
        _logger.debug("started")

        time_asleep_heartbeat = 0
        time_asleep_buttons = 0

        while not self._stop_event.is_set():
            while not self.cip.tx_queue.empty():
                tx = self.cip.tx_queue.get()
                if self.cip.restart_connection is False:
                    _logger.debug(f"TX: <{str(binascii.hexlify(tx), 'ascii')}>")
                    try:
                        self.cip.socket.sendall(tx)
                    except socket.error:
                        with self.cip.restart_lock:
                            self.cip.restart_connection = True
                    time_asleep_heartbeat = 0

            time.sleep(0.01)

            if self.cip.connected is True and self.cip.restart_connection is False:
                time_asleep_heartbeat += 0.01
                if time_asleep_heartbeat >= 15:
                    self.cip.tx_queue.put(b"\x0D\x00\x02\x00\x00")
                    time_asleep_heartbeat = 0

                time_asleep_buttons += 0.01
                if time_asleep_buttons >= 0.50 and len(self.cip.buttons_pressed):
                    with self.cip.buttons_lock:
                        for join in self.cip.buttons_pressed:
                            try:
                                if self.cip.join["out"]["d"][join][0] == 1:
                                    self.cip.tx_queue.put(
                                        self.cip.buttons_pressed[join]
                                    )
                            except KeyError:
                                pass
                    time_asleep_buttons = 0

        _logger.debug("stopped")

    def join(self, timeout=None):
        """Stop the CIP outgoing packet processing thread."""
        self._stop_event.set()
        threading.Thread.join(self, timeout)


class ReceiveThread(threading.Thread):
    """Process incoming CIP packets."""

    def __init__(self, cip):
        """Set up the CIP incoming packet processing thread."""
        self._stop_event = threading.Event()
        self.cip = cip
        threading.Thread.__init__(self, name="Receive")

    def run(self):
        """Start the CIP incoming packet processing thread."""
        _logger.debug("started")

        while not self._stop_event.is_set():
            try:
                if self.cip.restart_connection is False:
                    rx = self.cip.socket.recv(4096)
                    _logger.debug(f'RX: <{str(binascii.hexlify(rx), "ascii")}>')

                    position = 0
                    length = len(rx)

                    while position < length:
                        if (length - position) < 4:
                            _logger.warning("Packet is too short")
                            break

                        payload_length = (rx[position + 1] << 8) + rx[position + 2]
                        packet_length = payload_length + 3

                        if (length - position) < packet_length:
                            _logger.warning("Packet length mismatch")
                            break

                        packet_type = rx[position]
                        payload = rx[position + 3 : position + 3 + payload_length]

                        self.cip._processPayload(packet_type, payload)
                        position += packet_length
                else:
                    time.sleep(0.1)

            except (socket.error, socket.timeout) as e:
                if e.args[0] != "timed out":
                    with self.cip.restart_lock:
                        self.cip.restart_connection = True

        _logger.debug("stopped")

    def join(self, timeout=None):
        """Stop the CIP incoming packet processing thread."""
        self._stop_event.set()
        threading.Thread.join(self, timeout)


class EventThread(threading.Thread):
    """Process join event queue."""

    def __init__(self, cip):
        """Set up the join event processing thread."""
        self._stop_event = threading.Event()
        self.cip = cip
        threading.Thread.__init__(self, name="Event")

    def run(self):
        """Start the join event processing thread."""
        _logger.debug("started")

        while not self._stop_event.is_set():
            if not self.cip.event_queue.empty():
                direction, sigtype, join, value = self.cip.event_queue.get()

                with self.cip.join_lock:
                    try:
                        self.cip.join[direction][sigtype[0]][join][0] = value
                        for callback in self.cip.join[direction][sigtype[0]][join][1:]:
                            callback(sigtype[0], join, value)
                    except KeyError:
                        self.cip.join[direction][sigtype[0]][join] = [
                            value,
                        ]
                _logger.debug(f"  : {sigtype} {direction} {join} = {value}")

                if direction == "out":
                    tx = bytearray(self.cip._cip_packet[sigtype])
                    cip_join = join - 1
                    if sigtype[0] == "d":
                        packed_join = (cip_join // 256) + ((cip_join % 256) * 256)
                        if value == 0:
                            packed_join |= 0x80
                        tx += packed_join.to_bytes(2, "big")
                        if sigtype == "db":
                            with self.cip.buttons_lock:
                                if value == 1:
                                    self.cip.buttons_pressed[join] = tx
                                elif join in self.cip.buttons_pressed:
                                    self.cip.buttons_pressed.pop(join)
                    elif sigtype == "a":
                        tx += cip_join.to_bytes(2, "big")
                        tx += value.to_bytes(2, "big")
                    elif sigtype == "s":
                        tx[2] = 8 + len(value)
                        tx[6] = 4 + len(value)
                        tx += cip_join.to_bytes(2, "big")
                        tx += b"\x03"
                        tx += bytearray(value, "ascii")
                    if (
                        self.cip.connected is True
                        and self.cip.restart_connection is False
                    ):
                        self.cip.tx_queue.put(tx)

            time.sleep(0.001)

        _logger.debug("stopped")

    def join(self, timeout=None):
        """Stop the join event processing thread."""
        self._stop_event.set()
        threading.Thread.join(self, timeout)


class ConnectionThread(threading.Thread):
    """Manage the socket connection to the control processor."""

    def __init__(self, cip):
        """Set up the socket management thread."""
        self._stop_event = threading.Event()
        self.cip = cip
        threading.Thread.__init__(self, name="Connection")

    def run(self):
        """Start the socket management thread."""
        _logger.debug("started")

        warning_posted = False

        while not self._stop_event.is_set():

            try:
                self.cip.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.cip.socket.settimeout(self.cip.timeout)
                self.cip.socket.connect((self.cip.host, self.cip.port))
            except socket.error:
                self.cip.socket.close()
                if warning_posted is False:
                    _logger.debug(
                        f"attempting to connect to {self.cip.host}:{self.cip.port}, "
                        "no success yet"
                    )
                    warning_posted = True
                if not self._stop_event.is_set():
                    time.sleep(1)
            else:
                warning_posted = False
                _logger.debug(f"connected to {self.cip.host}:{self.cip.port}")
                if not self.cip.restart_connection:
                    self.cip.event_thread.start()
                    self.cip.send_thread.start()
                    self.cip.receive_thread.start()
                self.cip.restart_connection = False
                while (
                    not self._stop_event.is_set()
                    and self.cip.restart_connection is False
                ):
                    time.sleep(1)
                if not self._stop_event.is_set():
                    self.cip.connected = False
                    self.cip.socket.close()
                    _logger.debug(f"lost connection to {self.cip.host}:{self.cip.port}")
                else:
                    self.cip.send_thread.join()
                    self.cip.event_thread.join()
                    self.cip.receive_thread.join()

        self.cip.socket.close()

        _logger.debug("stopped")

    def join(self, timeout=None):
        """Stop the socket management thread."""
        self._stop_event.set()
        threading.Thread.join(self, timeout)


class CIPSocketClient:
    """Facilitate communications with a Crestron control processor via CIP."""

    _cip_packet = {
        "d": b"\x05\x00\x06\x00\x00\x03\x00",  # standard digital join
        "db": b"\x05\x00\x06\x00\x00\x03\x27",  # button-style digital join
        "dp": b"\x05\x00\x06\x00\x00\x03\x27",  # pulse-style digital join
        "a": b"\x05\x00\x08\x00\x00\x05\x14",  # analog join
        "s": b"\x12\x00\x00\x00\x00\x00\x00\x34",  # serial join
    }

    def __init__(self, host, ipid, port=41794, timeout=2):
        """Set up CIP client instance."""
        self.host = host
        self.ipid = ipid.to_bytes(length=1, byteorder="big")
        self.port = port
        self.timeout = timeout
        self.socket = None
        self.connected = False
        self.restart_lock = threading.Lock()
        self.restart_connection = False
        self.buttons_pressed = {}
        self.buttons_lock = threading.Lock()

        self.send_thread = SendThread(self)
        self.receive_thread = ReceiveThread(self)
        self.event_thread = EventThread(self)
        self.connection_thread = ConnectionThread(self)

        self.tx_queue = queue.Queue()
        self.event_queue = queue.Queue()

        self.join_lock = threading.Lock()
        self.join = {
            "in": {"d": {}, "a": {}, "s": {}},
            "out": {"d": {}, "a": {}, "s": {}},
        }

    def start(self):
        """Start the CIP client instance."""
        if self.connection_thread.is_alive():
            _logger.error("start() called while already running")
        else:
            _logger.debug("start requested")
            self.connection_thread.start()

    def stop(self):
        """Stop the CIP client instance."""
        if not self.connection_thread.is_alive():
            _logger.error("stop() called while already stopped")
        else:
            _logger.debug("stop requested")
            self.connection_thread.join()

    def set(self, sigtype, join, value):
        """Set an outgoing join."""
        if sigtype == "d":
            if (value != 0) and (value != 1):
                _logger.error(f"set(): '{value}' is not a valid digital signal state")
                return
        elif sigtype == "a":
            if (type(value) is not int) or (value > 65535):
                _logger.error(f"set(): '{value}' is not a valid analog signal value")
                return
        elif sigtype == "s":
            value = str(value)
        else:
            _logger.debug(f"set(): '{sigtype}' is not a valid signal type")
            return

        self.event_queue.put(("out", sigtype, join, value))

    def press(self, join):
        """Set a digital output join to the active state using CIP button logic."""
        self.event_queue.put(("out", "db", join, 1))

    def release(self, join):
        """Set a digital output join to the inactive state using CIP button logic."""
        self.event_queue.put(("out", "db", join, 0))

    def pulse(self, join):
        """Generate an active-inactive pulse on the specified digital output join."""
        self.event_queue.put(("out", "dp", join, 1))
        self.event_queue.put(("out", "dp", join, 0))

    def get(self, sigtype, join, direction="in"):
        """Get the current value of a join."""
        if (direction != "in") and (direction != "out"):
            raise ValueError(f"get(): '{direction}' is not a valid signal direction")
        if (sigtype != "d") and (sigtype != "a") and (sigtype != "s"):
            raise ValueError(f"get(): '{sigtype}' is not a valid signal type")

        with self.join_lock:
            try:
                value = self.join[direction][sigtype][join][0]
            except KeyError:
                if sigtype == "s":
                    value = ""
                else:
                    value = 0
        return value

    def update_request(self):
        """Send an update request to the control processor."""
        if self.connected is True:
            self.tx_queue.put(b"\x05\x00\x05\x00\x00\x02\x03\x00")
        else:
            _logger.debug("update_request(): not currently connected")

    def subscribe(self, sigtype, join, callback, direction="in"):
        """Subscribe to join change events by specifying callback functions."""
        if (direction != "in") and (direction != "out"):
            raise ValueError(
                f"subscribe(): '{direction}' is not a valid signal direction"
            )
        if (sigtype != "d") and (sigtype != "a") and (sigtype != "s"):
            raise ValueError(f"subscribe(): '{sigtype}' is not a valid signal type")

        with self.join_lock:
            if join not in self.join[direction][sigtype]:
                if sigtype == "s":
                    value = ""
                else:
                    value = 0
                self.join[direction][sigtype][join] = [
                    value,
                ]
            self.join[direction][sigtype][join].append(callback)

    def _processPayload(self, ciptype, payload):
        """Process CIP packets."""
        _logger.debug(
            f'> Type 0x{ciptype:02x} <{str(binascii.hexlify(payload), "ascii")}>'
        )
        length = len(payload)

        if ciptype == 0x0D or ciptype == 0x0E:
            # heartbeat
            _logger.debug("  Heartbeat")
        elif ciptype == 0x05:
            # data
            datatype = payload[3]

            if datatype == 0x00:
                # digital join
                join = (((payload[5] & 0x7F) << 8) | payload[4]) + 1
                state = ((payload[5] & 0x80) >> 7) ^ 0x01
                self.event_queue.put(("in", "d", join, state))
                _logger.debug(f"  Incoming Digital Join {join:04} = {state}")
            elif datatype == 0x14:
                join = ((payload[4] << 8) | payload[5]) + 1
                value = (payload[6] << 8) + payload[7]
                self.event_queue.put(("in", "a", join, value))
                _logger.debug(f"  Incoming Analog Join {join:04} = {value}")
            elif datatype == 0x03:
                # update request
                update_request_type = payload[4]
                if update_request_type == 0x00:
                    # standard update request
                    _logger.debug("  Standard update request")
                elif update_request_type == 0x16:
                    # penultimate update request
                    _logger.debug("  Mysterious penultimate update-response")
                elif update_request_type == 0x1C:
                    # end-of-query
                    _logger.debug("  End-of-query")
                    self.tx_queue.put(b"\x05\x00\x05\x00\x00\x02\x03\x1d")
                    self.tx_queue.put(b"\x0D\x00\x02\x00\x00")
                    self.connected = True
                    with self.join_lock:
                        for sigtype, joins in self.join["out"].items():
                            for j in joins:
                                self.set(sigtype, j, joins[j][0])
                elif update_request_type == 0x1D:
                    # end-of-query acknowledgement
                    _logger.debug("  End-of-query acknowledgement")
                else:
                    # unexpected update request packet
                    _logger.debug("! We don't know what to do with this update request")
            elif datatype == 0x08:
                # date/time
                cip_date = str(binascii.hexlify(payload[4:]), "ascii")
                _logger.debug(
                    f"  Received date/time from control processor <"
                    f"{cip_date[2:4]}:{cip_date[4:6]}:"
                    f"{cip_date[6:8]} {cip_date[8:10]}/"
                    f"{cip_date[10:12]}/20{cip_date[12:]}>"
                )
            else:
                # unexpected data packet
                _logger.debug("! We don't know what to do with this data")
        elif ciptype == 0x12:
            join = ((payload[5] << 8) | payload[6]) + 1
            value = str(payload[8:], "ascii")
            self.event_queue.put(("in", "s", join, value))
            _logger.debug(f"  Incoming Serial Join {join:04} = {value}")
        elif ciptype == 0x0F:
            # registration request
            _logger.debug("  Client registration request")
            tx = (
                b"\x01\x00\x0b\x00\x00\x00\x00\x00"
                + self.ipid
                + b"\x40\xff\xff\xf1\x01"
            )
            self.tx_queue.put(tx)
        elif ciptype == 0x02:
            # registration result
            ipid_string = str(binascii.hexlify(self.ipid), "ascii")

            if length == 3 and payload == b"\xff\xff\x02":
                _logger.error(f"! The specified IPID (0x{ipid_string}) does not exist")
            elif length == 4 and payload == b"\x00\x00\x00\x1f":
                _logger.debug(f"  Registered IPID 0x{ipid_string}")
                self.tx_queue.put(b"\x05\x00\x05\x00\x00\x02\x03\x00")
            else:
                _logger.error(f"! Error registering IPID 0x{ipid_string}")
                # this is a problem - restart connection
        elif ciptype == 0x03:
            # control system disconnect
            _logger.debug("! Control system disconnect")
            # at this point we will have to restart the connection
        else:
            # unexpected packet
            _logger.debug("! We don't know what to do with this packet")
