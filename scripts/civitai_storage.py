"""Small, safe helpers for model sidecar files and disk checks."""

import json
import os
import re
import shutil
import tempfile
from html import escape as html_escape

MODEL_EXTENSIONS = frozenset({'.pt', '.ckpt', '.pth', '.safetensors', '.th', '.zip', '.vae'})

# Tags kept when sanitizing CivitAI model descriptions. CivitAI ships real
# formatting in that field (images, code blocks, links), so escaping everything
# would destroy the rendering. Everything else, and every attribute not listed
# below, is dropped.
_SAFE_TAGS = frozenset({'a', 'b', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2',
                        'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img', 'li', 'ol', 'p',
                        'pre', 's', 'span', 'strong', 'sub', 'sup', 'table', 'tbody',
                        'td', 'th', 'thead', 'tr', 'u', 'ul', 'video', 'source'})

_SAFE_ATTRS = {'*': frozenset({'class', 'id', 'title', 'style'}),
               'a': frozenset({'href', 'target', 'rel'}),
               'img': frozenset({'src', 'alt', 'width', 'height', 'loading'}),
               'video': frozenset({'src', 'controls', 'poster', 'width', 'height'}),
               'source': frozenset({'src', 'type'}),
               'td': frozenset({'colspan', 'rowspan'}),
               'th': frozenset({'colspan', 'rowspan', 'scope'})}

# Only these URL schemes may appear in src/href/poster. Notably excludes
# javascript:, data: and vbscript:.
_SAFE_URL_SCHEME = re.compile(r'^(?:https?:|/|blob:|file:)', re.IGNORECASE)
_TAG = re.compile(r'<\s*(/?)\s*([a-zA-Z][a-zA-Z0-9]*)([^>]*?)(/?)\s*>', re.DOTALL)
_ATTR = re.compile(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', re.DOTALL)
# Dropped together with their content, otherwise the body would survive as visible
# text after the tags are stripped.
_DANGEROUS_BLOCK = re.compile(
    r'<\s*(script|style|svg|math|template|iframe|object|embed)\b[^>]*>.*?<\s*/\s*\1\s*>',
    re.IGNORECASE | re.DOTALL)


def _safe_attr_value(tag, name, value):
    """Allow only listed attributes, and only safe URL schemes for URL slots."""
    allowed = _SAFE_ATTRS.get(tag, ())
    if name not in allowed and name not in _SAFE_ATTRS['*']:
        return None
    value = value.strip()
    if value[:1] in ('"', "'") and value[-1:] == value[:1]:
        value = value[1:-1]
    if name in ('src', 'href', 'poster'):
        if not _SAFE_URL_SCHEME.match(value):
            return None
    return f'{name}="{html_escape(value, quote=True)}"'


def sanitize_model_html(raw):
    """Strip scripts and event handlers from CivitAI-supplied HTML.

    Keeps the formatting CivitAI renders on purpose. Any tag outside the
    allowlist is dropped, and attributes are filtered per tag. Escaping instead
    would show the raw markup as text and break the preview.
    """
    if not raw:
        return ''

    def replace(match):
        closing, raw_name, raw_attrs, self_closing = match.groups()
        name = raw_name.lower()
        if name not in _SAFE_TAGS:
            return ''
        if closing:
            return f'</{name}>'
        attrs = []
        for attr_match in _ATTR.finditer(raw_attrs or ''):
            attr_name, attr_value = attr_match.group(1).lower(), attr_match.group(2)
            # Belt and braces: an on* handler must never survive, even if the
            # allowlist above is edited carelessly later.
            if attr_name.startswith('on'):
                continue
            rendered = _safe_attr_value(name, attr_name, attr_value)
            if rendered:
                attrs.append(rendered)
        rendered_attrs = ((' ' + ' '.join(attrs)) if attrs else '')
        if self_closing:
            return f'<{name}{rendered_attrs} />'
        return f'<{name}{rendered_attrs}>'

    cleaned = _DANGEROUS_BLOCK.sub('', str(raw))
    cleaned = _TAG.sub(replace, cleaned)
    return cleaned.replace('<!--', '').replace('-->', '')


def is_model_sidecar(folder, name, entries=None):
    """Only inspect metadata belonging to an actual model in this folder."""
    if not name.lower().endswith('.json') or name.lower().endswith('.cm-info.json'):
        return False
    stem = name[:-5]
    try:
        return any(os.path.splitext(entry)[0].casefold() == stem.casefold()
                   and os.path.splitext(entry)[1].lower() in MODEL_EXTENSIONS
                   for entry in (entries if entries is not None else os.listdir(folder)))
    except OSError:
        return False


def read_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else default
    except (OSError, ValueError):
        return default


def write_json(path, value):
    """Replace a complete JSON file; a failed write leaves the old file intact."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.civitai-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, indent=4, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def enough_space(path, required, reserve=512 * 1024 * 1024):
    """Check the destination volume, accounting for a small working reserve."""
    existing = os.path.abspath(path)
    while not os.path.exists(existing):
        parent = os.path.dirname(existing)
        if parent == existing:
            return False, 0
        existing = parent
    free = shutil.disk_usage(existing).free
    return free >= required + reserve, free
