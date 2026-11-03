"""v1.3.112: the contacts bot split, the bare contact format, the 5% photo
crop, the «Дааай в тг» give-request family and the B7ZK5 photo/startup
recoveries. Synthetic only; no network, no device."""
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import telegram_notify as p
import assistant_contact_photo as photo
import assistant_contact_clarify as clarify
import assistant_contact_policy as policy
import shared_contact as contacts
import mumu_recovery
from assistant_store import Store, StateError

TOKEN = '123456:' + ('a' * 35)
TOKEN2 = '654321:' + ('b' * 35)


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def flat_png(width=300, height=600, row=None, color=2, depth=8):
    """Filter-0 RGB/RGBA PNG whose row y starts with the byte y (mod 256)."""
    stride = width * (3 if color == 2 else 4)
    if row is None:
        row = lambda y: bytes([(y % 256) if i == 0 else (y // 256) % 256 for i in range(stride)])
    raw = b''.join(b'\x00' + row(y) for y in range(height))
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, depth, color, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw))
            + chunk(b'IEND', b''))


def up_png(width=300, height=600):
    """Filter-2 (Up) rows: exercises the full spec unfilter in crop_top.

    Returns (png bytes, original row bytes) so tests compare against the
    authored pixels, not against a naive filter-0 re-decode."""
    stride = width * 3
    rows = [bytes([(y * 7) % 256 if i < 4 else ((y + i) % 256) for i in range(stride)]) for y in range(height)]
    raw = bytearray()
    previous = bytes(stride)
    for line in rows:
        raw.append(2)
        raw.extend((line[i] - previous[i]) & 255 for i in range(stride))
        previous = line
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(bytes(raw)))
           + chunk(b'IEND', b''))
    return png, rows


def interlaced_png(width=300, height=600):
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 1))
            + chunk(b'IDAT', zlib.compress(b'\x00' * (width * 3 + 1) * height))
            + chunk(b'IEND', b''))


def rows_of(data):
    """Decode a filter-0 PNG back into its raw scanlines."""
    pos = 8
    header = None
    idat = []
    while pos + 12 <= len(data):
        n = struct.unpack('>I', data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        value = data[pos + 8:pos + 8 + n]
        if kind == b'IHDR':
            header = struct.unpack('>IIBBBBB', value)
        elif kind == b'IDAT':
            idat.append(value)
        pos = pos + 12 + n
    width, height, depth, color = header[:4]
    stride = width * (3 if color == 2 else 4) * (depth // 8)
    raw = zlib.decompress(b''.join(idat))
    return [raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)] for y in range(height)]


class Ack:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def read(self, n):
        return b'{"ok":true,"result":{"message_id":1}}'


class Opener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        return Ack()


class CropTop(unittest.TestCase):
    def test_filter_zero_rows_are_sliced_and_pixels_survive(self):
        image = flat_png(300, 600)
        out = photo.crop_top(image, 0.05)
        self.assertEqual(photo.png_size(out), (300, 570))
        source, cropped = rows_of(image), rows_of(out)
        self.assertEqual(cropped[0], source[30])
        self.assertEqual(cropped[-1], source[-1])

    def test_up_filtered_rows_defilter_to_the_same_pixels(self):
        image, original = up_png(300, 600)
        out = photo.crop_top(image, 0.05)
        self.assertEqual(photo.png_size(out), (300, 570))
        cropped = rows_of(out)
        self.assertEqual(cropped[0], original[30])
        self.assertEqual(cropped[569], original[599])

    def test_rgba_and_rounding(self):
        image = flat_png(240, 401, color=6)
        out = photo.crop_top(image, 0.05)
        self.assertEqual(photo.png_size(out), (240, 401 - 20))

    def test_minimum_height_is_never_crossed(self):
        base = flat_png(300, 200)
        self.assertEqual(photo.crop_top(base, 0.05), base)
        edge = flat_png(300, 205)
        self.assertEqual(photo.png_size(photo.crop_top(edge, 0.05)), (300, 200))

    def test_interlaced_returns_unchanged(self):
        image = interlaced_png()
        self.assertEqual(photo.crop_top(image, 0.05), image)

    def test_invalid_png_raises(self):
        for bad in (b'', b'not a png', flat_png(300, 600)[:-20]):
            with self.assertRaises(StateError):
                photo.crop_top(bad, 0.05)

    def test_output_is_a_structurally_valid_png(self):
        out = photo.crop_top(flat_png(300, 600), 0.05)
        self.assertEqual(photo.png_size(out), (300, 570))  # crcs included in png_size


