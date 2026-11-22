"""Read public policy documents without browser credentials or private-network access."""

import http.client
import ipaddress
import re
import socket
import ssl
from html.parser import HTMLParser
from time import monotonic
from urllib.parse import quote, unquote, urljoin, urlsplit

from .report_formats import ReportFormatError, pdf_sections


HOSTNAME = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}$", re.I)
POLICY_PATH = re.compile(r"(?:privacy|data[-_ ]protection|terms|conditions|user[-_ ]agreement)", re.I)
MAX_PAGE = 1024 * 1024
TLS_CONTEXT = ssl.create_default_context()
PATH_SAFE = "/%:@!$&'()*+,;=-._~"


class PageUnavailable(RuntimeError):
    pass


def public_url(value, *, homepage=False):
    if not isinstance(value, str) or not value.strip() or len(value) > 1200:
        raise ValueError("Enter a public website hostname or HTTPS URL.")
    value = value.strip()
    if "\\" in value or any(ord(char) < 33 for char in value):
        raise ValueError("Enter a public website hostname or HTTPS URL.")
    try:
        parts = urlsplit(value if "://" in value else f"https://{value}")
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        port = parts.port
    except (ValueError, UnicodeError):
        raise ValueError("Enter a public website hostname or HTTPS URL.") from None
    if (parts.scheme != "https" or parts.username is not None or port not in (None, 443)
            or len(host) > 253 or not HOSTNAME.fullmatch(host)):
        raise ValueError("The website must use HTTPS on a public hostname.")
    if host.endswith((".localhost", ".local", ".internal", ".home.arpa", ".test", ".invalid")):
        raise ValueError("The website must use HTTPS on a public hostname.")
    path = "/" if homepage else parts.path or "/"
    decoded = unquote(path)
    if len(path) > 350 or "\\" in decoded or any(ord(char) < 32 for char in decoded):
        raise ValueError("The public policy URL has an unsupported path.")
    return f"https://{host}{quote(path, safe=PATH_SAFE)}"


def public_addresses(host):
    addresses = list(dict.fromkeys(result[4][0] for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_loopback
                or getattr(ip, "ipv4_mapped", None) or getattr(ip, "scope_id", None)):
            raise PageUnavailable("A policy hostname resolved to a private or unsupported network address.")
    if not addresses:
        raise PageUnavailable("The policy hostname could not be resolved.")
    return addresses


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, 443, timeout=timeout, context=TLS_CONTEXT)
        self.address = address

    def connect(self):
        # Pin the validated address for the socket and validate TLS against the original hostname.
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = TLS_CONTEXT.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def download_page(url, deadline):
    url = public_url(url)
    for _ in range(3):
        parts = urlsplit(url)
        host = parts.hostname
        try:
            addresses = public_addresses(host)
            # Prefer IPv4 where available on machines without a routed IPv6 connection.
            address = next((ip for ip in addresses if ":" not in ip), addresses[0])
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise PageUnavailable("The website check reached its time limit.")
            connection = PublicHTTPSConnection(host, address, min(4, remaining))
            try:
                connection.request("GET", parts.path or "/", headers={
                    "Accept": "text/html, text/plain, application/xhtml+xml, application/pdf",
                    "Accept-Encoding": "identity",
                    "Accept-Language": "en-US,en;q=0.9",
                    "User-Agent": "GhostPrint policy reader (https://github.com/Shadowprofessor/Azkaban)",
                })
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308} and response.getheader("Location"):
                    url = public_url(urljoin(url, response.getheader("Location")))
                    continue
                if response.status != 200:
                    raise PageUnavailable(f"The public page returned HTTP {response.status}.")
                media = response.headers.get_content_type()
                if media not in {"text/html", "text/plain", "application/xhtml+xml", "application/pdf"}:
                    raise PageUnavailable("The public page did not return readable HTML, text, or PDF.")
                chunks = bytearray()
                while len(chunks) <= MAX_PAGE and monotonic() < deadline:
                    chunk = response.read1(min(64 * 1024, MAX_PAGE + 1 - len(chunks)))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                if len(chunks) > MAX_PAGE or monotonic() >= deadline:
                    raise PageUnavailable("The public page exceeded the local reading limit.")
                if media == "application/pdf":
                    try:
                        text = "\n".join(line for _, line in pdf_sections(bytes(chunks)))
                    except ReportFormatError as exc:
                        raise PageUnavailable(str(exc)) from None
                    return url, "text/plain", text
                charset = response.headers.get_content_charset() or "utf-8"
                try:
                    text = chunks.decode(charset, errors="replace")
                except LookupError:
                    text = chunks.decode("utf-8", errors="replace")
                return url, media, text
            finally:
                connection.close()
        except (OSError, http.client.HTTPException):
            raise PageUnavailable("Could not read the public page over HTTPS.") from None
        except ValueError:
            raise PageUnavailable("The public page redirected to an unsupported address.") from None
    raise PageUnavailable("The public page redirected too many times.")


