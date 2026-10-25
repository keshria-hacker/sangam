"""Design depth (open-design + impeccable salvage).

* Design-system contract: tokens (colour/type/spacing/radius/motion)
  + source evidence (each token traced to where it came from) + a
  version. Rebuilding from a CSS source re-derives tokens with
  evidence; a token with no source is reported, not silently kept.
* Critique/audit: MEASURED findings on HTML/CSS text — WCAG contrast
  ratios computed from actual colour pairs in the same rule, hairline
  (<1px) borders, hard-offset shadows, tiny body type, and fixed-width
  overflow risks — each with a selector/rule and a fix suggestion.
* bolder/quieter/distill: parameterised operations on a contract's
  tokens (weight steps, radius/spacing scale, palette reduction), not
  free-text re-prompts. Prototype generation itself stays on the
  existing Code Agent path, constrained by the contract's tokens.
"""
from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"--([a-z0-9-]+)\s*:\s*([^;]+);")
_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RULE_RE = re.compile(r"([^{]+)\{([^}]*)\}")
_PROP_RE = re.compile(r"([a-z-]+)\s*:\s*([^;]+)")

_TOKEN_GROUPS = (("color", ("color", "bg", "accent", "ink", "paper")),
                 ("typography", ("font", "type")),
                 ("spacing", ("space", "gap", "pad")),
                 ("radius", ("radius",)),
                 ("motion", ("motion", "duration", "ease")))


def _group_for(name: str) -> str:
    for group, prefixes in _TOKEN_GROUPS:
        if any(name.startswith(p) or f"-{p}-" in f"-{name}-" or name == p
               for p in prefixes):
            return group
    return "other"


def validate_contract(contract: object) -> list[dict]:
    errs: list[dict] = []

    def err(code: str, message: str, fix: str) -> dict:
        return {"code": code, "message": message, "supportedFixes": fix}

    if not isinstance(contract, dict):
        return [err("not-an-object", "Contract must be an object",
                    "Pass {name, version, tokens, evidence}.")]
    if not contract.get("name"):
        errs.append(err("missing-name", "contract.name is required",
                        "Name the design system."))
    version = contract.get("version", 1)
    if not isinstance(version, int) or version < 1:
        errs.append(err("bad-version", "version must be an int >= 1",
                        "Set version to 1 for a new contract, +1 on rebuild."))
    tokens = contract.get("tokens")
    if not isinstance(tokens, dict):
        errs.append(err("bad-tokens", "tokens must be an object of groups",
                        "Use tokens: {color: {...}, typography: {...}, ...}."))
        tokens = {}
    for group, group_tokens in tokens.items():
        if not isinstance(group_tokens, dict):
            errs.append(err("bad-token-group", f"tokens.{group} must be an object",
                            "Map token names to values."))
            continue
        for name, value in group_tokens.items():
            if group == "color" and isinstance(value, str) and not _HEX_RE.match(value.strip()):
                errs.append(err("bad-color",
                                f"tokens.color.{name}={value!r} is not a hex colour",
                                "Use #rgb or #rrggbb so contrast can be measured."))
    evidence = contract.get("evidence")
    if evidence is not None and not isinstance(evidence, list):
        errs.append(err("bad-evidence", "evidence must be a list",
                        "List {token, source} entries, or omit evidence."))
    return errs


def rebuild_from_css(css: str, source: str, name: str, version: int = 1) -> dict:
    """Extract ``--token: value`` custom properties from CSS text into
    a contract, each token carrying its source as evidence. Tokens
    found nowhere are simply absent — never carried over silently."""
    tokens: dict[str, dict[str, str]] = {}
    evidence = []
    for match in _TOKEN_RE.finditer(css or ""):
        token_name, value = match.group(1), match.group(2).strip()
        group = _group_for(token_name)
        tokens.setdefault(group, {})[token_name] = value
        evidence.append({"token": token_name, "source": source,
                         "excerpt": match.group(0)[:120]})
    return {"name": name, "version": version, "tokens": tokens,
            "evidence": evidence}


# ---------------------------------------------------------------- contrast

