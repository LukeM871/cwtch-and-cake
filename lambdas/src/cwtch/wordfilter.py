"""The cheap first check on reviews: obvious slurs and abuse (docs/API.md section 6, step 2).

How it matches:
- WHOLE WORDS only, never parts of words. Matching inside words is the classic
  "Scunthorpe problem": it would block Scunthorpe, "classic", "assessment" and
  Offa's Dyke. Abuse hidden inside longer words is left to Amazon Comprehend and
  to the admin, who checks every review anyway.
- Common disguises are undone first: capitals, accents (fück), look-alike letters
  from other alphabets (Cyrillic а/е/о), leetspeak (f4g, $, @, 1), stretched
  letters (fuuuuck), a plural s, and spaced-out letters (f u c k, f.u.c.k).

The blocked words themselves are NOT in this file. Each is stored as a SHA-256
hash, so the public repo doesn't contain a list of slurs. It's tidiness, not
secrecy: anyone could hash a dictionary to recover them. To add a word, run
    python scripts/wordfilter_hash.py
and paste the line it prints into BLOCKED.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

PEPPER = "cwtch-wordfilter:"
MAX_SPACED = 14  # longest spaced-out word tried (letters)

_TOKEN = re.compile(r"(?:[^\W_]|[@$])+")
_STRETCHED = re.compile(r"(.)\1{2,}")  # the same character 3+ times in a row
# Look-alike letters from Cyrillic and Greek that pass for Latin ones.
_LOOKALIKES = str.maketrans("аеорсухіјѕкмтвнԁɡοαιν", "aeopcyxijskmtbhdgoaiv")
_LEET = {"0": "o", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "9": "g", "@": "a", "$": "s"}
_LEET_AS_I = str.maketrans({**_LEET, "1": "i"})
_LEET_AS_L = str.maketrans({**_LEET, "1": "l"})


def word_hash(word: str) -> str:
    return hashlib.sha256((PEPPER + word).encode("utf-8")).hexdigest()


def fold(text: str) -> str:
    """Lower-case, accents removed, look-alike letters replaced by Latin ones."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold().translate(_LOOKALIKES)


def _variants(token: str) -> set[str]:
    """Every spelling a disguised word could be standing for."""
    if token.isdigit():
        return set()  # plain numbers ("4 of us", "2024") are never words
    out: set[str] = set()
    for table in (_LEET_AS_I, _LEET_AS_L):  # "1" can stand for i or l
        plain = token.translate(table)
        for squashed in (plain, _STRETCHED.sub(r"\1", plain), _STRETCHED.sub(r"\1\1", plain)):
            out.add(squashed)
            if len(squashed) > 3 and squashed.endswith("s"):
                out.add(squashed[:-1])
    return out


def _candidates(text: str) -> set[str]:
    tokens = _TOKEN.findall(fold(text))
    words = set(tokens)
    # Spaced-out letters: 3+ single characters in a row are also tried joined up.
    # Every stretch of the run is tried, so "what a c u n t" finds the word
    # even though "a" is a real word sitting right before it.
    run: list[str] = []
    for token in [*tokens, ""]:
        if len(token) == 1:
            run.append(token)
            continue
        for start in range(len(run)):
            for end in range(start + 3, min(len(run), start + MAX_SPACED) + 1):
                words.add("".join(run[start:end]))
        run = []
    out: set[str] = set()
    for word in words:
        out |= _variants(word)
    return out


def is_blocked(text: str) -> bool:
    return any(word_hash(word) in BLOCKED for word in _candidates(text))