class ContactFormat(unittest.TestCase):
    def test_message_is_the_contact_alone(self):
        self.assertEqual(p.contact_message(['@alex_test']), '@alex_test')
        self.assertEqual(p.contact_message(['+79991234567']), '79991234567')
        self.assertEqual(p.contact_message(['+79991234567', '@nick42']), '79991234567\n@nick42')

    def test_message_rejects_weaponised_values(self):
        for items in (['\nspam'], [''], ['x' * 65], [None]):
            with self.assertRaises(p.TelegramError):
                p.contact_message(items)

    def test_send_contact_text_has_no_header_name_or_disclaimer(self):
        opener = Opener()
        with patch.object(p.urllib.request, 'build_opener', return_value=opener):
            self.assertTrue(p.send_contact(TOKEN, '98765',
                                           {'name': 'Александр', 'contacts': ['@alex_test']}))
        body = parse_qs(opener.requests[0].data.decode())
        self.assertEqual(body['text'], ['@alex_test'])
        self.assertNotIn('Новый контакт', body['text'][0])
        self.assertNotIn('Александр', body['text'][0])
        self.assertNotIn('передан как прислан', body['text'][0])

    def test_send_contact_photo_is_cropped_and_caption_is_bare(self):
        opener = Opener()
        image = flat_png(300, 600)
        with patch.object(p.urllib.request, 'build_opener', return_value=opener):
            self.assertTrue(p.send_contact(TOKEN, '98765',
                                           {'name': 'Александр', 'contacts': ['+79991234567'], 'photo': image}))
        request = opener.requests[0]
        self.assertIn('sendPhoto', request.full_url)
        body = request.data
        self.assertIn(photo.crop_top(image, 0.05), body)
        self.assertNotIn(image, body)
        self.assertIn(b'79991234567', body)
        self.assertNotIn(b'+79991234567', body)

    def test_uncroppable_photo_never_leaks_and_text_still_goes(self):
        opener = Opener()
        broken = flat_png(300, 600)[:-8] + b'12345678'  # crc damage inside idat
        with patch.object(p.urllib.request, 'build_opener', return_value=opener):
            with patch.object(photo, 'png_size', side_effect=StateError('profile-photo-invalid')):
                # even a lying png_size cannot save a broken stream: crop fails first
                self.assertTrue(p.send_contact(TOKEN, '98765',
                                               {'name': 'А', 'contacts': ['@nick42'], 'photo': broken}))
        self.assertEqual(len(opener.requests), 1)
        self.assertIn('sendMessage', opener.requests[0].full_url)
        self.assertNotIn(broken, opener.requests[0].data)

    def test_contact_caption_skips_the_cloud_label(self):
        seen = []

        def marker(text):
            seen.append(text)
            return 'CLOUD|' + text

        with patch.object(p, 'cloud_label', side_effect=marker):
            opener = Opener()
            with patch.object(p.urllib.request, 'build_opener', return_value=opener):
                p.send_contact(TOKEN, '98765', {'name': 'А', 'contacts': ['@nick42']})
            self.assertEqual(seen, [])
            # other traffic keeps the label
            opener2 = Opener()
            with patch.object(p.urllib.request, 'build_opener', return_value=opener2):
                p.send(TOKEN, '98765', 'Обычное уведомление')
            self.assertEqual(seen, ['Обычное уведомление'])


