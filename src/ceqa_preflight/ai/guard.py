"""The legal-sufficiency guard: the founding boundary, enforced by code.

CEQA Preflight never determines legal sufficiency. Two deterministic checks hold that line
around the model. ``classify_question`` runs before any model call and refuses every form
of "is this filing sufficient / will it be accepted / is this exemption valid / did the
agency comply". ``determination_language`` runs on every sentence a model produces and
withholds any that upgrades an advisory finding into a determination. Both are pattern
lists, reviewable in one place, and the refusal eval in ``evals/refusal`` exercises them.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import Field

from ceqa_preflight.models import StrictModel

_REFUSAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "legal sufficiency",
        r"legal(?:ly)?[\s-]*sufficien|sufficien\w*\s+(?:under|for|as\s+a\s+matter\s+of)\s+(?:ceqa|the\s+law|law)",
    ),
    (
        "legal sufficiency",
        r"legally\s+(?:adequate|complete|valid|correct|ok|okay|fine|sound|defensible|enough)",
    ),
    (
        "acceptance prediction",
        r"(?:will|would|gonna|going\s+to|can|could|should|is\s+it\s+likely\s+to)\s+(?:it|this|that|they|we|(?:this|that|the|our|my)\s+\w+(?:\s+\w+)?)\s+(?:be\s+)?(?:get\s+)?(?:accepted|approved|rejected|bounced|kicked\s+back|posted|published|denied|turned\s+down)",
    ),
    (
        "acceptance prediction",
        r"(?:is|are)\s+(?:it|this|that|(?:this|that|the|our|my)\s+\w+(?:\s+\w+)?)\s+(?:going\s+to|gonna|likely\s+to|about\s+to)\s+(?:be\s+)?(?:get\s+)?(?:accepted|approved|rejected|bounced|kicked\s+back|posted|published|denied|turned\s+down)",
    ),
    (
        "acceptance prediction",
        r"likely\s+(?:\w+\s+){0,4}?to\s+(?:be\s+)?(?:get\s+)?(?:accepted|approved|rejected|posted|published)",
    ),
    (
        "acceptance prediction",
        r"(?:accept|approve|reject|post|publish)\w*\s+(?:this|it|the\s+\w+|our\s+\w+|my\s+\w+)\b.*\?",
    ),
    ("acceptance prediction", r"chances?\b.*\b(?:accept|approv|reject|post|publish)"),
    (
        "acceptance prediction",
        r"(?:state\s+)?clearinghouse\s+(?:will|would|is\s+going\s+to|gonna)\s+(?:accept|approve|reject|take|post|publish)",
    ),
    (
        "challenge prediction",
        r"(?:survive|withstand|hold\s+up|stand\s+up|defend\w*)\s+(?:in\s+court|(?:a|any|legal|judicial|to)\s+(?:legal\s+)?(?:challenge|scrutiny|review|lawsuit|litigation|suit|appeal))",
    ),
    (
        "challenge prediction",
        r"(?:legally\s+)?defensible|litigation\s+risk|legal\s+risk|exposure\s+to\s+(?:a\s+)?(?:lawsuit|challenge|litigation)|get\s+sued|be\s+sued|statute\s+of\s+limitations",
    ),
    (
        "exemption validity",
        r"(?:exemption|exempt\s+status|categorical\s+exemption|statutory\s+exemption|class\s+\d+\s*(?:exemption)?|section\s+15\d{3})\s+(?:is|was|be|seems?|looks?|sounds?|appears?|remains?)\s+(?:\w+\s+){0,2}?(?:valid|proper|correct|appropriate|applicable|justified|legitimate|right|ok|okay|fine|good|sound|legal|lawful|allowed|permissible|defensible|solid)",
    ),
    (
        "exemption validity",
        r"(?:valid|proper|correct|appropriate|applicable|justified|legitimate|right|lawful|permissible)\s+(?:\w+\s+){0,2}?(?:exemption|exempt\s+status|use\s+of\s+(?:the\s+)?exemption)",
    ),
    (
        "exemption validity",
        r"(?:is|was|are|were)\s+(?:the|this|that|our|my|a|an)?\s*(?:\w+\s+){0,2}?(?:exemption|exempt\s+status|section\s+15\d{3}|15\d{3}|class\s+\d+)\s+(?:\w+\s+){0,1}?(?:valid|proper|correct|appropriate|applicable|justified|legitimate|right|ok|okay|fine|good|sound|legal|lawful|allowed|permissible|defensible|solid)\b",
    ),
    (
        "exemption validity",
        r"(?:qualif(?:y|ies|ied)|eligible)\s+(?:for|under)\s+(?:a|an|the|this|that)?\s*(?:\w+\s+){0,2}?(?:exemption|exempt|class|section\s+15\d{3}|15\d{3})",
    ),
    (
        "exemption validity",
        r"(?:should|can|could|may|is\s+it\s+(?:ok|okay|fine|appropriate)\s+to)\s+(?:we|i|they|the\s+\w+)?\s*(?:use|claim|rely\s+on|apply|invoke|cite)\s+(?:a|an|the|this|that)?\s*(?:\w+\s+){0,2}?(?:exemption|class\s+\d+|section\s+15\d{3})",
    ),
    (
        "exemption validity",
        r"(?:right|correct|proper|appropriate|applicable|wrong)\s+(?:exemption|class|section|citation)\s+(?:for|to)\b",
    ),
    (
        "exemption validity",
        r"(?:exception|exemption)s?\s+to\s+the\s+(?:exemption|exemptions)\s+(?:apply|applies|triggered)",
    ),
    (
        "compliance determination",
        r"compl(?:y|ies|ied|iance|iant)\s+with\s+(?:ceqa|the\s+law|the\s+guidelines|the\s+statute|state\s+law|section|§|\w+\s+requirements)",
    ),
    (
        "compliance determination",
        r"(?:in\s+compliance|ceqa[\s-]*compliant|compliant\s+with|non[\s-]*compliant|out\s+of\s+compliance|violat(?:e|es|ed|ion)\s+(?:of\s+)?ceqa)",
    ),
    (
        "compliance determination",
        r"(?:did|does|has|have|is|was|are|were)\s+(?:the\s+)?(?:\w+\s+){0,3}?(?:agency|district|county|city|board|department|lead\s+agency|we|they|it|this)\s+(?:\w+\s+){0,2}?(?:compl(?:y|ied|ies)|follow(?:ed)?\s+(?:the\s+)?(?:law|ceqa|rules|requirements|guidelines)|meet\s+(?:its|their|the)\s+(?:legal\s+)?(?:obligations|duties|requirements)|do\s+(?:this|it)\s+(?:right|correctly|legally|properly))",
    ),
    (
        "adequacy determination",
        r"(?:is|was|are|were|be|seems?|looks?|sounds?|appears?)\s+(?:it|this|that|the\s+\w+(?:\s+\w+)?|everything|all\s+of\s+this)?\s*(?:\w+\s+){0,2}?(?:legally\s+)?(?:adequate|sufficient|complete\s+enough|good\s+enough|enough|ok\s+to\s+file|okay\s+to\s+file|ready\s+to\s+file|safe\s+to\s+file|fileable|acceptable|valid|lawful|legal|kosher|airtight|bulletproof|in\s+the\s+clear)\b",
    ),
    (
        "adequacy determination",
        r"(?:meets?|satisf(?:y|ies)|fulfil+s?)\s+(?:all\s+)?(?:the\s+)?(?:legal|statutory|ceqa|state|regulatory|filing|applicable)?\s*(?:requirements|standards|obligations|criteria|elements|mandates)",
    ),
    (
        "adequacy determination",
        r"(?:sign\s+off|signoff|rubber[\s-]*stamp|green[\s-]*light|bless|certify|certification|attest)\w*\s+(?:on\s+|that\s+)?(?:this|it|the\s+\w+|our\s+\w+|my\s+\w+)",
    ),
    (
        "adequacy determination",
        r"(?:can|could|should|may)\s+(?:we|i|they|one)\s+(?:just\s+)?(?:go\s+ahead\s+and\s+)?(?:file|submit|send|upload|go\s+ahead|proceed)\s+(?:this|it|now|as[\s-]+is|with\s+this|today|tonight)",
    ),
    (
        "adequacy determination",
        r"(?:anything|something|what)\s+(?:else\s+)?(?:legally\s+)?(?:wrong|missing|deficient|lacking|defective)\s+(?:with|in|from)\s+(?:this|the|our|my)\s+(?:filing|notice|package|submission|document|nod|noe|exemption)\b.*(?:legal|law|ceqa|court|challenge|valid)",
    ),
    (
        "legal advice",
        r"(?:legal\s+(?:advice|opinion|analysis|conclusion|judgment|judgement|assessment|determination|position|view|call)|as\s+(?:a|my)\s+lawyer|as\s+counsel|legal\s+standpoint|legally\s+speaking|from\s+a\s+legal\s+perspective|in\s+your\s+legal\s+opinion)",
    ),
    (
        "legal advice",
        r"(?:lawful|legal|unlawful|illegal)\s+(?:for|to)\s+(?:us|me|them|the\s+\w+)\s+to\b",
    ),
    (
        "sufficiency determination (Spanish)",
        r"(?:legalmente\s+)?suficiente|suficiencia\s+legal|legalmente\s+(?:v[aá]lid|adecuad|correct|complet|suficient)",
    ),
    (
        "acceptance prediction (Spanish)",
        r"(?:ser[aá]n?|va\s+a\s+ser|van\s+a\s+ser|lo\s+van\s+a|lo\s+va\s+a|podr[ií]an?\s+ser)\s+(?:aceptad|aprobad|rechazad|publicad)",
    ),
    (
        "acceptance prediction (Spanish)",
        r"(?:va|van|vas|vamos|ir[aá]n?)\s+a\s+(?:aceptar|aprobar|rechazar|publicar)",
    ),
    (
        "acceptance prediction (Spanish)",
        r"(?:aceptar|aprobar|rechazar|publicar)(?:[aá]n?)?\s+(?:este|esta|esto|el|la|lo|nuestro|nuestra|mi|su)\b",
    ),
    (
        "exemption validity (Spanish)",
        r"exenci[oó]n\s+(?:es|est[aá]|ser[ií]a|parece)\s+(?:\w+\s+)?(?:v[aá]lida|correcta|apropiada|adecuada|aplicable|justificada|leg[ií]tima|legal|procedente)|(?:v[aá]lida|correcta|apropiada|adecuada|aplicable|procedente)\s+(?:la\s+|esta\s+|esa\s+)?exenci[oó]n|califica\w*\s+(?:\w+\s+){0,3}?para\s+(?:la|una|esta)?\s*exenci[oó]n",
    ),
    (
        "compliance determination (Spanish)",
        r"cumpl(?:e|en|i[oó]|imos|ieron|imiento)\s+(?:\w+\s+){0,3}?(?:con\s+)?(?:ceqa|la\s+ley|las\s+normas|los\s+requisitos|el\s+reglamento|las\s+directrices)",
    ),
    (
        "challenge prediction (Spanish)",
        r"(?:sobrevivir|resistir|aguantar|soportar)\w*\s+(?:\w+\s+){0,2}?(?:una\s+|la\s+|cualquier\s+)?(?:impugnaci[oó]n|demanda|litigio|desaf[ií]o\s+legal|juicio)|riesgo\s+legal|impugnable|defendible",
    ),
    (
        "adequacy determination (Spanish)",
        r"(?:es|est[aá]|ser[ií]a|queda)\s+(?:todo\s+)?(?:\w+\s+)?(?:adecuad[oa]|suficiente|complet[oa]|list[oa]\s+para\s+(?:presentar|enviar|archivar)|en\s+regla|en\s+orden|correct[oa]\s+legalmente|legal|v[aá]lid[oa])\b",
    ),
    (
        "legal advice (Spanish)",
        r"(?:asesor[ií]a|opini[oó]n|consejo|an[aá]lisis|dictamen)\s+(?:legal|jur[ií]dic[oa])|desde\s+el\s+punto\s+de\s+vista\s+legal|legalmente\s+hablando",
    ),
)

_COMPILED = tuple((label, re.compile(pattern, re.I)) for label, pattern in _REFUSAL_PATTERNS)

# Sentences a model may not produce about a filing, whatever it was asked. These are the
# shapes of a determination; an explanation of a technical finding never needs them.
_DETERMINATION_PATTERNS: tuple[str, ...] = (
    r"\b(?:is|are|was|were|will\s+be|would\s+be|should\s+be|remains?|appears?\s+to\s+be|seems?\s+to\s+be|looks?)\s+(?:\w+\s+){0,2}?(?:legally\s+sufficient|sufficient|legally\s+adequate|adequate|compliant|in\s+compliance|legally\s+valid|valid|lawful|legal|defensible|acceptable|complete\s+and\s+correct)\b",
    r"\b(?:complies|comply|complied|conforms?|conformed)\s+with\b",
    r"\b(?:satisf(?:y|ies|ied)|meets?|met|fulfil+s?)\s+(?:all\s+)?(?:the\s+)?(?:legal|statutory|ceqa|state|regulatory|applicable)?\s*(?:requirements|standards|obligations|criteria)\b",
    r"\bwill\s+(?:be\s+)?(?:accepted|approved|rejected|posted|published)\b",
    r"\b(?:exemption|exempt\s+status|project)\s+(?:is|was|remains?)\s+(?:\w+\s+){0,2}?(?:valid|proper|appropriate|applicable|justified|correct)\b",
    r"\b(?:qualifies|qualify|qualified)\s+for\s+(?:a|an|the|this)\s+(?:\w+\s+){0,2}?exemption\b",
    r"\b(?:is|are)\s+(?:not\s+)?legally\s+(?:required|binding|necessary|mandated)\b",
    r"\bno\s+(?:further\s+)?legal\s+(?:issues?|problems?|defects?|risk)\b",
    r"\b(?:es|son|est[aá]n?|ser[aá]n?|ser[ií]a)\s+(?:legalmente\s+)?(?:suficiente|adecuad[oa]|v[aá]lid[oa]|conforme|legal|defendible)s?\b",
    r"\bcumpl(?:e|en)\s+con\b",
)
_DETERMINATIONS = tuple(re.compile(pattern, re.I) for pattern in _DETERMINATION_PATTERNS)


class GuardVerdict(StrictModel):
    """Whether a question is refused, and which boundary it crossed."""

    refused: bool
    category: str | None = None
    matched: str | None = Field(default=None, max_length=200)


def _normalize(text: str) -> str:
    stripped = unicodedata.normalize("NFKC", text)
    stripped = re.sub("[\u2018\u2019\u201c\u201d]", "'", stripped)  # curly quotes
    return re.sub(r"\s+", " ", stripped).strip()


def classify_question(text: str) -> GuardVerdict:
    """Refuse every phrasing that asks for a legal-sufficiency determination.

    The check is deterministic and runs before any model call, so a refusal costs nothing
    and cannot be talked around. Matching is case-insensitive over whitespace-normalized
    text; the category names the boundary crossed so the refusal can say which one.
    """

    normalized = _normalize(text)
    for category, pattern in _COMPILED:
        match = pattern.search(normalized)
        if match:
            return GuardVerdict(refused=True, category=category, matched=match.group(0)[:200])
    return GuardVerdict(refused=False)


def determination_language(text: str) -> str | None:
    """Return the first determination-shaped phrase in model output, or ``None``.

    Used by the verifier: a claim containing one is withheld regardless of its citations,
    because no official source the corpus holds makes a determination about a specific
    filing, and the tool never does either.
    """

    normalized = _normalize(text)
    for pattern in _DETERMINATIONS:
        match = pattern.search(normalized)
        if match:
            return match.group(0)
    return None
