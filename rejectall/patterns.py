"""Deterministic rules: classify a button's text into a consent role.

Every rule is a regex over the normalized label. Order matters and is fixed:
PAY before REJECT before SAVE before SETTINGS before ACCEPT, so that "reject
all and subscribe" counts as pay-or-ok, "accept only necessary" as a reject and
"accept selection" as a save.
"""
import re

ROLES = ("reject", "save", "settings", "accept", "pay")

# Labels longer than this are prose, not buttons.
MAX_LABEL = 60

_REJECT = [
    r"reject", r"decline", r"\bdeny\b", r"refuse", r"disagree",
    r"(?:do not|don'?t|i do not) (?:accept|agree|consent)",
    r"(?:only|just) (?:the )?(?:strictly )?(?:necessary|essential|required)",
    r"(?:necessary|essential|required) (?:cookies )?only",
    r"use (?:only )?(?:strictly )?(?:necessary|essential) cookies(?: only)?",
    r"(?:accept|allow) (?:only )?(?:strictly )?(?:necessary|essential|required)(?: cookies)?(?: only)?$",
    r"continue without (?:accepting|agreeing|consent)",
    r"no,? thanks", r"opt.?out", r"^no$",
    # de
    r"ablehnen", r"nicht (?:einverstanden|zustimmen|akzeptieren)", r"verweigern",
    r"nur (?:[a-zäöü]+ ){0,2}(?:notwendige|erforderliche|essen[sz]ielle|notwendigen|erforderlichen)",
    r"weiter ohne", r"ohne (?:zustimmung|einwilligung)",
    # fr / es / it / nl / pl / pt / ru / zh
    r"refuser", r"continuer sans accepter", r"rechazar", r"rifiut", r"weigeren", r"afwijzen",
    r"odrzu", r"rejeitar", r"recusar", r"отклон", r"拒绝", r"拒絕",
]
_SAVE = [
    r"save", r"confirm (?:my )?(?:choices|selection|preferences|settings)",
    r"(?:accept|allow) (?:the )?(?:current |my )?(?:selection|selected|choices)",
    r"submit (?:my )?(?:choices|preferences)",
    r"speichern", r"ausgewählte[mns]? (?:zustimmen|akzeptieren|erlauben|zulassen)", r"auswahl (?:bestätigen|übernehmen|akzeptieren|erlauben|zulassen)",
    r"bestätigen", r"enregistrer", r"confirmer (?:mes )?choix", r"guardar", r"salva", r"opslaan",
]
_SETTINGS = [
    r"manage", r"settings", r"preferences", r"\boptions?\b", r"customi[sz]e", r"configure",
    r"\bdetails\b", r"\bpurposes\b", r"choose", r"let me choose", r"set cookies",
    r"einstellungen", r"anpassen", r"verwalten", r"optionen", r"individuell", r"auswählen",
    r"präferenzen", r"zwecke", r"paramètres", r"personnaliser", r"gérer", r"configurar",
    r"personaliz", r"instellingen", r"ustawienia", r"настро", r"设置",
]
_ACCEPT = [
    r"accept", r"agree", r"\ballow\b", r"consent", r"^ok(?:ay)?\b", r"got it", r"^yes\b",
    r"i understand", r"understood", r"continue$",
    r"akzeptier", r"zustimm", r"einverstanden", r"zulassen", r"erlauben", r"annehmen",
    r"verstanden", r"^alles klar", r"einwilligen", r"stimme zu",
    r"accepter", r"j'accepte", r"aceptar", r"accett", r"accepteren", r"akceptuj", r"aceitar",
    r"принять", r"同意", r"接受",
]
# "Pay or okay" walls: the only alternative to consent is a subscription.
_PAY = [r"\babo\b", r"abonnieren", r"abonnement", r"subscribe", r"pur[- ]abo", r"werbefrei", r"ad-?free"]

# Marks a reject button as "reject ALL" rather than per-purpose.
ALL_WORD = re.compile(r"\ball\b|\balle[sn]?\b|\btout\b|\btodos?\b|\btutt[io]\b|\bwszystk|\bвсе|全部", re.I)

# Banner text that offers a paid alternative to consent.
PAY_TEXT = re.compile(r"pur[- ]?abo|werbefrei|ohne werbe(?:tracking|ung)|ad-?free|without (?:ads|advertising)|"
                      r"reject (?:all )?and subscribe|abo(?:nnement)? abschlie|sans publicité", re.I)

_COMPILED = {
    "reject": re.compile("|".join(_REJECT), re.I),
    "save": re.compile("|".join(_SAVE), re.I),
    "settings": re.compile("|".join(_SETTINGS), re.I),
    "accept": re.compile("|".join(_ACCEPT), re.I),
    "pay": re.compile("|".join(_PAY), re.I),
}

# Consent context: text that marks an element as part of a cookie/consent UI.
COOKIE_TEXT = re.compile(
    r"cookie|consent|gdpr|dsgvo|datenschutz|einwilligung|tracking|your privacy|"
    r"privacy (?:choices|settings|preferences)|\bpartners?\b|\bvendors?\b|personal data|"
    r"personalised ads|personalized ads|zustimmung|traceurs|données|privacidad|"
    r"легитим|legitimate interest|berechtigtes interesse",
    re.I,
)
# Container ids/classes used by consent-management platforms.
CMP_HINT = re.compile(
    r"cookie|consent|gdpr|\bcmp\b|onetrust|ot-sdk|didomi|cybot|usercentrics|uc-|sp_message|"
    r"qc-cmp|truste|trustarc|osano|iubenda|borlabs|klaro|cookiebanner|privacy-?banner|fc-consent|"
    r"cky-|cmplz|termly|axeptio|sourcepoint",
    re.I,
)
LEGIT_INTEREST = re.compile(
    r"legitimate interest|berechtigt(?:es|en) interesse|intérêt légitime|interés legítimo|"
    r"legittimo interesse|gerechtvaardigd belang",
    re.I,
)
NECESSARY = re.compile(
    r"strictly necessary|necessary|essential|required|notwendig|erforderlich|essen[sz]iell|nécessaires",
    re.I,
)
# A notice saying the site sets only necessary cookies: there is nothing to reject.
NECESSARY_ONLY = re.compile(
    r"(?:only|solely|exclusively) uses? (?:strictly )?(?:necessary|essential)|uses? only (?:strictly )?(?:necessary|essential) cookies|"
    r"(?:verwendet|nutzt|setzt|verwenden|nutzen|setzen) (?:nur|ausschließlich) (?:technisch )?(?:notwendige|erforderliche|essenzielle)",
    re.I,
)
# Bot walls and challenge pages. A match makes a site "unmeasurable": we never interact.
BOT_WALL = re.compile(
    r"just a moment|attention required|verify (?:that )?you are (?:a )?human|are you a robot|"
    r"captcha|unusual traffic|access denied|request blocked|bot detection|"
    r"checking your browser|please enable cookies and javascript|pardon our interruption|"
    r"sicherheitsüberprüfung|zugriff verweigert",
    re.I,
)


def normalize(text):
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def classify(label):
    """Return the consent role for a button label, or None. Pure and deterministic."""
    t = normalize(label)
    if not t or len(t) > MAX_LABEL:
        return None
    for role in ("pay", "reject", "save", "settings", "accept"):
        if _COMPILED[role].search(t):
            return role
    return None
