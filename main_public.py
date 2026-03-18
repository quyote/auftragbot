%%writefile /content/auftragapp/main.py
import re
import asyncio
import threading
import json
import os
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.uix.checkbox import CheckBox
from kivy.clock import Clock
from kivy.core.window import Window
from telethon import TelegramClient, events
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

Window.clearcolor = (0.08, 0.08, 0.08, 1)

try:
    from android.permissions import request_permissions, Permission
    request_permissions([Permission.INTERNET,
                        Permission.READ_EXTERNAL_STORAGE,
                        Permission.WRITE_EXTERNAL_STORAGE])
except:
    pass

SESSION_FILE = 'auftrag_session'
SETTINGS_FILE = 'auftrag_settings.json'

KATEGORIEN = [
    'Schlüsseldienst',
    'Sanitär',
    'Rohrverstopfung',
    'Schädlingsbekämpfung',
    'Elektro'
]

def load_settings():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}

def save_settings(data):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(data, f)
    except:
        pass

def send_notification(title, message):
    try:
        from jnius import autoclass
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        Context = autoclass('android.content.Context')
        NotificationBuilder = autoclass('android.app.Notification$Builder')
        activity = PythonActivity.mActivity
        nm = activity.getSystemService(Context.NOTIFICATION_SERVICE)
        builder = NotificationBuilder(activity)
        builder.setContentTitle(title)
        builder.setContentText(message)
        builder.setSmallIcon(activity.getApplicationInfo().icon)
        builder.setAutoCancel(True)
        nm.notify(1, builder.build())
    except:
        pass

class AnleitungPopup(Popup):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = 'Anleitung - API ID & Hash'
        self.size_hint = (0.95, 0.85)
        layout = BoxLayout(orientation='vertical', padding=15, spacing=10)
        anleitung = """So bekommst du API ID und API Hash:

1. Oeffne Browser und gehe auf:
   my.telegram.org

2. Handynummer eingeben
   (mit +49 vorne)

3. Code von Telegram eingeben

4. Klick auf:
   "API development tools"

5. Formular ausfullen:
   - App title: MeinBot
   - Short name: meinbot
   - Platform: Desktop
   - "Create application" klicken

6. Du siehst dann:
   - App api_id (Zahlen)
   - App api_hash (langer Text)

7. Beide Werte in die App
   eintragen und STARTEN!"""

        scroll = ScrollView()
        text = Label(text=anleitung, color=(0.9,0.9,0.9,1),
                    font_size=22, halign='left', valign='top',
                    size_hint_y=None)
        text.bind(texture_size=text.setter('size'))
        text.bind(size=lambda *x: setattr(text, 'text_size', (text.width, None)))
        scroll.add_widget(text)
        layout.add_widget(scroll)
        btn = Button(text='Verstanden!',
                    background_color=(0.1,0.7,0.1,1),
                    size_hint_y=None, height=55)
        btn.bind(on_press=self.dismiss)
        layout.add_widget(btn)
        self.content = layout

class CodePopup(Popup):
    def __init__(self, callback, **kwargs):
        super().__init__(**kwargs)
        self.callback = callback
        self.title = 'Telegram Code eingeben'
        self.size_hint = (0.9, 0.45)
        layout = BoxLayout(orientation='vertical', padding=15, spacing=10)
        info = Label(text='Telegram hat dir einen Code geschickt.\nBitte hier eingeben:',
                    color=(0.8,0.8,0.8,1), size_hint_y=None, height=50)
        self.code_input = TextInput(hint_text='z.B. 12345',
                                   multiline=False,
                                   background_color=(0.2,0.2,0.2,1),
                                   foreground_color=(1,1,1,1),
                                   font_size=24,
                                   size_hint_y=None, height=55)
        btn = Button(text='BESTAETIGEN',
                    background_color=(0.1,0.7,0.1,1),
                    font_size=18,
                    size_hint_y=None, height=55)
        btn.bind(on_press=self.confirm)
        layout.add_widget(info)
        layout.add_widget(self.code_input)
        layout.add_widget(btn)
        self.content = layout

    def confirm(self, instance):
        self.callback(self.code_input.text)
        self.dismiss()

