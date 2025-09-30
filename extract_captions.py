#!/usr/bin/env python3
"""
extract_captions.py

1. Extracts image captions from static HTML.
2. Optionally runs OCR fallback using Playwright if captions are JS-rendered.
3. Downloads all relevant images into an artifacts folder.
4. Exports structured JSON for downstream OCR/LLM analysis.
"""

import re
import os
import io
import json
import time
import hashlib
import requests
import signal
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from datetime import datetime
from PIL import Image
from PIL import ImageOps, ImageStat

# Playwright tuning (can be overridden via env vars). Enforce a maximum of 25s (25000 ms).
_pw_nav_env = int(os.getenv("PLAYWRIGHT_NAV_TIMEOUT_MS", "25000"))
PLAYWRIGHT_NAV_TIMEOUT_MS = min(_pw_nav_env, 25000)
PLAYWRIGHT_RENDER_WAIT_S = float(os.getenv("PLAYWRIGHT_RENDER_WAIT_S", "3"))

# OCR preprocessing toggle
OCR_PREPROCESS = os.getenv("OCR_PREPROCESS", "false").lower() in ("1", "true", "yes")

# tokens that indicate an image is likely a decorative logo/wordmark/affiliate asset and should be
# skipped at extraction time to avoid downloading and sending to expensive OCR/LLM stages.
IRRELEVANT_TOKENS = set(t.strip().lower() for t in os.getenv('IRRELEVANT_TOKENS', 'logo,wordmark,badge,brand,promo,affiliate,watermark,trademark,ads,advert,avatar,favicon,icon,share,share-icons,share-icon,social,button,close,thumb,thumbnail,sprite,inline-icon').split(','))

# Minimum image dimensions to keep (filter out marketing/avatars)
MIN_IMG_WIDTH = 300
MIN_IMG_HEIGHT = 200

# Optional OCR fallback (Playwright)
try:
    from playwright.sync_api import sync_playwright
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# configure logging
LOG_LEVEL = os.getenv("EXTRACT_CAPTIONS_LOG_LEVEL", "INFO")
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger(__name__)

