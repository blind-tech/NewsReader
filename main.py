import wx
import wx.adv
import os
import json
import time
import webbrowser
import threading
import requests
import feedparser
import time
from datetime import datetime

from feed_loader import FeedLoader, validate_rss_url
from tts_notifier import TTS, Notifier

DATA_FILE = 'news_reader_data.json'

DEFAULT_FEEDS = {
    "تقني": {
        "TechCrunch": "https://techcrunch.com/feed/",
        "The Verge": "https://www.theverge.com/rss/index.xml",
        "Engadget": "https://www.engadget.com/rss.xml",
        "NV Access": "https://www.nvaccess.org/feed/",
        "Cyberschool": "https://ar.cyberschool.ac/feed/",
        "tecwindow": "https://blog.tecwindow.net/feed/"
    },
    "رياضة": {
        "BBC Sport": "http://feeds.bbci.co.uk/sport/rss.xml",
        "Euro Sport": "https://www.eurosport.com/rss.xml",
        "Sky Sport": "https://www.skysports.com/rss/12040",
        "القلعة الحمراء": "https://www.elqalaaelhamraa.com/feed/"
    },
    "أخبار": {
        "BBC Arabic": "https://feeds.bbci.co.uk/arabic/rss.xml",
        "الجزيرة": "https://www.aljazeera.net/aljazeerarss/a9b8031c-4c8d-4b9e-b6d8-44b6a2f80b8a/2f5b5a1c-1a4c-4a5f-9b9d-9c9f9d9e9f9d",
        "CNN": "http://rss.cnn.com/rss/edition.rss"
    }
}


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'feeds': DEFAULT_FEEDS, 'seen_titles': []}


