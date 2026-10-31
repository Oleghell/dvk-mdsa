"""1.3.101 regression: the native baseline twin carries every DEFAULTS field.

Reported: «native test в гитхабе провальные» - every 'Build DvkAssistant' run
since v1.3.99 died in BOTH native jobs (windows-2022 and ubuntu-24.04) at the
same line: smoke_assistant_pass.py case 'combined-frame-baseline' ->
assistant_pass.validate -> assistant_profile_read.validate ->
ValueError('Missing profile read evidence').

The baseline case exists to prove the UNSPECIALIZED build dies by its own
frame/call budgets (the twin of 'combined-frame', which proves the
specialized build survives the same saturated frames). It strips
assistant_profile_read.specialize - the mechanism that Object.assigns ALL
validator-required DEFAULTS counters into the navigation object - and then
hand-re-added the injection for the three fields that existed when the twin
was written. v1.3.99 taught the validator a fourth counter
(submit_frame_retries) and the hand-kept twin kept three, so the
specialize-stripped build reached validate() without the field and EVERY
native run failed on both platforms. The suite had not actually been
executed before that push (the local attempt died at a frida attach failure
and was shipped anyway), which is exactly what the CI native jobs exist to
catch.

The twin now derives its injection from assistant_profile_read.DEFAULTS
itself: the stripped build stays free of the profile-read specializations
while carrying EXACTLY the evidence keys validate() will demand, whatever a
future version adds. These tests pin both sides: the derived twin satisfies
the validator's field gate, and the hand-kept form it replaced does not.
"""
import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assistant_pass
import assistant_profile_read as profile_read
from test_mumu1400_greeting_send_under_load import greeted

SMOKE = (Path(__file__).resolve().parents[1] / 'smoke_assistant_pass.py').read_text(encoding='utf-8')


def baseline_injection():
    """The smoke's baseline injection rule, verbatim (derived from DEFAULTS)."""
    return ''.join('r.navigation.%s=%s;' % (key, json.dumps(value))
                   for key, value in profile_read.DEFAULTS.items())


def composed_baseline():
    """The smoke's baseline build: specialize stripped, evidence injected."""
    with patch('assistant_profile_read.specialize', side_effect=lambda value: value):
        source = assistant_pass.build('Привет', [])
    return source.replace('r.navigation=emptyNavigation();',
                          'r.navigation=emptyNavigation();' + baseline_injection())


class SmokeSource(unittest.TestCase):
    """The smoke derives the twin's evidence from the module, not by hand."""

    def test_baseline_injection_is_derived_from_defaults(self):
        self.assertIn('for key,value in assistant_profile_read.DEFAULTS.items()', SMOKE)

    def test_hand_kept_field_list_is_gone(self):
        # The literal that broke every CI native run since v1.3.99: a frozen
        # three-field twin that silently loses any field a future version
        # adds to DEFAULTS.
        self.assertNotIn(
            'r.navigation.profile_read_budget_retries=0;'
            'r.navigation.greeting_frame_splits=0;r.navigation.profile_ready_waits=0', SMOKE)


class BaselineTwin(unittest.TestCase):
    """The stripped build carries exactly what validate() will demand."""

    def test_twin_carries_every_defaults_field(self):
        source = composed_baseline()
        anchor = 'r.navigation=emptyNavigation();'
        start = source.index(anchor) + len(anchor)
        # The injected run is a contiguous block of r.navigation.<key>=<v>;
        # assignments immediately after the anchor.
        assignments = dict(re.findall(
            r'r\.navigation\.([A-Za-z_][A-Za-z0-9_]*)=([^;]*);', source[start:start + 400]))
        self.assertTrue(set(profile_read.DEFAULTS) <= set(assignments),
                        (sorted(profile_read.DEFAULTS), sorted(assignments)))
        for key, value in profile_read.DEFAULTS.items():
            self.assertEqual(assignments[key], json.dumps(value))

    def test_original_three_fields_still_render(self):
        injection = baseline_injection()
        for field in ('profile_read_budget_retries', 'greeting_frame_splits',
                      'profile_ready_waits'):
            self.assertIn('r.navigation.%s=0;' % field, injection)

    def test_submit_frame_retries_reaches_the_twin(self):
        self.assertIn('r.navigation.submit_frame_retries=0;', baseline_injection())

    def test_hand_kept_form_is_the_ci_failure(self):
        hand_kept = {'profile_read_budget_retries', 'greeting_frame_splits',
                     'profile_ready_waits'}
        # The exact gate validate() applies first: set(DEFAULTS) <= set(n).
        self.assertFalse(set(profile_read.DEFAULTS) <= hand_kept)


class ValidatorGate(unittest.TestCase):
    """The validator demands every DEFAULTS field on the navigation object."""

    def test_missing_only_submit_frame_retries_is_the_reported_error(self):
        navigation = dict(greeted()['navigation'])
        del navigation['submit_frame_retries']
        with self.assertRaises(ValueError) as caught:
            profile_read.validate(navigation)
        self.assertEqual(str(caught.exception), 'Missing profile read evidence')

    def test_intact_navigation_passes_the_gate(self):
        navigation = dict(greeted()['navigation'])
        try:
            profile_read.validate(navigation)
        except ValueError as error:
            self.fail('intact navigation rejected: %s' % error)


if __name__ == '__main__':
    unittest.main()