class ContactsBot(unittest.TestCase):
    def encoder(self, key=42):
        return lambda data: bytes(x ^ key for x in data)

    def test_roundtrip_and_configured_flag(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'telegram-contacts.dpapi'
            self.assertFalse(p.contacts_configured(path))
            p.save_contacts(TOKEN2, '11122', path, encoder=self.encoder())
            self.assertTrue(p.contacts_configured(path))
            self.assertEqual(p.load_contacts(path, decoder=self.encoder()), (TOKEN2, '11122'))
            p.remove_contacts(path)
            self.assertFalse(p.contacts_configured(path))
            self.assertFalse(path.exists())

    def test_bad_credentials_never_write(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / 'telegram-contacts.dpapi'
            with self.assertRaises(p.TelegramError):
                p.save_contacts('bad', '1', path, encoder=self.encoder())
            self.assertFalse(path.exists())

    def fake_dpapi(self):
        return lambda data, decrypt=False: bytes(x ^ 42 for x in data)

    def test_contact_credentials_prefers_the_contacts_bot(self):
        with tempfile.TemporaryDirectory() as t:
            main = Path(t) / 'telegram.dpapi'
            second = Path(t) / 'telegram-contacts.dpapi'
            with patch.object(p, 'protect', self.fake_dpapi()):
                p.save(TOKEN, '98765', main, encoder=self.fake_dpapi())
                p.save_contacts(TOKEN2, '11122', second, encoder=self.fake_dpapi())
                with patch.object(p, 'settings_path', return_value=main), \
                        patch.object(p, 'contacts_settings_path', return_value=second):
                    self.assertEqual(p.contact_credentials(), (TOKEN2, '11122'))

    def test_contact_credentials_falls_back_to_the_main_bot(self):
        with tempfile.TemporaryDirectory() as t:
            main = Path(t) / 'telegram.dpapi'
            second = Path(t) / 'telegram-contacts.dpapi'
            with patch.object(p, 'protect', self.fake_dpapi()):
                p.save(TOKEN, '98765', main, encoder=self.fake_dpapi())
                with patch.object(p, 'settings_path', return_value=main), \
                        patch.object(p, 'contacts_settings_path', return_value=second):
                    self.assertEqual(p.contact_credentials(), (TOKEN, '98765'))
                    p.save_contacts(TOKEN2, '11122', second, encoder=self.fake_dpapi())
                    self.assertEqual(p.contact_credentials(), (TOKEN2, '11122'))

    def test_contact_notification_uses_the_contacts_bot(self):
        with tempfile.TemporaryDirectory() as t:
            main = Path(t) / 'telegram.dpapi'
            second = Path(t) / 'telegram-contacts.dpapi'
            opener = Opener()
            with patch.object(p, 'protect', self.fake_dpapi()), \
                    patch.object(p, 'settings_path', return_value=main), \
                    patch.object(p, 'contacts_settings_path', return_value=second), \
                    patch.object(p.urllib.request, 'build_opener', return_value=opener):
                p.save(TOKEN, '98765', main, encoder=self.fake_dpapi())
                p.save_contacts(TOKEN2, '11122', second, encoder=self.fake_dpapi())
                self.assertTrue(p.contact_notification({'name': 'А', 'contacts': ['@nick42']}))
            self.assertIn(TOKEN2, opener.requests[0].full_url)
            self.assertNotIn(TOKEN, opener.requests[0].full_url)

    def test_the_four_notifier_sites_use_the_contacts_credentials(self):
        from pathlib import Path as P
        root = P(__file__).resolve().parents[1]
        for name in ('assistant_dialogs.py', 'assistant_guided_chain.py',
                     'assistant_inbox.py', 'assistant_legacy.py'):
            source = (root / name).read_text(encoding='utf-8')
            self.assertIn('telegram_notify.contact_credentials()', source, name)
        # everything else keeps the primary bot
        exit_source = (root / 'assistant_exit_notify.py').read_text(encoding='utf-8')
        self.assertIn('telegram_notify.load()', exit_source)


class GiveRequestIntent(unittest.TestCase):
    """«Дааай в тг» (9104352d, ADB 5555): the ask for OUR contact is engagement."""

    def test_give_requests_are_choices(self):
        for text in ('Дааай в тг', 'Дай в тг', 'дай тг', 'Дааай в телегу', 'Дайте телеграм',
                     'скинь тг', 'Сбрось номер в ватсап', 'передай в тг', 'оставь тг'):
            with self.subTest(text=text):
                self.assertTrue(clarify.chosen([dict(text=text)]))

    def test_give_requests_pick_the_app_specific_question(self):
        from assistant_contact_intent import available_alternative
        self.assertEqual(available_alternative([dict(text='Дааай в тг')]), 'telegram')
        self.assertEqual(available_alternative([dict(text='Дай свой вотсап')]), 'whatsapp')
        self.assertEqual(available_alternative([dict(text='скинь свой тг')]), 'telegram')

    def test_refusals_stay_refusals(self):
        for text in ('Не пиши мне, давай тг', 'не дай свой номер', 'не скидывай ничего',
                     'ватсап не работает', 'Телеги нет', 'отдай телефон подруги'):
            with self.subTest(text=text):
                self.assertFalse(clarify.chosen([dict(text=text)]))

    def test_contact_only_policy_keeps_the_chain_open(self):
        class Row:
            def fetchone(self):
                return (1,)

        class DB:
            def execute(self, sql, params=()):
                return Row() if 'inbox_reply_policy' in sql else None
        self.assertFalse(policy.should_close(DB(), None, 'wait-contact',
                                             [dict(text='Дааай в тг')], requested=True))

    def test_a_number_attached_to_the_give_request_is_self_shared(self):
        self.assertEqual(contacts.self_shared('Дааай в тг 89991234567', requested=True),
                         ['+79991234567'])
        self.assertEqual(contacts.self_shared('Скинь вотсап +7 999 123-45-67', requested=True),
                         ['+79991234567'])

    def test_third_party_give_requests_stay_refused(self):
        self.assertEqual(contacts.self_shared('дай номер моей подруги 89991234567', requested=True), [])
        self.assertEqual(contacts.self_shared('передай телефон друга +79991234567', requested=True), [])


class MediaAttemptBudget(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'a.sqlite3', Path(self.temp.name) / 'old')

    def chain(self):
        import assistant_chain
        return assistant_chain.Chain(self.store, seal=lambda v: v, unseal=lambda v: v)

    def who(self):
        return dict(account='100', peer='200', chat='300')

    def test_attempts_counter_and_exhaustion(self):
        chain = self.chain()
        who = self.who()
        self.assertEqual(chain.media_attempts(who), 0)
        for expected in (1, 2, 3):
            chain.record_media_failure(who)
            self.assertEqual(chain.media_attempts(who), expected)
        self.assertTrue(chain.media_exhausted(who))
        chain.record_media_failure(who)
        self.assertEqual(chain.media_attempts(who), 4)

    def test_notify_requires_photo_only_until_the_limit(self):
        import assistant_chain
        import assistant_guided_chain as guided
        import test_guided_chain as guide
        chain = guided.GuidedChain(self.store, choose=lambda: 0,
                                   seal=lambda v: v, unseal=lambda v: v)
        who = guide.WHO
        chain.media_required = True
        from conversation_engine import CONTACT_TEXT
        chain.bind(guide.snapshot(), (guide.GREETING,), approved=True)
        h = [('Привет!', False), (guide.QUESTIONS[0], True), ('Отлично!', False), (CONTACT_TEXT, True)]
        stage = None
        for sample in [guide.snapshot(*h[:1]), guide.snapshot(*h[:2]), guide.snapshot(*h[:3]), guide.snapshot(*h)]:
            stage, action = chain.proposal(sample)
            if action:
                chain.reserve_confirmed(who, action)
                chain.finish(who, action, True)
        self.assertEqual(stage, 'wait-contact')
        self.assertEqual(chain.proposal(guide.snapshot(*h, ('@Love_1712 телега', False)))[0], 'done')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_contact_outbox').fetchone()[0], 'pending')
        for _ in range(assistant_chain.Chain.MEDIA_ATTEMPT_LIMIT):
            self.assertEqual(chain.notify(who, lambda payload: True), 'photo-required')
            chain.record_media_failure(who)
        # exhausted: the contact is delivered without the photo
        self.assertEqual(chain.notify(who, lambda payload: True), 'accepted')
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_contact_outbox').fetchone()[0], 'accepted')

    def test_the_table_is_registered_with_the_cloud_schema(self):
        from pathlib import Path as P
        root = P(__file__).resolve().parents[1]
        self.assertIn('chain_media_attempts', (root / 'mumu_store.py').read_text(encoding='utf-8'))
        self.assertIn('chain_media_attempts', (root / 'cloud_database.py').read_text(encoding='utf-8'))


class GuidedPhotoBudget(unittest.TestCase):
    """The B7ZK5 walk: three failed captures, then delivery without the photo."""

    def setUp(self):
        import test_guided_chain as guide
        import assistant_guided_chain as guided
        from conversation_engine import CONTACT_TEXT
        self.guide = guide
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'a.sqlite3', Path(self.temp.name) / 'old')
        self.stop = __import__('threading').Event()
        self.chain = guided.GuidedChain(self.store, choose=lambda: 0,
                                        seal=lambda v: v, unseal=lambda v: v)
        self.chain.media_required = True
        self.notifier = MagicMock(return_value=True)
        h = [('Приветик', False), (guide.QUESTIONS[0], True), ('нормально!а у тебя?😊', False), (CONTACT_TEXT, True)]
        self.chain.bind(guide.snapshot(), (guide.GREETING,), approved=True)
        stage = None
        for sample in [guide.snapshot(*h[:1]), guide.snapshot(*h[:2]), guide.snapshot(*h[:3]), guide.snapshot(*h)]:
            stage, action = self.chain.proposal(sample)
            if action:
                self.chain.reserve_confirmed(guide.WHO, action)
                self.chain.finish(guide.WHO, action, True)
        self.assertEqual(stage, 'wait-contact')
        self.sample = guide.snapshot(*h, ('@Love_1712 телега', False))
        self.assertEqual(self.chain.proposal(self.sample)[0], 'done')

    def walk(self, contact_photo):
        import assistant_guided_chain as guided
        reader = MagicMock(side_effect=self.guide.stable_snapshots([self.sample]))
        defaults = dict(approved=True, greetings=(self.guide.GREETING,), notifier=self.notifier,
                        pause=lambda _: False, max_polls=12, contact_photo=contact_photo)
        return guided.walk(self.chain, self.guide.WHO, self.stop, MagicMock(return_value=True),
                           reader, lambda before, text: dict(attempted=True, handler_returned=True),
                           **defaults)

    def test_three_failures_then_delivery_without_photo(self):
        from assistant_contact_photo import ProfilePhotoNotStarted
        failing = MagicMock(side_effect=StateError('profile-photo-unavailable'))
        for round_index in range(3):
            out = self.walk(failing)
            self.assertEqual(out['status'], 'chain-waiting')
            self.assertEqual(out['reason'], 'contact-photo-unavailable')
            self.assertEqual(out['diagnostics']['media_attempts'], round_index + 1)
        self.assertEqual(failing.call_count, 3)
        self.assertEqual(self.notifier.call_count, 0)
        # exhausted: the capture is skipped entirely and the contact goes out
        out = self.walk(MagicMock(side_effect=AssertionError('must not be called')))
        self.assertEqual(out['reason'], 'contact-forwarded')
        self.assertEqual(self.notifier.call_count, 1)
        self.assertEqual(self.notifier.call_args.args[0], dict(name=self.guide.PEER_NAME, contacts=['@Love_1712']))
        self.assertNotIn('photo', self.notifier.call_args.args[0])
        with self.store.connection() as db:
            self.assertEqual(db.execute('SELECT status FROM chain_contact_outbox').fetchone()[0], 'accepted')

    def test_a_soft_startup_failure_still_counts_once_per_walk(self):
        from assistant_contact_photo import ProfilePhotoNotStarted
        failing = MagicMock(side_effect=ProfilePhotoNotStarted(TimeoutError('t')))
        out = self.walk(failing)
        self.assertEqual(out['reason'], 'contact-photo-unavailable')
        self.assertEqual(out['diagnostics']['media_attempts'], 1)
        self.assertEqual(out['diagnostics']['photo_failure']['photo_checkpoint'], 'before-profile-open')


class StartupIdentityChanged(unittest.TestCase):
    def monitor_719(self, **overrides):
        report = dict(status='stopped', reason='dialog-list-not-verified',
                      passes_completed=0, dialogs_verified=False,
                      last_navigation=dict(stage='navigation-stopped', error='identity-changed',
                                           phase='wait-back', action_attempted=True,
                                           action_completed=True, destination_verified=False),
                      last_navigation_failure=dict(stage='navigation-destination',
                                                   error='startup-navigation-destination-failed',
                                                   error_type='ValueError', operation='list'))
        report.update(overrides)
        return report

    def test_the_startup_wait_back_transition_is_recoverable(self):
        self.assertTrue(mumu_recovery.recoverable(self.monitor_719()))

    def test_chat_level_identity_change_stays_blocked(self):
        report = dict(status='stopped', reason='inbox-pass-stopped',
                      last_pass=dict(status='inbox-stopped',
                                     last_navigation=dict(stage='navigation-stopped',
                                                          error='identity-changed', phase='wait-chat')))
        self.assertFalse(mumu_recovery.recoverable(report))

    def test_identity_changed_inside_a_completed_pass_stays_blocked(self):
        report = self.monitor_719(last_pass=dict(status='inbox-stopped', reason='chat-identity-changed',
                                                 last_navigation=dict(stage='navigation-stopped',
                                                                      error='identity-changed')))
        self.assertFalse(mumu_recovery.recoverable(report))

    def test_other_blocks_stay_blocked_at_startup(self):
        report = self.monitor_719()
        report['last_navigation']['error'] = 'identity-not-bound'
        self.assertFalse(mumu_recovery.recoverable(report))
        # the untouched shape still recovers after a mutating sibling ran
        self.assertTrue(mumu_recovery.recoverable(self.monitor_719()))


class SourcePins(unittest.TestCase):
    def test_crop_is_wired_into_the_contact_send(self):
        from pathlib import Path as P
        root = P(__file__).resolve().parents[1]
        source = (root / 'telegram_notify.py').read_text(encoding='utf-8')
        self.assertIn('crop_top(payload[\'photo\'],0.05)', source)
        self.assertNotIn('Новый контакт!', source)

    def test_capture_profile_carries_the_verified_back_recovery(self):
        from pathlib import Path as P
        import inspect
        root = P(__file__).resolve().parents[1]
        source = (root / 'assistant_contact_photo.py').read_text(encoding='utf-8')
        self.assertIn("check_chat('profile-after-back',retries=2)", source)


if __name__ == '__main__':
    unittest.main()
