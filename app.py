#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AnimeDekho Flask API – Single File
Converted from PHP version 62
Providers : AnimeDekho · HindiSubAnime · OnePace
Extractors: GDMirrorbot · AWSStream · Animedekhoco · StreamRuby · Blakiteapi · Abyass
"""

import re
import json
import base64
import threading
import traceback
from urllib.parse import urlparse, quote_plus
from concurrent.futures import ThreadPoolExecutor
import logging

import requests
import urllib3
from requests.adapters import HTTPAdapter
from lxml import html as lxml_html
from flask import Flask, request, Response

urllib3.disable_warnings()
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__)

# ── thread-local sessions for connection pooling ──
_tl = threading.local()
EXECUTOR = ThreadPoolExecutor(max_workers=32)
DEFAULT_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36')


def get_session():
    if not hasattr(_tl, 'session'):
        s = requests.Session()
        s.headers.update({'User-Agent': DEFAULT_UA})
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)
        s.mount('http://', adapter)
        s.mount('https://', adapter)
        _tl.session = s
    return _tl.session


# ════════════════════════════════════════════════
#  CONSTANTS
# ════════════════════════════════════════════════
AD_URL  = 'https://animedekho.app'
HSA_URL = 'https://hindisubanime.co'
OP_URL  = 'https://onepace.me'

AD_CATS = {
    'series': 'Series', 'movie': 'Movies',
    'category/anime': 'Anime', 'category/cartoon': 'Cartoon',
    'category/crunchyroll': 'Crunchyroll', 'category/hindi-dub': 'Hindi',
    'category/tamil': 'Tamil', 'category/telugu': 'Telugu',
}
HSA_CATS = {
    'category/shounen': 'Shounen', 'category/action': 'Action',
    'category/fantasy': 'Fantasy', 'serie': 'Series',
}


# ════════════════════════════════════════════════
#  HTTP HELPERS
# ════════════════════════════════════════════════
def http_get(url, headers=None, cookie=''):
    h = dict(headers) if headers else {}
    if cookie:
        h['Cookie'] = cookie
    r = get_session().get(url, headers=h, timeout=25,
                          allow_redirects=True, verify=False)
    return {'body': r.text, 'final_url': r.url}


def http_post(url, headers=None, form_data=None, json_body=''):
    h = dict(headers) if headers else {}
    s = get_session()
    if json_body != '':
        h['Content-Type'] = 'application/json'
        r = s.post(url, headers=h, data=json_body, timeout=25,
                   allow_redirects=True, verify=False)
    elif form_data:
        r = s.post(url, headers=h, data=form_data, timeout=25,
                   allow_redirects=True, verify=False)
    else:
        r = s.post(url, headers=h, timeout=25,
                   allow_redirects=True, verify=False)
    return r.text


def parse_html(text):
    if not text:
        return lxml_html.fromstring('<html><body></body></html>')
    try:
        return lxml_html.fromstring(text)
    except Exception:
        return lxml_html.fromstring('<html><body></body></html>')


def fetch_doc(url, headers=None, cookie=''):
    return parse_html(http_get(url, headers, cookie)['body'])


# ════════════════════════════════════════════════
#  XPATH / DOM HELPERS  (lxml-backed, very fast)
# ════════════════════════════════════════════════
def xtext(doc, expr):
    try:
        r = doc.xpath(expr)
        if r:
            n = r[0]
            if isinstance(n, str):
                return n.strip() or None
            return n.text_content().strip() or None
    except Exception:
        pass
    return None


def xattr(doc, expr, attr):
    try:
        r = doc.xpath(expr)
        if r and hasattr(r[0], 'get'):
            v = r[0].get(attr)
            return v or None
    except Exception:
        pass
    return None


def xtext_el(el, expr):
    try:
        r = el.xpath(expr)
        if r:
            n = r[0]
            if isinstance(n, str):
                return n.strip() or None
            return n.text_content().strip() or None
    except Exception:
        pass
    return None


def xattr_el(el, expr, attr):
    try:
        r = el.xpath(expr)
        if r and hasattr(r[0], 'get'):
            v = r[0].get(attr)
            return v or None
    except Exception:
        pass
    return None


def xown_text(el, expr):
    """Direct text nodes only (Jsoup ownText equivalent)."""
    try:
        r = el.xpath(expr)
        if r:
            n = r[0]
            if isinstance(n, str):
                return n.strip() or None
            parts = []
            if n.text:
                parts.append(n.text)
            for child in n.iterchildren():
                if child.tail:
                    parts.append(child.tail)
            return ''.join(parts).strip() or None
    except Exception:
        pass
    return None


def meta_content(doc, prop, attr_name='property'):
    try:
        r = doc.xpath(f"//meta[@{attr_name}='{prop}']")
        if r:
            return r[0].get('content') or None
    except Exception:
        pass
    return None


def body_class(doc):
    try:
        r = doc.xpath('//body')
        if r:
            return r[0].get('class') or ''
    except Exception:
        pass
    return ''


def extract_term_id(cls):
    m = re.search(r'(?:term|postid)-(\d+)', cls or '')
    return m.group(1) if m else None


def base_url(url):
    p = urlparse(url)
    return f"{p.scheme or 'https'}://{p.netloc}"


def re1(haystack, pattern):
    if haystack is None:
        return None
    m = re.search(pattern, haystack)
    return m.group(1) if m else None


def img_src(img_el):
    if img_el is None:
        return None
    for a in ('data-lazy-src', 'data-src', 'src'):
        v = img_el.get(a)
        if v and not v.startswith('data:'):
            return v
    return None


def ucfirst(s):
    return s[0].upper() + s[1:] if s else s


def parse_year(s):
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


# ════════════════════════════════════════════════
#  PROVIDER: AnimeDekho
# ════════════════════════════════════════════════
def ad_article(a):
    href = xattr_el(a, './/a[contains(@class,"lnk-blk")]', 'href')
    if not href:
        return None

    title = xtext_el(a, './/header//h2') or 'Unknown'

    img_els = a.xpath('.//img')
    poster = img_src(img_els[0]) if img_els else None

    season_episode = xtext_el(a, './/span[contains(@class,"season-episode")]')
    season = episode = None
    if season_episode:
        m = re.search(r'S(\d+)\s*-?\s*EP?(\d+)', season_episode, re.IGNORECASE)
        if m:
            season, episode = int(m.group(1)), int(m.group(2))
        else:
            m = re.search(r'EP?(\d+)', season_episode, re.IGNORECASE)
            if m:
                episode = int(m.group(1))
            else:
                m = re.search(r'S(\d+)', season_episode, re.IGNORECASE)
                if m:
                    season = int(m.group(1))

    quality = xtext_el(a, './/span[contains(@class,"quality")]')

    rn = a.xpath('.//span[contains(@class,"rating")]//span')
    rating = rn[0].text_content().strip() if rn else None

    yn = a.xpath('.//span[contains(@class,"year")]')
    year = yn[0].text_content().strip() if yn else None

    dn = a.xpath('.//span[contains(@class,"duration")]')
    duration = dn[0].text_content().strip() if dn else None

    is_series = (season_episode is not None) or ('/series-hindi/' in href) or ('/series/' in href)
    media_type = 2 if is_series else 1

    return {
        'title': title, 'url': href, 'poster': poster,
        'seasonEpisode': season_episode, 'season': season, 'episode': episode,
        'quality': quality, 'rating': rating, 'year': year, 'duration': duration,
        'mediaData': json.dumps({'url': href, 'poster': poster, 'mediaType': media_type}),
    }


def ad_parse_articles(doc):
    out = []
    for a in doc.xpath('//article'):
        item = ad_article(a)
        if item:
            out.append(item)
    return out


def ad_home(page, category):
    category = category.lstrip('/')
    label = AD_CATS.get(category, ucfirst(category))
    url = f"{AD_URL}/{category}/"
    if page > 1:
        url += f"page/{page}/"
    results = ad_parse_articles(fetch_doc(url))
    return {'provider': 'AnimeDekho', 'category': label,
            'page': page, 'count': len(results), 'results': results}


def ad_search(q):
    if not q:
        return {'error': 'q is required'}
    doc = fetch_doc(f"{AD_URL}/?s={quote_plus(q)}")
    results = []
    for a in doc.xpath('//ul[@data-results]//li//article'):
        item = ad_article(a)
        if item:
            results.append(item)
    return {'query': q, 'count': len(results), 'results': results}


def ad_load(url):
    if not url:
        return {'error': 'url is required'}
    doc = fetch_doc(url)

    title = xtext(doc, '//h1[contains(@class,"entry-title")]')
    if title:
        pos = title.find('Watch Online ')
        if pos != -1:
            title = title[pos + 13:].strip()
    if not title:
        title = meta_content(doc, 'og:title')
        if title:
            title = title.replace('Watch Online ', '').replace(' Movie in Hindi Dubbed Free', '').strip()
    title = title or 'No Title'

    poster = xattr(doc, '//div[contains(@class,"post-thumbnail")]//figure//img', 'src')
    if not poster:
        poster = meta_content(doc, 'og:image')

    plot = xtext(doc, '//div[contains(@class,"entry-content")]//p')
    if not plot:
        plot = meta_content(doc, 'twitter:description', 'name')

    year_raw = xtext(doc, '//span[contains(@class,"year")]')
    if not year_raw:
        updated = meta_content(doc, 'og:updated_time')
        if updated:
            year_raw = updated.split('-')[0]
    year = parse_year(year_raw)

    li_nodes = doc.xpath('//ul[contains(@class,"seasons-lst")]//li')
    if not li_nodes:
        return {
            'type': 'Movie', 'title': title, 'sourceUrl': url,
            'poster': poster, 'plot': plot, 'year': year,
            'mediaData': json.dumps({'url': url, 'poster': poster, 'mediaType': 1}),
        }

    episodes = []
    for li in li_nodes:
        name = xown_text(li, './/h3[contains(@class,"title")]')
        ep_url = xattr_el(li, './/a', 'href')
        if not ep_url:
            continue
        ep_poster = xattr_el(li, './/figure//img', 'src')
        span_txt = xtext_el(li, './/h3[contains(@class,"title")]//span')
        season = None
        if span_txt:
            m = re.search(r'S(\d+)', span_txt, re.IGNORECASE)
            if m:
                season = int(m.group(1))
        episodes.append({
            'name': name or xtext_el(li, './/h3[contains(@class,"title")]') or 'Episode',
            'url': ep_url, 'poster': ep_poster, 'season': season,
            'mediaData': json.dumps({'url': ep_url, 'poster': ep_poster, 'mediaType': 2}),
        })

    recs = []
    for art in doc.xpath('//div[contains(@class,"swiper-wrapper")]//article'):
        rh = xattr_el(art, './/a', 'href')
        if rh:
            recs.append({
                'title': xtext_el(art, './/h2') or 'Unknown',
                'url': rh,
                'poster': xattr_el(art, './/figure//img', 'src'),
            })

    return {
        'type': 'TvSeries', 'title': title, 'sourceUrl': url,
        'poster': poster, 'plot': plot, 'year': year,
        'episodeCount': len(episodes), 'episodes': episodes,
        'recommendations': recs,
    }


def ad_links(url, media_type):
    if not url:
        return {'error': 'url is required'}
    links = []

    # Step 1 – VidStream cookie
    try:
        doc = parse_html(http_get(url, cookie='toronites_server=vidstream')['body'])
        iframe_urls = [ifr.get('src') for ifr in
                       doc.xpath('//iframe[contains(@class,"serversel")]')
                       if ifr.get('src')]

        def _inner(srv):
            try:
                return ('vidstream', xattr(fetch_doc(srv), '//iframe', 'src'))
            except Exception:
                return None

        for r in EXECUTOR.map(_inner, iframe_urls):
            if r and r[1]:
                links.append({'source': r[0], 'url': r[1]})
    except Exception:
        pass

    # Step 2 – trdekho loop (parallel for speed)
    try:
        doc = fetch_doc(url)
        term = extract_term_id(body_class(doc))
        if term:
            def _tr(i):
                api = f"{AD_URL}/?trdekho={i}&trid={term}&trtype={media_type}"
                try:
                    src = xattr(fetch_doc(api), '//iframe', 'src')
                    if src:
                        return (f'trdekho_{i}', src)
                except Exception:
                    pass
                return None

            for r in EXECUTOR.map(_tr, range(0, 11)):
                if r:
                    links.append({'source': r[0], 'url': r[1]})
    except Exception:
        pass

    return {'url': url, 'mediaType': media_type, 'count': len(links), 'links': links}


# ════════════════════════════════════════════════
#  PROVIDER: HindiSubAnime
# ════════════════════════════════════════════════
def hsa_home(page, category):
    category = category.lstrip('/')
    label = HSA_CATS.get(category, ucfirst(category))
    url = f"{HSA_URL}/{category}/"
    if page > 1:
        url += f"page/{page}/"
    results = ad_parse_articles(fetch_doc(url))
    return {'provider': 'HindiSubAnime', 'category': label,
            'page': page, 'count': len(results), 'results': results}


def hsa_search(q):
    if not q:
        return {'error': 'q is required'}
    doc = fetch_doc(f"{HSA_URL}/?s={quote_plus(q)}")
    results = []
    for a in doc.xpath('//ul[@data-results]//li//article'):
        item = ad_article(a)
        if item:
            results.append(item)
    return {'query': q, 'count': len(results), 'results': results}


def hsa_load(url):
    if not url:
        return {'error': 'url is required'}
    doc = fetch_doc(url)

    title = xtext(doc, '//h1[contains(@class,"entry-title")]')
    if title:
        pos = title.find('Watch Online ')
        if pos != -1:
            title = title[pos + 13:].strip()
    title = title or 'No Title'

    poster = xattr(doc, '//div[contains(@class,"post-thumbnail")]//figure//img', 'src')
    if not poster:
        poster = meta_content(doc, 'og:image')

    plot = xtext(doc, '//div[contains(@class,"entry-content")]//p')
    if not plot:
        plot = meta_content(doc, 'twitter:description', 'name')

    year = parse_year(xtext(doc, '//span[contains(@class,"year")]'))

    li_nodes = doc.xpath('//ul[contains(@class,"seasons-lst")]//li')
    if not li_nodes:
        return {
            'type': 'Movie', 'title': title, 'sourceUrl': url,
            'poster': poster, 'plot': plot, 'year': year,
            'mediaData': json.dumps({'url': url, 'poster': poster, 'mediaType': 1}),
        }

    episodes = []
    for li in li_nodes:
        name = xown_text(li, './/h3[contains(@class,"title")]')
        ep_url = xattr_el(li, './/a', 'href')
        if not ep_url:
            continue
        ep_poster = xattr_el(li, './/figure//img', 'src')
        span_txt = xtext_el(li, './/h3[contains(@class,"title")]//span')
        season = None
        if span_txt:
            m = re.search(r'S(\d+)', span_txt, re.IGNORECASE)
            if m:
                season = int(m.group(1))
        episodes.append({
            'name': name or xtext_el(li, './/h3[contains(@class,"title")]') or 'Episode',
            'url': ep_url, 'poster': ep_poster, 'season': season,
            'mediaData': json.dumps({'url': ep_url, 'poster': ep_poster, 'mediaType': 2}),
        })

    return {'type': 'TvSeries', 'title': title, 'sourceUrl': url,
            'poster': poster, 'plot': plot, 'year': year,
            'episodeCount': len(episodes), 'episodes': episodes}


def hsa_links(url, media_type):
    if not url:
        return {'error': 'url is required'}
    doc = fetch_doc(url)
    term = extract_term_id(body_class(doc))
    if not term:
        return {'error': 'No postid/term found in body class', 'url': url}

    def _tr(i):
        api = f"{HSA_URL}/?trdekho={i}&trid={term}&trtype={media_type}"
        try:
            src = xattr(fetch_doc(api), '//iframe', 'src')
            if src:
                return (f'trdekho_{i}', src)
        except Exception:
            pass
        return None

    links = [{'source': r[0], 'url': r[1]} for r in EXECUTOR.map(_tr, range(0, 5)) if r]
    return {'url': url, 'mediaType': media_type, 'term': term,
            'count': len(links), 'links': links}


# ════════════════════════════════════════════════
#  PROVIDER: OnePace
# ════════════════════════════════════════════════
def op_home(category):
    path = ('/series/one-pace-english-dub/' if category == 'dub'
            else '/series/one-pace-english-sub/')
    doc = fetch_doc(OP_URL + path)
    boxes = doc.xpath(
        '//div[contains(@class,"seasons") and contains(@class,"aa-crd")]'
        '/div[contains(@class,"seasons-bx")]')
    results = []
    for box in boxes:
        img_els = box.xpath('.//picture//img')
        alt = img_els[0].get('alt', '') if img_els else ''
        is_dub = 'Dub' in alt
        href = (OP_URL + '/series/one-pace-english-dub' if is_dub
                else OP_URL + '/series/one-pace-english-sub')
        p_els = box.xpath('.//p')
        title = p_els[0].text_content().strip() if p_els else 'Unknown'
        all_imgs = box.xpath('.//img')
        poster = img_src(all_imgs[0]) if all_imgs else None
        results.append({'title': title, 'url': href, 'poster': poster,
                        'isDub': is_dub, 'isSub': not is_dub})
    return {'provider': 'OnePace', 'category': category.upper(),
            'count': len(results), 'results': results}


def op_load(url, arc_title=None):
    if not url:
        return {'error': 'url is required'}
    doc = fetch_doc(url)
    poster = 'https://images3.alphacoders.com/134/1342304.jpeg'
    plot = xtext(doc, '//div[contains(@class,"entry-content")]//p')
    title = arc_title if (arc_title and arc_title.strip()) else 'One Pace'

    arc_int = None
    if arc_title:
        m = re.search(r'Arc\s+(\S+)', arc_title, re.IGNORECASE)
        if m:
            arc_int = m.group(1)

    if arc_int is not None:
        cexpr = (f'//div[contains(@class,"seasons") and contains(@class,"aa-crd")]'
                 f'/div[contains(@class,"seasons-bx") and contains(.,"{arc_int}")]')
    else:
        cexpr = ('//div[contains(@class,"seasons") and contains(@class,"aa-crd")]'
                 '/div[contains(@class,"seasons-bx")]')

    containers = doc.xpath(cexpr)
    container = containers[0] if containers else None

    episodes = []
    if container is not None:
        for li in container.xpath(
                './/ul[contains(@class,"seasons-lst") and contains(@class,"anm-a")]//li'):
            name = xown_text(li, './/h3[contains(@class,"title")]')
            ep_url = xattr_el(li, './/a', 'href')
            if not ep_url:
                continue
            ep_poster = 'https://raw.githubusercontent.com/phisher98/TVVVV/refs/heads/main/OnePack.png'
            span_txt = xtext_el(li, './/h3[contains(@class,"title")]//span')
            season = None
            if span_txt:
                m = re.search(r'S(\d+)', span_txt, re.IGNORECASE)
                if m:
                    season = int(m.group(1))
            episodes.append({
                'name': name or xtext_el(li, './/h3[contains(@class,"title")]') or 'Episode',
                'url': ep_url, 'poster': ep_poster, 'season': season,
                'mediaData': json.dumps({'url': ep_url, 'poster': ep_poster, 'mediaType': 2}),
            })

    if not episodes:
        return {'type': 'Movie', 'title': title, 'sourceUrl': url,
                'poster': poster, 'plot': plot,
                'mediaData': json.dumps({'url': url, 'poster': None, 'mediaType': 1})}

    return {'type': 'TvSeries', 'title': title, 'sourceUrl': url,
            'poster': poster, 'plot': plot,
            'episodeCount': len(episodes), 'episodes': episodes}


def op_links(url, media_type):
    if not url:
        return {'error': 'url is required'}
    doc = fetch_doc(url)
    term = extract_term_id(body_class(doc))
    if not term:
        return {'error': 'No postid/term found', 'url': url}

    def _tr(i):
        api = f"{OP_URL}/?trdekho={i}&trid={term}&trtype={media_type}"
        try:
            src = xattr(fetch_doc(api), '//iframe', 'src')
            if src:
                return (f'trdekho_{i}', src)
        except Exception:
            pass
        return None

    links = [{'source': r[0], 'url': r[1]} for r in EXECUTOR.map(_tr, range(0, 5)) if r]
    return {'url': url, 'mediaType': media_type, 'term': term,
            'count': len(links), 'links': links}


# ════════════════════════════════════════════════
#  EXTRACTOR: GDMirrorbot
# ════════════════════════════════════════════════
def ext_gdmirrorbot(url):
    main_url = 'https://gdmirrorbot.nl'

    if 'key=' not in url:
        r = http_get(url)
        host = base_url(r['final_url'] or url)
        sid = url[url.rfind('/') + 1:]
        qpos = sid.find('?')
        if qpos != -1:
            sid = sid[:qpos]
    else:
        page_text = http_get(url)['body']
        final_id = re1(page_text, r'FinalID\s*=\s*"([^"]+)"')
        my_key = re1(page_text, r'myKey\s*=\s*"([^"]+)"')
        id_type = re1(page_text, r'idType\s*=\s*"([^"]+)"') or 'imdbid'
        base_url_j = re1(page_text, r'let\s+baseUrl\s*=\s*"([^"]+)"')
        host = base_url(base_url_j) if base_url_j else main_url
        sid = url[url.rfind('/') + 1:]
        qpos = sid.find('?')
        if qpos != -1:
            sid = sid[:qpos]

        if final_id and my_key:
            if '/tv/' in url:
                season = re1(url, r'/tv/\d+/(\d+)/') or '1'
                episode = re1(url, r'/tv/\d+/\d+/(\d+)') or '1'
                api_url = f"{main_url}/myseriesapi?tmdbid={final_id}&season={season}&epname={episode}&key={my_key}"
            else:
                api_url = f"{main_url}/mymovieapi?{id_type}={final_id}&key={my_key}"
            page_text = http_get(api_url)['body']

        try:
            jd = json.loads(page_text)
        except Exception:
            return {'error': 'GDMirrorbot: could not parse JSON', 'raw': page_text[:300]}

        data = jd.get('data', []) if isinstance(jd, dict) else []
        if isinstance(data, list) and data and isinstance(data[0], dict) and data[0].get('fileslug'):
            sid = data[0]['fileslug']

    resp = http_post(f"{host}/embedhelper.php", form_data={'sid': sid})
    try:
        root = json.loads(resp)
    except Exception:
        return {'error': 'GDMirrorbot: embedhelper bad JSON', 'raw': resp[:300]}

    if not isinstance(root, dict):
        return {'error': 'GDMirrorbot: embedhelper bad JSON', 'raw': resp[:300]}

    site_urls = root.get('siteUrls') or {}
    friendly_map = root.get('siteFriendlyNames') or {}
    mresult = root.get('mresult')

    if isinstance(mresult, str):
        try:
            mresult = json.loads(base64.b64decode(mresult).decode('utf-8', errors='ignore'))
        except Exception:
            pass

    if not isinstance(mresult, dict):
        return {'error': 'GDMirrorbot: could not decode mresult'}

    links = []
    for key in site_urls.keys():
        if key not in mresult:
            continue
        base = (site_urls.get(key) or '').rstrip('/')
        path = (mresult.get(key) or '').lstrip('/')
        if not base or not path:
            continue
        links.append({'name': friendly_map.get(key, key), 'url': f"{base}/{path}"})

    return {'extractor': 'GDMirrorbot', 'sourceUrl': url,
            'count': len(links), 'links': links}


# ════════════════════════════════════════════════
#  EXTRACTOR: AWSStream / ascdn21
# ════════════════════════════════════════════════
def ext_awsstream(url):
    main_url = 'https://as-cdn21.top' if 'as-cdn21.top' in url else 'https://z.awstream.net'
    hash_val = url[url.rfind('/') + 1:]
    qpos = hash_val.find('?')
    if qpos != -1:
        hash_val = hash_val[:qpos]

    api_url = f"{main_url}/player/index.php?data={hash_val}&do=getVideo"
    resp = http_post(api_url, headers={'x-requested-with': 'XMLHttpRequest'},
                     form_data={'hash': hash_val, 'r': main_url})
    try:
        data = json.loads(resp)
    except Exception:
        data = None

    if not data or not data.get('videoSource'):
        return {'error': 'AWSStream: no videoSource', 'raw': resp[:300]}

    links = [{'type': 'm3u8', 'quality': '1080p', 'url': data['videoSource']}]

    try:
        page_html = http_get(url)['body']
        unpacked = js_unpack_page(page_html)
        if unpacked:
            sub = re1(unpacked,
                      r'"kind"\s*:\s*"captions"\s*,\s*"file"\s*:\s*"(https[^"]+\.srt)"')
            if sub:
                links.append({'type': 'subtitle', 'language': 'English', 'url': sub})
    except Exception:
        pass

    name = 'ascdn21/Zephyrflick' if 'as-cdn21.top' in url else 'AWSStream'
    return {'extractor': name, 'sourceUrl': url, 'links': links}


# ════════════════════════════════════════════════
#  EXTRACTOR: Animedekhoco
# ════════════════════════════════════════════════
def ext_animedekhoco(url):
    links = []
    if 'url=' in url:
        doc = fetch_doc(url)
        for opt in doc.xpath('//select[@id="serverSelector"]//option'):
            val = opt.get('value', '')
            name = opt.text_content().strip() if opt.text_content() else ''
            if not name:
                name = 'Unknown'
            if val:
                links.append({'name': name, 'url': val})
    else:
        text = http_get(url)['body']
        m = re1(text, r'file\s*:\s*"([^"]+)"')
        if m:
            links.append({'name': 'Player File', 'url': m})
    return {'extractor': 'Animedekhoco', 'sourceUrl': url,
            'count': len(links), 'links': links}


# ════════════════════════════════════════════════
#  EXTRACTOR: StreamRuby
# ════════════════════════════════════════════════
def ext_streamruby(url):
    cleaned_url = url.replace('/e', '')
    html_text = http_get(cleaned_url, headers={
        'X-Requested-With': 'XMLHttpRequest', 'Referer': cleaned_url})['body']
    doc = parse_html(html_text)
    script_data = ''
    for sc in doc.xpath('//script'):
        txt = sc.text_content()
        if txt and 'vplayer' in txt:
            script_data = txt
            break
    links = []
    if script_data:
        file_url = re1(script_data, r'file\s*:\s*"([^"]+)"')
        if file_url:
            links.append({
                'url': file_url, 'quality': '1080p',
                'headers': {
                    'Accept': '*/*', 'Origin': cleaned_url,
                    'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Mode': 'cors',
                    'Sec-Fetch-Site': 'cross-site', 'Connection': 'keep-alive',
                },
            })
    return {'extractor': 'StreamRuby', 'sourceUrl': url,
            'count': len(links), 'links': links}


# ════════════════════════════════════════════════
#  EXTRACTOR: Blakiteapi
# ════════════════════════════════════════════════
def ext_blakiteapi(url):
    main_url = 'https://blakiteapi.xyz'
    id_val = url[url.rfind('/') + 1:]
    qpos = id_val.find('?')
    if qpos != -1:
        id_val = id_val[:qpos]
    tmdb_id = re1(url, r'/embed/([^/]+)/') or ''

    api_url = f"{main_url}/api/get.php?id={id_val}&tmdbId={tmdb_id}"
    resp = http_get(api_url)['body']
    try:
        j = json.loads(resp)
    except Exception:
        j = None

    if not j or not j.get('success'):
        return {'error': 'Blakiteapi: no success in response', 'raw': resp[:300]}

    data = j.get('data') or {}
    quality = data.get('quality', '480p')
    fmt = data.get('format', 'MP4')
    data_id = data.get('dataId', '')
    stream = f"{main_url}/stream/{data_id}.{fmt}"

    q = 0
    for k, v in [('1080', 1080), ('720', 720), ('480', 480), ('360', 360)]:
        if k in quality:
            q = v
            break

    return {'extractor': 'Blakiteapi', 'sourceUrl': url,
            'links': [{'url': stream, 'quality': f"{q}p", 'format': fmt}]}


# ════════════════════════════════════════════════
#  EXTRACTOR: Abyass
# ════════════════════════════════════════════════
def ext_abyass(url):
    headers = {
        'User-Agent': DEFAULT_UA,
        'Origin': 'https://playhydrax.com',
        'Referer': 'https://playhydrax.com/',
    }
    html_text = http_get(url, headers=headers)['body']
    encrypted = re1(html_text, r'const\s+datas\s*=\s*"([^"]*)"')
    if not encrypted:
        return {'error': 'Abyass: datas token not found in page'}

    dec_resp = http_post('https://enc-dec.app/api/dec-abyss',
                         headers=headers,
                         json_body=json.dumps({'text': encrypted}))
    try:
        dec = json.loads(dec_resp)
    except Exception:
        dec = None

    if not dec or 'result' not in dec or 'sources' not in dec.get('result', {}):
        return {'error': 'Abyass: decrypt failed or no sources', 'raw': dec_resp[:300]}

    links = []
    for src in dec['result']['sources']:
        if not src.get('status'):
            continue
        links.append({
            'url': src.get('url', ''),
            'quality': src.get('type', 'unknown'),
            'codec': src.get('codec', '').upper(),
            'headers': {'Referer': 'https://playhydrax.com/'},
        })
    return {'extractor': 'Abyass', 'sourceUrl': url,
            'count': len(links), 'links': links}


# ════════════════════════════════════════════════
#  JS UNPACKER
# ════════════════════════════════════════════════
def js_unpack_page(html_text):
    if not html_text:
        return None
    m = re.search(
        r'\beval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*d\s*\)'
        r'(.*?)(?=</script>)', html_text, re.DOTALL)
    if not m:
        return None
    block = m.group(0)

    m2 = re.search(
        r"\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*"
        r"'((?:[^'\\]|\\.)*)'\.split\('\|'\)", block, re.DOTALL)
    if not m2:
        return None

    p = m2.group(1)
    a = int(m2.group(2))
    k = m2.group(4).split('|')
    a_use = 36 if a > 36 else a

    def _repl(match):
        token = match.group(1)
        try:
            idx = int(token, a_use)
        except (ValueError, TypeError):
            try:
                idx = int(token)
            except (ValueError, TypeError):
                return token
        if 0 <= idx < len(k) and k[idx] != '':
            return k[idx]
        return token

    return re.sub(r'\b([0-9a-zA-Z]+)\b', _repl, p) or None


# ════════════════════════════════════════════════
#  FLASK ROUTER
# ════════════════════════════════════════════════
@app.after_request
def _cors(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    return resp


@app.route('/', methods=['GET', 'OPTIONS'])
def api():
    if request.method == 'OPTIONS':
        return Response('', status=200, mimetype='application/json')

    try:
        action    = (request.args.get('action')    or 'info').lower().strip()
        provider  = (request.args.get('provider')  or 'animedekho').lower().strip()
        extractor = (request.args.get('extractor') or '').lower().strip()
        url       = (request.args.get('url')       or '').strip()
        q         = (request.args.get('q')         or '').strip()
        category  = (request.args.get('category')  or 'category/anime').strip()
        try:
            page = max(1, int(request.args.get('page') or 1))
        except (ValueError, TypeError):
            page = 1
        try:
            media_type = int(request.args.get('type') or 2)
        except (ValueError, TypeError):
            media_type = 2

        if action == 'home':
            if provider == 'hindisubanime':
                if category == 'category/anime':
                    category = 'category/action'
                data = hsa_home(page, category)
            elif provider == 'onepace':
                data = op_home('dub' if category == 'dub' else 'sub')
            else:
                data = ad_home(page, category)

        elif action == 'search':
            data = hsa_search(q) if provider == 'hindisubanime' else ad_search(q)

        elif action == 'load':
            if provider == 'hindisubanime':
                data = hsa_load(url)
            elif provider == 'onepace':
                data = op_load(url, (request.args.get('arc') or '').strip())
            else:
                data = ad_load(url)

        elif action == 'links':
            if provider == 'hindisubanime':
                data = hsa_links(url, media_type)
            elif provider == 'onepace':
                data = op_links(url, media_type)
            else:
                data = ad_links(url, media_type)

        elif action == 'extract':
            if not url:
                data = {'error': 'url parameter required'}
            elif extractor in ('gdmirrorbot', 'techinmind'):
                data = ext_gdmirrorbot(url)
            elif extractor in ('awsstream', 'ascdn21', 'zephyrflick'):
                data = ext_awsstream(url)
            elif extractor == 'animedekhoco':
                data = ext_animedekhoco(url)
            elif extractor == 'streamruby':
                data = ext_streamruby(url)
            elif extractor == 'blakiteapi':
                data = ext_blakiteapi(url)
            elif extractor == 'abyass':
                data = ext_abyass(url)
            else:
                data = {
                    'error': f'Unknown extractor: {extractor}',
                    'available': ['gdmirrorbot', 'techinmind', 'awsstream', 'ascdn21',
                                  'animedekhoco', 'streamruby', 'blakiteapi', 'abyass'],
                }

        else:
            data = {
                'name': 'AnimeDekho PHP API',
                'version': 62,
                'note': 'All parameters are GET query strings.',
                'endpoints': {
                    'info':    '?action=info',
                    'home':    '?action=home   &provider=animedekho|hindisubanime|onepace &category=<slug> &page=<n>',
                    'search':  '?action=search &provider=animedekho|hindisubanime         &q=<query>',
                    'load':    '?action=load   &provider=animedekho|hindisubanime|onepace &url=<page-url>',
                    'links':   '?action=links  &provider=animedekho|hindisubanime|onepace &url=<ep-url>  &type=<1=movie|2=episode>',
                    'extract': '?action=extract &extractor=<name> &url=<embed-url>',
                },
                'providers': {
                    'animedekho':    {'baseUrl': 'https://animedekho.app',   'categories': AD_CATS},
                    'hindisubanime': {'baseUrl': 'https://hindisubanime.co', 'categories': HSA_CATS},
                    'onepace':       {'baseUrl': 'https://onepace.me',       'categories': ['sub', 'dub']},
                },
                'extractors': {
                    'gdmirrorbot':  'https://gdmirrorbot.nl',
                    'techinmind':   'https://stream.techinmind.space',
                    'awsstream':    'https://z.awstream.net',
                    'ascdn21':      'https://as-cdn21.top',
                    'animedekhoco': 'https://animedekho.co',
                    'streamruby':   'https://rubystm.com',
                    'blakiteapi':   'https://blakiteapi.xyz',
                    'abyass':       'https://abyssplayer.com',
                },
            }

        return Response(
            json.dumps(data, ensure_ascii=False, separators=(',', ':')),
            mimetype='application/json; charset=utf-8')

    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line = tb[-1].lineno if tb else 0
        return Response(
            json.dumps({'error': str(e), 'file': __file__, 'line': line},
                       ensure_ascii=False, separators=(',', ':')),
            status=500, mimetype='application/json; charset=utf-8')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)