def doc_kind(url, label=""):
    path = unquote(urlsplit(url).path).lower().replace("_", "-")
    label = " ".join(label.lower().split()).strip(" .")
    if re.search(r"/(?:cookie-settings|privacy-settings|privacy-preferences|compare-privacy)(?:/|$)", path):
        return None
    if re.fullmatch(r"(?:terms(?: of (?:service|use))?|terms and conditions|user agreement)", label):
        return "Terms"
    if re.fullmatch(r"(?:privacy (?:policy|notice|statement)|data protection policy)", label):
        return "Privacy policy"
    if re.search(r"/(?:terms(?:-of-(?:service|use)|-and-conditions)?|termsandconditions|user-agreement)(?:[/.]|$)", path):
        return "Terms"
    if re.search(r"/(?:privacy(?:-policy|-notice|-statement)?|privacypolicy|data-protection)(?:[/.]|$)", path):
        return "Privacy policy"
    return None


class PolicyPage(HTMLParser):
    HEADINGS = {"title", "h1", "h2", "h3", "h4", "h5"}
    BLOCK = HEADINGS | {"p", "div", "li", "tr", "td", "th", "section", "br", "main"}

    def __init__(self, base, media, text):
        super().__init__(convert_charrefs=True)
        self.url = base
        self.blocks = []
        self.links = []
        self._anchor = None
        self._blocked = 0
        self._chunks = []
        self._heading = False
        self._navigation = 0
        if media == "text/plain":
            self.blocks = [(False, line.strip()) for line in text.splitlines() if line.strip()]
        else:
            self.feed(text)
            self.flush()

    def flush(self):
        text = " ".join("".join(self._chunks).split())
        if text:
            self.blocks.append((self._heading, text))
        self._chunks.clear()

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "template", "noscript"}:
            self._blocked += 1
        if self._blocked:
            return
        if tag in self.BLOCK:
            self.flush()
            self._heading = tag in self.HEADINGS
        if tag in {"nav", "footer", "header"}:
            self.flush()
            self._navigation += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href and len(href) < 800:
                self._anchor = (href, [])

    def handle_endtag(self, tag):
        if tag in {"script", "style", "template", "noscript"} and self._blocked:
            self._blocked -= 1
            return
        if self._blocked:
            return
        if tag in self.BLOCK:
            self.flush()
            self._heading = False
        if tag in {"nav", "footer", "header"} and self._navigation:
            self._navigation -= 1
        if tag == "a" and self._anchor:
            href, label = self._anchor
            self._anchor = None
            try:
                url = public_url(urljoin(self.url, href))
                kind = doc_kind(url, " ".join(label))
            except ValueError:
                return
            if kind and POLICY_PATH.search(urlsplit(url).path):
                self.links.append((kind, url))

    def handle_data(self, text):
        if self._blocked:
            return
        if not self._navigation:
            self._chunks.append(text)
        if self._anchor:
            self._anchor[1].append(text)
