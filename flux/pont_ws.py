"""Pont WebSocket -> socket : le relais Flux sur Cloudflare passe par des WebSocket (seul moyen d'y entrer), mais
tout le code du relais (et TLS par-dessus) travaille sur des sockets ordinaires.

ouvrir(url) renvoie une vraie socket (une moitié de socketpair) ; deux fils recopient les octets entre l'autre moitié
et la WebSocket (messages binaires). Pour le code qui l'utilise, c'est exactement une connexion TCP vers le relais.

Maintien en vie : le message texte « PING » part toutes les 30 s ; Cloudflare répond « PONG » sans réveiller le
relais. Sans réponse pendant 95 s, le pont ferme tout (la socket voit la fin de connexion et le code se reconnecte).

Même fichier dans Flux et Flux Remote (FluxLite a son équivalent Java : PontWs.java).
"""
import socket
import threading
import time

INTERVALLE_PING = 30
SILENCE_MAX = 95
TAMPON = 65536


class AdresseWs(tuple):
    """(hôte, port) d'un relais joint en WebSocket ; tls=False pour ws:// (essais locaux seulement)."""

    ws = True

    def __new__(cls, hote, port, tls=True):
        t = super().__new__(cls, (hote, port))
        t.tls = tls
        return t

    def url(self, cle):
        hote, port = self
        h = f"[{hote}]" if ":" in hote else hote
        defaut = 443 if self.tls else 80
        return f"{'wss' if self.tls else 'ws'}://{h}{'' if port == defaut else f':{port}'}/relais/{cle}"

    def texte(self):
        hote, port = self
        h = f"[{hote}]" if ":" in hote else hote
        defaut = 443 if self.tls else 80
        return f"{'wss' if self.tls else 'ws'}://{h}" + ("" if port == defaut else f":{port}")


def lire_adresse_ws(texte):
    """« wss://relais.exemple.be », « wss://x.workers.dev:443/relais », « ws://127.0.0.1:8787 » -> AdresseWs ou None."""
    import re
    t = str(texte or "").strip()
    bas = t.lower()
    if bas.startswith("wss://"):
        tls, t = True, t[6:]
    elif bas.startswith("ws://"):
        tls, t = False, t[5:]
    else:
        return None
    t = t.split("/")[0].strip()
    if not t:
        return None
    if t.startswith("["):
        hote, _, reste = t[1:].partition("]")
        port = reste[1:] if reste.startswith(":") else ""
    elif t.count(":") == 1:
        hote, port = t.split(":")
    else:
        hote, port = t, ""
    try:
        port = int(port) if port else (443 if tls else 80)
    except ValueError:
        return None
    if not hote or not 0 < port < 65536 or not re.fullmatch(r"[A-Za-z0-9.\-:]+", hote):
        return None
    return AdresseWs(hote, port, tls)


class Pont:
    def __init__(self, ws, local):
        self.ws = ws
        self.local = local
        self.ferme = threading.Event()
        self.dernier_pong = time.monotonic()

    def demarrer(self):
        for cible, nom in ((self._vers_local, "relais-ws-entree"), (self._vers_ws, "relais-ws-sortie"),
                           (self._maintien, "relais-ws-ping")):
            threading.Thread(target=cible, daemon=True, name=nom).start()

    def fermer(self):
        if self.ferme.is_set():
            return
        self.ferme.set()
        for f in (lambda: self.local.shutdown(socket.SHUT_RDWR), self.local.close, self.ws.close):
            try:
                f()
            except Exception:  # noqa: BLE001 - déjà fermé
                pass

    def _vers_local(self):
        import websocket
        try:
            while not self.ferme.is_set():
                op, donnees = self.ws.recv_data(control_frame=True)
                if op == websocket.ABNF.OPCODE_BINARY or op == websocket.ABNF.OPCODE_CONT:
                    if donnees:
                        self.local.sendall(donnees)
                elif op == websocket.ABNF.OPCODE_TEXT:
                    self.dernier_pong = time.monotonic()  # « PONG » de Cloudflare
                elif op == websocket.ABNF.OPCODE_PONG:
                    self.dernier_pong = time.monotonic()
                elif op == websocket.ABNF.OPCODE_CLOSE:
                    break
        except Exception:  # noqa: BLE001 - connexion coupée
            pass
        self.fermer()

    def _vers_ws(self):
        try:
            while not self.ferme.is_set():
                d = self.local.recv(TAMPON)
                if not d:
                    break
                self.ws.send_binary(d)
        except Exception:  # noqa: BLE001
            pass
        self.fermer()

    def _maintien(self):
        while not self.ferme.wait(INTERVALLE_PING):
            if time.monotonic() - self.dernier_pong > SILENCE_MAX:
                break
            try:
                self.ws.send("PING")
            except Exception:  # noqa: BLE001
                break
        self.fermer()


def _paire():
    """Deux sockets TCP reliées par la boucle locale (comme socketpair, mais TCP partout : TLS et les options de
    socket se comportent alors exactement comme sur une vraie connexion)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ecoute:
        ecoute.bind(("127.0.0.1", 0))
        ecoute.listen(1)
        a = socket.create_connection(ecoute.getsockname(), timeout=10)
        ecoute.settimeout(10)
        while True:
            b, origine = ecoute.accept()
            if origine == a.getsockname():
                break
            b.close()  # quelqu'un d'autre sur la boucle locale : refusé
    b.settimeout(None)
    for s in (a, b):
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return a, b


def ouvrir(adresse, cle, delai=15):
    """Ouvre wss://<relais>/relais/<cle> et renvoie une socket qui s'y rattache. Lève OSError si c'est impossible."""
    try:
        import websocket
    except ImportError:
        raise OSError("module « websocket-client » absent (il s'installe tout seul au prochain démarrage de Flux)") \
            from None
    try:
        ws = websocket.create_connection(adresse.url(cle), timeout=delai, enable_multithread=True,
                                         header=["User-Agent: Flux-relais"])
    except websocket.WebSocketBadStatusException as e:
        raise OSError(f"le relais refuse la connexion (HTTP {e.status_code})") from None
    except websocket.WebSocketException as e:
        raise OSError(str(e) or "connexion au relais impossible") from None
    ws.settimeout(None)
    a, b = _paire()
    Pont(ws, b).demarrer()
    a.settimeout(delai)
    return a
