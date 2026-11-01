"""TLS real em loopback: nao acessa Bitcoin mainnet nem servicos externos."""
import datetime
import json
import ssl
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from cartorio_documentos.lightning import CoreLightningREST
from cartorio_documentos.registry import RegistryError
from cartorio_documentos.security import atomic_private


class RestTransportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        current = datetime.datetime.now(datetime.timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(current - datetime.timedelta(minutes=1))
            .not_valid_after(current + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True).sign(key, hashes.SHA256()))
        cls.ca = cls.root / "ca.pem"
        cls.ca.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path = cls.root / "server.pem"
        atomic_private(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()))
        cls.rune = cls.root / "rune"
        atomic_private(cls.rune, b"synthetic-test-rune")
        cls.requests = []
        cls.redirect = False
        owner = cls

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.requests.append((self.path, self.headers.get("Rune"), body))
                if owner.redirect:
                    self.send_response(302)
                    self.send_header("Location", "/v1/unexpected")
                    self.end_headers()
                    return
                result = {"network": "bitcoin", "id": "02" + "11" * 32}
                raw = json.dumps(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cls.ca), str(key_path))
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"https://localhost:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.tmp.cleanup()

    def setUp(self):
        type(self).requests.clear()
        type(self).redirect = False

    def test_verified_https_sends_rune_header_and_json(self):
        client = CoreLightningREST(self.url, self.rune, self.ca, node_id="02" + "11" * 32)
        client.ensure_network("bitcoin")
        self.assertEqual(self.requests, [("/v1/getinfo", "synthetic-test-rune", {})])

    def test_untrusted_certificate_is_rejected(self):
        client = CoreLightningREST(self.url, self.rune, None)
        with self.assertRaises(RegistryError):
            client.call("getinfo")
        self.assertEqual(self.requests, [])

    def test_redirect_does_not_retransmit_rune(self):
        type(self).redirect = True
        client = CoreLightningREST(self.url, self.rune, self.ca)
        with self.assertRaises(RegistryError):
            client.call("getinfo")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0][0], "/v1/getinfo")

    def test_forbidden_financial_methods_never_reach_server(self):
        client = CoreLightningREST(self.url, self.rune, self.ca)
        for method in ("pay", "withdraw", "fundchannel", "close", "exposesecret", "createrune"):
            with self.subTest(method=method), self.assertRaises(RegistryError):
                client.call(method)
        self.assertEqual(self.requests, [])

    def test_wrong_node_identity_is_rejected(self):
        client = CoreLightningREST(self.url, self.rune, self.ca, node_id="03" + "22" * 32)
        with self.assertRaises(RegistryError):
            client.ensure_network("bitcoin")

    def test_invoice_gate_runs_before_any_http_request(self):
        def paused(amount):
            raise RegistryError("mainnet receiving paused")
        client = CoreLightningREST(self.url, self.rune, self.ca, invoice_gate=paused)
        with self.assertRaises(RegistryError):
            client.call("invoice", amount_msat="2500msat", label="cartorio-documento-test")
        self.assertEqual(self.requests, [])