# requests session with retries
def _make_session(retries: int = 2, backoff: float = 0.5) -> requests.Session:
    s = requests.Session()
    retry = Retry(total=retries, backoff_factor=backoff,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET", "POST"])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

_session = _make_session()

def get_with_retries(url: str, timeout: int = 20, headers: dict | None = None) -> requests.Response:
    headers = headers or {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
    # Per-URL attempt tracking so we don't keep hammering an unresponsive host
    MAX_FETCH_ATTEMPTS = int(os.getenv("MAX_FETCH_ATTEMPTS", "2"))
    if not hasattr(get_with_retries, "_attempts"):
        get_with_retries._attempts = {}

    attempts = get_with_retries._attempts.get(url, 0)
    if attempts >= MAX_FETCH_ATTEMPTS:
        raise RuntimeError(f"Max fetch attempts reached for {url} ({attempts} tries); skipping further requests")

    try:
        logger.debug("HTTP GET %s (timeout=%s) attempt=%d", url, timeout, attempts + 1)
        resp = _session.get(url, timeout=timeout, headers=headers)
        # reset attempt counter on success
        if url in get_with_retries._attempts:
            del get_with_retries._attempts[url]
        return resp
    except requests.exceptions.ReadTimeout as e:
        logger.warning("ReadTimeout for %s (timeout=%s): %s", url, timeout, e)
        # increment attempt counter
        get_with_retries._attempts[url] = attempts + 1
        # try one more time with a longer timeout if we haven't exhausted attempts
        if get_with_retries._attempts[url] < MAX_FETCH_ATTEMPTS:
            try:
                logger.debug("Retrying %s with longer timeout", url)
                resp = _session.get(url, timeout=timeout * 2, headers=headers)
                if url in get_with_retries._attempts:
                    del get_with_retries._attempts[url]
                return resp
            except Exception as e2:
                logger.error("Retry failed for %s: %s", url, e2)
                get_with_retries._attempts[url] = get_with_retries._attempts.get(url, 1)
                raise
        else:
            logger.error("Max retries exhausted for %s", url)
            raise
    except Exception as e:
        logger.error("HTTP request failed for %s: %s", url, e)
        # increment attempts for other failures as well
        get_with_retries._attempts[url] = attempts + 1
        raise


# -------------------- Utilities --------------------
def slugify(text: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]', '_', text)

def clean_caption(text: str) -> str:
    text = re.sub(r'\|\s*Image:.*$', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def hash_url(url: str) -> str:
    return hashlib.md5(url.encode('utf-8')).hexdigest()[:10]

def is_stray_url(img_url: str) -> bool:
    if img_url.startswith("data:image"):
        return True
    low = img_url.lower()
    if any(bad in low for bad in ["gravatar.com", "avatar", "favicon"]):
        return True
    # also treat explicit small-looking tokens as stray in the URL
    if any(tok in low for tok in IRRELEVANT_TOKENS):
        return True
    return False


def contains_irrelevant_token(text: str | None) -> bool:
    if not text:
        return False
    tl = text.lower()
    for tok in IRRELEVANT_TOKENS:
        if tok and tok in tl:
            return True
    return False

def is_stray_file(filepath: str) -> bool:
    """Reject tiny or broken files based on actual pixel dimensions."""
    try:
        with Image.open(filepath) as img:
            w, h = img.size
            return (w < MIN_IMG_WIDTH or h < MIN_IMG_HEIGHT)
    except Exception:
        return True


# -------------------- Image Download --------------------
def download_image(img_url: str, folder: str) -> str | None:
    try:
        if is_stray_url(img_url):
            return None

        h = hash_url(img_url)
        ext = os.path.splitext(urlparse(img_url).path)[-1]
        if not ext or len(ext) > 5:
            ext = ".jpg"
        filename = f"{h}{ext}"
        filepath = os.path.join(folder, filename)
        if os.path.exists(filepath):
            if is_stray_file(filepath):
                os.remove(filepath)
                return None
            return filepath

        r = requests.get(img_url, timeout=15)
        r.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(r.content)

        if is_stray_file(filepath):
            print(f"[INFO] ⏩ Skipping small/non-relevant image: {img_url}")
            os.remove(filepath)
            return None

        return filepath
    except Exception:
        return None


# -------------------- HTML Caption Extraction --------------------
def extract_html_captions(url: str):
    try:
        resp = get_with_retries(url, timeout=20)
        html = resp.text
    except Exception as e:
        logger.warning("Static fetch failed for %s: %s", url, e)
        if OCR_AVAILABLE:
            logger.info("Falling back to Playwright-rendered capture for %s", url)
            return extract_ocr_captions(url)
        else:
            logger.error("Playwright not available; cannot render JS for %s", url)
            return []

    soup = BeautifulSoup(html, "html.parser")

    # --- Landing-page / redirect detection heuristics ---
    def is_landing_page(html_text: str, soup_obj: BeautifulSoup, resp_obj: requests.Response) -> tuple[bool, str]:
        """Detect likely landing/affiliate/redirect pages to avoid large irrelevant downloads.
        Returns (is_landing, reason).
        Heuristics used:
        - meta refresh or immediate JS redirect
        - extremely low visible text content compared to number of images (low text-to-image ratio)
        - presence of typical landing keywords (subscribe, sign up, click here, get started, promo, affiliate)
        - excessive number of iframes or scripts from ad domains
        - redirect chain (response.history length)
        """
        try:
            # meta refresh
            meta_refresh = soup_obj.find('meta', attrs={'http-equiv': lambda v: v and v.lower() == 'refresh'})
            if meta_refresh:
                return True, 'meta-refresh'

            # JS redirect pattern (very simple): location.replace or location.href in inline scripts near top
            top_scripts = ' '.join([s.get_text(' ', strip=True) or '' for s in soup_obj.find_all('script', limit=6)])
            if re.search(r"location\.href\s*=|location\.replace\(|window\.location", top_scripts, re.IGNORECASE):
                return True, 'js-redirect'

            # redirect chain
            try:
                if hasattr(resp_obj, 'history') and resp_obj.history and len(resp_obj.history) > 0:
                    # treat as suspicious only if final domain is different and history length > 1
                    first = urlparse(resp_obj.history[0].url).netloc if resp_obj.history and resp_obj.history[0].url else None
                    final = urlparse(resp_obj.url).netloc
                    if first and final and first != final and len(resp_obj.history) >= 1:
                        return True, 'redirect-chain'
            except Exception:
                pass

            # visible text length vs images
            texts = [t.strip() for t in soup_obj.stripped_strings]
            visible_text = ' '.join(texts)
            text_len = len(visible_text)
            img_count = len(soup_obj.find_all('img'))
            # if text_len is tiny and many images (e.g., landing/article-preview) treat as landing
            if text_len < 200 and img_count > 8:
                return True, 'low-text-many-images'

            # presence of landing keywords in body
            body_text = visible_text.lower()
            landing_tokens = ['subscribe', 'sign up', 'get started', 'click here', 'sponsored', 'advertisement', 'promo', 'buy now', 'limited time']
            for t in landing_tokens:
                if t in body_text:
                    return True, f'landing-token:{t}'

            # too many iframes (ads), many different third-party script srcs
            iframes = soup_obj.find_all('iframe')
            if len(iframes) > 6:
                return True, 'many-iframes'

            script_srcs = [s.get('src') for s in soup_obj.find_all('script') if s.get('src')]
            third_party = 0
            for src in script_srcs:
                try:
                    parsed = urlparse(src)
                    host = parsed.netloc
                    if host and host not in urlparse(url).netloc:
                        third_party += 1
                except Exception:
                    continue
            if third_party > 10:
                return True, 'many-third-party-scripts'

            return False, ''
        except Exception:
            return False, ''

    landing, reason = is_landing_page(html, soup, resp)
    if landing:
        logger.warning("Detected landing/fake/redirect page for %s -> skipping extraction (reason=%s)", url, reason)
        return []
    results = []

    def _collect_candidates(soup, html_text):
        seen = []

        # from <img> and <source>
        for img in soup.find_all(['img', 'source']):
            # source may have srcset
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or img.get('data-original')
            if not src:
                ss = img.get('srcset') or img.get('data-srcset') or img.get('data-lazy-srcset')
                if ss:
                    # pick last candidate in srcset
                    try:
                        src = [p.strip().split()[0] for p in ss.split(',') if p.strip()][-1]
                    except Exception:
                        src = None
            if src:
                u = urljoin(url, src)
                if u not in seen:
                    seen.append(u)

        # noscript blocks often contain fallback <img>
        for nos in soup.find_all('noscript'):
            try:
                inner = BeautifulSoup(nos.decode_contents(), 'html.parser')
                for img in inner.find_all('img'):
                    src = img.get('src') or img.get('data-src')
                    if src:
                        u = urljoin(url, src)
                        if u not in seen:
                            seen.append(u)
            except Exception:
                continue

        # OG and link rel
        og = soup.find('meta', property='og:image')
        if og and og.get('content'):
            u = urljoin(url, og.get('content'))
            if u not in seen:
                seen.append(u)
        link_img = soup.find('link', rel='image_src')
        if link_img and link_img.get('href'):
            u = urljoin(url, link_img.get('href'))
            if u not in seen:
                seen.append(u)

        # inline style background-images
        for el in soup.find_all(style=True):
            style = el['style']
            m = re.search(r'url\(([^)]+)\)', style)
            if m:
                raw = m.group(1).strip('"\'')
                u = urljoin(url, raw)
                if u not in seen:
                    seen.append(u)

        # JSON-LD and other script-embedded images
        for script in soup.find_all('script', type=lambda x: x in (None, 'application/ld+json')):
            text = script.string or script.get_text(' ', strip=True)
            if not text:
                continue
            # quick url regex
            for match in re.findall(r'https?://[^\s\"\'>)]+', text):
                if 'wp-content/uploads' in match or match.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    u = match
                    if u not in seen:
                        seen.append(u)

        # fallback: raw html search for wp-content/uploads
        for m in re.findall(r'https?://[^\s\"\'>)]+wp-content/uploads[^\s\"\'>)]+', html_text):
            u = m
            if u not in seen:
                seen.append(u)

        return seen

    candidates = _collect_candidates(soup, html)

    # map candidate -> caption (try to attach figcaption / alt / nearby paragraph)
    for c in candidates:
        if is_stray_url(c):
            continue
        caption = None
        # try to find an <img> with this src
        img = soup.find('img', src=lambda s: s and (c.endswith(s) or s in c or c in s))
        if not img:
            # try match by filename
            fname = os.path.basename(urlparse(c).path)
            img = soup.find('img', src=lambda s: s and fname in s)
        if img:
            fig = img.find_parent('figure')
            if fig and fig.find('figcaption'):
                caption = fig.find('figcaption').get_text(strip=True)
            else:
                # nearby paragraph
                sib = img.find_next_sibling()
                if sib and sib.name == 'p':
                    caption = sib.get_text(strip=True)
                else:
                    caption = img.get('alt') or None

        if not caption:
            # try to find a fig with background-image referencing this url
            for fig in soup.find_all(['figure', 'div']):
                style = fig.get('style') or ''
                if c in style:
                    # look for a figcaption inside
                    fc = fig.find('figcaption')
                    if fc:
                        caption = fc.get_text(strip=True)
                        break

        if caption:
            # skip obvious logo/wordmark/affiliate assets at extraction time
            if contains_irrelevant_token(caption) or contains_irrelevant_token(os.path.basename(urlparse(c).path)):
                logger.debug("Skipping extraction of irrelevant image by caption/filename token: %s (caption=%s)", c, caption)
                continue
            results.append({
                'image_url': c,
                'caption_raw': caption,
                'caption_clean': clean_caption(caption),
                'method': 'html',
                'local_image_path': None
            })
        else:
            # include without caption (some pages only have images)
            # if the filename or URL contains irrelevant tokens, skip even if no caption
            if contains_irrelevant_token(os.path.basename(urlparse(c).path)) or contains_irrelevant_token(c):
                logger.debug("Skipping extraction of irrelevant image by filename/URL token: %s", c)
                continue
            results.append({
                'image_url': c,
                'caption_raw': None,
                'caption_clean': None,
                'method': 'html',
                'local_image_path': None
            })
    def _select_from_srcset(srcset: str) -> str | None:
        # srcset: "a.jpg 300w, b.jpg 600w" or "a.jpg 1x, b.jpg 2x" — choose highest resolution (last)
        try:
            parts = [p.strip() for p in srcset.split(',') if p.strip()]
            if not parts:
                return None
            last = parts[-1]
            return last.split()[0]
        except Exception:
            return None

    def _image_url_from_tag(img_tag):
        # prefer src, then data-src, then srcset/data-srcset (pick highest)
        attrs = img_tag.attrs
        candidates = []
        for a in ("src", "data-src", "data-lazy-src", "data-original"):
            v = attrs.get(a)
            if v:
                candidates.append(v)
        # check srcset variants
        ss = attrs.get("srcset") or attrs.get("data-srcset") or attrs.get("data-lazy-srcset")
        if ss:
            sel = _select_from_srcset(ss)
            if sel:
                candidates.append(sel)

        # if inside <picture>, look at <source> elements
        parent = img_tag.find_parent('picture')
        if parent:
            for source in parent.find_all('source'):
                sss = source.get('srcset') or source.get('data-srcset')
                if sss:
                    sel = _select_from_srcset(sss)
                    if sel:
                        candidates.append(sel)
                v = source.get('src') or source.get('data-src')
                if v:
                    candidates.append(v)

        # return first non-empty candidate resolved relative to page
        for c in candidates:
            if c and not is_stray_url(c):
                return urljoin(url, c)
        return None

    # Also consider Open Graph images as a last resort
    og = soup.find('meta', property='og:image')
    og_url = og.get('content') if og and og.get('content') else None

    for img in soup.find_all("img"):
        img_url = _image_url_from_tag(img)
        if not img_url and og_url:
            img_url = urljoin(url, og_url)
        if not img_url:
            continue
        if is_stray_url(img_url):
            continue

        # early skip: filename or nearby alt/figcaption containing irrelevant tokens
        alt_text = (img.get('alt') or '')
        fname = os.path.basename(urlparse(img_url).path)
        if contains_irrelevant_token(alt_text) or contains_irrelevant_token(fname) or contains_irrelevant_token(img_url):
            logger.debug("Skipping extraction of irrelevant <img> by alt/filename/URL token: %s (alt=%s)", img_url, alt_text)
            continue

        caption = None
        fig = img.find_parent("figure")
        if fig and fig.find("figcaption"):
            caption = fig.find("figcaption").get_text(strip=True)
        else:
            # look for nearby paragraph or alt text
            sib = img.find_parent()
            if sib:
                # check next siblings up to 3 for paragraph captions
                for _ in range(3):
                    sib = sib.find_next_sibling()
                    if not sib:
                        break
                    if sib.name == 'p':
                        caption = sib.get_text(strip=True)
                        break
            if not caption:
                caption = img.get('alt') or None

        if caption:
            results.append({
                "image_url": img_url,
                "caption_raw": caption,
                "caption_clean": clean_caption(caption),
                "method": "html",
                "local_image_path": None
            })
    return results


# -------------------- OCR fallback --------------------
def extract_ocr_captions(url: str):
    """Run a bounded OCR fallback using Playwright to gather image URLs and then run local OCR."""
    if not OCR_AVAILABLE:
        return []

    from pytesseract import image_to_string
    results = []

    WATCHDOG_SECONDS = int(os.getenv("OCR_WATCHDOG_SECONDS", "70"))
    MAX_IMAGES_TO_PROCESS = int(os.getenv("OCR_MAX_IMAGES", "8"))

    def _watchdog(signum, frame):
        raise TimeoutError("OCR watchdog timeout")

    try:
        signal.signal(signal.SIGALRM, _watchdog)
        signal.alarm(WATCHDOG_SECONDS)

        with sync_playwright() as p:
            # launch with a few stealthy args
            browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-blink-features=AutomationControlled'])
            # create a context with a real-looking UA and referer
            context = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36', viewport={'width':1200,'height':800}, extra_http_headers={'referer': url})
            try:
                context.add_init_script("() => { Object.defineProperty(navigator, 'webdriver', {get: () => false}); }")
            except Exception:
                pass
            page = context.new_page()
            page.set_default_navigation_timeout(PLAYWRIGHT_NAV_TIMEOUT_MS)
            page.set_default_timeout(PLAYWRIGHT_NAV_TIMEOUT_MS)

            nav_timeout_s = PLAYWRIGHT_NAV_TIMEOUT_MS / 1000
            try:
                print(f"[DEBUG] [Playwright] Navigating to {url} (timeout={nav_timeout_s:.0f}s)...")
                page.goto(url, timeout=PLAYWRIGHT_NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=PLAYWRIGHT_NAV_TIMEOUT_MS)
                except Exception:
                    pass
            except Exception as nav_err:
                print(f"[WARN] [Playwright] Navigation failed or timed out after {nav_timeout_s:.0f}s: {nav_err}")
                browser.close()
                return results

            # give the page a chance to lazy-load images by scrolling
            try:
                scroll_js = """async () => {
                    const delay = (ms) => new Promise(r => setTimeout(r, ms));
                    const height = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
                    const step = window.innerHeight || 800;
                    for (let y = 0; y < height; y += step) {
                        window.scrollTo(0, y);
                        await delay(250);
                    }
                    // small extra wait for network
                    await delay(500);
                    window.scrollTo(0, 0);
                    return true;
                }"""
                try:
                    page.evaluate(scroll_js)
                except Exception:
                    # some pages don't like long-running evaluate; ignore
                    pass
            except Exception:
                pass

            time.sleep(PLAYWRIGHT_RENDER_WAIT_S)

            try:
                entries = page.evaluate("""() => {
                    const out = new Set();
                    function add(u){ if(!u) return; try { u = (new URL(u, location.href)).toString(); } catch(e) {} out.add(u); }

                    // images
                    document.querySelectorAll('img').forEach(img => {
                        add(img.currentSrc || img.src || img.getAttribute('data-src') || img.getAttribute('data-lazy-src'));
                        const ss = img.getAttribute('srcset') || img.getAttribute('data-srcset') || img.getAttribute('data-lazy-srcset');
                        if (ss) {
                            const parts = ss.split(',').map(p => p.trim().split(/\s+/)[0]).filter(Boolean);
                            if (parts.length) add(parts[parts.length-1]);
                        }
                    });

                    // picture/source
                    document.querySelectorAll('source').forEach(s => {
                        add(s.src || s.getAttribute('data-src'));
                        const ss = s.getAttribute('srcset') || s.getAttribute('data-srcset');
                        if (ss) {
                            const parts = ss.split(',').map(p => p.trim().split(/\s+/)[0]).filter(Boolean);
                            if (parts.length) add(parts[parts.length-1]);
                        }
                    });

                    // background-images
                    document.querySelectorAll('*').forEach(el => {
                        try {
                            const st = window.getComputedStyle(el);
                            if (st && st.backgroundImage && st.backgroundImage !== 'none') {
                                const m = st.backgroundImage.match(/url\(([^)]+)\)/);
                                if (m && m[1]) add(m[1].replace(/['\"]/g, ''));
                            }
                        } catch(e) {}
                    });

                    // noscript fallbacks
                    document.querySelectorAll('noscript').forEach(ns => {
                        try {
                            const div = document.createElement('div'); div.innerHTML = ns.innerHTML || '';
                            div.querySelectorAll('img').forEach(img => add(img.src || img.getAttribute('data-src')));
                        } catch(e) {}
                    });

                    return Array.from(out).slice(0, 60);
                }""")
            except Exception as e:
                print(f"[WARN] JS evaluation failed: {e}")
                entries = []

            # fallback: if JS didn't return candidates, parse the rendered HTML for images
            if not entries:
                try:
                    rendered = page.content()
                    bs = BeautifulSoup(rendered, 'html.parser')
                    cand = set()
                    for img in bs.find_all(['img','source']):
                        v = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
                        if not v:
                            ss = img.get('srcset') or img.get('data-srcset') or img.get('data-lazy-srcset')
                            if ss:
                                try:
                                    v = [p.strip().split()[0] for p in ss.split(',') if p.strip()][-1]
                                except Exception:
                                    v = None
                        if v:
                            cand.add(urljoin(url, v))
                    # inline styles
                    for el in bs.find_all(style=True):
                        m = re.search(r'url\(([^)]+)\)', el['style'])
                        if m:
                            raw = m.group(1).strip('"\'')
                            cand.add(urljoin(url, raw))
                    # noscript
                    for ns in bs.find_all('noscript'):
                        try:
                            inner = BeautifulSoup(ns.decode_contents(), 'html.parser')
                            for img in inner.find_all('img'):
                                s = img.get('src') or img.get('data-src')
                                if s:
                                    cand.add(urljoin(url, s))
                        except Exception:
                            pass
                    # og:image
                    og = bs.find('meta', property='og:image')
                    if og and og.get('content'):
                        cand.add(urljoin(url, og.get('content')))
                    entries = list(cand)[:MAX_IMAGES_TO_PROCESS]
                except Exception:
                    entries = []

            entries = entries[:MAX_IMAGES_TO_PROCESS]

            # entries are URLs (strings) from the page context; try fetching them using the browser's request API first
            for src in entries:
                if not src:
                    continue
                # normalize
                try:
                    src = src.strip()
                except Exception:
                    continue

                # extraction-time skip: if URL or filename contains irrelevant tokens (logo/promo/etc.)
                try:
                    if is_stray_url(src) or contains_irrelevant_token(src) or contains_irrelevant_token(os.path.basename(urlparse(src).path)):
                        logger.debug("Skipping render candidate with irrelevant token in URL/filename: %s", src)
                        continue
                except Exception:
                    pass

                # try to capture any figcaption nearby by querying for elements referencing this src
                figcap = None
                try:
                    # query by matching filename
                    fname = src.split('/').pop().split('?')[0]
                    cap = page.evaluate("""(fname) => {
                        const img = Array.from(document.querySelectorAll('img')).find(i => (i.currentSrc||i.src||i.getAttribute('data-src')||'').includes(fname));
                        if (!img) return null;
                        const fig = img.closest('figure');
                        if (fig && fig.querySelector('figcaption')) return fig.querySelector('figcaption').innerText.trim();
                        const alt = img.alt || null;
                        if (alt) return alt.trim();
                        let sib = img.parentElement;
                        for (let j=0;j<3 && sib;j++){ sib = sib.nextElementSibling; if (sib && sib.tagName && sib.tagName.toLowerCase() === 'p') return sib.innerText.trim(); }
                        return null;
                    }""", fname)
                    figcap = cap
                except Exception:
                    figcap = None

                # if figcap exists, add as html result
                if figcap:
                    # skip if figcaption contains irrelevant tokens
                    if contains_irrelevant_token(figcap) or contains_irrelevant_token(os.path.basename(urlparse(src).path)):
                        logger.debug("Skipping render candidate by figcaption/filename token: %s (figcap=%s)", src, figcap)
                        continue
                    results.append({
                        "image_url": src,
                        "caption_raw": figcap,
                        "caption_clean": clean_caption(figcap),
                        "method": "html",
                        "local_image_path": None
                    })
                    continue

                # try to fetch bytes using Playwright's request API (uses browser context)
                def _fetch_via_playwright(page_obj, url_to_get, attempts=2, timeout_ms=8000):
                    """Try multiple strategies to fetch bytes via playwright's request API.
                    Returns bytes or None."""
                    last_exc = None
                    for attempt in range(attempts):
                        try:
                            # prefer page.request if available
                            req_owner = None
                            if hasattr(page_obj, 'request') and page_obj.request:
                                req_owner = page_obj.request
                            elif hasattr(page_obj, 'context') and hasattr(page_obj.context, 'request') and page_obj.context.request:
                                req_owner = page_obj.context.request
                            elif page_obj and hasattr(page_obj, 'context') and getattr(page_obj.context, 'request', None):
                                req_owner = page_obj.context.request

                            if req_owner:
                                r = req_owner.get(url_to_get, timeout=timeout_ms)
                                try:
                                    # newer API: r.body()
                                    return r.body()
                                except Exception:
                                    try:
                                        return r.content()
                                    except Exception:
                                        # try text->bytes
                                        try:
                                            t = r.text()
                                            return t.encode('utf-8')
                                        except Exception:
                                            pass

                            # last resort: try the page.evaluate fetch() within page context
                            try:
                                js = """async (u) => {
                                    const resp = await fetch(u, {method: 'GET'});
                                    if (!resp.ok) return null;
                                    const buf = await resp.arrayBuffer();
                                    const arr = Array.from(new Uint8Array(buf));
                                    return arr;
                                }"""
                                arr = page.evaluate(js, url_to_get)
                                if arr:
                                    return bytes(arr)
                            except Exception:
                                pass

                        except Exception as e:
                            last_exc = e
                            continue
                    return None

                img_bytes = _fetch_via_playwright(page, src, attempts=2, timeout_ms=8000)

                # fallback to requests if playwright fetch didn't work
                if img_bytes is None:
                    try:
                        r = requests.get(src, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                        r.raise_for_status()
                        img_bytes = r.content
                    except Exception:
                        img_bytes = None

                if not img_bytes:
                    continue

                try:
                    img = Image.open(io.BytesIO(img_bytes))
                    if img.size[0] < MIN_IMG_WIDTH or img.size[1] < MIN_IMG_HEIGHT:
                        continue
                    text = ''
                    try:
                        # optional preprocessing to improve OCR
                        if OCR_PREPROCESS:
                            try:
                                def preprocess_image(pil_img: Image.Image) -> Image.Image:
                                    # ensure RGB then scale up if small
                                    pil_img = pil_img.convert('RGB')
                                    maxw = int(os.getenv('OCR_MAX_WIDTH', '1200'))
                                    if pil_img.width < maxw:
                                        ratio = maxw / pil_img.width
                                        nw = maxw
                                        nh = int(pil_img.height * ratio)
                                        pil_img = pil_img.resize((nw, nh), Image.LANCZOS)
                                    # grayscale + autocontrast
                                    pil_img = pil_img.convert('L')
                                    pil_img = ImageOps.autocontrast(pil_img)
                                    # adaptive threshold based on mean
                                    mean = int(ImageStat.Stat(pil_img).mean[0])
                                    # threshold slightly below mean to keep faint text
                                    thresh = int(os.getenv('OCR_THRESHOLD', str(max(60, mean - 10))))
                                    bw = pil_img.point(lambda p: 255 if p > thresh else 0)
                                    return bw
                                proc = preprocess_image(img)
                                text = image_to_string(proc).strip()
                            except Exception:
                                # fallback to raw OCR
                                text = image_to_string(img).strip()
                        else:
                            text = image_to_string(img).strip()
                    except Exception:
                        text = ''
                    if text:
                        # skip OCR result if text or filename indicates irrelevant asset
                        if contains_irrelevant_token(text) or contains_irrelevant_token(os.path.basename(urlparse(src).path)):
                            logger.debug("Skipping OCR result due to irrelevant token: %s (ocr_text=%s)", src, text)
                        else:
                            results.append({
                                "image_url": src,
                                "caption_raw": text,
                                "caption_clean": clean_caption(text),
                                "method": "ocr",
                                "local_image_path": None
                            })
                    else:
                        # No OCR text found, but we still want to keep discovered article images
                        # however skip if filename/URL contains irrelevant tokens
                        if contains_irrelevant_token(os.path.basename(urlparse(src).path)) or contains_irrelevant_token(src):
                            logger.debug("Skipping render-only candidate due to irrelevant filename/URL: %s", src)
                        else:
                            results.append({
                                "image_url": src,
                                "caption_raw": None,
                                "caption_clean": None,
                                "method": "render",
                                "local_image_path": None
                            })
                except Exception:
                    # if image processing failed, still try to include the URL as a render candidate
                    results.append({
                        "image_url": src,
                        "caption_raw": None,
                        "caption_clean": None,
                        "method": "render",
                        "local_image_path": None
                    })

            browser.close()

    except TimeoutError:
        print(f"[WARN] OCR watchdog fired after {WATCHDOG_SECONDS}s; aborting OCR fallback")
    except Exception as e:
        print(f"[WARN] OCR fallback failed entirely: {e}")
    finally:
        try:
            signal.alarm(0)
        except Exception:
            pass

    return results


# -------------------- Main callable --------------------
def extract_and_save(url: str, base_output="artifacts", run_ocr: bool = True, download_images: bool = True) -> str:
    """Extracts captions + images for a URL and saves JSON. Returns JSON path."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_folder = os.path.join(base_output, slugify(domain), timestamp)
    img_folder = os.path.join(base_folder, "images")
    os.makedirs(img_folder, exist_ok=True)

    print(f"[INFO] Extracting HTML captions from {url}")
    results = extract_html_captions(url)

    if run_ocr and OCR_AVAILABLE:
        print(f"[INFO] Running OCR fallback for JS-rendered captions")
        results.extend(extract_ocr_captions(url))

    # Deduplicate by image_url
    seen = set()
    unique = []
    for r in results:
        u = r.get("image_url")
        if u and u not in seen:
            seen.add(u)
            unique.append(r)
    results = unique

    # Relevance scoring
    filtered = []
    for r in results:
        img_url = r.get("image_url", "")
        caption = (r.get("caption_raw") or "").strip()
        if is_stray_url(img_url):
            continue

        score = 0
        if caption:
            score += 5
            if re.search(r"(rescue|helicopter|avalanche|mountain|peak|ridge|summit|snow|glacier|teams|SAR|cliff|fatal|missing)", caption, re.IGNORECASE):
                score += 10
        if re.search(r"/(wp-content|uploads|media|images)/", img_url, re.IGNORECASE):
            score += 5
        if re.search(r"\.(jpg|jpeg|png|webp)$", img_url, re.IGNORECASE):
            score += 5

        r["_score"] = score
        if score >= 5:
            filtered.append(r)

    filtered.sort(key=lambda x: x["_score"], reverse=True)
    results = filtered

    if not results:
        print(f"[INFO] 💤 No relevant images found for {url}. Skipping download.")
        json_path = os.path.join(base_folder, "captions.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2, ensure_ascii=False)
        return json_path

    if not download_images:
        print(f"[INFO] Skipping image downloads (download_images=False). Writing captions JSON with URLs only.")
    else:
        print(f"[INFO] Downloading {len(results)} images")
    # Additional pre-download heuristics to avoid fetching landing/ad images:
    # - prefer same-origin images or images under common upload paths
    # - skip external images without caption unless they're from trusted upload paths
    MIN_IMG_BYTES = int(os.getenv('MIN_IMG_BYTES', '4096'))

    def _head_checks(img_url: str) -> bool:
        """Return True if HEAD indicates this is worth downloading (image content-type and sufficient size)."""
        try:
            h = _session.head(img_url, allow_redirects=True, timeout=6)
            ct = h.headers.get('content-type', '')
            if not ct.startswith('image'):
                return False
            cl = h.headers.get('content-length')
            if cl and int(cl) < MIN_IMG_BYTES:
                return False
            return True
        except Exception:
            return False

    article_domain = domain
    filtered_for_download = []
    for r in results:
        img_url = r.get('image_url')
        if not img_url:
            continue
        parsed_img = urlparse(img_url)
        img_host = parsed_img.netloc.replace('www.', '')
        same_origin = (img_host == article_domain)
        # preferred if in uploads/wp-content or same-origin
        if same_origin or re.search(r"/(wp-content|uploads|media|images)/", parsed_img.path, re.IGNORECASE):
            if _head_checks(img_url):
                filtered_for_download.append(r)
            else:
                logger.debug("Skipping after HEAD check (not image or too small): %s", img_url)
        else:
            # external host: only download if we have a caption/alt text and HEAD looks ok
            caption = (r.get('caption_raw') or '').strip()
            if caption and _head_checks(img_url):
                filtered_for_download.append(r)
            else:
                logger.debug("Skipping external image without caption or failing HEAD: %s", img_url)

    # perform the actual download for the filtered set
    if download_images:
        for r in filtered_for_download:
            if r["image_url"]:
                r["local_image_path"] = download_image(r["image_url"], img_folder)
    else:
        # If not downloading images, ensure local_image_path stays None
        for r in filtered_for_download:
            r["local_image_path"] = None

    json_path = os.path.join(base_folder, "captions.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"[INFO] ✅ Exported {len(results)} relevant entries to {json_path}")
    print(f"[INFO] 🖼  Images stored in: {img_folder}")
    return json_path