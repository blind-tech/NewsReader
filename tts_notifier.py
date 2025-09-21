import threading
import pyttsx3
import sys

try:
    from win10toast import ToastNotifier
    _WIN10 = True
except Exception:
    _WIN10 = False
    try:
        from plyer import notification
        _PLYER = True
    except Exception:
        _PLYER = False


class TTS:
    def __init__(self):
        try:
            self.engine = pyttsx3.init()
        except Exception as e:
            print("pyttsx3 init error:", e)
            self.engine = None

        if self.engine:
            # slightly slower default rate for clearer reading
            try:
                rate = self.engine.getProperty("rate")
                self.engine.setProperty("rate", int(rate * 0.95))
            except Exception:
                pass

    def speak_async(self, text):
        if not self.engine:
            print("TTS engine not available. Text:\n", text)
            return
        threading.Thread(target=self._speak, args=(text,), daemon=True).start()

    def _speak(self, text):
        try:
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception as e:
            print("TTS error:", e)


class Notifier:
    def __init__(self):
        self._win = None
        if _WIN10:
            try:
                self._win = ToastNotifier()
            except Exception:
                self._win = None

    def notify(self, title, msg, timeout=5):
        if self._win:
            try:
                self._win.show_toast(title, msg, duration=timeout, threaded=True)
                return
            except Exception:
                pass
        if _PLYER:
            try:
                from plyer import notification
                notification.notify(title=title, message=msg, timeout=timeout)
                return
            except Exception:
                pass
        # fallback
        print(f"[NOTIFY] {title}: {msg}")