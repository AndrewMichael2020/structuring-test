"""fetcher.py

Encapsulates URL fetching and article text extraction (Playwright fallback).

This module contains the moved `_extract_article_text` logic from `accident_info.py` so
other modules can reuse it and `accident_info.py` becomes smaller.
"""
import os
import re
import requests
from bs4 import BeautifulSoup
from typing import Tuple
import logging

# attempt to reuse optional helper available elsewhere
try:
    from extract_captions import get_with_retries
except Exception:
    get_with_retries = None

PLAYWRIGHT_STEALTH = os.getenv("PLAYWRIGHT_STEALTH", "true").lower() in ("1", "true", "yes")

# module logger
logger = logging.getLogger(__name__)
try:
    # ensure library modules don't emit warnings when the app hasn't configured logging
    logger.addHandler(logging.NullHandler())
except Exception:
    pass


def _clean_text_blocks(txt: str) -> str:
    return re.sub(r"\s+", " ", txt).strip()


def extract_article_text(url: str, timeout: int = 25) -> Tuple[str, str, str]:
    """Return (full_text, focused_text, final_url).

    This preserves the behavior of the original `_extract_article_text` in `accident_info.py`.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (GitHub Codespaces; +metadata-extractor)"
    }
    resp = None
    html = ""
    final_url = url
    try:
        if get_with_retries is not None:
            resp = get_with_retries(url, timeout=timeout, headers=headers)
            html = resp.text
            final_url = getattr(resp, 'url', url) or url
        else:
            r = requests.get(url, headers=headers, timeout=timeout)
            resp = r
            html = r.text
            final_url = getattr(r, 'url', url) or url
    except Exception as e:
        logger.warning(f"Failed to fetch article HTML for {url}: {e}")
        return "", "", url

    soup = BeautifulSoup(html, "html.parser")
    body_text = ' '.join([t.strip() for t in soup.stripped_strings])
    if (resp is not None and getattr(resp, 'status_code', None) == 403) or len(body_text) < 100 or 'access denied' in body_text.lower() or '403 forbidden' in body_text.lower():
        try:
            from playwright.sync_api import sync_playwright
            logger.info(f"Static fetch appears blocked (status={getattr(resp,'status_code',None)}). Falling back to Playwright for {url}")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-blink-features=AutomationControlled'])
                context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36', viewport={'width':1200,'height':800}, extra_http_headers={'referer': url})
                try:
                    if PLAYWRIGHT_STEALTH:
                        context.add_init_script("() => { Object.defineProperty(navigator, 'webdriver', {get: () => false}); }")
                except Exception:
                    pass
                page = context.new_page()
                page.set_default_navigation_timeout(int(os.getenv('PLAYWRIGHT_NAV_TIMEOUT_MS','60000')))
                try:
                    page.goto(url, timeout=int(os.getenv('PLAYWRIGHT_NAV_TIMEOUT_MS','60000')), wait_until='domcontentloaded')
                    try:
                        page.wait_for_load_state('networkidle', timeout=int(os.getenv('PLAYWRIGHT_NAV_TIMEOUT_MS','60000')))
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning(f"Playwright navigation failed: {e}")
                    browser.close()
                    soup = BeautifulSoup(html, 'html.parser')
                    return _clean_text_blocks(' '.join([t.strip() for t in soup.stripped_strings])), _clean_text_blocks(' '.join([t.strip() for t in soup.stripped_strings])), url

                try:
                    page.evaluate("async () => { const delay=(ms)=>new Promise(r=>setTimeout(r,ms)); for(let y=0;y<document.body.scrollHeight;y+=window.innerHeight){ window.scrollTo(0,y); await delay(200);} await delay(300);}")
                except Exception:
                    pass
                rendered = page.content()
                try:
                    final_url = page.url or final_url
                except Exception:
                    pass
                browser.close()
                soup = BeautifulSoup(rendered, 'html.parser')
        except Exception as e:
            logger.warning(f"Playwright fallback failed: {e}")
            soup = BeautifulSoup(html, "html.parser")
            final_url = getattr(resp, 'url', url) or url

    # prefer article containers
    candidates = []
    for sel in [
        "article",
        "div.entry-content",
        "div.post-content",
        "main",
        "div#content",
        "div.content",
    ]:
        node = soup.select_one(sel)
        if node:
            candidates.append(node)

    node = candidates[0] if candidates else None
    if node is None:
        best = None
        best_len = 0
        for el in soup.find_all(['article', 'section', 'div']):
            ps = el.find_all('p')
            total = sum(len(p.get_text(' ', strip=True) or '') for p in ps)
            if total > best_len:
                best_len = total
                best = el
        if best is not None and best_len > 200:
            node = best
        else:
            node = soup.body or soup

    blocks = []
    title = None
    for h in node.find_all(['h1', 'h2']):
        t = h.get_text(' ', strip=True)
        if t and len(t) > 10:
            title = t
            break

    BOILER_TOKENS = [
        'subscribe now', 'sign in', 'create an account', 'unlimited online access',
        'get exclusive access', 'support local journalists', 'daily puzzles', 'share this story',
        'advertisement'
    ]

    seen_blocks = set()
    for el in node.find_all(["p", "h1", "h2", "h3", "li"]):
        t = el.get_text(" ", strip=True)
        if not t or len(t) < 30:
            continue
        tl = t.lower()
        if tl.startswith('conversation') or tl.startswith('comments') or 'comment by' in tl:
            break
        skip = False
        for token in BOILER_TOKENS:
            if token in tl:
                skip = True
                break
        if skip:
            continue
        if t in seen_blocks:
            continue
        seen_blocks.add(t)
        blocks.append(t)

    if not title:
        for h in soup.find_all(['h1', 'h2']):
            t = h.get_text(' ', strip=True)
            if t and len(t) > 10:
                title = t
                break

    STOP_TOKENS = ['enjoy insights', 'access articles from across canada', 'share your thoughts', 'join the conversation']
    STOP_PREFIXES = ['related:', 'you might also like', 'more on', 'from our partners']

    full_blocks = []
    for b in blocks:
        bl = b.lower()
        if re.match(r'^(author\b|by\s+[A-Z][\w\-\']+)', b.strip()):
            full_blocks.append(b)
            continue
        if any(bl.startswith(pfx) for pfx in STOP_PREFIXES):
            continue
        if any(tok in bl for tok in STOP_TOKENS):
            continue
        if len(b.strip()) < 30:
            if not (len(b.strip()) >= 30 or re.match(r'^[A-Z][\w\s\'’:-]+$', b.strip())):
                continue
        full_blocks.append(b)

    substantive_tokens = ['coroners', 'investigation', 'harness', 'leash', 'recovery', 'recovered', 'found', 'fell', 'died', 'death']
    last_idx = None
    for i, b in enumerate(full_blocks):
        bl = b.lower()
        if any(tok in bl for tok in substantive_tokens):
            last_idx = i
    if last_idx is not None:
        full_blocks = full_blocks[: last_idx + 1]

    para_blocks = []
    if title:
        para_blocks.append(title.strip())
    para_blocks.extend([b.strip() for b in full_blocks if b and b.strip()])
    full_text = "\n\n".join(para_blocks)
    full_text = re.sub(r"By signing up[\s\S]*?(?=\n\n|$)", "", full_text, flags=re.IGNORECASE)
    full_text = re.sub(r"\n{3,}", "\n\n", full_text)

    email_m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", full_text)
    if email_m:
        full_text = full_text[: email_m.end()].strip()
    else:
        paras = [p.strip() for p in full_text.split('\n\n') if p.strip()]
        last_para_idx = None
        for i, p in enumerate(paras):
            pl = p.lower()
            if any(tok in pl for tok in substantive_tokens):
                last_para_idx = i
        if last_para_idx is not None:
            paras = paras[: last_para_idx + 1]
            full_text = '\n\n'.join(paras)

    paras = [p.strip() for p in full_text.split('\n\n') if p.strip()]
    tail_run = 0
    for p in reversed(paras):
        if len(re.findall(r"\w+", p)) <= 12:
            tail_run += 1
        else:
            break
    if tail_run >= 3:
        paras = paras[:-tail_run]
    full_text = '\n\n'.join(paras)

    anchor_regex = re.compile(r"\b(slackline|fell|died|death|fatal|RCMP|Coroners|recovery|recover)\b", re.IGNORECASE)
    anchor_idx = None
    for i, b in enumerate(blocks):
        if anchor_regex.search(b):
            anchor_idx = i
            break
    if anchor_idx is not None:
        start = max(0, anchor_idx - 1)
        end = min(len(blocks), anchor_idx + 6)
        focused = blocks[start:end]
    else:
        focused = blocks

    CLEAN_TOKENS = ['enjoy insights', 'access articles from across canada', 'share your thoughts']
    final = []
    for b in focused:
        bl = b.lower()
        if any(tok in bl for tok in CLEAN_TOKENS):
            continue
        if len(b) < 60 and re.match(r"^[A-Z][\w\s'’:-]+$", b) and ' ' in b:
            continue
        final.append(b)

    text = " ".join(final)
    focused_text = _clean_text_blocks(text)
    full_text = _clean_text_blocks(full_text)
    return full_text, focused_text, final_url