class AuftragApp(App):
    def build(self):
        self.client = None
        self.running = False
        self.loop = None
        self.plz_cache = {}
        self.bekannte_auftraege = set()
        self.geolocator = Nominatim(user_agent="auftrag_bot")
        self.heute_ok = 0
        self.heute_mom = 0
        self.heute_zu_weit = 0
        self.checkboxes = {}
        s = load_settings()

        root = BoxLayout(orientation='vertical', padding=12, spacing=8)

        titel_layout = BoxLayout(size_hint_y=None, height=50, spacing=10)
        titel = Label(text='AuftragBot Pro', font_size=22, bold=True,
                     color=(0.2, 0.9, 0.2, 1))
        info_btn = Button(text='? Hilfe', size_hint_x=None, width=90,
                         background_color=(0.2,0.4,0.8,1), font_size=14)
        info_btn.bind(on_press=lambda x: AnleitungPopup().open())
        titel_layout.add_widget(titel)
        titel_layout.add_widget(info_btn)
        root.add_widget(titel_layout)

        scroll_input = ScrollView(size_hint=(1, 0.65))
        input_layout = BoxLayout(orientation='vertical', spacing=6,
                                size_hint_y=None, padding=(0, 5))
        input_layout.bind(minimum_height=input_layout.setter('height'))

        def make_input_row(hint, key, secret=False):
            row = BoxLayout(size_hint_y=None, height=52, spacing=5)
            ti = TextInput(hint_text=hint, multiline=False,
                          background_color=(0.18,0.18,0.18,1),
                          foreground_color=(1,1,1,1),
                          hint_text_color=(0.5,0.5,0.5,1),
                          font_size=18,
                          password=secret,
                          text=s.get(key, ''))
            clear_btn = Button(text='X', size_hint_x=None, width=45,
                             background_color=(0.5,0.1,0.1,1),
                             font_size=16, bold=True)
            clear_btn.bind(on_press=lambda x, t=ti: setattr(t, 'text', ''))
            row.add_widget(ti)
            row.add_widget(clear_btn)
            input_layout.add_widget(row)
            return ti

        self.phone = make_input_row('Handynummer (+49...)', 'phone')
        self.plz = make_input_row('Deine PLZ', 'plz')
        self.ok_km = make_input_row('OK bis KM (z.B. 50)', 'ok_km')
        self.mom_km = make_input_row('MOM bis KM (z.B. 70)', 'mom_km')
        self.gruppe = make_input_row('Gruppenname', 'gruppe')

        # Kategorien Auswahl
        kat_titel = Label(text='--- Kategorien auswaehlen ---',
                         color=(0.4,0.4,0.4,1), size_hint_y=None, height=28,
                         font_size=12)
        input_layout.add_widget(kat_titel)

        gespeicherte_kats = s.get('kategorien', KATEGORIEN)

        for kat in KATEGORIEN:
            row = BoxLayout(size_hint_y=None, height=45, spacing=10)
            cb = CheckBox(size_hint_x=None, width=45,
                         active=kat in gespeicherte_kats)
            lbl = Label(text=kat, font_size=18, color=(0.9,0.9,0.9,1),
                       halign='left')
            self.checkboxes[kat] = cb
            row.add_widget(cb)
            row.add_widget(lbl)
            input_layout.add_widget(row)

        trenn = Label(text='--- Erweiterte Einstellungen ---',
                     color=(0.4,0.4,0.4,1), size_hint_y=None, height=28,
                     font_size=12)
        input_layout.add_widget(trenn)

        self.api_id = make_input_row('API ID (von my.telegram.org)', 'api_id')
        self.api_hash = make_input_row('API Hash', 'api_hash', secret=True)

        scroll_input.add_widget(input_layout)
        root.add_widget(scroll_input)

        btn_layout = BoxLayout(size_hint_y=None, height=65, spacing=10)
        self.start_btn = Button(text='STARTEN',
                               background_color=(0.1,0.7,0.1,1),
                               font_size=20, bold=True)
        self.start_btn.bind(on_press=self.start_bot)
        self.stop_btn = Button(text='STOPPEN',
                              background_color=(0.7,0.1,0.1,1),
                              font_size=20, bold=True)
        self.stop_btn.bind(on_press=self.stop_bot)
        btn_layout.add_widget(self.start_btn)
        btn_layout.add_widget(self.stop_btn)
        root.add_widget(btn_layout)

        self.status = Label(text='Gestoppt', font_size=18,
                           color=(0.8,0.8,0.8,1), size_hint_y=None, height=35)
        self.stats = Label(text='OK: 0     MOM: 0     Zu weit: 0',
                          font_size=16, color=(0.7,0.7,0.7,1), size_hint_y=None, height=30)
        root.add_widget(self.status)
        root.add_widget(self.stats)

        log_titel = Label(text='Auftrags-Log:', font_size=15,
                         color=(0.5,0.5,0.5,1), size_hint_y=None, height=25)
        root.add_widget(log_titel)

        self.log = Label(text='', size_hint_y=None, font_size=22,
                        color=(0.9,0.9,0.9,1), halign='left', valign='top')
        self.log.bind(texture_size=self.log.setter('size'))
        self.log.bind(size=lambda *x: setattr(self.log, 'text_size',
                      (self.log.width, None)))
        scroll_log = ScrollView()
        scroll_log.add_widget(self.log)
        root.add_widget(scroll_log)

        return root

    def get_aktive_kategorien(self):
        return [k for k, cb in self.checkboxes.items() if cb.active]

    def add_log(self, msg):
        def update(dt):
            self.log.text = msg + '\n' + self.log.text
        Clock.schedule_once(update)

    def update_stats(self):
        def update(dt):
            self.stats.text = f'OK: {self.heute_ok}     MOM: {self.heute_mom}     Zu weit: {self.heute_zu_weit}'
        Clock.schedule_once(update)

    def show_code_popup(self):
        future = asyncio.Future()
        def callback(code):
            self.loop.call_soon_threadsafe(future.set_result, code)
        Clock.schedule_once(lambda dt: CodePopup(callback).open())
        return future

    def start_bot(self, instance):
        if self.running:
            return
        aktive = self.get_aktive_kategorien()
        if not aktive:
            self.add_log('Bitte mindestens eine Kategorie auswaehlen!')
            return
        if not self.phone.text or not self.plz.text or not self.gruppe.text or not self.api_id.text or not self.api_hash.text:
            self.add_log('Bitte alle Felder ausfullen!')
            return
        self.running = True
        self.status.text = 'Bot laeuft...'
        save_settings({
            'phone': self.phone.text,
            'api_id': self.api_id.text,
            'api_hash': self.api_hash.text,
            'plz': self.plz.text,
            'ok_km': self.ok_km.text,
            'mom_km': self.mom_km.text,
            'gruppe': self.gruppe.text,
            'kategorien': aktive
        })
        t = threading.Thread(target=self.run_bot)
        t.daemon = True
        t.start()

    def stop_bot(self, instance):
        self.running = False
        self.status.text = 'Gestoppt'
        if self.client:
            try:
                if self.loop and self.loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self.client.disconnect(), self.loop)
            except:
                pass
        self.add_log('Bot gestoppt!')

    def plz_zu_koordinaten(self, plz):
        if plz in self.plz_cache:
            return self.plz_cache[plz]
        loc = self.geolocator.geocode(f"{plz}, Germany")
        if loc:
            self.plz_cache[plz] = (loc.latitude, loc.longitude)
            return self.plz_cache[plz]
        return None

    def entfernung_km(self, plz1, plz2):
        k1 = self.plz_zu_koordinaten(plz1)
        k2 = self.plz_zu_koordinaten(plz2)
        if k1 and k2:
            return round(geodesic(k1, k2).km, 1)
        return None

    def run_bot(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.bot_main())

    async def bot_main(self):
        try:
            api_id = int(self.api_id.text)
            api_hash = self.api_hash.text
            phone = self.phone.text
            mein_plz = self.plz.text
            ok_km = int(self.ok_km.text or '50')
            mom_km = int(self.mom_km.text or '70')
            gruppe = self.gruppe.text
            aktive_kategorien = self.get_aktive_kategorien()

            self.add_log(f'Aktiv: {", ".join(aktive_kategorien)}')

            self.client = TelegramClient(SESSION_FILE, api_id, api_hash)
            await self.client.connect()

            if not await self.client.is_user_authorized():
                await self.client.send_code_request(phone)
                self.add_log('Code wurde geschickt!')
                code = await self.show_code_popup()
                await self.client.sign_in(phone, code)
            else:
                self.add_log('Bereits eingeloggt!')

            gruppe_entity = None
            async for dialog in self.client.iter_dialogs():
                if gruppe.lower() in dialog.title.lower():
                    gruppe_entity = dialog.entity
                    self.add_log(f'Gruppe: {dialog.title}')
                    break

            if not gruppe_entity:
                self.add_log('Gruppe nicht gefunden!')
                self.running = False
                Clock.schedule_once(lambda dt: setattr(self.status, 'text', 'Gestoppt'))
                return

            async for message in self.client.iter_messages(gruppe_entity, limit=500):
                if message.text:
                    for nr in re.findall(r'#\d+', message.text):
                        self.bekannte_auftraege.add(nr)
            self.add_log(f'{len(self.bekannte_auftraege)} alte Auftraege geladen')
            self.add_log('Warte auf Auftraege...')

            @self.client.on(events.NewMessage(chats=gruppe_entity))
            async def handler(event):
                if not self.running:
                    return
                if not event.message.fwd_from:
                    return
                text = event.message.text or ''

                # Kategorie prüfen
                kat_gefunden = False
                for kat in self.get_aktive_kategorien():
                    if kat.lower() in text.lower():
                        kat_gefunden = True
                        break
                if not kat_gefunden:
                    return

                nummern = re.findall(r'#\d+', text)
                if not nummern:
                    return
                nummer = nummern[0]
                if nummer in self.bekannte_auftraege:
                    return
                self.bekannte_auftraege.add(nummer)
                plz_liste = re.findall(r'\b\d{5}\b', text)
                if not plz_liste:
                    return
                km = self.entfernung_km(mein_plz, plz_liste[0])
                if km is None:
                    return
                if km <= ok_km:
                    await event.reply('ok')
                    self.heute_ok += 1
                    self.add_log(f'OK - {plz_liste[0]} - {km} km')
                    send_notification('Auftrag OK!', f'{plz_liste[0]} - {km} km')
                    self.update_stats()
                elif km <= mom_km:
                    await event.reply('mom')
                    self.heute_mom += 1
                    self.add_log(f'MOM - {plz_liste[0]} - {km} km')
                    send_notification('MOM!', f'{plz_liste[0]} - {km} km')
                    self.update_stats()
                else:
                    await event.reply('Zu weit')
                    self.heute_zu_weit += 1
                    self.add_log(f'Zu weit - {plz_liste[0]} - {km} km')
                    self.update_stats()

            await self.client.run_until_disconnected()

        except Exception as e:
            if self.running:
                self.add_log(f'Fehler: {str(e)}')
            self.running = False
            Clock.schedule_once(lambda dt: setattr(self.status, 'text', 'Gestoppt'))

if __name__ == '__main__':
    AuftragApp().run()