# SHA-256 of PEPPER + word, for each blocked word (lower-case, no accents).
BLOCKED: frozenset[str] = frozenset({
    "018b50cec41fb6ea879d1c51bf466b538013dbcdadee44b19531f19338980d6f",
    "01f4398d4a4066a3c5f9f63873c8a4ab5d6939cc4adf51895915a9fab3501654",
    "0558191806256d8ac7996835961feb4f11af32cbd07f2db39453bf1b1066ef67",
    "0928ef4d08bc801778dca238cdc1a26dbae3b91c0c8c86a542359d5d69f46b48",
    "0f01af2ed1b75160972baa00842ed09c6e16387d6e499e189a042bc5b5e1b227",
    "10f635d7ecae3d1848cc0982de5d302cb8c88565081e1d88057300bdbc6d15dd",
    "13039ece018330ea1bbb44da4189ae0be456e87f50d5eedfcaa28e1c79054d2c",
    "2586df3a04685fece5d170145f00aa7fa58f7c28f73838bcf3b4d766abac9fd2",
    "26b00e483de05d52756dc1bc86db67d67c4481be28317c45018ab476adc1f851",
    "27ffadfb6559c78142629dfe6ab9cebe3232fdac596c20e9d23ad1c98c948b52",
    "2d1b33d3fa761e76b226e658d5fcf3440f0457180725fd6067e1d6e7b41ceaa6",
    "2d2a87c2eb94f02b3fed919ff26ef55f72e43aafebe3b2b6ab40b5e1774ad416",
    "2eea928d1bd943139e298ed128eac0b14e251d93bd3d8195232c5166ff9a4718",
    "2f1cb936b2bf05f43e4bd3f2eb63fc7d80eed5d3e1cc4b1faa44775e23e59f36",
    "32bf9527ac48d1220d3483fe4ef6bcbe337b075b8c83f86ed17b3f19dc29a934",
    "3379f357620b5ea18b350dc34c0e0c07446a5ca54c29bba34c7482b98fdccd19",
    "3a62e2b08241b1e9ce54a8887a70793ba9ace8a261a8f18a457deee09e0d4f17",
    "3d66896212d9f637a201f94dc936a60c45fc436366711ce7f83fa95cfb12f928",
    "43218a09d1d3ad728503bcaf49578ad3463848adde34cbbdf5d891cd7de5838e",
    "464bd53e87a7b6e7a413c9225cee36c57f4e0fd4db08bb37d9da0ea8052f58f8",
    "483c8845700a73b136073190faee6257c3cd044fb546b62bb829adab4a5eccdb",
    "491da596e19cf832596fce93498eebc09e2654c325f8692036a075d4cf9b19b2",
    "4a2ecf546dbd81ec0603028b38c86251b74265f21161071c6585ff84fedd24bf",
    "4db02f654de51e503c239136949267a2b4e1fe43f7602f8e9dddab9be2a0438a",
    "5505a56becc62a525cf0f824732964c523331326d7777f1df84a982aed95001a",
    "59e3d524d92cd8350a6881735be15d8e19bd5340affca644df8446e8cba9dd3c",
    "623c0d97a4f9e3fe36f2a82e3fc4da4728ea87fd3ab36cb0ff9f85a13e8eaa06",
    "62d830b302ecb4b68b4ae7512c09f70c516bd6e38fb2bf676ad9ff462bd0b4c3",
    "6372aaf2281d026513060ca7488b07d0b831e40f2717d872a9f3a89762176517",
    "672a420e02a7ee963a5a461b614effd1fec6ca72b103b0ba0463fb844a021fe4",
    "674883afbb451171692d4c4dfe54d80e41f689ac07f463d8f8812e5af25f9f9f",
    "6a12c8e494990211441f21f471fc669f77c1bfb366a83b0d1c598650bd505ca7",
    "6fc0f37502f11f0ad102c631bbfd776a32b8450596b0468e0f38b5581575a722",
    "7074a0147e6033b3cb7ba512b9428cfebe7892c26947809780ff9c7bce4a848b",
    "71a76be8c2733ec2ac43c07fe32f58ceb2ee6dc03b18b8b8db7d0290f47bc3b4",
    "72680afb2670c74430d99f7df771e60a07ada243c6889e06e613c1922093b56c",
    "7b7cb587747ab2043cacd57462e65fa6b4e605bbd8bb036eb1832c83a6c68b22",
    "7e7e0bae1ea9c9cfe7f814b152581b443a2390d1f199ded33ae4bb2b356ab456",
    "7ea7c34c6c4bfa29e3570ae9e268083294ca693f00d56afc4e10e01dceb546ae",
    "7ee6d44eede1d357cbe55d106e19e15c3ee28c32b815d287fb5f0386cdc7c9a2",
    "7efe30dce3f0cc44dbab0d50d30eb70c1d6b1d413602062da3380feb6ee8d137",
    "880ae9aeac45c74e77194800fb5eabd61bfb15a75ae37de8f1a13ca93a44442a",
    "8a753dc54ea0fd469f6d8c8a86cacac8f0db265cc6182a31eb166d60f314c6f8",
    "8dfc5885a8d2161238b92bcd471a12ea1ab6737cf57afe956769ce6b2832a507",
    "9de375c18df11f2c68f208b765d32666c56fcd12709782d218da4366839e6887",
    "9e0098ba078a1a267cfff2dce055e31d09afa0bfc61077bcd5af22a0221a2de7",
    "9f6c181f32132bb7112fc378162ea20d32221642a97e09409fa17e82baf12eaa",
    "a0c1923e95a77d8b97f5206ccb4f0d44e4751bfa3c0880378a7932dc24a7dba0",
    "a15e9bba2903f56312dd47088e93b22cf0c948d12f9c8b93e5e42514c43254d8",
    "a1f60fca0f3834083ba25ea8d06173de1e3ab01694ccce2f73d5091d22fb1916",
    "a779457640748e6683a74e93fd654032aeb189b997856d9eb779b8b3bd20d027",
    "aad93ee9d5cd7d121a4416ee9c0f50ab7ba2bfe80cdce4c5e78a880d3a370d73",
    "acbe7b87d8c2931ef658313a92e6e1b00674fa370b69bd6898cd2bb5a70e594f",
    "b41b3beec49409e88e63ac4cb022a3db117267aefc5394f325a1d6043a2c4731",
    "b9586ab1fff64a8396bf3d9acfb3470f63346a30f95f308edefabf80b0324894",
    "bafa6efdcae9ad3e99a222dec70626397f590de8bd15c1f1f1e9a43a2cdd2036",
    "c52c7db7d34ae61262d0d0fdb07c920114f207f0d12462a0ce93b3ac928a4e26",
    "c8d0b4bb795c180774ec4ad86ea5d0ab3e2b97b9d7fa093e5a19d064a146b10d",
    "ca28635cfd393914588e937714c85122ab3c18cdce643abef9bb88795c2f3a7f",
    "d656cff8e4bb32be4ad974fb1d3d42d3766dc72439beb7467dea1d7474b2ce37",
    "d759af60c6e6a77831b2dfce7be41d7c4403d2752d789b29d32b049700843f87",
    "dab97a6a36003147f421ee1e271f9a460543b365f0a03e6d48f3f7da112fdd85",
    "de91d5275839c285112aa3caa8015c14df178b28667a31fe8f4867bc0c08ce9c",
    "e09dd9866893fb75c544295c647aba130995eb81d1afee66e78c691fccedd4cb",
    "e14c31f583a130bb8413030471451f415b0efa76adad5568e3c574a7918d2aa9",
    "e3fd1e6cec5e7ff78328febc0a797ed49bdd14cc16d0ab403a7201db36e5804f",
    "e5182b74d8e24f382fe7f68c386c9bf72568ab4c1220235881bc4ed50fe2365f",
    "e593e9c9a376078e67bbe130118d8b64dab96af87ecf1915d67313f1b4933b8f",
    "e81327401546be0577a96bc35b1841056bea3b75784dc1fff157d73f996306e8",
    "e86cae85bec3d74db73f585bcd06f60f029a35f6496e6f4d56c5d9b1115549f4",
    "f0bc4bf87cd351ae153679e27e197e0639965cf34317c181e6be1a9353ea8020",
    "f2f2c13f63e737d14002f1179cf5233803a2f908fde8ddb5cb33404eb3fd8689",
    "f371ea28254c2f87c96c092ee9b11a428e3d32f41b753b7400bbda5cd5f14429",
    "fa555cfdbeef150a4beb1ecae69887e1f8542abd03f65708e9c1e80d5ecc4a62",
    "fb6b7966c9f5e99ba7ad9340546533a1a4911c5c04018b0342f65b96b33a386f",
    "fbc896ee4310a029b307a2d233343e534d1c49e94c7f10add2dcd853f5912141",
})