def save_data(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print('Error saving data:', e)


class MainFrame(wx.Frame):
    def __init__(self):
        wx.Frame.__init__(self, None, title='News Reader - قارئ الأخبار', size=(1100, 700))
        self.panel = wx.Panel(self)

        self.data = load_data()
        self.feeds = self.data.get('feeds', {})
        self.seen = set(self.data.get('seen_titles', []))

        self.feed_loader = FeedLoader()
        self.tts = TTS()
        self.notifier = Notifier()

        # UI layout
        self._build_ui()

        # periodic checker thread (light) - checks current site only
        self.check_interval = 60  # seconds
        self._periodic = threading.Thread(target=self._periodic_loop, daemon=True)
        self._periodic.start()

        # initial population
        self.populate_categories()
        if self.cat_list.GetCount() > 0:
            self.cat_list.Select(0)
            self.on_category_selected(None)

        # close handler
        self.Bind(wx.EVT_CLOSE, self.on_close)

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(wx.StaticText(self.panel, label='التصنيفات'), 0, wx.ALL, 4)
        self.cat_list = wx.ListBox(self.panel)
        self.cat_list.Bind(wx.EVT_LISTBOX, self.on_category_selected)
        left.Add(self.cat_list, 1, wx.EXPAND | wx.ALL, 4)
        btn_box = wx.BoxSizer(wx.HORIZONTAL)
        add_cat = wx.Button(self.panel, label='إضافة تصنيف')
        add_cat.Bind(wx.EVT_BUTTON, self.on_add_category)
        del_cat = wx.Button(self.panel, label='حذف تصنيف')
        del_cat.Bind(wx.EVT_BUTTON, self.on_delete_category)
        btn_box.Add(add_cat, 0, wx.RIGHT, 4)
        btn_box.Add(del_cat, 0, wx.RIGHT, 4)
        left.Add(btn_box, 0, wx.ALL, 4)

        left.Add(wx.StaticText(self.panel, label='المواقع في التصنيف'), 0, wx.ALL, 4)
        self.site_list = wx.ListBox(self.panel)
        self.site_list.Bind(wx.EVT_LISTBOX, self.on_site_selected)
        left.Add(self.site_list, 1, wx.EXPAND | wx.ALL, 4)
        site_btn_box = wx.BoxSizer(wx.HORIZONTAL)
        add_site = wx.Button(self.panel, label='إضافة رابط RSS')
        add_site.Bind(wx.EVT_BUTTON, self.on_add_feed)
        edit_site = wx.Button(self.panel, label='تحرير/حذف')
        edit_site.Bind(wx.EVT_BUTTON, self.on_edit_feed)
        site_btn_box.Add(add_site, 0, wx.RIGHT, 4)
        site_btn_box.Add(edit_site, 0, wx.RIGHT, 4)
        left.Add(site_btn_box, 0, wx.ALL, 4)

        sizer.Add(left, 0, wx.EXPAND | wx.ALL, 6)

        center = wx.BoxSizer(wx.VERTICAL)
        top_controls = wx.BoxSizer(wx.HORIZONTAL)
        refresh_btn = wx.Button(self.panel, label='تحديث يدوياً')
        refresh_btn.Bind(wx.EVT_BUTTON, lambda e: self.manual_refresh())
        self.notify_chk = wx.CheckBox(self.panel, label='الإشعارات')
        self.notify_chk.SetValue(True)
        top_controls.Add(refresh_btn, 0, wx.RIGHT, 6)
        top_controls.Add(self.notify_chk, 0, wx.RIGHT, 6)
        center.Add(top_controls, 0, wx.ALL, 4)

        center.Add(wx.StaticText(self.panel, label='قائمة الأخبار'), 0, wx.ALL, 4)
        # TreeCtrl with columns
        self.news_ctrl = wx.ListCtrl(self.panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.news_ctrl.InsertColumn(0, 'العنوان', width=500)
        self.news_ctrl.InsertColumn(1, 'التاريخ', width=140)
        self.news_ctrl.InsertColumn(2, 'الرابط', width=420)
        self.news_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_open_article)
        self.news_ctrl.Bind(wx.EVT_CONTEXT_MENU, self.on_news_context)
        center.Add(self.news_ctrl, 1, wx.EXPAND | wx.ALL, 4)

        sizer.Add(center, 1, wx.EXPAND | wx.ALL, 6)

        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(wx.StaticText(self.panel, label='محتوى الخبر / معاينة'), 0, wx.ALL, 4)
        self.preview = wx.TextCtrl(self.panel, style=wx.TE_MULTILINE | wx.TE_READONLY)
        right.Add(self.preview, 1, wx.EXPAND | wx.ALL, 4)
        preview_btns = wx.BoxSizer(wx.HORIZONTAL)
        open_src = wx.Button(self.panel, label='فتح المصدر')
        open_src.Bind(wx.EVT_BUTTON, lambda e: self.open_selected_article())
        read_btn = wx.Button(self.panel, label='قراءة صوتية')
        read_btn.Bind(wx.EVT_BUTTON, lambda e: self.read_selected_article())
        preview_btns.Add(open_src, 0, wx.RIGHT, 4)
        preview_btns.Add(read_btn, 0, wx.RIGHT, 4)
        right.Add(preview_btns, 0, wx.ALL, 4)

        sizer.Add(right, 0, wx.EXPAND | wx.ALL, 6)

        self.panel.SetSizer(sizer)

    def populate_categories(self):
        self.cat_list.Clear()
        for c in sorted(self.feeds.keys()):
            self.cat_list.Append(c)

    def on_category_selected(self, event):
        sel = self.cat_list.GetSelection()
        if sel == wx.NOT_FOUND:
            return
        cat = self.cat_list.GetString(sel)
        self.site_list.Clear()
        for s in sorted(self.feeds.get(cat, {}).keys()):
            self.site_list.Append(s)
        if self.site_list.GetCount() > 0:
            self.site_list.SetSelection(0)
            self.on_site_selected(None)

    def on_add_category(self, event):
        dlg = wx.TextEntryDialog(self, 'أدخل اسم التصنيف:', 'إضافة تصنيف')
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetValue().strip()
            if not name:
                wx.MessageBox('الاسم فارغ', 'خطأ', wx.OK | wx.ICON_ERROR)
            elif name in self.feeds:
                wx.MessageBox('التصنيف موجود', 'معلومات', wx.OK | wx.ICON_INFORMATION)
            else:
                self.feeds[name] = {}
                self.populate_categories()
                save_data({'feeds': self.feeds, 'seen_titles': list(self.seen)})
        dlg.Destroy()

    def on_delete_category(self, event):
        sel = self.cat_list.GetSelection()
        if sel == wx.NOT_FOUND:
            wx.MessageBox('اختر تصنيفًا للحذف', 'معلومات', wx.OK | wx.ICON_INFORMATION)
            return
        cat = self.cat_list.GetString(sel)
        confirm = wx.MessageBox(f"هل تريد حذف التصنيف '{cat}' وكل روابطه؟", 'تأكيد', wx.YES_NO | wx.ICON_QUESTION)
        if confirm == wx.YES:
            self.feeds.pop(cat, None)
            self.populate_categories()
            self.site_list.Clear()
            save_data({'feeds': self.feeds, 'seen_titles': list(self.seen)})

    def on_add_feed(self, event):
        sel = self.cat_list.GetSelection()
        if sel == wx.NOT_FOUND:
            wx.MessageBox('اختر تصنيفًا أولاً أو أنشئ واحدًا جديدًا.', 'معلومات', wx.OK | wx.ICON_INFORMATION)
            return
        cat = self.cat_list.GetString(sel)
        dlg_name = wx.TextEntryDialog(self, 'أدخل اسم الموقع/المصدر:', 'اسم الموقع')
        if dlg_name.ShowModal() != wx.ID_OK:
            dlg_name.Destroy(); return
        site_name = dlg_name.GetValue().strip()
        dlg_name.Destroy()
        dlg_url = wx.TextEntryDialog(self, 'أدخل رابط RSS/Atom:', 'رابط RSS')
        if dlg_url.ShowModal() != wx.ID_OK:
            dlg_url.Destroy(); return
        rss_url = dlg_url.GetValue().strip()
        dlg_url.Destroy()

        # show busy
        busy = wx.BusyInfo('جارٍ التحقق من الرابط، الرجاء الانتظار...')
        wx.Yield()

        def validate_and_add():
            ok, msg = validate_rss_url(rss_url)
            wx.CallAfter(busy.Destroy)
            if not ok:
                wx.CallAfter(wx.MessageBox, f"الرابط غير صالح:\n{msg}", 'خطأ', wx.OK | wx.ICON_ERROR)
                return
            # add
            self.feeds.setdefault(cat, {})[site_name] = rss_url
            wx.CallAfter(self.populate_categories)
            wx.CallAfter(self.on_category_selected, None)
            save_data({'feeds': self.feeds, 'seen_titles': list(self.seen)})
            wx.CallAfter(wx.MessageBox, 'تمت إضافة مصدر RSS بنجاح.', 'تم', wx.OK | wx.ICON_INFORMATION)

        threading.Thread(target=validate_and_add, daemon=True).start()

    def on_edit_feed(self, event):
        sel_cat = self.cat_list.GetSelection()
        sel_site = self.site_list.GetSelection()
        if sel_cat == wx.NOT_FOUND or sel_site == wx.NOT_FOUND:
            wx.MessageBox('اختر تصنيفًا وموقعًا لتحريره.', 'معلومات', wx.OK | wx.ICON_INFORMATION)
            return
        cat = self.cat_list.GetString(sel_cat)
        site = self.site_list.GetString(sel_site)
        rss_url = self.feeds[cat][site]
        dlg = wx.MessageDialog(self, 'هل تريد تحرير (نعم) أم حذف (لا) هذا المصدر؟', 'تحرير أو حذف', wx.YES_NO | wx.ICON_QUESTION)
        ans = dlg.ShowModal(); dlg.Destroy()
        if ans == wx.ID_NO:
            if wx.MessageBox(f"حذف {site} من {cat}؟", 'تأكيد', wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
                self.feeds[cat].pop(site, None)
                if not self.feeds[cat]:
                    self.feeds.pop(cat, None)
                self.populate_categories()
                save_data({'feeds': self.feeds, 'seen_titles': list(self.seen)})
            return
        # edit
        edit_name = wx.TextEntryDialog(self, 'اسم الموقع:', 'تحرير الاسم', value=site)
        if edit_name.ShowModal() != wx.ID_OK:
            edit_name.Destroy(); return
        new_name = edit_name.GetValue().strip(); edit_name.Destroy()
        edit_url = wx.TextEntryDialog(self, 'رابط RSS:', 'تحرير الرابط', value=rss_url)
        if edit_url.ShowModal() != wx.ID_OK:
            edit_url.Destroy(); return
        new_url = edit_url.GetValue().strip(); edit_url.Destroy()

        busy = wx.BusyInfo('جارٍ التحقق من الرابط، الرجاء الانتظار...')
        wx.Yield()
        def validate_edit():
            ok, msg = validate_rss_url(new_url)
            wx.CallAfter(busy.Destroy)
            if not ok:
                wx.CallAfter(wx.MessageBox, f"الرابط غير صالح:\n{msg}", 'خطأ', wx.OK | wx.ICON_ERROR)
                return
            # perform edit
            self.feeds[cat].pop(site, None)
            self.feeds.setdefault(cat, {})[new_name] = new_url
            wx.CallAfter(self.populate_categories)
            save_data({'feeds': self.feeds, 'seen_titles': list(self.seen)})
            wx.CallAfter(wx.MessageBox, 'تم التعديل بنجاح.', 'تم', wx.OK | wx.ICON_INFORMATION)
        threading.Thread(target=validate_edit, daemon=True).start()

    def on_site_selected(self, event):
        sel_cat = self.cat_list.GetSelection()
        sel_site = self.site_list.GetSelection()
        if sel_cat == wx.NOT_FOUND or sel_site == wx.NOT_FOUND:
            return
        cat = self.cat_list.GetString(sel_cat)
        site = self.site_list.GetString(sel_site)
        rss_url = self.feeds[cat][site]
        # request async load via feed_loader
        self.feed_loader.request_load(cat, site, rss_url, update_callback=self.on_feed_loaded, force=True)

    def on_feed_loaded(self, region, site, rss_url, entries):
        # called inside loader thread: marshal to GUI
        wx.CallAfter(self._update_news_view, region, site, rss_url, entries)

    def _update_news_view(self, region, site, rss_url, entries):
        self.news_ctrl.DeleteAllItems()
        # sort entries by published if possible
        def entry_date(e):
            t = e.get('published_parsed') or e.get('updated_parsed')
            if t:
                return datetime.fromtimestamp(time.mktime(t))
            return datetime.min
        import time as _t
        sorted_entries = sorted(entries, key=lambda e: e.get('published_parsed') or e.get('updated_parsed') if (e.get('published_parsed') or e.get('updated_parsed')) else None, reverse=True)
        # better sort with fallback
        try:
            sorted_entries = sorted(entries, key=lambda e: (e.get('published_parsed') or e.get('updated_parsed') or _t.gmtime(0)), reverse=True)
        except Exception:
            sorted_entries = entries
        for e in sorted_entries:
            title = e.get('title','بدون عنوان')
            link = e.get('link','')
            pub = ''
            t = e.get('published_parsed') or e.get('updated_parsed')
            if t:
                pub = datetime.fromtimestamp(time.mktime(t)).strftime('%Y-%m-%d %H:%M')
            idx = self.news_ctrl.InsertItem(self.news_ctrl.GetItemCount(), title)
            self.news_ctrl.SetItem(idx, 1, pub)
            self.news_ctrl.SetItem(idx, 2, link)
        # select first and show preview
        if self.news_ctrl.GetItemCount() > 0:
            self.news_ctrl.Select(0)
            self.show_preview_by_index(0, sorted_entries)

    def show_preview_by_index(self, index, entries):
        if index < 0 or index >= len(entries):
            return
        e = entries[index]
        title = e.get('title','')
        summary = e.get('summary','') or e.get('description','') or ''
        link = e.get('link','')
        pub = ''
        t = e.get('published_parsed') or e.get('updated_parsed')
        if t:
            pub = datetime.fromtimestamp(time.mktime(t)).strftime('%Y-%m-%d %H:%M')
        preview = f"{title}\n\n{pub}\n\n{summary}\n\nالمصدر: {link}"
        self.preview.SetValue(preview)

    def on_news_context(self, event):
        pos = event.GetPosition()
        pos = self.ScreenToClient(pos)
        index, flags = self.news_ctrl.HitTest(pos)
        if index == -1:
            return
        self.news_ctrl.Select(index)
        menu = wx.Menu()
        menu.Append(101, 'فتح في المتصفح')
        menu.Append(102, 'قراءة الخبر بصوت عالٍ')
        self.Bind(wx.EVT_MENU, lambda e: self.open_selected_article(), id=101)
        self.Bind(wx.EVT_MENU, lambda e: self.read_selected_article(), id=102)
        self.PopupMenu(menu)
        menu.Destroy()

    def on_open_article(self, event):
        idx = event.GetIndex()
        link = self.news_ctrl.GetItemText(idx, 2)
        if link:
            webbrowser.open(link)

    def open_selected_article(self):
        idx = self._get_selected_index()
        if idx is None:
            return
        link = self.news_ctrl.GetItemText(idx, 2)
        if link:
            webbrowser.open(link)

    def read_selected_article(self):
        idx = self._get_selected_index()
        if idx is None:
            return
        title = self.news_ctrl.GetItemText(idx, 0)
        link = self.news_ctrl.GetItemText(idx, 2)
        # try to fetch entry summary from current feed
        sel_cat = self.cat_list.GetSelection()
        sel_site = self.site_list.GetSelection()
        if sel_cat == wx.NOT_FOUND or sel_site == wx.NOT_FOUND:
            self.tts.speak_async(title)
            return
        cat = self.cat_list.GetString(sel_cat)
        site = self.site_list.GetString(sel_site)
        rss_url = self.feeds.get(cat, {}).get(site)
        def do_read():
            try:
                entries = feedparser.parse(requests.get(rss_url, timeout=15).content).entries
                entry = None
                for e in entries:
                    if e.get('link') == link or e.get('title') == title:
                        entry = e
                        break
                text = title
                if entry:
                    text = entry.get('title','') + '. ' + (entry.get('summary','') or entry.get('description','') or '')
                else:
                    text = title + ((' — ' + link) if link else '')
                self.tts.speak_async(text)
            except Exception as ex:
                print('Read error:', ex)
                self.tts.speak_async(title)
        threading.Thread(target=do_read, daemon=True).start()

    def _get_selected_index(self):
        idx = self.news_ctrl.GetFirstSelected()
        if idx == -1:
            wx.MessageBox('اختر خبراً أولاً.', 'معلومات', wx.OK | wx.ICON_INFORMATION)
            return None
        return idx

    def manual_refresh(self):
        self.on_site_selected(None)

    def _periodic_loop(self):
        import time as _t
        while True:
            try:
                sel_cat = self.cat_list.GetSelection()
                sel_site = self.site_list.GetSelection()
                if sel_cat != wx.NOT_FOUND and sel_site != wx.NOT_FOUND:
                    cat = self.cat_list.GetString(sel_cat)
                    site = self.site_list.GetString(sel_site)
                    rss_url = self.feeds.get(cat, {}).get(site)
                    if rss_url:
                        try:
                            entries = feedparser.parse(requests.get(rss_url, timeout=15).content).entries
                            new = []
                            for e in entries:
                                title = e.get('title','')
                                if title and title not in self.seen:
                                    self.seen.add(title)
                                    new.append(title)
                                    if self.notify_chk.GetValue():
                                        self.notifier.notify('خبر جديد', title, timeout=5)
                            if new:
                                save_data({'feeds': self.feeds, 'seen_titles': list(self.seen)})
                                # refresh view
                                wx.CallAfter(self.feed_loader.request_load, cat, site, rss_url, self.on_feed_loaded, True)
                        except Exception as e:
                            print('Periodic check error:', e)
                _t.sleep(self.check_interval)
            except Exception as e:
                print('Periodic loop error:', e)
                _t.sleep(5)

    def on_close(self, event):
        try:
            self.feed_loader.stop()
        except Exception:
            pass
        save_data({'feeds': self.feeds, 'seen_titles': list(self.seen)})
        self.Destroy()


if __name__ == '__main__':
    app = wx.App(False)
    frame = MainFrame()
    frame.Show()
    app.MainLoop()