def _channel(c: float) -> float:
    c /= 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two hex colours."""
    l1, l2 = _luminance(fg), _luminance(bg)
    light, dark = max(l1, l2), min(l1, l2)
    return (light + 0.05) / (dark + 0.05)


def _is_gold(hex_color: str) -> bool:
    """Kinpaku rule (impeccable's bundled language): gold accents are
    for large display only — small gold text on paper fails contrast
    and must swap to a darker tone."""
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return r > 150 and g > 110 and b < 120 and r >= g >= b


def critique_prototype(html_or_css: str, contract: dict | None = None) -> list[dict]:
    """Measured critique of a prototype's HTML/CSS text.

    Finds colour pairs in the same CSS rule (or inline style) and
    measures their ratio; flags hairlines, hard shadows, tiny type and
    fixed-width overflow risks. Findings carry the rule, the measured
    value and a fix — never a vibe judgement without a number.
    """
    findings: list[dict] = []
    text = html_or_css or ""
    rules: list[tuple[str, str]] = []
    for match in _RULE_RE.finditer(text):
        rules.append((match.group(1).strip(), match.group(2)))
    # Inline styles: treat the element tag as the selector.
    for match in re.finditer(r"<[a-zA-Z][^>]*style=\"([^\"]+)\"", text):
        rules.append(("(inline style)", match.group(1)))
    for selector, body in rules:
        props = {k.strip(): v.strip() for k, v in _PROP_RE.findall(body)}
        fg = props.get("color")
        bg = props.get("background-color") or props.get("background")
        font_size = props.get("font-size", "")
        size_px = None
        m = re.match(r"([\d.]+)px", font_size)
        if m:
            size_px = float(m.group(1))
        if fg and bg:
            fg_m = re.search(r"#[0-9a-fA-F]{3,6}", fg)
            bg_m = re.search(r"#[0-9a-fA-F]{3,6}", bg)
            if fg_m and bg_m:
                ratio = contrast_ratio(fg_m.group(0), bg_m.group(0))
                if ratio < 4.5:
                    findings.append({
                        "rule": selector, "check": "contrast",
                        "severity": "error",
                        "measured": f"contrast {ratio:.2f}:1 "
                                    f"({fg_m.group(0)} on {bg_m.group(0)})",
                        "fix": "Darken the text or lighten the background "
                               "until the ratio reaches 4.5:1 for body text."})
                if size_px is not None and size_px < 18 and _is_gold(fg_m.group(0)):
                    findings.append({
                        "rule": selector, "check": "gold-small-text",
                        "severity": "warning",
                        "measured": f"gold {fg_m.group(0)} at {size_px:g}px",
                        "fix": "Keep gold for large display only; swap small "
                               "text to a darker verdigris/ink tone."})
        for prop, value in props.items():
            if prop.startswith("border") and "width" in prop:
                wm = re.match(r"([\d.]+)px", value)
                if wm and float(wm.group(1)) < 1:
                    findings.append({"rule": selector, "check": "hairline",
                                     "severity": "warning",
                                     "measured": f"border width {value}",
                                     "fix": "Use a 1px hairline (sub-pixel borders "
                                            "render inconsistently)."})
            if prop == "box-shadow" and value != "none":
                nums = [float(x) for x in re.findall(r"(-?[\d.]+)px", value)]
                # box-shadow: offset-x offset-y blur spread colour.
                # Hard = blur 0; large = offset beyond 8px.
                if (len(nums) >= 2 and (abs(nums[0]) > 8 or abs(nums[1]) > 8)) \
                        or (len(nums) >= 3 and nums[2] == 0):
                    findings.append({"rule": selector, "check": "hard-shadow",
                                     "severity": "warning",
                                     "measured": f"box-shadow {value}",
                                     "fix": "Soften the shadow (blur > 0, offset "
                                            "<= 8px) or drop it for a hairline."})
            if prop == "font-size":
                m2 = re.match(r"([\d.]+)px", value)
                if m2 and float(m2.group(1)) < 12:
                    findings.append({"rule": selector, "check": "tiny-type",
                                     "severity": "warning",
                                     "measured": f"font-size {value}",
                                     "fix": "Raise body text to at least 12px."})
            if prop == "width":
                m3 = re.match(r"([\d.]+)px", value)
                if m3 and float(m3.group(1)) > 1200:
                    findings.append({"rule": selector, "check": "overflow-risk",
                                     "severity": "warning",
                                     "measured": f"fixed width {value}",
                                     "fix": "Use max-width + width: 100% so the "
                                            "layout cannot overflow small screens."})
    if contract is not None:
        # Contract drift: colours used but not in the contract.
        known = {v.lower() for group in contract.get("tokens", {}).values()
                 if isinstance(group, dict) for v in group.values()
                 if isinstance(v, str)}
        used = {c.lower() for c in re.findall(r"#[0-9a-fA-F]{3,6}", text)}
        for colour in sorted(used - known):
            findings.append({"rule": "(prototype)", "check": "off-contract-colour",
                             "severity": "info",
                             "measured": f"colour {colour} not in contract tokens",
                             "fix": "Add it to the contract with source "
                                    "evidence, or swap to a contract token."})
    return findings


# ---------------------------------------------------------------- transforms

def _darken(hex_color: str, amount: float = 0.15) -> str:
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return hex_color
    return "#%02x%02x%02x" % tuple(max(0, int(c * (1 - amount))) for c in (r, g, b))


def _is_grey(hex_color: str) -> bool:
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return True
    return max(r, g, b) - min(r, g, b) <= 12


def transform_contract(contract: dict, operation: str) -> dict:
    """Parameterised bolder/quieter/distill on contract tokens.

    bolder: weights +100 (cap 900), radius -2px (floor 0), colours
    darkened 15%. quieter: weights -100 (floor 300), radius +2px,
    spacing x1.25. distill: shadows off, radius 0, non-accent chromatic
    colours dropped (kept: greys + the first colour token, the accent).
    Returns {contract, changes}.
    """
    if operation not in ("bolder", "quieter", "distill"):
        raise ValueError("operation must be bolder, quieter or distill")
    import copy
    new = copy.deepcopy(contract)
    tokens = new.setdefault("tokens", {})
    changes: list[str] = []
    typo = tokens.get("typography", {})
    for key, value in list(typo.items()):
        if "weight" in key and str(value).isdigit():
            w = int(value)
            if operation == "bolder":
                typo[key] = str(min(900, w + 100))
            elif operation == "quieter":
                typo[key] = str(max(300, w - 100))
            if typo[key] != str(value):
                changes.append(f"typography.{key}: {value} -> {typo[key]}")
    radius = tokens.get("radius", {})
    for key, value in list(radius.items()):
        m = re.match(r"([\d.]+)px", str(value))
        if not m:
            continue
        num = float(m.group(1))
        if operation == "bolder":
            new_v = f"{max(0, num - 2):g}px"
        elif operation == "quieter":
            new_v = f"{num + 2:g}px"
        elif operation == "distill":
            new_v = "0px"
        else:
            continue
        radius[key] = new_v
        changes.append(f"radius.{key}: {value} -> {new_v}")
    spacing = tokens.get("spacing", {})
    if operation == "quieter":
        for key, value in list(spacing.items()):
            m = re.match(r"([\d.]+)px", str(value))
            if m:
                new_v = f"{float(m.group(1)) * 1.25:g}px"
                spacing[key] = new_v
                changes.append(f"spacing.{key}: {value} -> {new_v}")
    colors = tokens.get("color", {})
    if operation == "bolder":
        for key, value in list(colors.items()):
            if _HEX_RE.match(str(value).strip()):
                colors[key] = _darken(str(value).strip())
                changes.append(f"color.{key}: {value} -> {colors[key]}")
    if operation == "distill":
        accent_key = next(iter(colors), None)
        for key in list(colors):
            value = str(colors[key]).strip()
            if _HEX_RE.match(value) and not _is_grey(value) and key != accent_key:
                del colors[key]
                changes.append(f"color.{key}: removed (distilled to accent + neutrals)")
        motion = tokens.get("motion", {})
        for key in list(motion):
            if "shadow" in key:
                motion[key] = "none"
                changes.append(f"motion.{key}: removed shadow")
    new["version"] = int(contract.get("version", 1)) + 1
    return {"contract": new, "changes": changes}
