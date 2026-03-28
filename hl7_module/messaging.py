"""
HL7 v2 messaging over MLLP (Minimal Lower Layer Protocol).
Supports sending and receiving HL7 messages.
"""

import socket
import threading
import logging
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# MLLP framing characters
MLLP_START = b'\x0b'
MLLP_END   = b'\x1c\x0d'

HL7_AVAILABLE = True
try:
    import hl7 as hl7lib
except ImportError:
    HL7_AVAILABLE = False


def check_available():
    if not HL7_AVAILABLE:
        raise RuntimeError("hl7 library not installed.\nRun: pip install hl7")


def wrap_mllp(message: str) -> bytes:
    """Wrap HL7 message in MLLP framing."""
    return MLLP_START + message.encode("latin-1") + MLLP_END


def unwrap_mllp(data: bytes) -> str:
    """Remove MLLP framing and return the HL7 message string."""
    if data.startswith(MLLP_START):
        data = data[1:]
    if data.endswith(MLLP_END):
        data = data[:-2]
    return data.decode("latin-1", errors="replace")


def format_raw_bytes(data: bytes, label: str = "") -> str:
    """
    Format a raw byte buffer for debug display.

    Printable ASCII characters are shown as-is. Everything else —
    including the MLLP framing bytes (0x0B, 0x1C, 0x0D) and any other
    control/non-ASCII bytes — is shown as <0xNN> so nothing is invisible.

    Example output:
      TX (47 bytes):
      <0x0B>MSH|^~\\&|SEND|FAC|REC|FAC|...<CR><0x1C><0x0D>

    Carriage returns (0x0D = \\r) inside the HL7 message are shown as <CR>
    so segment boundaries are visible without breaking the log line.
    """
    parts = []
    for byte in data:
        if byte == 0x0D:
            parts.append("<CR>")          # HL7 segment separator — show explicitly
        elif byte == 0x0B:
            parts.append("<0x0B>")        # MLLP start-of-block
        elif byte == 0x1C:
            parts.append("<0x1C>")        # MLLP end-of-block
        elif 0x20 <= byte <= 0x7E:
            parts.append(chr(byte))       # printable ASCII — show as-is
        else:
            parts.append(f"<0x{byte:02X}>")  # everything else as hex
    prefix = f"{label} ({len(data)} bytes):\n  " if label else ""
    return prefix + "".join(parts)


def send_hl7(host: str, port: int, message: str,
             timeout: int = 10,
             debug_callback: Optional[Callable] = None) -> tuple[bool, str]:
    """
    Send an HL7 message via MLLP and return the ACK.

    debug_callback: if provided, called with a formatted string showing
                    the raw bytes sent and received (including MLLP framing).
    Returns (success, ack_message_or_error)
    """
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            raw_out = wrap_mllp(message)

            # Log what we're about to send before actually sending
            if debug_callback:
                debug_callback(format_raw_bytes(raw_out, "TX"))

            sock.sendall(raw_out)

            # Read response
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if MLLP_END in response:
                    break

            # Log what we received
            if debug_callback:
                debug_callback(format_raw_bytes(response, "RX"))

            ack = unwrap_mllp(response)
            return True, ack
    except socket.timeout:
        return False, f"Connection timed out after {timeout}s"
    except ConnectionRefusedError:
        return False, f"Connection refused to {host}:{port}"
    except Exception as e:
        return False, str(e)


def parse_hl7(message: str) -> dict:
    """Parse HL7 message into a dict of segment -> fields."""
    result = {}
    for line in message.strip().split("\r"):
        if not line:
            continue
        parts = line.split("|")
        seg = parts[0]
        result[seg] = parts
    return result


def format_hl7_display(message: str) -> str:
    """Format HL7 message for display with segment labels."""
    lines = []
    for seg in message.strip().split("\r"):
        if seg:
            lines.append(seg)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HL7 MLLP Listener
# ---------------------------------------------------------------------------

class HL7Listener:
    """Simple MLLP TCP server to receive HL7 messages."""

    def __init__(self, port: int, callback: Optional[Callable] = None,
                 debug_callback: Optional[Callable] = None):
        self.port = port
        self.callback = callback
        # debug_callback receives formatted raw-byte strings when enabled
        self.debug_callback = debug_callback
        self._sock = None
        self._thread = None
        self.running = False
        self.received_messages = []

    def _handle_client(self, conn, addr):
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if MLLP_END in data:
                    break
            if data:
                # Log raw received bytes if debug is on
                if self.debug_callback:
                    self.debug_callback(format_raw_bytes(data, f"RX from {addr[0]}:{addr[1]}"))

                msg = unwrap_mllp(data)
                self.received_messages.append({
                    "timestamp": datetime.now().isoformat(),
                    "from": str(addr),
                    "message": msg
                })
                if self.callback:
                    self.callback(msg, addr)

                # Build and send ACK
                ack = self._build_ack(msg)
                raw_ack = wrap_mllp(ack)

                # Log raw ACK bytes if debug is on
                if self.debug_callback:
                    self.debug_callback(format_raw_bytes(raw_ack, f"TX ACK to {addr[0]}:{addr[1]}"))

                conn.sendall(raw_ack)
        except Exception as e:
            logger.error(f"HL7 client error: {e}")
        finally:
            conn.close()

    def _build_ack(self, message: str) -> str:
        """Build a simple AA ACK, swapping sender/receiver from the incoming MSH."""
        now = datetime.now().strftime("%Y%m%d%H%M%S")
        lines = message.strip().split("\r")
        ctrl_id = "UNKNOWN"
        # Default to the incoming message's receiving fields (i.e. us)
        send_app = ""
        send_fac = ""
        recv_app = ""
        recv_fac = ""
        for line in lines:
            if line.startswith("MSH"):
                parts = line.split("|")
                ctrl_id = parts[9] if len(parts) > 9 else "UNKNOWN"
                # Swap: our ACK's sender = incoming receiver, and vice-versa
                recv_app = parts[2] if len(parts) > 2 else ""
                recv_fac = parts[3] if len(parts) > 3 else ""
                send_app = parts[4] if len(parts) > 4 else ""
                send_fac = parts[5] if len(parts) > 5 else ""
                break
        return (
            f"MSH|^~\\&|{send_app}|{send_fac}|{recv_app}|{recv_fac}|{now}||ACK|{now}|P|2.3\r"
            f"MSA|AA|{ctrl_id}|Message received successfully\r"
        )

    def _run(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("", self.port))
        self._sock.listen(5)
        self._sock.settimeout(1.0)
        self.running = True
        while self.running:
            try:
                conn, addr = self._sock.accept()
                t = threading.Thread(target=self._handle_client,
                                     args=(conn, addr), daemon=True)
                t.start()
            except socket.timeout:
                continue
            except Exception:
                break
        self._sock.close()

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(f"HL7 listener started on port {self.port}")

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("HL7 listener stopped")


def send_mllp(host: str, port: int, message: str,
              debug_callback: Optional[Callable] = None):
    """
    Send an HL7 message via MLLP.
    debug_callback: if provided, receives formatted raw-byte strings for TX and RX.
    """
    try:
        ok, response = send_hl7(host, port, message, debug_callback=debug_callback)
        return ok, response
    except Exception as e:
        return False, str(e)
