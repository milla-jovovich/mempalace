#!/usr/bin/env python3
"""
burgess.py — Burgess Principle Human-Impact Scanner
====================================================

Scans text for content that touches areas affecting real people.
Pure heuristic — no LLM required. Same pattern as general_extractor.py.

Based on the Burgess Principle by Lewis James Burgess:
"Was a human member of the team able to personally review
 the specific facts of my situation?"

When content is filed into the palace, the scanner checks whether it
touches any of the seven human-impact areas. If so, it tags the content
and recommends human review before the changes are shipped.

Human-Impact Areas:
  1. ACCESSIBILITY  — UI, ARIA, screen readers, keyboard nav, alt text
  2. PRIVACY        — personal data, tracking, consent, GDPR, DSAR
  3. SECURITY       — auth, credentials, encryption, input validation
  4. USER_LANGUAGE   — error messages, notifications, onboarding text
  5. BILLING        — payment flows, pricing, subscriptions, refunds
  6. AUTOMATED_DECISIONS — scoring, ranking, filtering, approving/denying
  7. DEPLOYMENT     — production changes, feature flags, migrations

Attribution:
  The Burgess Principle (https://github.com/ljbudgie/burgess-principle)
  UK Certification Mark: UK00004343685
  Free for personal use under MIT licence.
"""

import re
from typing import Dict, List, Tuple


# =============================================================================
# MARKER SETS — One per human-impact area
# =============================================================================

ACCESSIBILITY_MARKERS = [
    r"\baria[-_]?\b",
    r"\bscreen[\s-]?reader\b",
    r"\bkeyboard[\s-]?nav\b",
    r"\balt[\s-]?text\b",
    r"\bfocus[\s-]?(ring|trap|management|order|indicator)\b",
    r"\btab[\s-]?index\b",
    r"\btabindex\b",
    r"\bcolor[\s-]?contrast\b",
    r"\ba11y\b",
    r"\baccessib\w+\b",
    r"\bwcag\b",
    r"\bsection[\s-]?508\b",
    r"\bskip[\s-]?(to[\s-]?)?content\b",
    r"\brole=",
    r"\bvisually[\s-]?hidden\b",
    r"\bsr[-_]?only\b",
    r"\breduced[\s-]?motion\b",
    r"\bprefers[-_]reduced[-_]motion\b",
    r"\bhearing[\s-]?(aid|impair|loss|loop)\b",
    r"\bdeaf\b",
    r"\bblind\b",
    r"\bdyslexia\b",
    r"\bdyslexi[ac]\b",
    r"\bautisx?\w*\b",
    r"\breasonable[\s-]?adjust\w+\b",
    r"\bequality[\s-]?act\b",
    r"\bada\s+complian\w+\b",
    r"\bfont[\s-]?size\b",
    r"\bzoom\b.*\blayout\b",
]

PRIVACY_MARKERS = [
    r"\bpersonal[\s-]?data\b",
    r"\bgdpr\b",
    r"\bdsar\b",
    r"\bdata[\s-]?subject\b",
    r"\bconsent\b",
    r"\bcookie\b",
    r"\btracking\b",
    r"\banalytics\b",
    r"\bdata[\s-]?retention\b",
    r"\bdata[\s-]?processing\b",
    r"\bdata[\s-]?collection\b",
    r"\bpii\b",
    r"\bpersonally[\s-]?identif\w+\b",
    r"\bright[\s-]?to[\s-]?(be[\s-]?)?forget\w*\b",
    r"\bdata[\s-]?portability\b",
    r"\bprivacy[\s-]?polic\w+\b",
    r"\bopt[\s-]?(in|out)\b",
    r"\bdo[\s-]?not[\s-]?track\b",
    r"\bccpa\b",
    r"\bpipeda\b",
    r"\barticle[\s-]?22\b",
    r"\bdata[\s-]?protection\b",
    r"\bsurveillance\b",
    r"\bfingerprint\w*\b",
    r"\buser[\s-]?profil\w+\b",
    r"\bdata[\s-]?breach\b",
    r"\bencrypt\w+\b.*\b(personal|user|customer)\b",
]

SECURITY_MARKERS = [
    r"\bauth\w*\b",
    r"\bpassword\b",
    r"\bcredential\b",
    r"\bencrypt\w*\b",
    r"\bdecrypt\w*\b",
    r"\btoken\b",
    r"\bjwt\b",
    r"\boauth\b",
    r"\bsso\b",
    r"\bcors\b",
    r"\bcsp\b",
    r"\bxss\b",
    r"\bcsrf\b",
    r"\bsql[\s-]?inject\w*\b",
    r"\binput[\s-]?valid\w*\b",
    r"\bsaniti[sz]\w+\b",
    r"\bescap\w+\b.*\binput\b",
    r"\brate[\s-]?limit\w*\b",
    r"\bbrute[\s-]?force\b",
    r"\bvulnerabil\w+\b",
    r"\bpermission\b",
    r"\brole[\s-]?based\b",
    r"\baccess[\s-]?control\b",
    r"\brbac\b",
    r"\bapi[\s-]?key\b",
    r"\bsecret\b",
    r"\bcertificat\w+\b",
    r"\btls\b",
    r"\bssl\b",
    r"\bhttps\b",
]

