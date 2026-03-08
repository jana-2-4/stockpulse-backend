"""
StockPulse News Backend
Fetches real RSS news from Indian & global financial sources.
Runs on Render.com free tier.
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import feedparser
import requests
from datetime import datetime
import re
import time
import threading
import os

app = Flask(__name__)
CORS(app)  # Allow requests from your StockPulse web app

# ================================================================
# NEWS SOURCES — Official RSS feeds
# ================================================================
FEEDS = {
    # Indian Sources
    "moneycontrol_latest": {
        "url": "https://www.moneycontrol.com/rss/latestnews.xml",
        "name": "Moneycontrol",
        "type": "india"
    },
    "moneycontrol_markets": {
        "url": "https://www.moneycontrol.com/rss/marketreports.xml",
        "name": "Moneycontrol",
        "type": "india"
    },
    "et_markets": {
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "name": "Economic Times",
        "type": "india"
    },
    "et_stocks": {
        "url": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
        "name": "Economic Times",
        "type": "india"
    },
    "livemint": {
        "url": "https://www.livemint.com/rss/markets",
        "name": "Livemint",
        "type": "india"
    },
    "business_standard": {
        "url": "https://www.business-standard.com/rss/markets-106.rss",
        "name": "Business Standard",
        "type": "india"
    },
    "financial_express": {
        "url": "https://www.financialexpress.com/market/feed/",
        "name": "Financial Express",
        "type": "india"
    },
    "ndtv_profit": {
        "url": "https://feeds.feedburner.com/ndtvprofit-latest",
        "name": "NDTV Profit",
        "type": "india"
    },
    "hindu_business": {
        "url": "https://www.thehindubusinessline.com/markets/?service=rss",
        "name": "Hindu BusinessLine",
        "type": "india"
    },
    # Global Sources
    "reuters_business": {
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "name": "Reuters",
        "type": "global"
    },
    "reuters_markets": {
        "url": "https://feeds.reuters.com/reuters/markets",
        "name": "Reuters Markets",
        "type": "global"
    },
    "ft_markets": {
        "url": "https://www.ft.com/markets?format=rss",
        "name": "Financial Times",
        "type": "global"
    },
    "wsj_markets": {
        "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        "name": "Wall Street Journal",
        "type": "global"
    },
    "cnbc_world": {
        "url": "https://www.cnbc.com/id/15839069/device/rss/rss.xml",
        "name": "CNBC",
        "type": "global"
    },
    "nikkei": {
        "url": "https://asia.nikkei.com/rss/feed/site",
        "name": "Nikkei Asia",
        "type": "global"
    },
}

# Google News RSS — for stock-specific searches
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"

# ================================================================
# SENTIMENT ANALYSIS
# ================================================================
POSITIVE = [
    'beat', 'surge', 'gain', 'rise', 'rally', 'profit', 'upgrade', 'buy',
    'bullish', 'growth', 'strong', 'record', 'win', 'deal', 'dividend',
    'higher', 'up', 'crosses', 'cuts rate', 'stimulus', 'jump', 'soar',
    'boom', 'outperform', 'exceed', 'positive', 'recovery', 'rebound'
]
NEGATIVE = [
    'fall', 'drop', 'decline', 'loss', 'miss', 'downgrade', 'sell', 'bearish',
    'weak', 'probe', 'fraud', 'fine', 'penalty', 'risk', 'pressure', 'warning',
    'lower', 'drag', 'war', 'conflict', 'escalat', 'recession', 'crash',
    'selloff', 'tumble', 'slump', 'plunge', 'concern', 'worry', 'underperform'
]

def get_sentiment(text):
    text_lower = text.lower()
    score = sum(1 for k in POSITIVE if k in text_lower)
    score -= sum(1 for k in NEGATIVE if k in text_lower)
    return 'bullish' if score > 0 else 'bearish' if score < 0 else 'neutral'

# ================================================================
# HELPERS
# ================================================================
def clean_html(text):
    """Strip HTML tags and clean whitespace."""
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:300]

def parse_date(date_str):
    """Convert RSS date string to Unix timestamp (ms)."""
    if not date_str:
        return int(time.time() * 1000)
    try:
        t = feedparser._parse_date(date_str)
        if t:
            return int(time.mktime(t) * 1000)
    except Exception:
        pass
    return int(time.time() * 1000)

def item_to_news(entry, source_name, source_type, origin='market'):
    """Convert a feedparser entry to our news format."""
    title   = clean_html(entry.get('title', ''))
    excerpt = clean_html(entry.get('summary') or entry.get('description', ''))
    url     = entry.get('link') or entry.get('id', '#')
    pub     = entry.get('published') or entry.get('updated', '')

    if not title:
        return None

    return {
        'id':        f"rss-{hash(title+url)}",
        'title':     title,
        'excerpt':   excerpt[:200] if excerpt else 'Click to read the full article.',
        'url':       url,
        'source':    source_name,
        'sourceType': source_type,
        'sentiment': get_sentiment(title + ' ' + excerpt),
        'time':      parse_date(pub),
        'isMacro':   source_type == 'global',
        'origin':    origin,
        'stock':     'MARKET',
        'sector':    'Global' if source_type == 'global' else 'India',
    }

def fetch_feed(feed_key):
    """Fetch and parse a single RSS feed. Returns list of news items."""
    feed_info = FEEDS.get(feed_key)
    if not feed_info:
        return []
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 StockPulse News Aggregator/1.0',
            'Accept': 'application/rss+xml, application/xml, text/xml',
        }
        resp = requests.get(feed_info['url'], headers=headers, timeout=10)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        items = []
        for entry in parsed.entries[:20]:
            news = item_to_news(entry, feed_info['name'], feed_info['type'])
            if news:
                items.append(news)
        return items
    except Exception as e:
        print(f"[WARN] Feed {feed_key} failed: {e}")
        return []

def is_relevant_to_stock(news_item, symbol, company_name):
    """Check if a news article mentions this stock."""
    text = (news_item.get('title','') + ' ' + news_item.get('excerpt','')).lower()
    sym_lower = symbol.lower()

    # Match symbol directly
    if sym_lower in text:
        return True

    # Match meaningful words from company name (4+ chars)
    name_words = [w for w in company_name.lower().split() if len(w) >= 4
                  and w not in ('india', 'limited', 'industries', 'company', 'corp', 'ltd')]
    return any(word in text for word in name_words[:3])

# ================================================================
# NEWS CACHE — refresh every 6 minutes
# ================================================================
cache = {
    'all_news': [],
    'last_updated': 0,
}
CACHE_TTL = 6 * 60  # 6 minutes

def refresh_cache():
    """Fetch all feeds and update cache."""
    print("[INFO] Refreshing news cache...")
    all_news = []

    # Fetch all feeds concurrently using threads
    results = {}
    def fetch_and_store(key):
        results[key] = fetch_feed(key)

    threads = [threading.Thread(target=fetch_and_store, args=(k,)) for k in FEEDS]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    for key, items in results.items():
        all_news.extend(items)

    # Sort by time, deduplicate by title
    seen_titles = set()
    unique_news = []
    for item in sorted(all_news, key=lambda x: x['time'], reverse=True):
        title_key = item['title'][:60].lower()
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_news.append(item)

    cache['all_news'] = unique_news
    cache['last_updated'] = time.time()
    print(f"[INFO] Cache updated: {len(unique_news)} articles from {len(FEEDS)} sources")

def get_cached_news():
    """Return cached news, refreshing if stale."""
    if time.time() - cache['last_updated'] > CACHE_TTL or not cache['all_news']:
        refresh_cache()
    return cache['all_news']

# Background refresh thread
def background_refresh():
    while True:
        time.sleep(CACHE_TTL)
        try:
            refresh_cache()
        except Exception as e:
            print(f"[ERROR] Background refresh failed: {e}")

bg_thread = threading.Thread(target=background_refresh, daemon=True)
bg_thread.start()

# ================================================================
# API ROUTES
# ================================================================

@app.route('/stock/search', methods=['GET'])
def stock_search():
    """
    GET /stock/search?q=tata
    Searches NSE for stocks matching the query.
    Returns list of {symbol, name, exchange} results.
    """
    q = request.args.get('q', '').strip()
    if not q or len(q) < 1:
        return jsonify({'status': 'error', 'results': []})

    results = []
    seen = set()

    # Try NSE autocomplete API
    try:
        url = f'https://www.nseindia.com/api/search/autocomplete?q={requests.utils.quote(q)}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'https://www.nseindia.com/',
        }
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.ok:
            data = resp.json()
            for item in (data.get('symbols') or []):
                sym = item.get('symbol','').strip()
                name = item.get('symbol_info') or item.get('company_name') or sym
                stype = item.get('symbol_type','')
                # Only equity stocks
                if sym and sym not in seen and (stype in ('EQ','') or not stype):
                    seen.add(sym)
                    results.append({'symbol': sym, 'name': name, 'exchange': 'NSE'})
                if len(results) >= 8:
                    break
    except Exception as e:
        print(f'[WARN] NSE search failed: {e}')

    # Fallback: Tickertape search (covers BSE-only stocks)
    if not results:
        try:
            url2 = f'https://api.tickertape.in/search?text={requests.utils.quote(q)}&filter=stock'
            resp2 = requests.get(url2, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            if resp2.ok:
                data2 = resp2.json()
                for s in (data2.get('data',{}).get('stocks') or [])[:8]:
                    sym = s.get('ticker') or s.get('sid','')
                    name = s.get('longName') or s.get('shortName') or sym
                    exch = 'NSE' if 'NSE' in (s.get('exchanges') or []) else 'BSE'
                    if sym and sym not in seen:
                        seen.add(sym)
                        results.append({'symbol': sym, 'name': name, 'exchange': exch})
        except Exception as e:
            print(f'[WARN] Tickertape search failed: {e}')

    return jsonify({'status': 'ok', 'results': results})


@app.route('/stock/verify', methods=['GET'])
def stock_verify():
    """
    GET /stock/verify?symbol=RELIANCE
    Checks if a symbol is actually listed on NSE or BSE.
    Returns {valid: true/false, name, sector}
    """
    symbol = request.args.get('symbol', '').strip().upper()
    if not symbol:
        return jsonify({'valid': False, 'reason': 'No symbol provided'})

    # Check NSE quote API
    try:
        url = f'https://www.nseindia.com/api/quote-equity?symbol={requests.utils.quote(symbol)}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'https://www.nseindia.com/',
        }
        resp = requests.get(url, headers=headers, timeout=7)
        if resp.ok:
            data = resp.json()
            if data.get('info') or data.get('priceInfo'):
                info = data.get('info', {})
                return jsonify({
                    'valid': True,
                    'symbol': symbol,
                    'name': info.get('companyName') or symbol,
                    'sector': info.get('industry') or 'Equity',
                    'exchange': 'NSE',
                })
    except Exception as e:
        print(f'[WARN] NSE verify failed for {symbol}: {e}')

    # Fallback: check via Tickertape
    try:
        url2 = f'https://api.tickertape.in/search?text={requests.utils.quote(symbol)}&filter=stock'
        resp2 = requests.get(url2, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if resp2.ok:
            data2 = resp2.json()
            stocks = data2.get('data', {}).get('stocks') or []
            for s in stocks:
                if s.get('ticker','').upper() == symbol or s.get('sid','').upper() == symbol:
                    return jsonify({
                        'valid': True,
                        'symbol': symbol,
                        'name': s.get('longName') or s.get('shortName') or symbol,
                        'sector': s.get('sector') or 'Equity',
                        'exchange': 'NSE' if 'NSE' in (s.get('exchanges') or []) else 'BSE',
                    })
    except Exception as e:
        print(f'[WARN] Tickertape verify failed for {symbol}: {e}')

    return jsonify({'valid': False, 'symbol': symbol, 'reason': 'Not found on NSE or BSE'})



def health():
    """Health check — Render.com pings this to keep server alive."""
    return jsonify({
        'status': 'ok',
        'articles_cached': len(cache['all_news']),
        'last_updated': cache['last_updated'],
        'sources': len(FEEDS),
    })

@app.route('/news/all', methods=['GET'])
def all_news():
    """
    GET /news/all
    Returns all latest market news from all sources.
    Optional: ?limit=30
    """
    news = get_cached_news()
    limit = min(int(request.args.get('limit', 50)), 100)
    return jsonify({
        'status': 'ok',
        'count': len(news[:limit]),
        'articles': news[:limit],
        'last_updated': cache['last_updated'],
    })

@app.route('/news/stock/<symbol>', methods=['GET'])
def stock_news(symbol):
    """
    GET /news/stock/RELIANCE
    Returns news relevant to a specific stock.
    Also searches Google News RSS for the symbol.
    """
    symbol = symbol.upper().strip()
    company_name = request.args.get('name', symbol)

    # Filter cached news
    relevant = [n for n in get_cached_news()
                if is_relevant_to_stock(n, symbol, company_name)]

    # Also fetch from Google News RSS for this specific stock
    google_items = []
    try:
        query = f"{symbol} {company_name} stock NSE India"
        url   = GOOGLE_NEWS_RSS.format(query=requests.utils.quote(query))
        headers = {'User-Agent': 'Mozilla/5.0 StockPulse/1.0'}
        resp  = requests.get(url, headers=headers, timeout=8)
        parsed = feedparser.parse(resp.content)
        for entry in parsed.entries[:10]:
            item = item_to_news(entry, 'Google News', 'india', 'port')
            if item:
                item['stock'] = symbol
                google_items.append(item)
    except Exception as e:
        print(f"[WARN] Google News fetch failed for {symbol}: {e}")

    # Merge and deduplicate
    seen = set()
    merged = []
    for item in google_items + relevant:
        key = item['title'][:50].lower()
        if key not in seen:
            seen.add(key)
            item['stock'] = symbol
            merged.append(item)

    merged.sort(key=lambda x: x['time'], reverse=True)

    return jsonify({
        'status': 'ok',
        'symbol': symbol,
        'count': len(merged[:20]),
        'articles': merged[:20],
    })

@app.route('/news/portfolio', methods=['POST'])
def portfolio_news():
    """
    POST /news/portfolio
    Body: { "stocks": [{"symbol": "RELIANCE", "name": "Reliance Industries"}, ...] }
    Returns news filtered for all portfolio stocks combined.
    """
    data    = request.get_json() or {}
    stocks  = data.get('stocks', [])

    if not stocks:
        return jsonify({'status': 'error', 'message': 'No stocks provided'}), 400

    all_cached = get_cached_news()
    result = []
    seen   = set()

    for stock in stocks:
        sym  = stock.get('symbol', '').upper()
        name = stock.get('name', sym)

        # Filter from cache
        for item in all_cached:
            if is_relevant_to_stock(item, sym, name):
                key = item['title'][:50].lower()
                if key not in seen:
                    seen.add(key)
                    new_item = dict(item)
                    new_item['stock']  = sym
                    new_item['origin'] = 'port'
                    result.append(new_item)

    # Also fetch Google News for each stock (limited to avoid slowness)
    for stock in stocks[:5]:  # max 5 stocks via Google News
        sym  = stock.get('symbol', '').upper()
        name = stock.get('name', sym)
        try:
            query  = f"{sym} {name} NSE stock"
            url    = GOOGLE_NEWS_RSS.format(query=requests.utils.quote(query))
            resp   = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=6)
            parsed = feedparser.parse(resp.content)
            for entry in parsed.entries[:5]:
                item = item_to_news(entry, 'Google News', 'india', 'port')
                if item:
                    key = item['title'][:50].lower()
                    if key not in seen:
                        seen.add(key)
                        item['stock'] = sym
                        result.append(item)
        except Exception:
            pass

    result.sort(key=lambda x: x['time'], reverse=True)

    return jsonify({
        'status': 'ok',
        'count': len(result[:60]),
        'articles': result[:60],
    })

@app.route('/news/global', methods=['GET'])
def global_news():
    """
    GET /news/global
    Returns only global/macro news (Reuters, FT, WSJ, CNBC, Nikkei).
    """
    news = [n for n in get_cached_news() if n.get('isMacro') or n.get('sourceType') == 'global']
    return jsonify({
        'status': 'ok',
        'count': len(news[:30]),
        'articles': news[:30],
    })

@app.route('/news/india', methods=['GET'])
def india_news():
    """
    GET /news/india
    Returns only Indian market news.
    """
    news = [n for n in get_cached_news() if n.get('sourceType') == 'india']
    return jsonify({
        'status': 'ok',
        'count': len(news[:40]),
        'articles': news[:40],
    })

# ================================================================
# STARTUP
# ================================================================
if __name__ == '__main__':
    print("[INFO] StockPulse backend starting...")
    refresh_cache()  # Load news immediately on start
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
