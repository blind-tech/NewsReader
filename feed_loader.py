import threading
import queue
import time
import requests
import feedparser

from urllib.parse import urlparse


def is_valid_url(url):
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and p.netloc != ""
    except Exception:
        return False


def validate_rss_url(url, timeout=10):
    """Return (ok: bool, message: str)"""
    if not is_valid_url(url):
        return False, "الرابط غير صالح كـ URL"
    headers = {"User-Agent": "NewsReaderPython/1.0 (+https://example)"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        return False, f"خطأ أثناء الوصول للرابط: {e}"
    # quick content-type check
    ctype = resp.headers.get("Content-Type", "").lower()
    parsed = feedparser.parse(resp.content)
    if not parsed.entries:
        return False, "المحتوى لا يبدو كـ RSS/Atom صالح أو لا يحتوي على عناصر"
    return True, "تم التحقق: يحتوي على عناصر"


class FeedLoader:
    """Background feed loader. Use request_load() to fetch.

    update_callback(region, site, rss_url, entries) will be called in the worker thread
    so use wx.CallAfter in the GUI to marshal to main thread.
    """
    def __init__(self):
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._worker_fn, daemon=True)
        self._worker.start()

    def stop(self):
        self._stop_event.set()
        try:
            self._queue.put(None)
        except Exception:
            pass

    def request_load(self, region, site, rss_url, update_callback, force=False):
        # push a job tuple
        self._queue.put((region, site, rss_url, update_callback, force))

    def _worker_fn(self):
        while not self._stop_event.is_set():
            try:
                job = self._queue.get(timeout=1)
            except queue.Empty:
                continue
            if job is None:
                break
            region, site, rss_url, update_callback, force = job
            try:
                entries = self._fetch_feed(rss_url)
                # call provided callback (will likely need wx.CallAfter in GUI)
                try:
                    update_callback(region, site, rss_url, entries)
                except Exception as e:
                    print("Feed update callback error:", e)
            except Exception as e:
                print(f"Feed load error for {rss_url}: {e}")

    def _fetch_feed(self, url, timeout=15):
        headers = {"User-Agent": "NewsReaderPython/1.0 (+https://example)"}
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        # if no entries -> error
        if not feed.entries:
            raise ValueError("المحتوى المستلم ليس RSS/Atom صالحًا أو لا يحتوي على عناصر.")
        return feed.entries