USER_LANGUAGE_MARKERS = [
    r"\berror[\s-]?messag\w+\b",
    r"\bnotification\b",
    r"\bonboarding\b",
    r"\bwelcome[\s-]?(messag|screen|page|text)\w*\b",
    r"\btooltip\b",
    r"\bplaceholder\b.*\btext\b",
    r"\blabel\b",
    r"\b(help|info)[\s-]?text\b",
    r"\bterms[\s-]?of[\s-]?service\b",
    r"\bprivacy[\s-]?notice\b",
    r"\bcopy[\s-]?(writ|text|string)\w*\b",
    r"\bi18n\b",
    r"\bl10n\b",
    r"\btranslat\w+\b",
    r"\blocali[sz]\w+\b",
    r"\bconfirmation[\s-]?(messag|dialog|text)\w*\b",
    r"\bwarning[\s-]?(messag|text|dialog)\w*\b",
    r"\buser[\s-]?facing\b",
    r"\bdisplay[\s-]?text\b",
    r"\bempty[\s-]?state\b",
    r"\b(success|failure)[\s-]?messag\w+\b",
]

BILLING_MARKERS = [
    r"\bpayment\b",
    r"\bbilling\b",
    r"\binvoic\w+\b",
    r"\bsubscription\b",
    r"\bpric\w+\b",
    r"\bcost\b",
    r"\bcharg\w+\b",
    r"\brefund\b",
    r"\btrial[\s-]?(period|expir|end)\w*\b",
    r"\bfree[\s-]?tier\b",
    r"\bcredit[\s-]?card\b",
    r"\bstripe\b",
    r"\bpaypal\b",
    r"\bcurrenc\w+\b",
    r"\btax\b",
    r"\bvat\b",
    r"\bdiscount\b",
    r"\bcoupon\b",
    r"\bpromo[\s-]?code\b",
    r"\bupgrade\b.*\bplan\b",
    r"\bdowngrade\b",
    r"\bcancell?\w*\b",
    r"\bmetered\b",
    r"\busage[\s-]?based\b",
    r"\bpay[\s-]?per[\s-]?use\b",
]

AUTOMATED_DECISION_MARKERS = [
    r"\bscor\w+\b.*\b(user|customer|applicant|candidate)\b",
    r"\brank\w*\b.*\b(user|content|result|candidate)\b",
    r"\bfilter\w*\b.*\b(user|content|applicant)\b",
    r"\brecommend\w+\b",
    r"\bapprov\w+\b.*\bautomat\w*\b",
    r"\bden\w+\b.*\bautomat\w*\b",
    r"\bautomat\w+\b.*\bdecision\b",
    r"\bcredit[\s-]?check\b",
    r"\bcredit[\s-]?scor\w+\b",
    r"\brisk[\s-]?(assess|scor|evaluat)\w+\b",
    r"\bcontent[\s-]?moderat\w+\b",
    r"\bhiring[\s-]?filter\b",
    r"\beligib\w+\b.*\bautomat\w*\b",
    r"\balgorithm\w*\b.*\b(decide|decision|determine)\b",
    r"\bml[\s-]?model\b.*\b(predict|classif|decide)\b",
    r"\bbias\b",
    r"\bfairness\b",
    r"\bdiscriminat\w+\b",
    r"\bblacklist\b",
    r"\bwhitelist\b",
    r"\bblock\w*\b.*\buser\b",
    r"\bban\b.*\buser\b",
    r"\bsuspend\w*\b.*\b(user|account)\b",
]

DEPLOYMENT_MARKERS = [
    r"\bproduction\b",
    r"\bprod[\s-]?env\w*\b",
    r"\bfeature[\s-]?flag\b",
    r"\brollout\b",
    r"\brollback\b",
    r"\bmigrat\w+\b",
    r"\bschema[\s-]?change\b",
    r"\bbreaking[\s-]?change\b",
    r"\bdowntime\b",
    r"\bmaintenance[\s-]?window\b",
    r"\bblue[\s-]?green\b",
    r"\bcanary\b",
    r"\ba[\s/]?b[\s-]?test\w*\b",
    r"\binfrastructure\b",
    r"\bterraform\b",
    r"\bkubernetes\b",
    r"\bdeploy\w+\b",
    r"\bci[\s/]?cd\b",
    r"\bpipeline\b",
    r"\bmonitoring\b",
    r"\balerting\b",
    r"\bthreshold\b.*\b(alert|monitor|metric)\b",
    r"\bsla\b",
    r"\buptime\b",
    r"\bincident\b",
]

