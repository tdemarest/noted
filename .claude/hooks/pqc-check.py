#!/usr/bin/env python3
"""Cryptography gate: FIPS-approved and post-quantum (PQC) ready algorithms only.

Scans the repo's tracked and untracked-but-not-ignored source, config and manifest
files for cryptographic algorithms and libraries, and fails when it finds one that
is:

  broken     disallowed by NIST outright (MD5, SHA-1 for security, DES/3DES, RC4,
             ECB, RSA < 2048, DSA signing, SSL/TLS < 1.2, JWT alg "none")
  quantum    classical public-key crypto that a quantum computer breaks (RSA, ECDSA,
             ECDH, EdDSA, X25519/X448, finite-field DH, RS*/PS*/ES*/EdDSA JWTs).
             NIST IR 8547 (draft) deprecates these after 2030 and disallows them after 2035;
             use ML-KEM (FIPS 203), ML-DSA (FIPS 204) or SLH-DSA (FIPS 205), or a
             hybrid such as X25519MLKEM768.
  non-fips   not a FIPS-approved algorithm or module (ChaCha20, bcrypt/scrypt/argon2,
             libsodium/NaCl, pre-standard Kyber/Dilithium/SPHINCS+, a non-approved
             RNG for secrets, pure-JS/Python crypto libraries)

Advisory findings (BLAKE2/3, TLS 1.2, liboqs) print only with --all and never fail.
A classical key-agreement or signature finding in a file that also uses ML-KEM or
ML-DSA/SLH-DSA counts as one half of a hybrid and passes.

Exceptions, each with a reason (an exception without one fails):
  inline     `pqc-allow: <rule>[,<rule>] <reason>` in a comment on the same line or
             the line above (`*` matches every rule)
  .pqc-policy at the repo root:
               profile nist|cnsa2
               allow <rule|category|*> <path-glob> [until=YYYY-MM-DD] -- <reason>
             A `quantum` exception needs `until=` no later than 2035-12-31, and an
             expired one fails.
Python's `usedforsecurity=False` on a hashlib call exempts a weak hash on that line.

Profiles: `nist` (default) and `cnsa2` (NSA CNSA 2.0: also requires AES-256,
SHA-384/512, ML-KEM-1024 and ML-DSA-87).

Usage:
  pqc-check.py [--root DIR] [--profile nist|cnsa2] [--all] [--json] [--list-rules]

Exit codes: 0 pass . 1 blocking findings . 2 usage or policy-file error
Stdlib only, Python 3.9+.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

QUANTUM_DISALLOWED = dt.date(2035, 12, 31)
POLICY_FILE = ".pqc-policy"
SELF = ".claude/hooks/pqc-check.py"

CODE_EXT = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".scala",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".m",
    ".mm",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".sql",
    ".tf",
    ".hcl",
}
CONFIG_EXT = {".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".conf", ".cnf", ".properties", ".xml"}
CONFIG_NAMES = {"Dockerfile", "Containerfile", "nginx.conf", "Caddyfile", "openssl.cnf"}
MANIFESTS = {"package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Gemfile", "composer.json"}
SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "coverage",
    ".next",
    ".vite",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".pyrefly",
    ".serena",
    "vendor",
    "target",
    ".project-init",
    "docs",
}
SKIP_NAMES = {
    "bun.lock",
    "bun.lockb",
    "uv.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
    POLICY_FILE,
}
MAX_BYTES = 1_000_000

FIX_KEM = "ML-KEM-768/1024 (FIPS 203), or hybrid X25519MLKEM768 in TLS 1.3"
FIX_SIG = "ML-DSA-65/87 (FIPS 204) or SLH-DSA (FIPS 205); LMS/XMSS (SP 800-208) for firmware"


@dataclass(frozen=True)
class Rule:
    id: str
    category: str  # broken | quantum | non-fips | advisory
    pattern: re.Pattern[str]
    message: str
    fix: str
    group: str = ""  # kex | sig | hash: lets a PQC marker in the file mark it hybrid
    scope: str = "all"  # all | manifest
    profile: str = ""  # "" = every profile; "cnsa2" = only that profile
    context: re.Pattern[str] | None = None  # must also match the line


def rx(p: str, flags: int = re.IGNORECASE) -> re.Pattern[str]:
    return re.compile(p, flags)


B = r"(?<![A-Za-z0-9])"  # left boundary that treats _ as a separator
E = r"(?![A-Za-z0-9])"

RULES: tuple[Rule, ...] = (
    # -- broken: disallowed by NIST regardless of quantum --
    Rule(
        "weak-hash",
        "broken",
        rx(B + r"(md[245]|sha-?1|sha_1)" + r"(?![0-9])"),
        "MD5/SHA-1 are not approved for security use (SHA-1 is being withdrawn: SP 800-131A)",
        "SHA-256/384/512 or SHA3; for non-security use in Python pass usedforsecurity=False",
        "hash",
    ),
    Rule(
        "weak-cipher",
        "broken",
        rx(
            r"['\"](des|des-cbc|des-ecb|des-ede3?(-cbc)?|des3|3des|rc2|rc4|bf-cbc|cast5-cbc|idea-cbc)['\"]"
            r"|\b(TripleDES|DES3|DESede|TDEA|ARC4|ARC2|Blowfish|CAST5|IDEA)\b|" + B + r"(rc4|arcfour|3des)" + E,
            re.IGNORECASE,
        ),
        "DES/3DES/RC4/RC2/Blowfish/CAST/IDEA are not approved (TDEA disallowed after 2023)",
        "AES-256-GCM",
    ),
    Rule(
        "ecb-mode",
        "broken",
        rx(r"modes\.ECB\b|MODE_ECB|['\"]aes-\d+-ecb['\"]|\bECB\b", 0),
        "ECB mode leaks plaintext structure",
        "AES-GCM (or AES-CCM / AES-KW for key wrapping)",
    ),
    Rule(
        "rsa-small-key",
        "broken",
        rx(r"\b(key_size|keysize|modulusLength|modulus_length|bits)\s*[=:]\s*(384|512|768|1024|1536)\b"),
        "RSA/DH below 2048 bits is disallowed",
        "ML-KEM / ML-DSA; RSA is quantum-vulnerable at any size",
        "kex",
    ),
    Rule(
        "dsa",
        "broken",
        rx(r"\bdsa\.generate_private_key|\bDSA\.(generate|new)\b|['\"]dsa['\"]|\bDSA_\w+"),
        "DSA signature generation is no longer approved (FIPS 186-5)",
        FIX_SIG,
        "sig",
    ),
    Rule(
        "legacy-tls",
        "broken",
        rx(r"\b(SSLv[23]|PROTOCOL_SSLv\d+|PROTOCOL_TLSv1(?:_1)?|TLSv1(?:[._][01])?)(?![._]?\d)"),
        "SSL and TLS 1.0/1.1 are disallowed (SP 800-52)",
        "TLS 1.3 (needed for PQC hybrid key exchange)",
    ),
    Rule(
        "jwt-none",
        "broken",
        rx(r"['\"]alg['\"]\s*:\s*['\"]none['\"]|algorithms?\s*=\s*\[?\s*['\"]none['\"]"),
        "unsigned JWTs (alg none)",
        "sign the token; HS256/384/512 with a 256-bit key, or ML-DSA",
    ),
    # -- quantum-vulnerable public-key crypto --
    Rule(
        "quantum-rsa",
        "quantum",
        rx(B + r"rsa" + E + r"|RSA_|RSASSA|\bOAEP\b|PKCS1v15"),
        "RSA is broken by a quantum computer (NIST IR 8547 draft: deprecated 2030, disallowed 2035)",
        f"key transport: {FIX_KEM}. Signatures: {FIX_SIG}",
        "kex,sig",
    ),
    Rule(
        "quantum-ecc",
        "quantum",
        rx(
            B
            + r"(ecdsa|ecdhe?|ecies|ecmqv|secp\d{3}[rk]1|prime256v1|brainpoolP\d+r1)"
            + E
            + r"|\bec\.(generate_private_key|SECP\w+|ECDH|ECDSA)\b|\bnamedCurve\b|\bP-(256|384|521)\b"
        ),
        "elliptic-curve DSA/DH is broken by a quantum computer (NIST IR 8547)",
        f"signatures: {FIX_SIG}. Key agreement: {FIX_KEM}",
        "kex,sig",
    ),
    Rule(
        "quantum-eddsa",
        "quantum",
        rx(B + r"(ed25519|ed448|eddsa)" + E),
        "EdDSA is FIPS 186-5 approved today but quantum-vulnerable (NIST IR 8547)",
        FIX_SIG,
        "sig",
    ),
    Rule(
        "quantum-x25519",
        "quantum",
        rx(B + r"(x25519|x448|curve25519|curve448)" + E),
        "X25519/X448 key agreement alone is quantum-vulnerable (harvest-now-decrypt-later)",
        FIX_KEM,
        "kex",
    ),
    Rule(
        "quantum-dh",
        "quantum",
        rx(
            r"diffie[-_ ]?hellman|\bdh\.generate_parameters|createDiffieHellman|getDiffieHellman|\bDHE-|"
            + B
            + r"(ffdhe\d+|modp\d+)"
            + E
        ),
        "finite-field Diffie-Hellman is quantum-vulnerable (NIST IR 8547)",
        FIX_KEM,
        "kex",
    ),
    Rule(
        "quantum-jwt",
        "quantum",
        rx(r"\b(RS|PS|ES)(256|384|512)\b|\bES256K\b|['\"]EdDSA['\"]", 0),
        "RSA/ECDSA/EdDSA-signed JWTs are quantum-vulnerable",
        "HS256+ for tokens this service both issues and verifies; ML-DSA (JOSE 'ML-DSA-65') where supported",
        "sig",
    ),
    # -- not FIPS-approved --
    Rule(
        "nonfips-cipher",
        "non-fips",
        rx(B + r"(x?chacha20(?:[-_]?poly1305)?|x?salsa20|poly1305)" + E),
        "ChaCha20/Salsa20/Poly1305 are not FIPS-approved",
        "AES-256-GCM",
    ),
    Rule(
        "nonfips-kdf",
        "non-fips",
        rx(B + r"(bcrypt|bcryptjs|scrypt|argon2(?:id|i|d)?|argon2-cffi)" + E),
        "bcrypt/scrypt/argon2 are not FIPS-approved password hashes",
        "PBKDF2-HMAC-SHA-256/512 (SP 800-132) with >= 600000 iterations and a 128-bit salt",
    ),
    Rule(
        "nonfips-lib",
        "non-fips",
        rx(B + r"(nacl|pynacl|tweetnacl|libsodium|sodium-native|libsodium-wrappers)" + E),
        "NaCl/libsodium use non-approved primitives (Curve25519, XSalsa20)",
        "a FIPS 140-3 validated module: OpenSSL 3 FIPS provider, AWS-LC, or the OS crypto",
    ),
    Rule(
        "nonfips-impl",
        "non-fips",
        rx(
            r"['\"]?\b(crypto-js|node-forge|jsencrypt|sjcl|elliptic|pycryptodomex?|pycrypto|rsa|ecdsa|tlslite-ng)\b['\"]?\s*"
            r"(:|[<>=~!;\[\"']|$)"
        ),
        "pure-JS/Python crypto implementation, not a FIPS 140-3 validated module",
        "Node `crypto` / WebCrypto, or Python `cryptography` on a FIPS-validated OpenSSL",
        scope="manifest",
    ),
    Rule(
        "nonfips-rng",
        "non-fips",
        rx(
            r"Math\.random\(\)|\brandom\."
            r"(random|randint|randrange|choice|choices|getrandbits|sample|shuffle)\("
        ),
        "non-cryptographic RNG used for a secret (SP 800-90A requires an approved DRBG)",
        "Python `secrets`; JS `crypto.getRandomValues` / `crypto.randomUUID`",
        context=rx(r"token|secret|nonce|salt|passw|otp|session|api_?key|csrf|\biv\b|\bkey\b"),
    ),
    Rule(
        "prestandard-pqc",
        "non-fips",
        rx(B + r"(kyber(?:512|768|1024)?|dilithium[235]?|sphincs\+?|sphincsplus)" + E),
        "pre-standard Kyber/Dilithium/SPHINCS+ are not FIPS 203/204/205 and don't interoperate with them",
        "ML-KEM / ML-DSA / SLH-DSA from a FIPS 203/204/205 implementation",
    ),
    Rule(
        "falcon",
        "non-fips",
        rx(B + r"(falcon-?(512|1024)|fn-?dsa)" + E),
        "Falcon / FN-DSA (FIPS 206) is not yet a final FIPS standard",
        FIX_SIG,
    ),
    # -- advisory (never fail) --
    Rule(
        "advisory-blake",
        "advisory",
        rx(B + r"(blake2[bs]?|blake3)" + E),
        "BLAKE2/BLAKE3 are not FIPS-approved: fine for cache keys and dedup, never for security",
        "SHA-256/384/512 or SHA3 for integrity, signatures and MACs",
        "hash",
    ),
    Rule(
        "advisory-tls12",
        "advisory",
        rx(r"\bTLSv1[._]2\b|PROTOCOL_TLSv1_2|TLSVersion\.TLSv1_2"),
        "TLS 1.2 has no PQC hybrid key exchange",
        "TLS 1.3 minimum with X25519MLKEM768",
    ),
    Rule(
        "advisory-oqs",
        "advisory",
        rx(r"\bliboqs\b|\bimport oqs\b|\bfrom oqs\b|\boqs-provider\b|\bpqcrypto\b"),
        "liboqs/pqcrypto are research implementations, not FIPS 140-3 validated",
        "ML-KEM/ML-DSA from OpenSSL 3.5+ (FIPS provider), AWS-LC, Go crypto/mlkem or Node crypto",
    ),
    # -- CNSA 2.0 profile only --
    Rule(
        "cnsa2-aes",
        "broken",
        rx(B + r"aes[-_]?(128|192)" + E + r"|\bAES(128|192)\b"),
        "CNSA 2.0 requires AES-256",
        "AES-256-GCM",
        profile="cnsa2",
    ),
    Rule(
        "cnsa2-hash",
        "broken",
        rx(B + r"sha-?(224|256)" + E + r"|\bSHA(224|256)\b|sha3[-_]?(224|256)"),
        "CNSA 2.0 requires SHA-384 or SHA-512",
        "SHA-384/512",
        "hash",
        profile="cnsa2",
    ),
    Rule(
        "cnsa2-pqc-level",
        "broken",
        rx(r"ml[-_]?kem[-_]?(512|768)|ml[-_]?dsa[-_]?(44|65)"),
        "CNSA 2.0 requires ML-KEM-1024 and ML-DSA-87",
        "ML-KEM-1024 / ML-DSA-87",
        profile="cnsa2",
    ),
)

PQC_KEM = rx(r"ml[-_]?kem|mlkem|x-?wing|hqc")
PQC_SIG = rx(r"ml[-_]?dsa|mldsa|slh[-_]?dsa|slhdsa|\blms\b|\bhss\b|\bxmss")
ALLOW_INLINE = rx(r"pqc-allow:\s*([\w*,-]+)\s*(.*)")
USEDFORSECURITY = rx(r"usedforsecurity\s*=\s*False", 0)


@dataclass
class Allow:
    rule: str
    glob: str
    until: dt.date | None
    reason: str
    line: int
    used: bool = False


@dataclass
class Finding:
    path: str
    line: int
    rule: str
    category: str
    match: str
    message: str
    fix: str
    status: str = "fail"  # fail | allowed | hybrid | advisory
    note: str = ""
    extra: dict[str, str] = field(default_factory=dict)


def repo_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", "surrogateescape")
        files = sorted({f for f in out.split("\0") if f})
    except (OSError, subprocess.CalledProcessError):
        files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                files.append(Path(dirpath, name).relative_to(root).as_posix())
    return [f for f in files if wanted(f) and (root / f).is_file()]


def wanted(rel: str) -> bool:
    p = Path(rel)
    if rel == SELF or p.name in SKIP_NAMES or any(part in SKIP_DIRS for part in p.parts[:-1]):
        return False
    if p.name.endswith(".min.js") or p.suffix == ".md":
        return False
    return (
        p.suffix in CODE_EXT
        or p.suffix in CONFIG_EXT
        or p.name in CONFIG_NAMES
        or p.name in MANIFESTS
        or fnmatch.fnmatch(p.name, "requirements*.txt")
    )


def is_manifest(rel: str) -> bool:
    name = Path(rel).name
    return name in MANIFESTS or fnmatch.fnmatch(name, "requirements*.txt")


def load_policy(root: Path) -> tuple[str, list[Allow], list[str]]:
    profile, allows, errors = "nist", [], []
    path = root / POLICY_FILE
    if not path.exists():
        return profile, allows, errors
    for n, raw in enumerate(path.read_text("utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("profile"):
            parts = line.split()
            if len(parts) != 2 or parts[1] not in ("nist", "cnsa2"):
                errors.append(f"{POLICY_FILE}:{n}: expected `profile nist|cnsa2`")
            else:
                profile = parts[1]
            continue
        m = re.match(r"allow\s+(\S+)\s+(\S+)(?:\s+until=(\S+))?\s+--\s*(.*)$", line)
        if not m:
            errors.append(f"{POLICY_FILE}:{n}: expected `allow <rule> <glob> [until=YYYY-MM-DD] -- <reason>`")
            continue
        rule, glob, until_s, reason = m.groups()
        until = None
        if until_s:
            try:
                until = dt.date.fromisoformat(until_s)
            except ValueError:
                errors.append(f"{POLICY_FILE}:{n}: bad date {until_s!r}")
                continue
        if len(reason.split()) < 3:
            errors.append(f"{POLICY_FILE}:{n}: give a reason of at least three words")
            continue
        allows.append(Allow(rule, glob, until, reason, n))
    return profile, allows, errors


def rule_matches(spec: str, rule: Rule) -> bool:
    return any(s in ("*", rule.id, rule.category) for s in spec.split(","))


def apply_policy(f: Finding, rule: Rule, allows: list[Allow], today: dt.date) -> None:
    for a in allows:
        if not (rule_matches(a.rule, rule) and fnmatch.fnmatch(f.path, a.glob)):
            continue
        a.used = True
        if rule.category == "quantum" and (a.until is None or a.until > QUANTUM_DISALLOWED):
            f.note = f"{POLICY_FILE}:{a.line} needs until= on or before {QUANTUM_DISALLOWED} for a quantum exception"
            return
        if a.until and a.until < today:
            f.note = f"{POLICY_FILE}:{a.line} expired {a.until}"
            return
        f.status, f.note = "allowed", f"{POLICY_FILE}:{a.line}: {a.reason}"
        return


def inline_allow(lines: list[str], i: int, rule: Rule) -> str | None:
    for j in (i, i - 1):
        if j < 0:
            continue
        m = ALLOW_INLINE.search(lines[j])
        if m and rule_matches(m.group(1), rule):
            reason = m.group(2).strip()
            return reason if len(reason.split()) >= 3 else ""
    return None


def scan(root: Path, profile: str, allows: list[Allow]) -> list[Finding]:
    today = dt.date.today()
    findings: list[Finding] = []
    rules = [r for r in RULES if not r.profile or r.profile == profile]
    for rel in repo_files(root):
        path = root / rel
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", "replace")
        lines = text.splitlines()
        has_kem, has_sig = bool(PQC_KEM.search(text)), bool(PQC_SIG.search(text))
        manifest = is_manifest(rel)
        for i, line in enumerate(lines):
            for rule in rules:
                if rule.scope == "manifest" and not manifest:
                    continue
                m = rule.pattern.search(line)
                if not m or (rule.context and not rule.context.search(line)):
                    continue
                f = Finding(rel, i + 1, rule.id, rule.category, m.group(0).strip()[:60], rule.message, rule.fix)
                groups = set(rule.group.split(",")) - {""}
                if rule.category == "advisory":
                    f.status = "advisory"
                elif rule.id == "weak-hash" and USEDFORSECURITY.search(line):
                    f.status, f.note = "allowed", "usedforsecurity=False"
                elif rule.category == "quantum" and groups and (("kex" in groups and has_kem) or ("sig" in groups and has_sig)):
                    f.status, f.note = "hybrid", "file also uses a PQC algorithm"
                else:
                    reason = inline_allow(lines, i, rule)
                    if reason == "":
                        f.note = "pqc-allow needs a reason of at least three words"
                    elif reason is not None and rule.category == "quantum":
                        f.note = "quantum exceptions need a dated entry in .pqc-policy (until=), not an inline allow"
                    elif reason is not None:
                        f.status, f.note = "allowed", f"inline: {reason}"
                    else:
                        apply_policy(f, rule, allows, today)
                findings.append(f)
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, help="repo root (default: git toplevel, else cwd)")
    ap.add_argument("--profile", choices=("nist", "cnsa2"), help="override the .pqc-policy profile")
    ap.add_argument("--all", action="store_true", help="also print allowed, hybrid and advisory findings")
    ap.add_argument("--json", action="store_true", help="print every finding as JSON")
    ap.add_argument("--list-rules", action="store_true")
    args = ap.parse_args()

    if args.list_rules:
        for r in RULES:
            print(f"{r.id:18s} {r.category:9s} {r.profile or 'all':6s} {r.message}")
        return 0

    root = args.root
    if root is None:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        root = Path(top.stdout.strip()) if top.returncode == 0 else Path.cwd()
    root = root.resolve()

    profile, allows, errors = load_policy(root)
    profile = args.profile or profile
    findings = scan(root, profile, allows)
    failing = [f for f in findings if f.status == "fail"]
    stale = [a for a in allows if not a.used]

    if args.json:
        print(
            json.dumps(
                {
                    "profile": profile,
                    "findings": [asdict(f) for f in findings],
                    "policy_errors": errors,
                    "unused_allows": [f"{POLICY_FILE}:{a.line} {a.rule} {a.glob}" for a in stale],
                },
                indent=2,
            )
        )
        return 2 if errors else (1 if failing else 0)

    shown = findings if args.all else failing
    for f in shown:
        tag = f.category if f.status == "fail" else f.status
        print(f"{f.path}:{f.line}: [{f.rule}] {tag}: {f.message} ({f.match!r})", file=sys.stderr)
        print(f"    fix: {f.fix}" + (f"\n    note: {f.note}" if f.note else ""), file=sys.stderr)
    for e in errors:
        print(f"policy error: {e}", file=sys.stderr)
    for a in stale:
        print(f"warning: {POLICY_FILE}:{a.line} allow {a.rule} {a.glob} matches nothing; remove it", file=sys.stderr)

    counts = {s: sum(1 for f in findings if f.status == s) for s in ("fail", "allowed", "hybrid", "advisory")}
    print(
        f"pqc-check ({profile}): {counts['fail']} failing, {counts['allowed']} allowed, "
        f"{counts['hybrid']} hybrid, {counts['advisory']} advisory"
        + ("" if args.all or not (counts["allowed"] or counts["advisory"]) else " (--all to list them)"),
        file=sys.stderr,
    )
    if errors:
        return 2
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
