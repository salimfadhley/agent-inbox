"""This hub's signing key, and the public half peers read.

A hub proves who it is by signing the requests it makes. The key is generated once, kept
beside the mail, and never regenerated silently — a new key would make every peer that
had learned the old one stop believing us.

**Only the public half ever leaves.** It appears in actor documents so a peer can
verify us; the private half appears in no response, no log, no error and no audit
entry. The one mistake here that is silent and total is leaking it, so this type
redacts itself however it is printed.

RSA rather than Ed25519, and it is worth saying why: the fediverse's installed base
verifies RSA-SHA256, and a key nothing can check is decoration. The standing rule is to
do the most normal thing for the fediverse unless it conflicts with the goals of a
developer tool. It does not conflict here.
"""

from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

#: The size the fediverse settled on. Smaller is not interoperable; larger costs
#: signing time for no peer that asked.
KEY_BITS = 2048

#: Where the private half lives, in the settings the hub already keeps about itself.
PRIVATE_KEY_SETTING = "signing_key"


@dataclass(frozen=True, slots=True)
class SigningKey:
    """A hub's key. Holds the private half; never renders it."""

    private_pem: str

    def __repr__(self) -> str:
        """Never the key material, however this object is logged or asserted on."""
        return "SigningKey(<redacted>)"

    __str__ = __repr__

    @property
    def public_pem(self) -> str:
        """The half a peer reads, in the PEM shape actor documents carry."""
        private = serialization.load_pem_private_key(
            self.private_pem.encode(), password=None
        )
        return (
            private.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )

    def sign(self, message: bytes) -> bytes:
        """Sign bytes with RSA-SHA256, the shape the fediverse verifies."""
        private = serialization.load_pem_private_key(
            self.private_pem.encode(), password=None
        )
        if not isinstance(private, rsa.RSAPrivateKey):
            raise TypeError("this hub's signing key is not RSA")
        return private.sign(message, padding.PKCS1v15(), hashes.SHA256())


def generate() -> SigningKey:
    """Mint a key. Called once per hub, and never again by accident."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=KEY_BITS)
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return SigningKey(pem)


def verify(public_pem: str, message: bytes, signature: bytes) -> bool:
    """Whether `signature` is this key's signature over `message`.

    Returns False rather than raising on every failure — a bad signature, a malformed
    key, the wrong algorithm. **The caller must treat False as "refuse".** Any path
    through a verifier that ends in acceptance without a checked signature is the whole
    hole, so there is exactly one way to succeed here.
    """
    try:
        public = serialization.load_pem_public_key(public_pem.encode())
        if not isinstance(public, rsa.RSAPublicKey):
            return False
        public.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
    except Exception:
        # Deliberately broad: a verifier that distinguishes failure modes to its caller
        # invites one of them being handled as success.
        return False
    return True