ALL_IMPACT_AREAS = {
    "accessibility": ACCESSIBILITY_MARKERS,
    "privacy": PRIVACY_MARKERS,
    "security": SECURITY_MARKERS,
    "user_language": USER_LANGUAGE_MARKERS,
    "billing": BILLING_MARKERS,
    "automated_decisions": AUTOMATED_DECISION_MARKERS,
    "deployment": DEPLOYMENT_MARKERS,
}

# Human-readable descriptions for each area
AREA_DESCRIPTIONS = {
    "accessibility": "Accessibility — changes affecting people with disabilities or assistive technology users",
    "privacy": "Privacy & Personal Data — collection, storage, or processing of personal information",
    "security": "Security — authentication, authorization, or data protection changes",
    "user_language": "User-Facing Language — text that real people read (errors, notifications, onboarding)",
    "billing": "Pricing & Billing — payment flows, subscription logic, or financial calculations",
    "automated_decisions": "Automated Decisions — algorithms that score, rank, filter, or decide for real people",
    "deployment": "Deployment & Infrastructure — production environment or release configuration changes",
}

# Recommended reviewer for each area
AREA_REVIEWERS = {
    "accessibility": "an accessibility specialist or someone who uses assistive technology",
    "privacy": "a privacy/data-protection officer or legal team",
    "security": "a security engineer",
    "user_language": "a UX writer or product designer",
    "billing": "a product manager and someone from finance",
    "automated_decisions": "a domain expert and someone from the ethics/fairness team",
    "deployment": "a DevOps engineer or SRE",
}


# =============================================================================
# SCANNER
# =============================================================================


def _score_area(text: str, markers: list) -> Tuple[float, List[str]]:
    """Score text against a set of markers. Returns (score, matched_patterns)."""
    text_lower = text.lower()
    score = 0.0
    matched = []
    for pattern in markers:
        hits = re.findall(pattern, text_lower)
        if hits:
            score += len(hits)
            matched.append(pattern)
    return score, matched


def scan_human_impact(text: str, threshold: float = 1.0) -> Dict:
    """
    Scan text for human-impact areas.

    Returns a dict with:
      - flagged: bool — True if any area was flagged
      - areas: list of dicts with area name, description, score, reviewer
      - summary: human-readable summary
      - burgess_question: the core principle question

    threshold: minimum score to flag an area (default: 1.0 = at least one match)
    """
    flagged_areas = []

    for area_name, markers in ALL_IMPACT_AREAS.items():
        score, matched = _score_area(text, markers)
        if score >= threshold:
            flagged_areas.append({
                "area": area_name,
                "description": AREA_DESCRIPTIONS[area_name],
                "score": score,
                "match_count": int(score),
                "reviewer": AREA_REVIEWERS[area_name],
            })

    # Sort by score descending
    flagged_areas.sort(key=lambda x: x["score"], reverse=True)

    flagged = len(flagged_areas) > 0

    if flagged:
        area_names = [a["area"] for a in flagged_areas]
        summary = (
            f"⚠️ Human-impact review recommended. "
            f"This content touches {len(flagged_areas)} area(s): "
            f"{', '.join(area_names)}. "
            f"A human should review the specific implications before shipping."
        )
    else:
        summary = "No human-impact areas detected. ✅"

    return {
        "flagged": flagged,
        "areas": flagged_areas,
        "summary": summary,
        "burgess_question": (
            "Was a human member of the team able to personally review "
            "the specific facts of my situation?"
        ),
    }


def format_review_block(scan_result: Dict) -> str:
    """
    Format a scan result as a human-readable review block.
    Matches the output format from hermes-agent's coding-agent-review skill.
    """
    lines = ["## 🔍 Human-Impact Review (Burgess Principle)", ""]

    if not scan_result["flagged"]:
        lines.append("No human-impact areas were affected by this content. ✅")
        return "\n".join(lines)

    lines.append(
        "The following areas affect real people and should be "
        "reviewed by a human before shipping:"
    )
    lines.append("")

    for area in scan_result["areas"]:
        lines.append(f"- **{area['description']}** ({area['match_count']} signal(s))")

    lines.append("")
    reviewers = set(a["reviewer"] for a in scan_result["areas"])
    lines.append(f"**Recommendation**: Review by {'; '.join(reviewers)}.")

    lines.append("")
    lines.append(
        f'> *"{scan_result["burgess_question"]}"*  '
    )
    lines.append(
        "> — The Burgess Principle "
        "(https://github.com/ljbudgie/burgess-principle)"
    )

    return "\n".join(lines)
