import re
import asyncio
import threading
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock
from telethon import TelegramClient, events
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

class AuftragApp(App):
    def build(self):
        self.client = None
        self.running = False
        self.loop = None
        self.plz_cache = {}
        self.bekannte_auftraege = set()
        self.geolocator = Nominatim(user_agent="auftrag_bot")

        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)

        self.api_id_input = TextInput(hint_text='API ID', multiline=False)
        self.api_hash_input = TextInput(hint_text='API Hash', multiline=False)
        self.phone_input = TextInput(hint_text='Handynummer (+49...)', multiline=False)
        self.plz_input = TextInput(hint_text='Deine PLZ', multiline=False, text='40225')
        self.km_input = TextInput(hint_text='Max KM', multiline=False, text='50')
        self.gruppe_input = TextInput(hint_text='Gruppen-ID (z.B. -1003501049732)', multiline=False)

        self.start_btn = Button(text='BOT STARTEN', background_color=(0,0.7,0,1), size_hint_y=None, height=60)
        self.start_btn.bind(on_press=self.start_bot)

        self.stop_btn = Button(text='BOT STOPPEN', background_color=(0.7,0,0,1), size_hint_y=None, height=60)
        self.stop_btn.bind(on_press=self.stop_bot)

        self.status_label = Label(text='Status: Gestoppt', size_hint_y=None, height=40)
        self.log_label = Label(text='', size_hint_y=None, markup=True)
        self.log_label.bind(texture_size=self.log_label.setter('size'))

        scroll = ScrollView()
        scroll.add_widget(self.log_label)

        for w in [self.api_id_input, self.api_hash_input, self.phone_input,
                  self.plz_input, self.km_input, self.gruppe_input,
                  self.start_btn, self.stop_btn, self.status_label, scroll]:
            layout.add_widget(w)

        return layout

    def log(self, msg):
        Clock.schedule_once(lambda dt: setattr(self.log_label, 'text', self.log_label.text + '\n' + msg))

    def start_bot(self, instance):
        if self.running:
            return
        self.running = True
        self.status_label.text = 'Status: Läuft...'
        t = threading.Thread(target=self.run_bot)
        t.daemon = True
        t.start()

    def stop_bot(self, instance):
        self.running = False
        if self.client:
            asyncio.run_coroutine_threadsafe(self.client.disconnect(), self.loop)
        self.status_label.text = 'Status: Gestoppt'

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
        api_id = int(self.api_id_input.text)
        api_hash = self.api_hash_input.text
        phone = self.phone_input.text
        mein_plz = self.plz_input.text
        max_km = int(self.km_input.text)
        gruppe = int(self.gruppe_input.text)

        self.client = TelegramClient('auftrag_session', api_id, api_hash)
        await self.client.start(phone=phone)
        self.log('✅ Eingeloggt!')

        async for message in self.client.iter_messages(gruppe, limit=500):
            if message.text:
                for nr in re.findall(r'#\d+', message.text):
                    self.bekannte_auftraege.add(nr)

        self.log(f'📖 {len(self.bekannte_auftraege)} alte Aufträge geladen')

        @self.client.on(events.NewMessage(chats=gruppe))
        async def handler(event):
            if not event.message.fwd_from:
                return
            text = event.message.text or ''
            if 'Schlüsseldienst' not in text:
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
            if km and km <= max_km:
                await event.reply('ok')
                self.log(f'✅ OK gesendet! {plz_liste[0]} – {km} km')

        self.log('🤖 Bot läuft – warte auf Aufträge...')
        await self.client.run_until_disconnected()

if __name__ == '__main__':
    AuftragApp().run()
